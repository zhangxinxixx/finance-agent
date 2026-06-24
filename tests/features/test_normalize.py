"""Tests for CME option data normalization (M1: P3-CME-OPT-01)."""

from __future__ import annotations

import json
from pathlib import Path

from apps.features.options.normalize import (
    GroupedViews,
    NormalizationReport,
    build_grouped_views,
    normalize_option_rows,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "options"
SAMPLE_ROWS_PATH = FIXTURES / "sample_option_rows.json"


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

def _load_sample_rows() -> list[dict]:
    return json.loads(SAMPLE_ROWS_PATH.read_text())


def _make_row(
    *,
    trade_date: str = "2026-05-06",
    report_date: str = "2026-05-06",
    product_code: str = "OG",
    expiry: str = "JUL26",
    strike: int = 4000,
    option_type: str = "CALL",
    settlement: float | None = 100.0,
    delta: float | None = 0.5,
    open_interest: int | None = 1000,
    oi_change: int | None = 10,
    total_volume: int | None = 200,
    block_volume: int | None = 20,
    pnt_volume: int | None = 5,
    globex_volume: int | None = 100,
    outcry_volume: int | None = 50,
    exercises: int | None = 0,
    pt_change: float | None = 1.0,
) -> dict:
    return {
        "trade_date": trade_date,
        "report_date": report_date,
        "product_code": product_code,
        "expiry": expiry,
        "strike": strike,
        "option_type": option_type,
        "settlement": settlement,
        "delta": delta,
        "open_interest": open_interest,
        "oi_change": oi_change,
        "total_volume": total_volume,
        "block_volume": block_volume,
        "pnt_volume": pnt_volume,
        "globex_volume": globex_volume,
        "outcry_volume": outcry_volume,
        "exercises": exercises,
        "pt_change": pt_change,
    }


# -----------------------------------------------------------------------
# Put delta sign
# -----------------------------------------------------------------------

def test_put_delta_becomes_negative_for_exposure() -> None:
    """Put delta > 0 must be flipped to negative in normalized output."""
    row = _make_row(option_type="PUT", delta=0.35)
    normalized, report = normalize_option_rows([row])

    assert len(normalized) == 1
    r = normalized[0]
    assert r.option_type == "PUT"
    assert r.delta == -0.35, "Put delta should be negative for DEX"
    assert r.delta_raw == 0.35, "Raw delta should be preserved"


def test_put_delta_already_negative_stays_negative() -> None:
    """If delta is already negative, keep it."""
    row = _make_row(option_type="PUT", delta=-0.35)
    normalized, _ = normalize_option_rows([row])
    assert normalized[0].delta == -0.35


def test_call_delta_unchanged() -> None:
    """Call delta should remain positive."""
    row = _make_row(option_type="CALL", delta=0.65)
    normalized, _ = normalize_option_rows([row])
    assert normalized[0].delta == 0.65
    assert normalized[0].delta_raw == 0.65


def test_put_delta_none_stays_none() -> None:
    """Missing delta stays None for both delta and delta_raw."""
    row = _make_row(option_type="PUT", delta=None)
    normalized, _ = normalize_option_rows([row])
    assert normalized[0].delta is None
    assert normalized[0].delta_raw is None


# -----------------------------------------------------------------------
# Duplicate aggregation
# -----------------------------------------------------------------------

def test_duplicate_rows_are_aggregated() -> None:
    """Same (trade_date, expiry, strike, type) rows should merge."""
    row_a = _make_row(
        open_interest=1000,
        total_volume=200,
        settlement=100.0,
        delta=0.50,
        oi_change=10,
    )
    row_b = _make_row(
        open_interest=500,
        total_volume=100,
        settlement=102.0,
        delta=0.48,
        oi_change=5,
    )

    normalized, report = normalize_option_rows([row_a, row_b])

    assert len(normalized) == 1
    assert report.duplicates_merged == 1
    r = normalized[0]
    assert r.open_interest == 1500, "OI should be summed"
    assert r.total_volume == 300, "Volume should be summed"
    assert r.oi_change == 15, "OI change should be summed"
    # OI-weighted settlement: (100*1000 + 102*500) / 1500 = 100.666...
    assert abs(r.settlement - 100.6667) < 0.01, f"Expected OI-weighted settle ~100.67, got {r.settlement}"
    # OI-weighted delta: (0.50*1000 + 0.48*500) / 1500 = 0.4933
    assert abs(r.delta - 0.4933) < 0.01, f"Expected OI-weighted delta ~0.493, got {r.delta}"


def test_no_aggregation_when_disabled() -> None:
    """With aggregate_duplicates=False, duplicate rows stay separate."""
    row_a = _make_row(open_interest=1000)
    row_b = _make_row(open_interest=500)

    normalized, report = normalize_option_rows(
        [row_a, row_b],
        aggregate_duplicates=False,
    )

    assert len(normalized) == 2
    assert report.duplicates_merged == 0


def test_non_duplicate_rows_not_aggregated() -> None:
    """Different strike or type should NOT merge."""
    call_row = _make_row(strike=4000, option_type="CALL")
    put_row = _make_row(strike=4000, option_type="PUT")
    diff_strike = _make_row(strike=4100, option_type="CALL")

    normalized, report = normalize_option_rows([call_row, put_row, diff_strike])

    assert len(normalized) == 3
    assert report.duplicates_merged == 0


# -----------------------------------------------------------------------
# Strike interval filter
# -----------------------------------------------------------------------

def test_strike_filter_excludes_out_of_range() -> None:
    """Rows outside [strike_min, strike_max] should be filtered."""
    in_range = _make_row(strike=4200)
    below = _make_row(strike=3000)
    above = _make_row(strike=5500)

    normalized, report = normalize_option_rows([in_range, below, above])

    assert len(normalized) == 1
    assert normalized[0].strike == 4200
    assert report.rows_filtered_by_strike == 2


def test_custom_strike_range() -> None:
    """Custom strike_min/max should work."""
    row = _make_row(strike=4000)
    normalized, report = normalize_option_rows(
        [row],
        strike_min=4000,
        strike_max=4500,
    )
    assert len(normalized) == 1

    normalized2, report2 = normalize_option_rows(
        [row],
        strike_min=4500,
        strike_max=5000,
    )
    assert len(normalized2) == 0
    assert report2.rows_filtered_by_strike == 1


def test_filter_strikes_disabled() -> None:
    """With filter_strikes=False, all rows pass through."""
    low = _make_row(strike=2000)
    high = _make_row(strike=6000)

    normalized, report = normalize_option_rows(
        [low, high],
        filter_strikes=False,
    )
    assert len(normalized) == 2
    assert report.rows_filtered_by_strike == 0


# -----------------------------------------------------------------------
# Data quality flags
# -----------------------------------------------------------------------

def test_missing_settlement_flag() -> None:
    row = _make_row(settlement=None)
    normalized, report = normalize_option_rows([row])

    assert "missing_settlement" in normalized[0].data_quality
    assert report.rows_missing_settlement == 1


def test_missing_delta_flag() -> None:
    row = _make_row(delta=None)
    normalized, report = normalize_option_rows([row])

    assert "missing_delta" in normalized[0].data_quality
    assert report.rows_missing_delta == 1


def test_zero_oi_flag() -> None:
    row = _make_row(open_interest=0)
    normalized, report = normalize_option_rows([row])

    assert "zero_oi" in normalized[0].data_quality
    assert report.rows_missing_oi == 1


def test_low_oi_flag() -> None:
    row = _make_row(open_interest=5)
    normalized, _ = normalize_option_rows([row])

    assert "low_oi" in normalized[0].data_quality


def test_prelim_data_flag() -> None:
    row = _make_row()
    normalized, _ = normalize_option_rows([row], source="PRELIM")

    assert "prelim_data" in normalized[0].data_quality
    assert normalized[0].source == "PRELIM"


# -----------------------------------------------------------------------
# Parser-row dict input
# -----------------------------------------------------------------------

def test_dict_input_normalizes_correctly() -> None:
    """Plain dicts (parser output) should work as input."""
    row = _make_row()
    normalized, report = normalize_option_rows([row])

    assert len(normalized) == 1
    assert report.total_input_rows == 1
    r = normalized[0]
    assert r.strike == 4000
    assert r.settlement == 100.0
    assert r.option_type == "CALL"


# -----------------------------------------------------------------------
# Real 2026-05-06 sample fixture
# -----------------------------------------------------------------------

def test_sample_fixture_loads_and_normalizes() -> None:
    """Real parsed 2026-05-06 fixture should normalize without errors."""
    rows = _load_sample_rows()
    normalized, report = normalize_option_rows(rows, filter_strikes=True)

    assert report.total_input_rows == len(rows)
    # All sample strikes are within 3800-5000, so no filtering
    assert report.rows_filtered_by_strike == 0
    # JUL26 4100 CALL has null settlement
    assert report.rows_missing_settlement == 1
    # JUL26 4100 PUT has null delta
    assert report.rows_missing_delta == 1
    # All rows should normalize
    assert len(normalized) == len(rows)
    for r in normalized:
        assert r.trade_date == "2026-05-06"


def test_sample_fixture_without_filter() -> None:
    """Without strike filter, all sample rows should be present."""
    rows = _load_sample_rows()
    normalized, report = normalize_option_rows(rows, filter_strikes=False)

    assert report.total_input_rows == len(rows)
    assert report.rows_filtered_by_strike == 0
    assert len(normalized) == len(rows)


# -----------------------------------------------------------------------
# Grouped views
# -----------------------------------------------------------------------

def test_grouped_views_by_expiry() -> None:
    rows = _load_sample_rows()
    normalized, _ = normalize_option_rows(rows, filter_strikes=False)
    views = build_grouped_views(normalized)

    assert isinstance(views, GroupedViews)
    assert "JUN26" in views.by_expiry
    assert "JUL26" in views.by_expiry
    # All JUL26 calls together
    jul26_calls = views.call_by_expiry["JUL26"]
    assert all(r.option_type == "CALL" for r in jul26_calls)
    # All JUL26 puts together
    jul26_puts = views.put_by_expiry["JUL26"]
    assert all(r.option_type == "PUT" for r in jul26_puts)


def test_grouped_views_by_expiry_strike() -> None:
    rows = _load_sample_rows()
    normalized, _ = normalize_option_rows(rows, filter_strikes=False)
    views = build_grouped_views(normalized)

    # JUL26 strike 4200 should have CALL + PUT
    jul26_4200 = views.by_expiry_strike["JUL26"][4200]
    types = {r.option_type for r in jul26_4200}
    assert types == {"CALL", "PUT"}


# -----------------------------------------------------------------------
# Source passthrough
# -----------------------------------------------------------------------

def test_source_propagated_to_normalized_rows() -> None:
    row = _make_row()
    normalized, _ = normalize_option_rows([row], source="FINAL")
    assert normalized[0].source == "FINAL"


# -----------------------------------------------------------------------
# Aggregation with Put delta sign
# -----------------------------------------------------------------------

def test_aggregated_put_delta_is_negative() -> None:
    """Aggregated duplicate Put rows should have negative delta."""
    r1 = _make_row(option_type="PUT", delta=0.40, open_interest=1000)
    r2 = _make_row(option_type="PUT", delta=0.38, open_interest=500)

    normalized, _ = normalize_option_rows([r1, r2])
    assert len(normalized) == 1
    assert normalized[0].delta < 0, "Aggregated put delta should be negative"
    assert normalized[0].delta_raw > 0, "Raw delta should remain positive"


# -----------------------------------------------------------------------
# NormalizationReport structure
# -----------------------------------------------------------------------

def test_report_fields() -> None:
    rows = _load_sample_rows()
    _, report = normalize_option_rows(rows)

    assert isinstance(report, NormalizationReport)
    assert report.total_input_rows == len(rows)
    assert isinstance(report.duplicates_merged, int)
    assert isinstance(report.rows_missing_settlement, int)
    assert isinstance(report.rows_missing_delta, int)
    assert isinstance(report.rows_missing_oi, int)
    assert isinstance(report.rows_filtered_by_strike, int)
    assert isinstance(report.warnings, list)
