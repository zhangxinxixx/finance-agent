"""Collect the Federal Reserve's official FOMC meeting calendar."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from apps.collectors.news.base import NewsCollectionResult, RawNewsItem, archive_news_payload, utc_now_iso
from apps.parsers.news.fomc_calendar import (
    FOMC_ACCESS_MODE,
    FOMC_CALENDAR_URL,
    FOMC_FEED_KEY,
    FOMC_SOURCE_KEY,
    FOMCParseError,
    parse_fomc_calendar_html,
)

FOMC_DEFAULT_REQUEST_TIMEOUT_SECONDS = 20.0


def collect_fomc_calendar(
    *,
    retrieved_date: str,
    storage_root: Path,
    calendar_url: str = FOMC_CALENDAR_URL,
    years: Iterable[int] | None = None,
    year: int | None = None,
    months: Iterable[int | str] | None = None,
    month: int | str | None = None,
    start_date: str | date | None = None,
    end_date: str | date | None = None,
    request_timeout: float | httpx.Timeout | None = None,
    client: Any | None = None,
) -> NewsCollectionResult:
    """Fetch, archive, and parse official scheduled FOMC meetings.

    Filters are applied to the parsed meeting interval.  A meeting spanning a
    requested date or month is retained.  The official calendar publishes no
    meeting clock time, so item ``published_at`` is date-only.
    """

    _validate_retrieved_date(retrieved_date)
    normalized_years = tuple(years) if years is not None else None
    normalized_months = tuple(months) if months is not None else None
    if client is not None:
        return _collect_with_client(
            retrieved_date=retrieved_date,
            storage_root=storage_root,
            calendar_url=calendar_url,
            years=normalized_years,
            year=year,
            months=normalized_months,
            month=month,
            start_date=start_date,
            end_date=end_date,
            client=client,
        )

    with httpx.Client(
        timeout=FOMC_DEFAULT_REQUEST_TIMEOUT_SECONDS if request_timeout is None else request_timeout,
        headers={"User-Agent": "finance-agent/0.1"},
        trust_env=False,
    ) as http_client:
        return _collect_with_client(
            retrieved_date=retrieved_date,
            storage_root=storage_root,
            calendar_url=calendar_url,
            years=normalized_years,
            year=year,
            months=normalized_months,
            month=month,
            start_date=start_date,
            end_date=end_date,
            client=http_client,
        )


def _collect_with_client(
    *,
    retrieved_date: str,
    storage_root: Path,
    calendar_url: str,
    years: tuple[int, ...] | None,
    year: int | None,
    months: tuple[int | str, ...] | None,
    month: int | str | None,
    start_date: str | date | None,
    end_date: str | date | None,
    client: Any,
) -> NewsCollectionResult:
    try:
        response = client.get(calendar_url)
        response.raise_for_status()
        html_text = response.text
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        warning = f"{FOMC_SOURCE_KEY}:{FOMC_FEED_KEY} fetch_failed: {reason}"
        return NewsCollectionResult(
            source_key=FOMC_SOURCE_KEY,
            status="unavailable",
            items=[],
            unavailable_feeds=[FOMC_FEED_KEY],
            warnings=[warning],
            source_refs=[
                {
                    "source_ref": f"{FOMC_SOURCE_KEY}:{FOMC_FEED_KEY}",
                    "source": FOMC_SOURCE_KEY,
                    "feed_key": FOMC_FEED_KEY,
                    "source_url": calendar_url,
                    "access_mode": FOMC_ACCESS_MODE,
                    "status": "failed",
                    "reason_code": "fetch_failed",
                    "reason": reason,
                    "warning": warning,
                    **_filter_fields(
                        years=years,
                        year=year,
                        months=months,
                        month=month,
                        start_date=start_date,
                        end_date=end_date,
                    ),
                }
            ],
        )

    fetched_at = utc_now_iso()
    raw_path = archive_news_payload(
        storage_root=storage_root,
        layer="raw",
        source_key=FOMC_SOURCE_KEY,
        retrieved_date=retrieved_date,
        name="meeting_calendar",
        payload={
            "source_key": FOMC_SOURCE_KEY,
            "feed_key": FOMC_FEED_KEY,
            "source_url": calendar_url,
            "fetched_at": fetched_at,
            "html": html_text,
        },
    )

    parse_error: str | None = None
    try:
        parsed_items = parse_fomc_calendar_html(
            html_text,
            fetched_at=fetched_at,
            source_url=calendar_url,
            years=years,
            year=year,
            months=months,
            month=month,
            start_date=start_date,
            end_date=end_date,
        )
    except (FOMCParseError, ValueError) as exc:
        parsed_items = []
        parse_error = f"{type(exc).__name__}: {exc}"

    parsed_path = archive_news_payload(
        storage_root=storage_root,
        layer="parsed",
        source_key=FOMC_SOURCE_KEY,
        retrieved_date=retrieved_date,
        name="meeting_calendar",
        payload={
            "source_key": FOMC_SOURCE_KEY,
            "feed_key": FOMC_FEED_KEY,
            "source_url": calendar_url,
            "fetched_at": fetched_at,
            "filters": _filter_fields(
                years=years,
                year=year,
                months=months,
                month=month,
                start_date=start_date,
                end_date=end_date,
            ),
            "parse_error": parse_error,
            "items": [item.to_dict() for item in parsed_items],
        },
    )
    items = [
        RawNewsItem(**{**item.to_dict(), "raw_path": raw_path, "parsed_path": parsed_path}) for item in parsed_items
    ]
    source_ref = {
        "source_ref": f"{FOMC_SOURCE_KEY}:{FOMC_FEED_KEY}",
        "source": FOMC_SOURCE_KEY,
        "feed_key": FOMC_FEED_KEY,
        "source_url": calendar_url,
        "access_mode": FOMC_ACCESS_MODE,
        "raw_path": raw_path,
        "parsed_path": parsed_path,
        "status": "available" if items else "empty",
        **_filter_fields(
            years=years,
            year=year,
            months=months,
            month=month,
            start_date=start_date,
            end_date=end_date,
        ),
    }
    if parse_error:
        reason = f"FOMC calendar parse failed: {parse_error}"
        warning = f"{FOMC_SOURCE_KEY}:{FOMC_FEED_KEY} parse_failed: {reason}"
        source_ref.update({"reason_code": "parse_failed", "reason": reason, "warning": warning})
    elif not items:
        reason = "FOMC calendar returned no meetings matching the requested filters"
        warning = f"{FOMC_SOURCE_KEY}:{FOMC_FEED_KEY} no_items: {reason}"
        source_ref.update({"reason_code": "no_items", "reason": reason, "warning": warning})
    else:
        warning = None

    return NewsCollectionResult(
        source_key=FOMC_SOURCE_KEY,
        status="success" if items else "unavailable",
        items=items,
        source_refs=[source_ref],
        unavailable_feeds=[] if items else [FOMC_FEED_KEY],
        warnings=[] if warning is None else [warning],
    )


def _filter_fields(
    *,
    years: tuple[int, ...] | None,
    year: int | None,
    months: tuple[int | str, ...] | None,
    month: int | str | None,
    start_date: str | date | None,
    end_date: str | date | None,
) -> dict[str, Any]:
    return {
        "years": list(years) if years is not None else None,
        "year": year,
        "months": list(months) if months is not None else None,
        "month": month,
        "start_date": _date_text(start_date),
        "end_date": _date_text(end_date),
    }


def _date_text(value: str | date | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() if isinstance(value, date) else value


def _validate_retrieved_date(value: str) -> None:
    if not isinstance(value, str):
        raise ValueError("retrieved_date must be an ISO date string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("retrieved_date must be YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise ValueError("retrieved_date must be YYYY-MM-DD")
