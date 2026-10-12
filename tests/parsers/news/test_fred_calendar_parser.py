from __future__ import annotations

import pytest

from apps.parsers.news.fred_calendar import parse_fred_release_dates_payload

FETCHED_AT = "2026-09-06T00:00:00+00:00"
SOURCE_URL = "https://api.stlouisfed.org/fred/release/dates?release_id=10"


def test_fred_parser_keeps_future_dates_as_date_only_scheduled_items() -> None:
    payload = {
        "release_dates": [
            {"release_id": 10, "date": "2026-09-04"},
            {"release_id": 10, "date": "2026-09-11"},
            {"release_id": 10, "date": "2026-10-14"},
        ]
    }

    items = parse_fred_release_dates_payload(
        payload,
        release_id=10,
        fetched_at=FETCHED_AT,
        source_url=SOURCE_URL,
        start_date="2026-09-06",
        end_date="2026-09-30",
    )

    assert len(items) == 1
    item = items[0]
    assert item.source_key == "fred_calendar"
    assert item.feed_key == "release_dates"
    assert item.source_type == "official"
    assert item.title == "CPI release"
    assert item.published_at == "2026-09-11"
    assert "T" not in (item.published_at or "")
    assert item.event_type == "inflation_release"
    assert item.verification_status == "official_confirmed"
    assert item.raw_payload["event_status"] == "scheduled"
    assert item.raw_payload["time_precision"] == "day"
    assert item.raw_payload["time_status"] == "unavailable"
    assert "event_time" not in item.raw_payload


def test_fred_parser_rejects_unknown_release_and_reversed_range() -> None:
    with pytest.raises(ValueError, match="Unsupported FRED release ID"):
        parse_fred_release_dates_payload(
            {"release_dates": []},
            release_id=999,
            fetched_at=FETCHED_AT,
            source_url=SOURCE_URL,
        )

    with pytest.raises(ValueError, match="start_date cannot be after end_date"):
        parse_fred_release_dates_payload(
            {"release_dates": []},
            release_id=10,
            fetched_at=FETCHED_AT,
            source_url=SOURCE_URL,
            start_date="2026-10-01",
            end_date="2026-09-01",
        )
