from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.analysis.strategy.price_events import detect_latest_price_event


NOW = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
LEVELS = [{"reference_price": 100.0, "role": "primary_resistance", "strength": 8.0}]


def _candles(closes: list[float], *, highs: list[float] | None = None, lows: list[float] | None = None) -> list[dict]:
    return [
        {
            "time": (NOW - timedelta(minutes=5 * (len(closes) - 1 - index))).isoformat(),
            "open": close,
            "close": close,
            "high": (highs or closes)[index],
            "low": (lows or closes)[index],
        }
        for index, close in enumerate(closes)
    ]


def _event(closes: list[float], **kwargs: object) -> dict | None:
    return detect_latest_price_event(candles_5m=_candles(closes, **kwargs), candles_15m=[], key_levels=LEVELS, atr14=2.0)


@pytest.mark.parametrize(
    ("close", "event_type"),
    [(101.0, "approach"), (100.1, "touch")],
)
def test_approach_and_touch(close: float, event_type: str) -> None:
    event = _event([98.0, close])
    assert event is not None
    assert event["event_type"] == event_type
    assert event["confirmed"] is False


def test_single_wick_breach_never_becomes_accepted_break() -> None:
    event = _event([99.8, 99.9], highs=[99.9, 100.5])
    assert event is not None
    assert event["event_type"] == "intrabar_breach"
    assert event["confirmed"] is False


def test_accepted_break_requires_two_5m_closes_and_completed_15m() -> None:
    candles = _candles([99.0, 100.4, 100.5])
    missing = detect_latest_price_event(candles_5m=candles, candles_15m=[], key_levels=LEVELS, atr14=2.0)
    partial = detect_latest_price_event(
        candles_5m=candles,
        candles_15m=[{"time": NOW.isoformat(), "close": 100.5, "partial": True}],
        key_levels=LEVELS,
        atr14=2.0,
    )
    confirmed = detect_latest_price_event(
        candles_5m=candles,
        candles_15m=[{"time": NOW.isoformat(), "close": 100.5, "partial": False}],
        key_levels=LEVELS,
        atr14=2.0,
    )

    assert missing is not None and missing["event_type"] == "intrabar_breach"
    assert partial is not None and partial["event_type"] == "intrabar_breach"
    assert confirmed is not None and confirmed["event_type"] == "accepted_break" and confirmed["confirmed"] is True
    assert confirmed["confirmation"] == {
        "five_minute_closes": [100.4, 100.5],
        "fifteen_minute_close": 100.5,
    }


def test_failed_break_retest_and_reclaim_have_frozen_priority() -> None:
    failed = _event([99.0, 100.5, 99.9])
    retest = _event([99.0, 100.4, 100.5, 100.2])
    reclaim = _event([100.5] + [99.0] * 9 + [100.1, 100.2])

    assert failed is not None and failed["event_type"] == "failed_break"
    assert retest is not None and retest["event_type"] == "retest"
    assert reclaim is not None and reclaim["event_type"] == "reclaim"


def test_directional_roles_reject_breaks_on_the_wrong_side() -> None:
    support = [{"reference_price": 98.0, "role": "primary_support", "strength": 7.0}]
    resistance = [{"reference_price": 102.0, "role": "primary_resistance", "strength": 8.0}]

    above_support = detect_latest_price_event(
        candles_5m=_candles([97.0, 98.4, 98.5]),
        candles_15m=[{"time": NOW.isoformat(), "close": 98.5, "partial": False}],
        key_levels=support,
        atr14=2.0,
    )
    below_resistance = detect_latest_price_event(
        candles_5m=_candles([103.0, 101.6, 101.5]),
        candles_15m=[{"time": NOW.isoformat(), "close": 101.5, "partial": False}],
        key_levels=resistance,
        atr14=2.0,
    )

    assert above_support is not None and above_support["event_type"] != "accepted_break"
    assert below_resistance is not None and below_resistance["event_type"] != "accepted_break"


def test_accepted_break_must_be_new_in_the_current_window() -> None:
    persistent = detect_latest_price_event(
        candles_5m=_candles([100.5, 100.6, 100.7]),
        candles_15m=[{"time": NOW.isoformat(), "close": 100.7, "partial": False}],
        key_levels=LEVELS,
        atr14=2.0,
    )

    assert persistent is not None
    assert persistent["event_type"] != "accepted_break"
