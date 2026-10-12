from __future__ import annotations

from pathlib import Path

from apps.collectors.news.base import RawNewsItem
from apps.features.news.official_calendar import build_official_calendar_snapshot
from apps.parsers.news.fred_calendar import parse_fred_release_dates_payload
from apps.parsers.news.fomc_calendar import parse_fomc_calendar_html

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "news" / "fomc_calendar.html"
AS_OF = "2026-09-06T12:31:00+00:00"


def test_official_calendar_projects_only_upcoming_14d_without_a_clock_time() -> None:
    items = parse_fomc_calendar_html(
        FIXTURE.read_text(encoding="utf-8"),
        fetched_at=AS_OF,
        year=2026,
    )

    snapshot = build_official_calendar_snapshot(
        [*items, *items],
        as_of=AS_OF,
        source_refs=[
            {
                "source": "fomc_calendar",
                "source_ref": "fomc_calendar:fomc_meetings",
                "status": "available",
            }
        ],
    )

    assert snapshot["status"] == "available"
    assert snapshot["window_start_date"] == "2026-09-06"
    assert snapshot["window_end_date"] == "2026-09-20"
    assert len(snapshot["events"]) == 1
    event = snapshot["events"][0]
    assert event["start_date"] == "2026-09-15"
    assert event["end_date"] == "2026-09-16"
    assert event["date_text"] == "15-16*"
    assert event["is_sep"] is True
    assert event["event_status"] == "scheduled"
    assert event["time_precision"] == "day"
    assert event["time_status"] == "unavailable"
    assert "event_time" not in event
    assert event["source_refs"][0]["source"] == "fomc_calendar"


def test_official_calendar_preserves_unavailable_source_status_without_fake_events() -> None:
    snapshot = build_official_calendar_snapshot(
        [],
        as_of=AS_OF,
        source_refs=[
            {
                "source": "fomc_calendar",
                "source_ref": "fomc_calendar:fomc_meetings",
                "status": "failed",
                "reason_code": "fetch_failed",
            }
        ],
    )

    assert snapshot["status"] == "unavailable"
    assert snapshot["events"] == []
    assert snapshot["reason"] == "official_calendar_unavailable"
    assert snapshot["source_refs"][0]["reason_code"] == "fetch_failed"


def test_official_calendar_combines_fred_cpi_ppi_dates_without_event_time() -> None:
    items = parse_fred_release_dates_payload(
        {
            "release_dates": [
                {"release_id": 46, "date": "2026-09-10"},
            ]
        },
        release_id=46,
        fetched_at=AS_OF,
        source_url="https://api.stlouisfed.org/fred/release/dates?release_id=46",
        start_date="2026-09-06",
    )
    items.extend(
        parse_fred_release_dates_payload(
            {"release_dates": [{"release_id": 10, "date": "2026-09-11"}]},
            release_id=10,
            fetched_at=AS_OF,
            source_url="https://api.stlouisfed.org/fred/release/dates?release_id=10",
            start_date="2026-09-06",
        )
    )

    snapshot = build_official_calendar_snapshot(
        items,
        as_of=AS_OF,
        source_refs=[
            {"source": "fred_calendar", "source_ref": "fred_calendar:46", "status": "available"},
            {"source": "fred_calendar", "source_ref": "fred_calendar:10", "status": "available"},
            {
                "source": "bls_calendar",
                "source_ref": "bls_calendar:release_calendar",
                "status": "unavailable",
                "reason_code": "upstream_access_blocked",
                "http_status": 403,
            },
        ],
    )

    assert snapshot["status"] == "available"
    assert snapshot["source_key"] == "official_calendar"
    assert snapshot["source_keys"] == ["bls_calendar", "fred_calendar"]
    assert [(event["title"], event["start_date"]) for event in snapshot["events"]] == [
        ("PPI release", "2026-09-10"),
        ("CPI release", "2026-09-11"),
    ]
    assert all(event["event_status"] == "scheduled" for event in snapshot["events"])
    assert all(event["time_precision"] == "day" for event in snapshot["events"])
    assert all(event["time_status"] == "unavailable" for event in snapshot["events"])
    assert all("event_time" not in event for event in snapshot["events"])
    assert {event["source_refs"][0]["source"] for event in snapshot["events"]} == {"fred_calendar"}
    assert all(
        "api.stlouisfed.org/fred/release/dates" in event["source_refs"][0]["source_url"] for event in snapshot["events"]
    )


def test_official_calendar_keeps_other_scheduled_release_sources_out_of_event_time() -> None:
    item = RawNewsItem(
        source_key="bea_calendar",
        source_name="BEA Release Schedule",
        source_type="official",
        feed_key="release_schedule",
        title="Personal Income and Outlays",
        url="https://www.bea.gov/news/schedule",
        domain="bea.gov",
        published_at="2026-09-14T12:30:00+00:00",
        fetched_at=AS_OF,
        event_type="pce_release",
        verification_status="official_confirmed",
        duplicate_key="bea:pce:2026-09-14",
        raw_payload={"release_name": "Personal Income and Outlays"},
    )

    snapshot = build_official_calendar_snapshot([item], as_of=AS_OF)

    assert snapshot["status"] == "available"
    assert snapshot["events"][0]["start_date"] == "2026-09-14"
    assert snapshot["events"][0]["event_status"] == "scheduled"
    assert snapshot["events"][0]["time_precision"] == "day"
    assert "event_time" not in snapshot["events"][0]
