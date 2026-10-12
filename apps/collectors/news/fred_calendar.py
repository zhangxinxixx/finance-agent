"""Collect official CPI/PPI release dates from the FRED API."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from apps.collectors.news.base import NewsCollectionResult, RawNewsItem, archive_news_payload, utc_now_iso
from apps.parsers.news.fred_calendar import (
    FRED_CALENDAR_ACCESS_MODE,
    FRED_CALENDAR_FEED_KEY,
    FRED_CALENDAR_SOURCE_KEY,
    FRED_CALENDAR_SOURCE_NAME,
    FRED_RELEASE_DATES_URL,
    FRED_RELEASE_DEFINITIONS,
    fred_release_dates_source_url,
    parse_fred_release_dates_payload,
)
from apps.runtime.secret_resolver import resolve_runtime_secret

FRED_RELEASE_CALENDAR_DEFAULT_TIMEOUT_SECONDS = 20.0
FRED_RELEASE_CALENDAR_RELEASE_IDS = (10, 46)


def collect_fred_release_calendar(
    *,
    retrieved_date: str,
    storage_root: Path,
    release_ids: Iterable[int] = FRED_RELEASE_CALENDAR_RELEASE_IDS,
    api_key: str | None = None,
    include_release_dates_with_no_data: bool = True,
    request_timeout: float | httpx.Timeout | None = None,
    client: Any | None = None,
) -> NewsCollectionResult:
    """Fetch CPI/PPI date-only schedules from official FRED release records.

    FRED requires an API key for this endpoint.  The key is read from the
    existing runtime secret resolver and is only sent in the request query;
    it is never written to archives, source references, warnings, or logs.
    Future dates are enabled through ``include_release_dates_with_no_data``;
    the parser intentionally emits no release clock time.
    """

    cutoff = _validate_date(retrieved_date, field_name="retrieved_date")
    requested_ids = tuple(release_ids)
    _validate_release_ids(requested_ids)
    if not requested_ids:
        return NewsCollectionResult(
            source_key=FRED_CALENDAR_SOURCE_KEY,
            status="empty",
            items=[],
            source_refs=[],
        )
    resolved_api_key = (api_key or resolve_runtime_secret("FRED_API_KEY") or "").strip()
    if not resolved_api_key:
        return _credentials_unavailable(retrieved_date=retrieved_date, requested_ids=requested_ids)

    if client is not None:
        return _collect_with_client(
            client=client,
            retrieved_date=retrieved_date,
            cutoff=cutoff,
            storage_root=storage_root,
            release_ids=requested_ids,
            api_key=resolved_api_key,
            include_release_dates_with_no_data=include_release_dates_with_no_data,
        )

    with httpx.Client(
        timeout=FRED_RELEASE_CALENDAR_DEFAULT_TIMEOUT_SECONDS if request_timeout is None else request_timeout,
        headers={"User-Agent": "finance-agent/0.1"},
        trust_env=False,
    ) as http_client:
        return _collect_with_client(
            client=http_client,
            retrieved_date=retrieved_date,
            cutoff=cutoff,
            storage_root=storage_root,
            release_ids=requested_ids,
            api_key=resolved_api_key,
            include_release_dates_with_no_data=include_release_dates_with_no_data,
        )


def _collect_with_client(
    *,
    client: Any,
    retrieved_date: str,
    cutoff: date,
    storage_root: Path,
    release_ids: tuple[int, ...],
    api_key: str,
    include_release_dates_with_no_data: bool,
) -> NewsCollectionResult:
    fetched_at = utc_now_iso()
    all_items: list[RawNewsItem] = []
    source_refs: list[dict[str, Any]] = []
    unavailable_feeds: list[str] = []

    for release_id in release_ids:
        source_url = fred_release_dates_source_url(
            release_id,
            include_release_dates_with_no_data=include_release_dates_with_no_data,
        )
        release_short_name, release_name = FRED_RELEASE_DEFINITIONS[release_id]
        params = {
            "release_id": str(release_id),
            "api_key": api_key,
            "file_type": "json",
            "include_release_dates_with_no_data": "true" if include_release_dates_with_no_data else "false",
            "sort_order": "asc",
            "order_by": "release_date",
            "limit": "1000",
        }
        try:
            response = client.get(FRED_RELEASE_DATES_URL, params=params)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            reason = _safe_failure_reason(exc)
            unavailable_feeds.append(_feed_name(release_id))
            source_refs.append(
                _source_ref(
                    release_id=release_id,
                    release_short_name=release_short_name,
                    release_name=release_name,
                    source_url=source_url,
                    fetched_at=fetched_at,
                    status="failed",
                    reason_code="fetch_failed",
                    reason=reason,
                )
            )
            continue

        raw_path = archive_news_payload(
            storage_root=storage_root,
            layer="raw",
            source_key=FRED_CALENDAR_SOURCE_KEY,
            retrieved_date=retrieved_date,
            name=f"release_dates_{release_id}",
            payload={
                "source_key": FRED_CALENDAR_SOURCE_KEY,
                "feed_key": FRED_CALENDAR_FEED_KEY,
                "release_id": release_id,
                "release_short_name": release_short_name,
                "release_name": release_name,
                "source_url": source_url,
                "fetched_at": fetched_at,
                "request": {key: value for key, value in params.items() if key != "api_key"},
                "response": payload,
            },
        )
        parse_error: str | None = None
        try:
            parsed_items = parse_fred_release_dates_payload(
                payload,
                release_id=release_id,
                fetched_at=fetched_at,
                source_url=source_url,
                start_date=cutoff,
                include_release_dates_with_no_data=include_release_dates_with_no_data,
            )
        except (TypeError, ValueError) as exc:
            parsed_items = []
            parse_error = f"{type(exc).__name__}: {exc}"
        parsed_path = archive_news_payload(
            storage_root=storage_root,
            layer="parsed",
            source_key=FRED_CALENDAR_SOURCE_KEY,
            retrieved_date=retrieved_date,
            name=f"release_dates_{release_id}",
            payload={
                "source_key": FRED_CALENDAR_SOURCE_KEY,
                "feed_key": FRED_CALENDAR_FEED_KEY,
                "release_id": release_id,
                "release_short_name": release_short_name,
                "release_name": release_name,
                "source_url": source_url,
                "fetched_at": fetched_at,
                "include_release_dates_with_no_data": include_release_dates_with_no_data,
                "parse_error": parse_error,
                "items": [item.to_dict() for item in parsed_items],
            },
        )
        items = [
            RawNewsItem(**{**item.to_dict(), "raw_path": raw_path, "parsed_path": parsed_path}) for item in parsed_items
        ]
        all_items.extend(items)
        status = "available" if items else "empty"
        ref = _source_ref(
            release_id=release_id,
            release_short_name=release_short_name,
            release_name=release_name,
            source_url=source_url,
            fetched_at=fetched_at,
            raw_path=raw_path,
            parsed_path=parsed_path,
            status=status,
            reason_code="parse_failed" if parse_error else ("no_future_dates" if not items else None),
            reason=f"FRED release dates parse failed: {parse_error}" if parse_error else None,
        )
        source_refs.append(ref)
        if not items:
            unavailable_feeds.append(_feed_name(release_id))

    if all_items and unavailable_feeds:
        status = "partial"
    elif all_items:
        status = "success"
    else:
        status = "unavailable"
    return NewsCollectionResult(
        source_key=FRED_CALENDAR_SOURCE_KEY,
        status=status,
        items=sorted(all_items, key=lambda item: (item.published_at or "", item.title)),
        source_refs=source_refs,
        unavailable_feeds=unavailable_feeds,
        warnings=[f"{FRED_CALENDAR_SOURCE_KEY}:{feed} unavailable" for feed in unavailable_feeds],
    )


def _source_ref(
    *,
    release_id: int,
    release_short_name: str,
    release_name: str,
    source_url: str,
    fetched_at: str,
    status: str,
    reason_code: str | None = None,
    reason: str | None = None,
    raw_path: str | None = None,
    parsed_path: str | None = None,
) -> dict[str, Any]:
    ref: dict[str, Any] = {
        "source_ref": f"{FRED_CALENDAR_SOURCE_KEY}:{release_id}",
        "source": FRED_CALENDAR_SOURCE_KEY,
        "source_name": FRED_CALENDAR_SOURCE_NAME,
        "feed_key": FRED_CALENDAR_FEED_KEY,
        "source_url": source_url,
        "access_mode": FRED_CALENDAR_ACCESS_MODE,
        "release_id": release_id,
        "release_short_name": release_short_name,
        "release_name": release_name,
        "fetched_at": fetched_at,
        "time_precision": "day",
        "status": status,
    }
    if raw_path is not None:
        ref["raw_path"] = raw_path
    if parsed_path is not None:
        ref["parsed_path"] = parsed_path
    if reason_code is not None:
        ref["reason_code"] = reason_code
    if reason is not None:
        ref["reason"] = reason
    return ref


def _credentials_unavailable(*, retrieved_date: str, requested_ids: tuple[int, ...]) -> NewsCollectionResult:
    refs = []
    for release_id in requested_ids:
        short_name, release_name = FRED_RELEASE_DEFINITIONS[release_id]
        refs.append(
            _source_ref(
                release_id=release_id,
                release_short_name=short_name,
                release_name=release_name,
                source_url=fred_release_dates_source_url(release_id),
                fetched_at=utc_now_iso(),
                status="failed",
                reason_code="missing_credentials",
                reason="FRED_API_KEY is unavailable",
            )
        )
    return NewsCollectionResult(
        source_key=FRED_CALENDAR_SOURCE_KEY,
        status="unavailable",
        items=[],
        source_refs=refs,
        unavailable_feeds=[_feed_name(release_id) for release_id in requested_ids],
        warnings=[f"{FRED_CALENDAR_SOURCE_KEY}:missing_credentials"],
    )


def _safe_failure_reason(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return type(exc).__name__


def _feed_name(release_id: int) -> str:
    return f"{FRED_CALENDAR_FEED_KEY}:{release_id}"


def _validate_release_ids(release_ids: Iterable[int]) -> None:
    unsupported = [release_id for release_id in release_ids if release_id not in FRED_RELEASE_DEFINITIONS]
    if unsupported:
        raise ValueError(f"Unsupported FRED release IDs: {', '.join(str(value) for value in unsupported)}")


def _validate_date(value: str, *, field_name: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be an ISO date string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{field_name} must be YYYY-MM-DD")
    return parsed


__all__ = [
    "FRED_RELEASE_CALENDAR_DEFAULT_TIMEOUT_SECONDS",
    "FRED_RELEASE_CALENDAR_RELEASE_IDS",
    "collect_fred_release_calendar",
]
