from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, time, timedelta

import pytest

from apps.analysis.evaluation.maturity import (
    HORIZONS,
    RETRYABLE_REASON_CODES,
    SCHEMA,
    TERMINAL_UNSCORABLE_REASON_CODES,
    build_outcome_maturity_plan,
)
from apps.analysis.evaluation.strategy_snapshot import build_strategy_snapshot


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
        "entry_conditions": [{"trigger_price": 100.5}],
        "invalidation": {"invalidation_level": 99.0},
        "source_refs": [{"source": "canonical_5m", "status": "ok"}],
    }
    values.update(overrides)
    return build_strategy_snapshot(**values)


def _complete_candles():
    points = (
        AS_OF + timedelta(minutes=5),
        AS_OF + timedelta(hours=1),
        AS_OF + timedelta(hours=4),
        datetime.combine(AS_OF.date(), time.max, tzinfo=UTC),
        AS_OF + timedelta(hours=24),
    )
    return [
        {
            "time": at.isoformat(),
            "high": 101.5,
            "low": 99.5,
            "close": 101.0,
            "partial": False,
        }
        for at in points
    ]


@pytest.mark.parametrize(
    ("now", "persistable"),
    [
        (AS_OF + timedelta(hours=1), ("1h",)),
        (AS_OF + timedelta(hours=4), ("1h", "4h")),
        (datetime.combine(AS_OF.date(), time.max, tzinfo=UTC), ("1h", "4h", "session")),
        (AS_OF + timedelta(hours=24), HORIZONS),
    ],
)
def test_approved_horizons_only_become_persistable_at_their_boundaries(now, persistable) -> None:
    plan = build_outcome_maturity_plan(_snapshot(), _complete_candles(), now=now)

    assert plan.schema_version == SCHEMA
    assert plan.to_dict()["schema_version"] == SCHEMA
    assert tuple(item.horizon for item in plan.horizons) == HORIZONS
    assert tuple(item.horizon for item in plan.horizons if item.persistable) == persistable
    for item in plan.horizons:
        if item.horizon in persistable:
            assert item.outcome is not None
            assert item.outcome.status == "scored"
        else:
            assert item.status == "pending"
            assert item.outcome is None
            assert item.reasons == ("horizon_not_mature",)


def test_blocked_snapshot_is_immediately_persistable_for_every_horizon() -> None:
    snapshot = _snapshot(publish_allowed=False, quality_gate={"status": "blocked"})

    plan = build_outcome_maturity_plan(snapshot, [], now=AS_OF)

    assert tuple(item.horizon for item in plan.horizons) == HORIZONS
    assert all(item.status == "persistable" for item in plan.horizons)
    assert all(item.outcome is not None and item.outcome.status == "blocked" for item in plan.horizons)
    assert all(item.reasons == ("quality_gate_blocked",) for item in plan.horizons)


@pytest.mark.parametrize(
    ("candles", "reason"),
    [
        ([], "complete_candle_after_as_of_missing"),
        (
            [{"time": (AS_OF + timedelta(hours=2)).isoformat(), "high": 101, "low": 99, "close": 100}],
            "horizon_data_missing",
        ),
        (
            [{"time": (AS_OF + timedelta(minutes=5)).isoformat(), "high": 101, "low": 99, "close": 100}],
            "horizon_data_incomplete",
        ),
    ],
)
def test_retryable_candle_gaps_remain_pending(candles, reason) -> None:
    plan = build_outcome_maturity_plan(_snapshot(), candles, now=AS_OF + timedelta(hours=1))
    one_hour = plan.horizons[0]

    assert reason in RETRYABLE_REASON_CODES
    assert one_hour.status == "pending"
    assert one_hour.persistable is False
    assert one_hour.outcome is not None
    assert one_hour.outcome.status == "unscorable"
    assert one_hour.reasons == (reason,)


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"source_refs": [{"source": "canonical_5m", "status": "degraded"}]}, "degraded_input"),
        ({"reference_price": None}, "reference_price_missing"),
    ],
)
def test_immutable_terminal_unscorable_outcomes_are_persistable(overrides, reason) -> None:
    plan = build_outcome_maturity_plan(
        _snapshot(**overrides),
        _complete_candles(),
        now=AS_OF + timedelta(hours=1),
    )
    one_hour = plan.horizons[0]

    assert reason in TERMINAL_UNSCORABLE_REASON_CODES
    assert one_hour.status == "persistable"
    assert one_hour.outcome is not None
    assert one_hour.outcome.status == "unscorable"
    assert one_hour.reasons == (reason,)


def test_plan_id_and_order_are_stable_and_inputs_are_not_mutated() -> None:
    snapshot = _snapshot()
    candles = _complete_candles()
    snapshot_before = snapshot.to_dict()
    candles_before = deepcopy(candles)

    first = build_outcome_maturity_plan(snapshot, candles, now=AS_OF + timedelta(hours=1))
    replay = build_outcome_maturity_plan(snapshot, candles, now=AS_OF + timedelta(hours=1))
    later = build_outcome_maturity_plan(snapshot, candles, now=AS_OF + timedelta(hours=24))

    assert first == replay
    assert first.maturity_id == replay.maturity_id == later.maturity_id
    assert tuple(item.horizon for item in first.horizons) == HORIZONS
    assert snapshot.to_dict() == snapshot_before
    assert candles == candles_before
    assert first.to_dict()["horizons"][0]["outcome"]["status"] == "scored"


def test_off_grid_horizon_is_persistable_when_final_close_is_within_one_interval() -> None:
    as_of = datetime(2026, 7, 18, 10, 39, 7, tzinfo=UTC)
    snapshot = _snapshot(as_of=as_of, trade_date="2026-07-18")
    candles = [
        {"time": "2026-07-18T10:40:00+00:00", "high": 101.0, "low": 99.5, "close": 100.5},
        {"time": "2026-07-18T11:30:00+00:00", "high": 101.0, "low": 99.5, "close": 100.5},
    ]

    plan = build_outcome_maturity_plan(
        snapshot,
        candles,
        now=as_of + timedelta(hours=1),
        expected_candle_interval_seconds=300,
    )

    one_hour = plan.horizons[0]
    assert one_hour.persistable is True
    assert one_hour.outcome is not None
    assert one_hour.outcome.status == "scored"


@pytest.mark.parametrize("value", ["300", True, float("nan"), float("inf"), 0, -1])
def test_maturity_rejects_invalid_expected_candle_interval(value: object) -> None:
    with pytest.raises(ValueError, match="expected_candle_interval_seconds"):
        build_outcome_maturity_plan(
            _snapshot(),
            [],
            now=AS_OF,
            expected_candle_interval_seconds=value,  # type: ignore[arg-type]
        )
