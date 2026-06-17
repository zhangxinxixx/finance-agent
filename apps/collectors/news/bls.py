from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx

from apps.collectors.news.base import (
    NewsCollectionResult,
    RawNewsItem,
    archive_news_payload,
    stable_news_item_id,
    utc_now_iso,
)

BLS_CALENDAR_URL = "https://www.bls.gov/schedule/news_release/bls.ics"
BLS_SOURCE_NAME = "BLS Release Calendar"
BLS_ACCESS_MODE = "direct_official_ics"


def collect_bls_calendar(
    *,
    retrieved_date: str,
    storage_root: Path,
    calendar_url: str = BLS_CALENDAR_URL,
    request_timeout: float | httpx.Timeout | None = None,
    request_proxy: str | None = None,
    trust_env: bool = True,
    client: Any | None = None,
) -> NewsCollectionResult:
    if client is not None:
        return _collect_with_client(
            retrieved_date=retrieved_date,
            storage_root=storage_root,
            calendar_url=calendar_url,
            client=client,
        )
    client_kwargs: dict[str, Any] = {
        "timeout": 20.0 if request_timeout is None else request_timeout,
        "headers": {"User-Agent": "finance-agent/0.1"},
        "trust_env": trust_env,
    }
    if request_proxy:
        client_kwargs["proxy"] = request_proxy
    with httpx.Client(**client_kwargs) as http_client:
        return _collect_with_client(
            retrieved_date=retrieved_date,
            storage_root=storage_root,
            calendar_url=calendar_url,
            client=http_client,
        )


def _collect_with_client(
    *,
    retrieved_date: str,
    storage_root: Path,
    calendar_url: str,
    client: Any,
) -> NewsCollectionResult:
    try:
        response = client.get(calendar_url)
        response.raise_for_status()
        calendar_text = response.text
    except Exception as exc:
        ref_status, reason_code, reason, extra_source_ref_fields = _classify_bls_fetch_failure(exc)
        warning = f"bls_calendar:release_calendar {reason_code}: {reason}"
        return NewsCollectionResult(
            source_key="bls_calendar",
            status="unavailable",
            items=[],
            unavailable_feeds=["release_calendar"],
            warnings=[warning],
            source_refs=[{
                "source_ref": "bls_calendar:release_calendar",
                "source": "bls_calendar",
                "source_url": calendar_url,
                "access_mode": BLS_ACCESS_MODE,
                "status": ref_status,
                "reason_code": reason_code,
                "reason": reason,
                "warning": warning,
                **extra_source_ref_fields,
            }],
        )

    fetched_at = utc_now_iso()
    raw_path = archive_news_payload(
        storage_root=storage_root,
        layer="raw",
        source_key="bls",
        retrieved_date=retrieved_date,
        name="release_calendar",
        payload={"source_key": "bls_calendar", "source_url": calendar_url, "fetched_at": fetched_at, "ics": calendar_text},
    )
    items = _parse_bls_ics(calendar_text=calendar_text, fetched_at=fetched_at)
    parsed_path = archive_news_payload(
        storage_root=storage_root,
        layer="parsed",
        source_key="bls",
        retrieved_date=retrieved_date,
        name="release_calendar",
        payload={
            "source_key": "bls_calendar",
            "source_url": calendar_url,
            "fetched_at": fetched_at,
            "items": [item.to_dict() for item in items],
        },
    )
    items = [RawNewsItem(**{**item.to_dict(), "raw_path": raw_path, "parsed_path": parsed_path}) for item in items]
    status = "success" if items else "unavailable"
    empty_reason = "BLS release calendar returned no parseable release events"
    empty_warning = f"bls_calendar:release_calendar no_items: {empty_reason}"
    return NewsCollectionResult(
        source_key="bls_calendar",
        status=status,
        items=items,
        warnings=[] if items else [empty_warning],
        source_refs=[{
            "source_ref": "bls_calendar:release_calendar",
            "source": "bls_calendar",
            "source_url": calendar_url,
            "access_mode": BLS_ACCESS_MODE,
            "raw_path": raw_path,
            "parsed_path": parsed_path,
            "status": "available" if items else "empty",
            **({"reason_code": "no_items", "reason": empty_reason, "warning": empty_warning} if not items else {}),
        }],
        unavailable_feeds=[] if items else ["release_calendar"],
    )


def _classify_bls_fetch_failure(exc: Exception) -> tuple[str, str, str, dict[str, Any]]:
    if isinstance(exc, httpx.HTTPStatusError):
        response = exc.response
        status_code = response.status_code
        server_header = response.headers.get("server", "")
        if status_code == 429:
            return (
                "rate_limited",
                "rate_limited",
                f"HTTP 429 from {BLS_CALENDAR_URL}",
                {"http_status": status_code},
            )
        if status_code == 403 and "akamai" in server_header.lower():
            return (
                "unavailable",
                "upstream_access_blocked",
                "HTTP 403 from official BLS ICS (Akamai)",
                {
                    "http_status": status_code,
                    "upstream_edge": "akamai",
                },
            )
        return (
            "unavailable",
            "upstream_http_error",
            f"HTTP {status_code} from {BLS_CALENDAR_URL}",
            {"http_status": status_code},
        )
    return (
        "network_blocked",
        "network_blocked",
        f"{type(exc).__name__}: {exc}",
        {},
    )


def _parse_bls_ics(*, calendar_text: str, fetched_at: str) -> list[RawNewsItem]:
    events = _parse_ics_events(calendar_text)
    items: list[RawNewsItem] = []
    for event in events:
        title = event.get("SUMMARY", "").strip()
        url = event.get("URL", "").strip() or "https://www.bls.gov/schedule/news_release/"
        if not title:
            continue
        published_at = _parse_ics_datetime(event.get("DTSTART", ""), event.get("DTSTART_TZID"))
        duplicate_key = stable_news_item_id(source_key="bls_calendar", title=title, url=url)
        items.append(RawNewsItem(
            source_key="bls_calendar",
            source_name=BLS_SOURCE_NAME,
            source_type="official",
            feed_key="release_calendar",
            title=title,
            url=url,
            domain=urlparse(url).netloc.lower().removeprefix("www.") or "bls.gov",
            published_at=published_at,
            fetched_at=fetched_at,
            summary=event.get("DESCRIPTION") or None,
            source_country="US",
            source_language="en",
            event_type=_classify_bls_event(title),
            verification_status="official_confirmed",
            duplicate_key=duplicate_key,
            raw_payload={"release_name": title},
        ))
    return items


def _parse_ics_events(calendar_text: str) -> list[dict[str, str]]:
    unfolded: list[str] = []
    for raw_line in calendar_text.splitlines():
        if not raw_line:
            continue
        if raw_line.startswith((" ", "\t")) and unfolded:
            unfolded[-1] += raw_line[1:]
        else:
            unfolded.append(raw_line.strip())

    events: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in unfolded:
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
            if current is not None:
                events.append(current)
            current = None
            continue
        if current is None or ":" not in line:
            continue
        raw_key, value = line.split(":", 1)
        parts = raw_key.split(";")
        key = parts[0].upper()
        current[key] = _decode_ics_text(value)
        for param in parts[1:]:
            if param.upper().startswith("TZID="):
                current[f"{key}_TZID"] = param.split("=", 1)[1]
    return events


def _decode_ics_text(value: str) -> str:
    return value.replace("\\n", " ").replace("\\,", ",").replace("\\;", ";").strip()


def _parse_ics_datetime(value: str, tzid: str | None) -> str | None:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            parsed = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        elif "T" in value:
            time_format = "%Y%m%dT%H%M%S" if len(value) == 15 else "%Y%m%dT%H%M"
            parsed = datetime.strptime(value, time_format)
            parsed = parsed.replace(tzinfo=ZoneInfo(tzid or "UTC"))
        else:
            parsed = datetime.strptime(value, "%Y%m%d").replace(tzinfo=ZoneInfo(tzid or "UTC"))
    except (ValueError, KeyError):
        return None
    return parsed.astimezone(timezone.utc).isoformat()


def _classify_bls_event(title: str) -> str:
    normalized = title.lower()
    if "consumer price" in normalized or "producer price" in normalized or "cpi" in normalized or "ppi" in normalized:
        return "inflation_release"
    if "employment situation" in normalized or "nonfarm" in normalized or "payroll" in normalized:
        return "labor_release"
    if "job openings" in normalized or "jolts" in normalized:
        return "labor_demand_release"
    return "macro_release_scheduled"
