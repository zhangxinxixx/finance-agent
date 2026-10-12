from __future__ import annotations

import json
from pathlib import Path

from apps.features.research.sessions import (
    CME_LABOR_DAY_2026_REFERENCE,
    HOLIDAY_CONFIDENCE_MULTIPLIER,
    build_session_quality,
)


FIXTURE = Path(__file__).parents[2] / "fixtures" / "research" / "session_calendar_2026.json"


def _snapshot(trade_date: str, *, otc_date: str | None = None, include_otc: bool = True) -> dict:
    technical = {
        "as_of": otc_date or trade_date,
        "price": 2500.0,
        "source_refs": [{"source": "twelvedata_xauusd_daily", "reference": "fixture:otc"}],
    }
    return {
        "trade_date": trade_date,
        "technical": {"data": technical if include_otc else {}},
        "options": {"data": {}},
    }


def test_labor_day_cme_closure_keeps_an_observed_otc_close_separate() -> None:
    result = build_session_quality(_snapshot("2026-09-07"))

    assert result["session_class"] == "HOLIDAY"
    assert result["cme_settlement"]["status"] == "unavailable"
    assert result["cme_settlement"]["available"] is False
    assert result["otc_daily_close"]["status"] == "available"
    assert result["confidence_multiplier"] == HOLIDAY_CONFIDENCE_MULTIPLIER
    assert any(ref.get("reference") == CME_LABOR_DAY_2026_REFERENCE for ref in result["source_refs"])


def test_weekend_and_cross_year_rules_do_not_copy_a_prior_otc_close_as_current() -> None:
    weekend = build_session_quality(_snapshot("2025-12-27", include_otc=False))
    new_year = build_session_quality(_snapshot("2026-01-01", include_otc=False))
    ordinary = build_session_quality(_snapshot("2025-12-31"))

    assert weekend["session_class"] == "HOLIDAY"
    assert weekend["day_type"] == "WEEKEND"
    assert weekend["otc_daily_close"]["status"] == "unavailable"
    assert new_year["session_class"] == "HOLIDAY"
    assert ordinary["session_class"] == "NORMAL"


def test_missing_calendar_is_partial_and_does_not_assume_normal() -> None:
    result = build_session_quality(_snapshot("2026-09-08"), calendar={})

    assert result["session_class"] == "PARTIAL"
    assert result["calendar_available"] is False
    assert result["calendar_known"] is False


def test_provided_early_close_entry_is_traceable_without_inventing_low_liquidity() -> None:
    calendar = json.loads(FIXTURE.read_text(encoding="utf-8"))
    result = build_session_quality(_snapshot("2026-11-27"), calendar=calendar)

    assert result["session_class"] == "EARLY_CLOSE"
    assert result["liquidity_class"] == "UNKNOWN"
    assert result["calendar_version"] == "cme_otc_session_calendar.2026.fixture"
    assert result["cme_settlement"]["status"] == "unknown"


def test_explicit_low_liquidity_is_distinct_from_a_cme_holiday() -> None:
    snapshot = _snapshot("2026-09-08")
    snapshot["session_quality"] = {
        "session_class": "LOW_LIQUIDITY",
        "liquidity_class": "LOW_LIQUIDITY",
        "confidence_multiplier": 1.0,
    }
    result = build_session_quality(snapshot)

    assert result["session_class"] == "LOW_LIQUIDITY"
    assert result["liquidity_class"] == "LOW_LIQUIDITY"
    assert result["cme_settlement"]["status"] == "unknown"
