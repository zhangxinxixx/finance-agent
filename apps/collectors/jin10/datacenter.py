"""Collector for Jin10 datacenter report shells and JS data scripts."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urljoin


DATACENTER_REPORT_URL = "https://datacenter.jin10.com/reportType/{slug}"
DATACENTER_SOURCE_KEY = "jin10_datacenter_reports"
DEFAULT_DATACENTER_SLUGS = ("dc_etf_gold", "dc_nonfarm_payrolls", "dc_cftc_nc_report")
DEFAULT_HEADERS = {
    "User-Agent": "finance-agent/0.1",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
_SLUG_RE = re.compile(r"^[a-z0-9_]+$")


@dataclass(slots=True)
class Jin10DatacenterFetchResult:
    slug: str
    status: str
    name_type: str | None = None
    report_name: str = ""
    shell_url: str = ""
    script_url: str | None = None
    raw_html_path: str | None = None
    raw_js_path: str | None = None
    raw_meta_path: str | None = None
    fetched_at: str = ""
    source_refs: list[dict[str, Any]] = field(default_factory=list)
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def fetch_datacenter_report(
    *,
    slug: str,
    storage_root: Path,
    retrieved_date: str | None = None,
    client: Any | None = None,
) -> Jin10DatacenterFetchResult:
    """Fetch and archive one Jin10 datacenter report shell plus latest JS."""
    _validate_slug(slug)
    retrieved_date = retrieved_date or datetime.now(timezone.utc).date().isoformat()
    shell_url = DATACENTER_REPORT_URL.format(slug=slug)
    close_client = False
    if client is None:
        import httpx

        client = httpx.Client(timeout=20.0, trust_env=False)
        close_client = True

    fetched_at = datetime.now(timezone.utc).isoformat()
    try:
        html_response = client.get(shell_url, headers=DEFAULT_HEADERS)
        html_response.raise_for_status()
        html = str(html_response.text)
        raw_html_path = _write_text(
            storage_root=storage_root,
            retrieved_date=retrieved_date,
            slug=slug,
            filename="shell.html",
            text=html,
        )
        name_type = _extract_name_type(html)
        report_name = _extract_report_name(html)
        if name_type != slug:
            return _result(
                slug=slug,
                status="schema_changed",
                name_type=name_type,
                report_name=report_name,
                shell_url=shell_url,
                raw_html_path=raw_html_path,
                fetched_at=fetched_at,
                error_message=f"nameType mismatch: expected={slug} actual={name_type}",
            )

        script_url = _extract_latest_script_url(html, slug=slug, shell_url=shell_url)
        if script_url is None:
            return _result(
                slug=slug,
                status="schema_changed",
                name_type=name_type,
                report_name=report_name,
                shell_url=shell_url,
                raw_html_path=raw_html_path,
                fetched_at=fetched_at,
                error_message="latest datacenter JS script not found",
            )

        js_response = client.get(script_url, headers=DEFAULT_HEADERS)
        js_response.raise_for_status()
        js_text = str(js_response.text)
        raw_js_path = _write_text(
            storage_root=storage_root,
            retrieved_date=retrieved_date,
            slug=slug,
            filename="latest.js",
            text=js_text,
        )
        raw_meta_path = _write_json(
            storage_root=storage_root,
            retrieved_date=retrieved_date,
            slug=slug,
            filename="fetch_meta.json",
            payload={
                "slug": slug,
                "name_type": name_type,
                "shell_url": shell_url,
                "script_url": script_url,
                "fetched_at": fetched_at,
                "html_headers": dict(getattr(html_response, "headers", {}) or {}),
                "js_headers": dict(getattr(js_response, "headers", {}) or {}),
            },
        )
        status = "ok" if "dataCenter_data" in js_text else "schema_changed"
        return _result(
            slug=slug,
            status=status,
            name_type=name_type,
            report_name=report_name,
            shell_url=shell_url,
            script_url=script_url,
            raw_html_path=raw_html_path,
            raw_js_path=raw_js_path,
            raw_meta_path=raw_meta_path,
            fetched_at=fetched_at,
            error_message=None if status == "ok" else "dataCenter_data assignment not found",
        )
    finally:
        if close_client:
            client.close()


def _result(
    *,
    slug: str,
    status: str,
    name_type: str | None = None,
    report_name: str = "",
    shell_url: str = "",
    script_url: str | None = None,
    raw_html_path: str | None = None,
    raw_js_path: str | None = None,
    raw_meta_path: str | None = None,
    fetched_at: str = "",
    error_message: str | None = None,
) -> Jin10DatacenterFetchResult:
    ref = {
        "source": "jin10_datacenter",
        "source_key": DATACENTER_SOURCE_KEY,
        "access_method": "js_data_script",
        "provider_role": "supplemental_source",
        "slug": slug,
        "status": status,
        "shell_url": shell_url,
    }
    if script_url:
        ref["script_url"] = script_url
    if raw_html_path:
        ref["raw_html_path"] = raw_html_path
    if raw_js_path:
        ref["raw_js_path"] = raw_js_path
    if raw_meta_path:
        ref["raw_meta_path"] = raw_meta_path
    if error_message:
        ref["reason"] = error_message
    return Jin10DatacenterFetchResult(
        slug=slug,
        status=status,
        name_type=name_type,
        report_name=report_name,
        shell_url=shell_url,
        script_url=script_url,
        raw_html_path=raw_html_path,
        raw_js_path=raw_js_path,
        raw_meta_path=raw_meta_path,
        fetched_at=fetched_at,
        source_refs=[ref],
        error_message=error_message,
    )


def _validate_slug(slug: str) -> None:
    if not _SLUG_RE.fullmatch(slug):
        raise ValueError(f"Invalid Jin10 datacenter slug: {slug}")


def _extract_name_type(html: str) -> str | None:
    match = re.search(r"\bnameType\s*=\s*['\"]([^'\"]+)['\"]", html)
    return match.group(1) if match else None


def _extract_report_name(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return re.sub(r"\s+", " ", unescape(match.group(1))).strip()


def _extract_latest_script_url(html: str, *, slug: str, shell_url: str) -> str | None:
    candidates: list[str] = []
    for match in re.finditer(r"<script[^>]+src=['\"]([^'\"]+)['\"]", html, flags=re.IGNORECASE):
        src = unescape(match.group(1))
        if f"/dc/reports/{slug}" in src or f"/dc/reports/{slug}_" in src or f"{slug}_latest" in src:
            candidates.append(urljoin(shell_url, src))
    if not candidates:
        return None
    latest = [item for item in candidates if "_latest" in item]
    return latest[-1] if latest else candidates[-1]


def _write_text(
    *,
    storage_root: Path,
    retrieved_date: str,
    slug: str,
    filename: str,
    text: str,
) -> str:
    rel_path = Path("raw") / "jin10" / "datacenter" / retrieved_date / slug / filename
    target = storage_root / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return rel_path.as_posix()


def _write_json(
    *,
    storage_root: Path,
    retrieved_date: str,
    slug: str,
    filename: str,
    payload: dict[str, Any],
) -> str:
    rel_path = Path("raw") / "jin10" / "datacenter" / retrieved_date / slug / filename
    target = storage_root / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return rel_path.as_posix()
