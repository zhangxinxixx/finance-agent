from __future__ import annotations

from datetime import UTC, datetime

import pytest

from apps.analysis.evaluation.live_snapshot import build_strategy_snapshot_from_live_output


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
        "setups": [{"setup_id": "setup-1", "direction": "long", "status": "watching", "entry_zone": [2397.0, 2399.0], "invalidation_level": 2395.0, "stop_reference": 2395.0}],
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
    assert snapshot.artifact_refs == ("storage/outputs/strategy_card/card-1.json",)


def test_partial_live_output_is_blocked_and_invalid_schema_rejected() -> None:
    blocked = build_strategy_snapshot_from_live_output(_live("partial"), as_of=datetime(2026, 7, 17, 12, tzinfo=UTC))
    assert blocked.publish_allowed is False
    assert blocked.quality_gate["status"] == "blocked"
    with pytest.raises(ValueError, match="live_strategy.v1"):
        build_strategy_snapshot_from_live_output({"schema_version": "other"}, as_of=datetime.now(UTC))
