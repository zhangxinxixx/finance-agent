"""Bounded, fail-closed collector for CME's public FedWatch iframe."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit
from uuid import uuid4

import httpx

from apps.parsers.macro.fedwatch_free import FedWatchParseError, parse_fedwatch_free_payload


SOURCE = "cme_fedwatch_free"
COLLECTOR_VERSION = "fedwatch-free-collector-v1"
PARENT_URL = "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html"
IFRAME_URL = (
    "https://cmegroup-tools.quikstrike.net/User/QuikStrikeTools.aspx"
    "?viewitemid=IntegratedFedWatchTool"
)
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_REDIRECTS = 4
REQUEST_TIMEOUT = httpx.Timeout(20.0, connect=10.0, read=15.0, write=10.0, pool=10.0)
_PARENT_HOSTS = frozenset({"www.cmegroup.com", "cmegroup.com"})
_IFRAME_HOSTS = frozenset({"cmegroup-tools.quikstrike.net"})
_SAFE_RESPONSE_HEADERS = frozenset(
    {"cache-control", "content-length", "content-type", "date", "etag", "last-modified"}
)
_SAFE_QUERY_KEYS = frozenset({"viewitemid"})


@dataclass(frozen=True)
class _PublicResponse:
    role: str
    requested_url: str
    response_url: str
    http_status: int | None
    content_type: str | None
    headers: dict[str, str]
    body: bytes
    truncated: bool = False

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.body).hexdigest()


@dataclass(frozen=True)
class _FetchOutcome:
    responses: list[_PublicResponse]
    reason: str | None


class _IframeSourceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "iframe":
            return
        for key, value in attrs:
            if key.lower() == "src" and value:
                self.sources.append(value.strip())


def collect_fedwatch_free(
    *,
    storage_root: Path,
    client: httpx.Client | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Collect public QuikStrike probabilities, preferring HTTP WebForms.

    Normal runs use the observed official view and its anonymous session/form
    redirects, then the native browser as fallback. Injected HTTP clients retain
    the existing parent/iframe adapter. No paid endpoint or inferred probability
    is used; successful HTTP collection does not start a browser.
    """

    if client is None:
        from apps.collectors.macro.fedwatch_webforms import collect_fedwatch_webforms
        direct = collect_fedwatch_webforms(storage_root=storage_root, now=now)
        if (direct.get("parse_status") == "missing" and direct.get("reason") in {
            "official_http_transport_curl_16", "official_http_transport_curl_28",
            "official_http_transport_curl_35", "official_http_transport_curl_56",
            "official_http_transport_curl_92",
        }):
            # One HTTP/1.1 anonymous session for transient connection failures;
            # never retry schema errors or replay a partial POST session.
            direct = collect_fedwatch_webforms(storage_root=storage_root, now=now, http1=True)
        if direct.get("parse_status") == "ok":
            return direct
        from apps.collectors.macro.fedwatch_browser import browser_available, collect_fedwatch_browser
        if browser_available():
            return collect_fedwatch_browser(storage_root=storage_root, now=now)
        return direct

    clock = _ensure_utc(now or datetime.now(timezone.utc))
    collected_at = clock.isoformat()
    snapshot_id = str(uuid4())
    responses: list[_PublicResponse] = []
    parse_result: dict[str, Any] | None = None
    parse_status = "missing"
    reason: str | None = None
    iframe_url: str | None = None

    close_client = client is None
    if client is None:
        client = httpx.Client(
            timeout=REQUEST_TIMEOUT,
            follow_redirects=False,
            trust_env=False,
            headers={
                "User-Agent": "finance-agent/0.1 (+public CME FedWatch collector)",
                "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.1",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )

    try:
        parent = _fetch_chain(
            client,
            url=PARENT_URL,
            role="parent",
            allowed_hosts=_PARENT_HOSTS,
            headers=None,
        )
        responses.extend(parent.responses)
        if parent.reason is not None:
            reason = f"official_parent_unavailable: {parent.reason}"
        elif not parent.responses or parent.responses[-1].http_status != 200:
            status = parent.responses[-1].http_status if parent.responses else None
            reason = f"official_parent_http_status_{status}"
        else:
            parent_response = parent.responses[-1]
            iframe_url = _discover_iframe_url(parent_response.body, parent_response.response_url)
            if iframe_url is None:
                reason = "official_parent_has_no_allowlisted_fedwatch_iframe"
            else:
                iframe = _fetch_chain(
                    client,
                    url=iframe_url,
                    role="iframe",
                    allowed_hosts=_IFRAME_HOSTS,
                    headers={"Referer": parent_response.response_url},
                )
                responses.extend(iframe.responses)
                if iframe.reason is not None:
                    reason = f"official_iframe_unavailable: {iframe.reason}"
                elif not iframe.responses or iframe.responses[-1].http_status != 200:
                    status = iframe.responses[-1].http_status if iframe.responses else None
                    reason = f"official_iframe_http_status_{status}"
                else:
                    iframe_response = iframe.responses[-1]
                    try:
                        parse_result = parse_fedwatch_free_payload(
                            iframe_response.body,
                            content_type=iframe_response.content_type,
                        )
                    except FedWatchParseError as exc:
                        parse_status = "parse_failed"
                        reason = f"official_iframe_parse_failed: {exc}"
                    else:
                        parse_status = "ok"
    finally:
        if close_client:
            client.close()

    if now is None:
        collected_at = datetime.now(timezone.utc).isoformat()
    primary = _primary_response(responses)
    try:
        raw_artifact_ref, source_refs = _archive_collection(
            storage_root=storage_root,
            snapshot_id=snapshot_id,
            collected_at=collected_at,
            responses=responses,
            parse_status=parse_status,
            reason=reason,
        )
    except OSError as exc:
        return _snapshot(
            snapshot_id=snapshot_id,
            collected_at=collected_at,
            source_url=_safe_public_url(iframe_url or IFRAME_URL),
            http_status=primary.http_status if primary else None,
            content_hash=primary.content_hash if primary else None,
            raw_artifact_ref=None,
            parse_status="missing",
            reason=f"raw_archival_failed: {type(exc).__name__}",
            source_refs=[],
            parse_result=None,
        )

    return _snapshot(
        snapshot_id=snapshot_id,
        collected_at=collected_at,
        source_url=_safe_public_url(iframe_url or IFRAME_URL),
        http_status=primary.http_status if primary else None,
        content_hash=primary.content_hash if primary else None,
        raw_artifact_ref=raw_artifact_ref,
        parse_status=parse_status,
        reason=reason,
        source_refs=source_refs,
        parse_result=parse_result,
    )


def _fetch_chain(
    client: httpx.Client,
    *,
    url: str,
    role: str,
    allowed_hosts: frozenset[str],
    headers: Mapping[str, str] | None,
) -> _FetchOutcome:
    responses: list[_PublicResponse] = []
    current_url = url
    for redirect_count in range(MAX_REDIRECTS + 1):
        invalid = _url_rejection(current_url, allowed_hosts)
        if invalid is not None:
            return _FetchOutcome(responses, invalid)
        try:
            with client.stream(
                "GET",
                current_url,
                headers=dict(headers or {}),
                timeout=REQUEST_TIMEOUT,
                follow_redirects=False,
            ) as response:
                body = bytearray()
                truncated = False
                for chunk in response.iter_bytes():
                    remaining = MAX_RESPONSE_BYTES - len(body)
                    if remaining <= 0:
                        truncated = True
                        break
                    body.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        truncated = True
                        break
                record = _PublicResponse(
                    role=role,
                    requested_url=current_url,
                    response_url=str(response.url),
                    http_status=response.status_code,
                    content_type=response.headers.get("content-type"),
                    headers={
                        key.lower(): value
                        for key, value in response.headers.items()
                        if key.lower() in _SAFE_RESPONSE_HEADERS
                    },
                    body=bytes(body),
                    truncated=truncated,
                )
                responses.append(record)
                if truncated:
                    return _FetchOutcome(responses, f"{role}_response_exceeded_{MAX_RESPONSE_BYTES}_bytes")
                if response.status_code not in {301, 302, 303, 307, 308}:
                    return _FetchOutcome(responses, None)
                location = response.headers.get("location")
                if not location:
                    return _FetchOutcome(responses, f"{role}_redirect_has_no_location")
                current_url = urljoin(str(response.url), location)
        except httpx.TimeoutException:
            return _FetchOutcome(responses, f"{role}_request_timed_out")
        except httpx.HTTPError as exc:
            return _FetchOutcome(responses, f"{role}_transport_error_{type(exc).__name__}")
        if redirect_count == MAX_REDIRECTS:
            return _FetchOutcome(responses, f"{role}_redirect_limit_exceeded")
    return _FetchOutcome(responses, f"{role}_redirect_limit_exceeded")


def _discover_iframe_url(body: bytes, parent_url: str) -> str | None:
    try:
        html = body.decode("utf-8")
    except UnicodeDecodeError:
        return None
    parser = _IframeSourceParser()
    parser.feed(html)
    parser.close()
    for source in parser.sources:
        candidate = urljoin(parent_url, source)
        if _url_rejection(candidate, _IFRAME_HOSTS) is not None:
            continue
        query = parse_qs(urlsplit(candidate).query)
        if query.get("viewitemid") == ["IntegratedFedWatchTool"]:
            return candidate
    return None


def _archive_collection(
    *,
    storage_root: Path,
    snapshot_id: str,
    collected_at: str,
    responses: list[_PublicResponse],
    parse_status: str,
    reason: str | None,
    collector_version: str = COLLECTOR_VERSION,
    capture_kind: str = "http_response",
) -> tuple[str, list[dict[str, Any]]]:
    collected_date = datetime.fromisoformat(collected_at).date().isoformat()
    parent_dir = storage_root / "raw" / "macro" / SOURCE / collected_date
    parent_dir.mkdir(parents=True, exist_ok=True)
    event_dir = parent_dir / snapshot_id
    event_dir.mkdir(exist_ok=False)
    response_entries: list[dict[str, Any]] = []
    source_refs: list[dict[str, Any]] = []

    role_counts: dict[str, int] = {}
    for index, response in enumerate(responses, start=1):
        role_counts[response.role] = role_counts.get(response.role, 0) + 1
        suffix = _response_suffix(response.content_type)
        filename = f"{index:02d}-{response.role}-{role_counts[response.role]}.{suffix}"
        raw_path = event_dir / filename
        with raw_path.open("xb") as handle:
            handle.write(response.body)
        if hashlib.sha256(raw_path.read_bytes()).hexdigest() != response.content_hash:
            raise ValueError("fedwatch_raw_hash_mismatch")
        raw_ref = raw_path.relative_to(storage_root).as_posix()
        entry = {
            "role": response.role,
            "requested_url": _safe_public_url(response.requested_url),
            "response_url": _safe_public_url(response.response_url),
            "http_status": response.http_status,
            "content_type": response.content_type,
            "headers": response.headers,
            "bytes": len(response.body),
            "content_hash": response.content_hash,
            "hash_verified_at_ingestion": True,
            "raw_artifact_ref": raw_ref,
            "truncated": response.truncated,
        }
        response_entries.append(entry)
        source_refs.append(
            {
                "source": SOURCE,
                "role": response.role,
                "source_url": _safe_public_url(response.response_url),
                "collected_at": collected_at,
                "http_status": response.http_status,
                "content_hash": response.content_hash,
                "hash_verified_at_ingestion": True,
                "raw_artifact_ref": raw_ref,
                "capture_kind": capture_kind,
            }
        )

    manifest_path = event_dir / "manifest.json"
    manifest = {
        "source": SOURCE,
        "snapshot_id": snapshot_id,
        "collected_at": collected_at,
        "collector_version": collector_version,
        "capture_kind": capture_kind,
        "parse_status": parse_status,
        "reason": reason,
        "limits": {"max_response_bytes": MAX_RESPONSE_BYTES, "max_redirects": MAX_REDIRECTS},
        "responses": response_entries,
    }
    with manifest_path.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return manifest_path.relative_to(storage_root).as_posix(), source_refs


def _snapshot(
    *,
    snapshot_id: str,
    collected_at: str,
    source_url: str,
    http_status: int | None,
    content_hash: str | None,
    raw_artifact_ref: str | None,
    parse_status: str,
    reason: str | None,
    source_refs: list[dict[str, Any]],
    parse_result: dict[str, Any] | None,
) -> dict[str, Any]:
    parsed = parse_result or {}
    result = {
        "source": SOURCE,
        "snapshot_id": snapshot_id,
        "collected_at": collected_at,
        "as_of": parsed.get("as_of"),
        "source_url": source_url,
        "collector_version": COLLECTOR_VERSION,
        "http_status": http_status,
        "content_hash": content_hash,
        "raw_artifact_ref": raw_artifact_ref,
        "parse_status": parse_status,
        "reason": reason,
        "source_refs": source_refs,
        "rows": parsed.get("rows", []),
        "futures": parsed.get("futures", []),
        "warnings": parsed.get("warnings", [reason] if reason else []),
        "coverage": parsed.get(
            "coverage",
            {"complete": False, "meetings": {}, "reason": reason},
        ),
    }
    if parsed:
        result["parser_version"] = parsed.get("parser_version")
    return result


def _primary_response(responses: list[_PublicResponse]) -> _PublicResponse | None:
    for response in reversed(responses):
        if response.role == "iframe":
            return response
    return responses[-1] if responses else None


def _url_rejection(url: str, allowed_hosts: frozenset[str]) -> str | None:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme.lower() != "https":
        return "non_https_url_rejected"
    if parts.username is not None or parts.password is not None:
        return "url_credentials_rejected"
    try:
        port = parts.port
    except ValueError:
        return "invalid_url_port_rejected"
    if port not in {None, 443}:
        return "non_https_port_rejected"
    if host not in allowed_hosts:
        return f"redirect_host_not_allowlisted_{host or 'missing'}"
    return None


def _safe_public_url(url: str) -> str:
    parts = urlsplit(url)
    query = parse_qs(parts.query, keep_blank_values=True)
    safe_query = []
    for key in sorted(_SAFE_QUERY_KEYS):
        for value in query.get(key, []):
            safe_query.append((key, value))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(safe_query), ""))


def _response_suffix(content_type: str | None) -> str:
    media_type = (content_type or "").split(";", 1)[0].strip().lower()
    if media_type == "application/json":
        return "json"
    if media_type in {"text/html", "application/xhtml+xml"}:
        return "html"
    if media_type == "text/plain":
        return "txt"
    return "bin"


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return value.astimezone(timezone.utc)


__all__ = [
    "COLLECTOR_VERSION",
    "IFRAME_URL",
    "MAX_REDIRECTS",
    "MAX_RESPONSE_BYTES",
    "PARENT_URL",
    "SOURCE",
    "collect_fedwatch_free",
]
