"""Parse official FRED release-date responses into scheduled news items."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from urllib.parse import urlparse

from apps.collectors.news.base import RawNewsItem, stable_news_item_id

FRED_RELEASE_DATES_URL = "https://api.stlouisfed.org/fred/release/dates"
FRED_CALENDAR_SOURCE_KEY = "fred_calendar"
FRED_CALENDAR_FEED_KEY = "release_dates"
FRED_CALENDAR_SOURCE_NAME = "FRED Release Dates"
FRED_CALENDAR_ACCESS_MODE = "official_fred_api"

# These IDs are the official FRED release records used for the CPI and PPI
# schedules.  Their release pages are kept as the item-level public reference;
# values are never fetched or inferred from this calendar source.
FRED_RELEASE_DEFINITIONS: dict[int, tuple[str, str]] = {
    10: ("CPI", "Consumer Price Index"),
    46: ("PPI", "Producer Price Index"),
}


def fred_release_page_url(release_id: int) -> str:
    """Return the public FRED release page for an official release ID."""

    if release_id not in FRED_RELEASE_DEFINITIONS:
        raise ValueError(f"Unsupported FRED release ID: {release_id}")
    return f"https://fred.stlouisfed.org/release?rid={release_id}"


def fred_release_dates_source_url(release_id: int, *, include_release_dates_with_no_data: bool = True) -> str:
    """Return an API reference URL without credentials in the query string."""

    if release_id not in FRED_RELEASE_DEFINITIONS:
        raise ValueError(f"Unsupported FRED release ID: {release_id}")
    include_no_data = "true" if include_release_dates_with_no_data else "false"
    return f"{FRED_RELEASE_DATES_URL}?release_id={release_id}&file_type=json&include_release_dates_with_no_data={include_no_data}"


def parse_fred_release_dates_payload(
    payload: Mapping[str, object],
    *,
    release_id: int,
    fetched_at: str,
    source_url: str,
    start_date: str | date | None = None,
    end_date: str | date | None = None,
    include_release_dates_with_no_data: bool = True,
) -> list[RawNewsItem]:
    """Parse date-only FRED release records into scheduled ``RawNewsItem`` s.

    ``release/dates`` returns both historical dates and future dates included
    by ``include_release_dates_with_no_data``.  The collector supplies the
    retrieval date as ``start_date`` so the news pipeline receives only
    current/future schedule entries.  No release clock time is synthesized.
    """

    if not isinstance(payload, Mapping):
        raise ValueError("FRED release dates payload must be an object")
    if release_id not in FRED_RELEASE_DEFINITIONS:
        raise ValueError(f"Unsupported FRED release ID: {release_id}")
    if not isinstance(fetched_at, str) or not fetched_at:
        raise ValueError("fetched_at is required")
    start = _coerce_date(start_date)
    end = _coerce_date(end_date)
    if start is not None and end is not None and start > end:
        raise ValueError("start_date cannot be after end_date")

    short_name, release_name = FRED_RELEASE_DEFINITIONS[release_id]
    release_page_url = fred_release_page_url(release_id)
    release_dates = payload.get("release_dates")
    if not isinstance(release_dates, list):
        raise ValueError("FRED response is missing release_dates")

    items: list[RawNewsItem] = []
    seen_dates: set[date] = set()
    for record in release_dates:
        if not isinstance(record, Mapping):
            continue
        record_release_id = record.get("release_id")
        if record_release_id is not None and str(record_release_id) != str(release_id):
            continue
        observation_date = _coerce_date(record.get("date"))
        if observation_date is None or observation_date in seen_dates:
            continue
        if start is not None and observation_date < start:
            continue
        if end is not None and observation_date > end:
            continue
        seen_dates.add(observation_date)
        release_date = observation_date.isoformat()
        title = f"{short_name} release"
        items.append(
            RawNewsItem(
                source_key=FRED_CALENDAR_SOURCE_KEY,
                source_name=FRED_CALENDAR_SOURCE_NAME,
                source_type="official",
                feed_key=FRED_CALENDAR_FEED_KEY,
                title=title,
                url=release_page_url,
                domain=urlparse(release_page_url).netloc.lower().removeprefix("www.") or "fred.stlouisfed.org",
                published_at=release_date,
                fetched_at=fetched_at,
                summary=f"Scheduled {release_name} release date from the official FRED release calendar.",
                source_country="US",
                source_language="en",
                event_type="inflation_release",
                verification_status="official_confirmed",
                duplicate_key=stable_news_item_id(
                    source_key=FRED_CALENDAR_SOURCE_KEY,
                    title=f"{title} {release_date}",
                    url=release_page_url,
                ),
                raw_payload={
                    "release_id": release_id,
                    "release_short_name": short_name,
                    "release_name": release_name,
                    "release_date": release_date,
                    "event_status": "scheduled",
                    "time_precision": "day",
                    "time_status": "unavailable",
                    "include_release_dates_with_no_data": include_release_dates_with_no_data,
                    "source_url": source_url,
                },
            )
        )
    items.sort(key=lambda item: item.published_at or "")
    return items


def _coerce_date(value: object | None) -> date | None:
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


__all__ = [
    "FRED_CALENDAR_ACCESS_MODE",
    "FRED_CALENDAR_FEED_KEY",
    "FRED_CALENDAR_SOURCE_KEY",
    "FRED_CALENDAR_SOURCE_NAME",
    "FRED_RELEASE_DATES_URL",
    "FRED_RELEASE_DEFINITIONS",
    "fred_release_dates_source_url",
    "fred_release_page_url",
    "parse_fred_release_dates_payload",
]
