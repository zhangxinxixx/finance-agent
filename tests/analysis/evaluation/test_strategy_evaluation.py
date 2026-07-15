from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.analysis.evaluation import build_strategy_snapshot, evaluate_strategy_outcome


AS_OF = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)


def _snapshot(**overrides):
    values = {
        "asset": "XAUUSD",
        "trade_date": "2026-07-17",
        "run_id": "run-1",
        "strategy_id": "live-1",
        "strategy_version": "strategy.rules.v1",
        "as_of": AS_OF,
        "reference_price": 100.0,
        "bias": "bullish",
        "confidence": 0.8,
        "publish_allowed": True,
        "quality_gate": {"status": "approved"},
        "entry_conditions": [{"trigger_price": 100.5, "direction": "above"}],
        "invalidation": {"invalidation_level": 99.0},
        "source_refs": [{"source": "canonical_5m", "status": "ok"}],
        "artifact_refs": ["storage/outputs/strategy_card/run-1.json"],
    }
    values.update(overrides)
    return build_strategy_snapshot(**values)


def _candles(*closes: float, high: float | None = None, low: float | None = None):
    rows = []
    for index, close in enumerate(closes, start=1):
        rows.append(
            {
                "time": (AS_OF + timedelta(minutes=5 * index)).isoformat(),
                "high": high if high is not None else close + 0.2,
                "low": low if low is not None else close - 0.2,
                "close": close,
                "partial": False,
            }
        )
    if rows and rows[-1]["time"] != (AS_OF + timedelta(hours=1)).isoformat():
        rows.append(
            {
                "time": (AS_OF + timedelta(hours=1)).isoformat(),
                "high": high if high is not None else closes[-1] + 0.2,
                "low": low if low is not None else closes[-1] - 0.2,
                "close": closes[-1],
                "partial": False,
            }
        )
    return rows


def test_snapshot_is_frozen_and_lineage_is_retained() -> None:
    first = _snapshot()
    second = _snapshot()
    revision = _snapshot(revision="r2")

    assert first == second
    assert first.evaluation_id == second.evaluation_id
    assert revision.evaluation_id != first.evaluation_id
    assert first.to_dict()["source_refs"] == [{"source": "canonical_5m", "status": "ok"}]
    with pytest.raises((AttributeError, TypeError)):
        first.reference_price = 101.0  # type: ignore[misc]
    with pytest.raises(TypeError):
        first.quality_gate["status"] = "blocked"  # type: ignore[index]


def test_triggered_outcome_scores_direction_and_mfe_mae() -> None:
    result = evaluate_strategy_outcome(
        _snapshot(),
        _candles(100.2, 100.7, 101.2, 100.9),
        horizon="1h",
        neutral_band=0.1,
    )

    assert result.status == "scored"
    assert result.classification == "correct"
    assert result.direction_accuracy == "correct"
    assert result.triggered is True
    assert result.invalidated is False
    assert result.trigger_time == AS_OF + timedelta(minutes=10)
    assert result.return_abs == pytest.approx(0.9)
    assert result.mfe == pytest.approx(1.4)
    assert result.mae == pytest.approx(0.0)


def test_invalidation_before_trigger_is_explicit() -> None:
    result = evaluate_strategy_outcome(
        _snapshot(),
        _candles(99.0, 100.8),
        horizon="1h",
    )

    assert result.status == "scored"
    assert result.classification == "invalidated"
    assert result.invalidated is True
    assert result.triggered is True
    assert result.reason_codes == ("invalidation_observed",)


def test_no_trigger_is_a_scored_hold_and_neutral_band_is_preserved() -> None:
    hold = evaluate_strategy_outcome(
        _snapshot(entry_conditions=[]),
        _candles(100.02, 100.04),
        horizon="1h",
        neutral_band=0.1,
    )
    neutral = evaluate_strategy_outcome(
        _snapshot(entry_conditions=[{"trigger_price": 100.0}]),
        _candles(100.02, 100.04),
        horizon="1h",
        neutral_band=0.1,
    )

    assert hold.classification == "hold"
    assert hold.scoreable is True
    assert "trigger_not_observed" in hold.reason_codes
    assert neutral.classification == "neutral"
    assert neutral.direction_accuracy == "neutral"


def test_blocked_and_missing_or_degraded_inputs_never_invent_results() -> None:
    blocked = evaluate_strategy_outcome(
        _snapshot(publish_allowed=False),
        _candles(101.0),
        horizon="4h",
    )
    missing = evaluate_strategy_outcome(
        _snapshot(reference_price=None),
        _candles(101.0),
        horizon="4h",
    )
    degraded = evaluate_strategy_outcome(
        _snapshot(source_refs=[{"source": "canonical_5m", "status": "degraded"}]),
        _candles(101.0),
        horizon="4h",
    )
    no_candle = evaluate_strategy_outcome(_snapshot(), [], horizon="session")

    assert blocked.status == "blocked"
    assert blocked.classification == "blocked"
    assert missing.status == "unscorable"
    assert missing.reference_price is None
    assert degraded.reason_codes == ("degraded_input",)
    assert no_candle.reason_codes == ("complete_candle_after_as_of_missing",)
    assert no_candle.exit_price is None


def test_horizon_and_invalid_candle_boundaries_are_deterministic() -> None:
    candles = _candles(100.4, 100.8, 101.1)
    candles[1]["partial"] = True
    one_hour = evaluate_strategy_outcome(_snapshot(), candles, horizon="1h")
    session = evaluate_strategy_outcome(_snapshot(), candles, horizon="session")
    invalid = evaluate_strategy_outcome(_snapshot(), candles, horizon="2h")

    assert one_hour.exit_time == AS_OF + timedelta(hours=1)
    assert session.status == "unscorable"
    assert session.reason_codes == ("horizon_data_incomplete",)
    assert invalid.status == "unscorable"
    assert invalid.reason_codes == ("unsupported_horizon",)


def test_interval_uses_candle_close_times_for_off_grid_horizons_and_excludes_boundaries() -> None:
    as_of = datetime(2026, 7, 18, 10, 39, 7, tzinfo=UTC)
    snapshot = _snapshot(as_of=as_of)
    candles = [
        {"time": "2026-07-18T10:35:00+00:00", "high": 200.0, "low": 1.0, "close": 200.0},
        {"time": "2026-07-18T10:40:00+00:00", "high": 100.4, "low": 99.5, "close": 100.1},
        {"time": "2026-07-18T11:30:00+00:00", "high": 100.4, "low": 99.5, "close": 100.2},
        {"time": "2026-07-18T11:35:00+00:00", "high": 200.0, "low": 1.0, "close": 200.0},
    ]

    result = evaluate_strategy_outcome(
        snapshot,
        candles,
        horizon="1h",
        expected_candle_interval_seconds=300,
    )

    assert result.status == "scored"
    assert result.classification == "hold"
    assert result.market_start == datetime(2026, 7, 18, 10, 45, tzinfo=UTC)
    assert result.exit_time == datetime(2026, 7, 18, 11, 35, tzinfo=UTC)
    assert result.exit_price == 100.2
    assert result.triggered is False
    assert result.invalidated is False


def test_interval_tail_gap_of_one_full_bar_remains_incomplete() -> None:
    as_of = datetime(2026, 7, 18, 10, 40, tzinfo=UTC)
    result = evaluate_strategy_outcome(
        _snapshot(as_of=as_of),
        [{"time": "2026-07-18T11:30:00+00:00", "high": 101.0, "low": 99.5, "close": 100.2}],
        horizon="1h",
        expected_candle_interval_seconds=300,
    )

    assert result.status == "unscorable"
    assert result.reason_codes == ("horizon_data_incomplete",)


@pytest.mark.parametrize("value", ["300", True, float("nan"), float("inf"), 0, -1])
def test_invalid_expected_candle_interval_is_rejected(value: object) -> None:
    with pytest.raises(ValueError, match="expected_candle_interval_seconds"):
        evaluate_strategy_outcome(_snapshot(), _candles(101.0), horizon="1h", expected_candle_interval_seconds=value)  # type: ignore[arg-type]
