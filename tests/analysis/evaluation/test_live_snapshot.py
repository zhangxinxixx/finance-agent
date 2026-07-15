from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.analysis.evaluation.live_snapshot import build_strategy_snapshot_from_live_output
from apps.analysis.evaluation.outcomes import evaluate_strategy_outcome


def _live(status: str = "available") -> dict[str, object]:
    return {
        "schema_version": "live_strategy.v1",
        "status": status,
        "strategy_id": "live-strategy-1",
        "strategy_version": "live_strategy.rules.v2",
        "asset": "XAUUSD",
        "strategy_status": "WATCHING",
        "baseline": {"strategy_card_id": "card-1", "run_id": "run-1", "trade_date": "2026-07-17", "bias": "bullish", "confidence": 0.7},
        "live_market": {"price": 2400.5},
        "market_state": {"key_levels": [{"role": "support", "reference_price": 2398.0}]},
        "feasibility": {"data_ready": True, "level_ready": True},
        "active_scenario": "long",
        "setups": [
            {
                "setup_id": "setup-1",
                "direction": "long",
                "status": "watching",
                "reference_level": {"reference_price": 2398.0},
                "entry_zone": [2397.0, 2399.0],
                "trigger_conditions": ["canonical_5m_price_event_matches_direction"],
                "confirmation_conditions": ["two_canonical_5m_closes"],
                "invalidation_level": 2395.0,
                "stop_reference": 2395.0,
                "targets": [{"label": "TP1", "price": 2403.0}],
            }
        ],
        "no_trade": {"reasons": []},
        "source_refs": [{"name": "canonical_xauusd_5m", "status": "ok"}],
        "artifact_refs": ["storage/outputs/strategy_card/card-1.json"],
        "data_quality": {"canonical_candle": {"status": "available"}, "warnings": []},
    }


def test_adapter_freezes_refs_levels_and_risk() -> None:
    snapshot = build_strategy_snapshot_from_live_output(_live(), as_of=datetime(2026, 7, 17, 12, tzinfo=UTC))

    assert snapshot.publish_allowed is True
    assert snapshot.reference_price == 2400.5
    assert snapshot.key_levels[0]["reference_price"] == 2398.0
    assert snapshot.entry_conditions[0]["setup_id"] == "setup-1"
    assert snapshot.invalidation["setups"][0]["level"] == 2395.0
    assert snapshot.evaluation_setups[0].to_dict() == {
        "setup_id": "setup-1",
        "direction": "long",
        "trigger_type": "break_above",
        "trigger_price": 2399.0,
        "entry_zone_low": 2397.0,
        "entry_zone_high": 2399.0,
        "confirmation_rule": ["two_canonical_5m_closes"],
        "invalidation_price": 2395.0,
        "stop_price": 2395.0,
        "target_prices": [2403.0],
        "fill_policy": "trigger_price_on_touch",
        "status": "watching",
    }
    assert snapshot.artifact_refs == ("storage/outputs/strategy_card/card-1.json",)


def test_partial_live_output_is_blocked_and_invalid_schema_rejected() -> None:
    blocked = build_strategy_snapshot_from_live_output(_live("partial"), as_of=datetime(2026, 7, 17, 12, tzinfo=UTC))
    assert blocked.publish_allowed is False
    assert blocked.quality_gate["status"] == "blocked"
    with pytest.raises(ValueError, match="live_strategy.v1"):
        build_strategy_snapshot_from_live_output({"schema_version": "other"}, as_of=datetime.now(UTC))


def test_real_live_output_adapter_drives_trigger_fill_and_excursions() -> None:
    as_of = datetime(2026, 7, 17, 12, tzinfo=UTC)
    snapshot = build_strategy_snapshot_from_live_output(_live(), as_of=as_of)
    candles = [
        {"time": (as_of + timedelta(minutes=5)).isoformat(), "high": 2399.4, "low": 2398.8, "close": 2399.2},
        {"time": (as_of + timedelta(minutes=10)).isoformat(), "high": 2401.0, "low": 2399.1, "close": 2400.5},
        {"time": (as_of + timedelta(hours=1)).isoformat(), "high": 2402.0, "low": 2400.0, "close": 2401.5},
    ]

    outcome = evaluate_strategy_outcome(snapshot, candles, horizon="1h")

    assert outcome.status == "scored"
    assert outcome.lifecycle_status == "triggered"
    assert outcome.triggered is True
    assert outcome.fill_price == 2399.0
    assert outcome.reference_price == 2400.5
    assert outcome.return_abs == pytest.approx(2.5)
    assert outcome.mfe == pytest.approx(3.0)
    assert outcome.mae == pytest.approx(0.2)
