from datetime import date, timedelta

from apps.features.technical.snapshot import build_price_structure


def test_previous_range_excludes_latest_extreme_and_records_close_breach():
    dates = [(date(2026, 8, 1) + timedelta(days=i)).isoformat() for i in range(22)]
    result = build_price_structure(dates=dates, closes=[100] * 21 + [90], highs=[105] * 21 + [101], lows=[95] * 21 + [89])
    assert result["status"] == "available"
    lows = [item for item in result["levels"] if item["kind"].endswith("low")]
    assert all(item["price"] == 95 and item["status"] == "broken_on_close" for item in lows)
    assert all(item["window_end"] == dates[-2] and item["formal_state_line"] is False for item in lows)


def test_intraday_breach_reclaimed_on_close_and_bad_alignment_stays_unavailable():
    dates = [f"2026-09-0{i}" for i in range(1, 7)]
    result = build_price_structure(dates=dates, closes=[100] * 6, highs=[105] * 6, lows=[95] * 5 + [94])
    low = next(item for item in result["levels"] if item["kind"] == "prior_5d_low")
    assert low["status"] == "reclaimed_after_intraday_breach"
    assert build_price_structure(dates=dates, closes=[100] * 5, highs=[105] * 6, lows=[95] * 6)["status"] == "unavailable"
