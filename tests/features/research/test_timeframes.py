from __future__ import annotations

from datetime import datetime, timedelta

from apps.features.research.timeframes import build_execution_timeframe_features


def _bars(day: str = "2026-09-07") -> list[dict[str, object]]:
    opened = datetime.fromisoformat(f"{day}T00:00:00+00:00")
    rows = []
    for index in range(3):
        start = opened + timedelta(minutes=5 * index)
        close = start + timedelta(minutes=5)
        price = 100.0 + index
        rows.append(
            {
                "open_time": start.isoformat(),
                "close_time": close.isoformat(),
                "open": price - 0.2,
                "high": price + 0.2,
                "low": price - 0.3,
                "close": price,
            }
        )
    return rows


def _raw(day: str = "2026-09-07") -> dict[str, dict[str, object]]:
    return {
        "5m": {
            "status": "available",
            "timeframe": "5m",
            "interval": "5min",
            "timezone": "UTC",
            "retrieved_at": f"{day}T00:16:00+00:00",
            "closed_before": f"{day}T00:15:30+00:00",
            "bars": _bars(day),
        }
    }


def test_holiday_with_otc_observation_keeps_completed_spot_execution_eligible() -> None:
    result = build_execution_timeframe_features(
        _raw(),
        analysis_date="2026-09-07",
        session_quality={
            "session_class": "HOLIDAY",
            "liquidity_class": "UNKNOWN",
            "confidence_multiplier": 0.7,
            "cme_settlement": {"status": "unavailable"},
            "otc_daily_close": {"status": "available", "observation_date": "2026-09-07"},
        },
    )

    feature = result["5m"]
    assert feature["status"] == "available"
    assert feature["session_class"] == "HOLIDAY"
    assert feature["execution_eligible"] is True
    assert feature["session_confidence_multiplier"] == 0.7


def test_holiday_without_otc_or_partial_liquidity_is_not_execution_eligible() -> None:
    no_otc = build_execution_timeframe_features(
        _raw(),
        analysis_date="2026-09-07",
        session_quality={"session_class": "HOLIDAY", "otc_daily_close": {"status": "unavailable"}},
    )["5m"]
    partial = build_execution_timeframe_features(
        _raw(),
        analysis_date="2026-09-07",
        session_quality={"session_class": "PARTIAL"},
    )["5m"]
    low_liquidity = build_execution_timeframe_features(
        _raw(),
        analysis_date="2026-09-07",
        session_quality={"session_class": "NORMAL", "liquidity_class": "LOW_LIQUIDITY"},
    )["5m"]

    assert no_otc["execution_eligible"] is False
    assert no_otc["execution_reason"] == "holiday_otc_observation_not_verified"
    assert partial["status"] == "partial"
    assert partial["execution_eligible"] is False
    assert low_liquidity["execution_eligible"] is False


def test_analysis_date_rejects_future_bars_without_inventing_an_execution_window() -> None:
    result = build_execution_timeframe_features(
        _raw("2026-09-08"),
        analysis_date="2026-09-07",
    )

    feature = result["5m"]
    assert feature["bar_count"] == 0
    assert feature["rejected_bar_count"] == 3
    assert feature["execution_eligible"] is False
