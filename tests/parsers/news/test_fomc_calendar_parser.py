from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from apps.parsers.news.fomc_calendar import parse_fomc_calendar_html

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "news" / "fomc_calendar.html"
FETCHED_AT = "2026-09-06T00:00:00+00:00"


def test_fomc_parser_maps_years_preserves_sep_and_does_not_invent_time() -> None:
    html_text = FIXTURE.read_text(encoding="utf-8")

    items = parse_fomc_calendar_html(html_text, fetched_at=FETCHED_AT, year=2026)

    assert len(items) == 3
    assert [item.published_at for item in items] == ["2026-03-17", "2026-09-15", "2026-10-27"]
    assert items[1].title == "FOMC Meeting: September 15-16*, 2026"
    assert items[1].published_at is not None
    assert "T" not in items[1].published_at
    assert items[1].raw_payload["date_text"] == "15-16*"
    assert items[1].raw_payload["is_sep"] is True
    assert items[1].raw_payload["time_status"] == "unavailable"
    assert "Summary of Economic Projections (SEP)" in (items[1].summary or "")
    assert items[1].event_type == "fomc_meeting"
    assert items[1].verification_status == "official_confirmed"
    assert items[0].raw_payload["links"] == ["/monetarypolicy/files/fomcminutes20260318.pdf"]


def test_fomc_parser_filters_by_month_and_date_range() -> None:
    html_text = FIXTURE.read_text(encoding="utf-8")

    september = parse_fomc_calendar_html(html_text, fetched_at=FETCHED_AT, month="September")
    may = parse_fomc_calendar_html(html_text, fetched_at=FETCHED_AT, month=5)
    date_range = parse_fomc_calendar_html(
        html_text,
        fetched_at=FETCHED_AT,
        start_date=date(2026, 9, 1),
        end_date="2026-09-30",
    )

    assert [item.published_at for item in september] == ["2026-09-15"]
    assert [item.published_at for item in may] == ["2025-04-30"]
    assert date_range[0].raw_payload["end_date"] == "2026-09-16"


def test_fomc_parser_handles_single_day_notation_vote_and_cross_month_meeting() -> None:
    html_text = FIXTURE.read_text(encoding="utf-8")

    items = parse_fomc_calendar_html(html_text, fetched_at=FETCHED_AT, year=2025)

    assert items[0].published_at == "2025-04-30"
    assert items[0].raw_payload["end_date"] == "2025-05-01"
    assert items[1].published_at == "2025-08-22"
    assert "notation vote" in (items[1].summary or "")


def test_fomc_parser_rejects_reversed_date_range() -> None:
    with pytest.raises(ValueError, match="start_date cannot be after end_date"):
        parse_fomc_calendar_html(
            FIXTURE.read_text(encoding="utf-8"),
            fetched_at=FETCHED_AT,
            start_date="2026-10-01",
            end_date="2026-09-01",
        )
