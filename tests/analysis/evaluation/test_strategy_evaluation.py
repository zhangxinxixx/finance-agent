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
    assert result.fill_price == pytest.approx(100.5)
    assert result.lifecycle_status == "triggered"
    assert result.return_abs == pytest.approx(0.4)
    assert result.mfe == pytest.approx(0.9)
    assert result.mae == pytest.approx(0.0)


def test_invalidation_before_trigger_is_explicit() -> None:
    result = evaluate_strategy_outcome(
        _snapshot(),
        _candles(99.0, 100.8),
        horizon="1h",
    )

    assert result.status == "scored"
    assert result.classification == "invalidated"
    assert result.lifecycle_status == "invalidated_before_entry"
    assert result.invalidated is True
    assert result.triggered is False
    assert result.fill_price is None
    assert result.return_abs is None
    assert result.reason_codes == ("invalidation_before_entry",)


def test_no_trigger_is_a_scored_hold_and_neutral_band_is_preserved() -> None:
    hold = evaluate_strategy_outcome(
        _snapshot(entry_conditions=[{"trigger_price": 101.0, "direction": "above"}]),
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
    assert hold.lifecycle_status == "never_triggered"
    assert hold.scoreable is True
    assert hold.return_abs is None
    assert "trigger_not_observed" in hold.reason_codes
    assert neutral.classification == "neutral"
    assert neutral.lifecycle_status == "triggered"
    assert neutral.direction_accuracy == "neutral"


def test_trigger_then_stop_uses_fill_and_stop_prices() -> None:
    candles = _candles(100.7, 98.8)
    candles[0].update({"high": 100.8, "low": 100.4})
    candles[1].update({"high": 100.4, "low": 98.8})

    result = evaluate_strategy_outcome(_snapshot(), candles, horizon="1h")

    assert result.status == "scored"
    assert result.classification == "invalidated"
    assert result.lifecycle_status == "triggered_then_invalidated"
    assert result.triggered is True
    assert result.invalidated is True
    assert result.fill_price == pytest.approx(100.5)
    assert result.exit_price == pytest.approx(99.0)
    assert result.return_abs == pytest.approx(-1.5)
    assert result.direction_accuracy == "incorrect"


def test_same_bar_trigger_and_stop_is_unscorable_without_inventing_path() -> None:
    candles = _candles(100.2)
    candles[0].update({"high": 100.8, "low": 98.8})

    result = evaluate_strategy_outcome(_snapshot(), candles, horizon="1h")

    assert result.status == "unscorable"
    assert result.classification == "unscorable"
    assert result.lifecycle_status == "same_bar_ambiguous"
    assert result.triggered is True
    assert result.invalidated is True
    assert result.fill_price is None
    assert result.reason_codes == ("same_bar_trigger_and_invalidation", "intrabar_path_unknown")


def test_same_bar_trigger_and_target_is_unscorable_without_inventing_fill_order() -> None:
    candles = _candles(100.8)
    candles[0].update({"high": 101.2, "low": 100.4})
    result = evaluate_strategy_outcome(
        _snapshot(
            evaluation_setups=[
                {
                    "setup_id": "long-target",
                    "direction": "long",
                    "trigger_price": 100.5,
                    "invalidation_price": 99.0,
                    "target_prices": [101.0],
                }
            ]
        ),
        candles,
        horizon="1h",
    )

    assert result.status == "unscorable"
    assert result.lifecycle_status == "same_bar_ambiguous"
    assert result.invalidated is False
    assert result.target_price == 101.0
    assert result.reason_codes == ("same_bar_trigger_and_target", "intrabar_path_unknown")


def test_active_short_setup_reaches_target_from_fill_price() -> None:
    candles = _candles(99.5, 97.9)
    candles[0].update({"high": 99.8, "low": 99.4})
    candles[1].update({"high": 99.4, "low": 97.8})
    result = evaluate_strategy_outcome(
        _snapshot(
            bias="bullish",
            risk={"active_scenario": "short"},
            evaluation_setups=[
                {"setup_id": "long", "direction": "long", "trigger_price": 101.0, "invalidation_price": 99.0},
                {
                    "setup_id": "short",
                    "direction": "short",
                    "trigger_price": 99.5,
                    "invalidation_price": 101.0,
                    "target_prices": [98.0],
                },
            ],
        ),
        candles,
        horizon="1h",
    )

    assert result.lifecycle_status == "target_reached"
    assert result.setup_id == "short"
    assert result.fill_price == 99.5
    assert result.exit_price == 98.0
    assert result.return_abs == pytest.approx(-1.5)
    assert result.mfe == pytest.approx(1.5)
    assert result.direction_accuracy == "correct"


def test_explicit_no_trade_does_not_evaluate_blocked_setup() -> None:
    result = evaluate_strategy_outcome(
        _snapshot(
            risk={"active_scenario": "no_trade"},
            evaluation_setups=[
                {
                    "setup_id": "blocked",
                    "direction": "long",
                    "status": "blocked_rr",
                    "trigger_price": 100.5,
                    "invalidation_price": 99.0,
                }
            ],
        ),
        _candles(101.0),
        horizon="1h",
    )

    assert result.status == "unscorable"
    assert result.lifecycle_status == "insufficient_strategy_contract"
    assert result.reason_codes == ("evaluation_setup_missing",)


def test_pretriggered_live_setup_does_not_require_future_retrigger() -> None:
    result = evaluate_strategy_outcome(
        _snapshot(
            evaluation_setups=[
                {
                    "setup_id": "already-triggered",
                    "direction": "long",
                    "status": "triggered",
                    "trigger_price": 100.5,
                    "invalidation_price": 99.0,
                }
            ]
        ),
        _candles(100.2),
        horizon="1h",
    )

    assert result.lifecycle_status == "triggered"
    assert result.trigger_time == AS_OF
    assert result.fill_time == AS_OF
    assert result.fill_price == 100.5


def test_invalid_stop_direction_is_terminal_unscorable() -> None:
    result = evaluate_strategy_outcome(
        _snapshot(invalidation={"invalidation_level": 101.0}),
        _candles(100.8),
        horizon="1h",
    )

    assert result.status == "unscorable"
    assert result.reason_codes == ("invalid_setup_price_order",)


def test_unknown_fill_policy_is_rejected_at_snapshot_boundary() -> None:
    with pytest.raises(ValueError, match="fill_policy"):
        _snapshot(
            evaluation_setups=[
                {
                    "setup_id": "unsupported-fill",
                    "direction": "long",
                    "trigger_price": 100.5,
                    "invalidation_price": 99.0,
                    "fill_policy": "next_open",
                }
            ]
        )


def test_missing_evaluation_setup_is_insufficient_strategy_contract() -> None:
    result = evaluate_strategy_outcome(
        _snapshot(entry_conditions=[], invalidation={}),
        _candles(100.2),
        horizon="1h",
    )

    assert result.status == "unscorable"
    assert result.lifecycle_status == "insufficient_strategy_contract"
    assert result.reason_codes == ("evaluation_setup_missing",)


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
