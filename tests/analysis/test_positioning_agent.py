from __future__ import annotations

from datetime import datetime, timezone

from apps.analysis.agents.positioning import analyze_positioning
from apps.analysis.agents.schemas import AgentBias, AgentStatus
from apps.features.positioning.snapshot import build_positioning_snapshot


def test_positioning_agent_separates_producer_and_swap_dealer_semantics() -> None:
    snapshot = {
        "snapshot_id": "positioning-snapshot-1",
        "input_snapshot_ids": {"macro": "macro-snapshot-1"},
        "positioning": {
            "status": "available",
            "data": {
                "commercial_net": -222_282,
                "producer_net": -20_986,
                "swap_net": -201_296,
                "noncomm_net": 116_161,
                "commercial_net_prev": -208_000,
                "producer_net_prev": -18_000,
                "swap_net_prev": -190_000,
                "noncomm_net_prev": 110_000,
                "commercial_direction": "increasing_short",
                "noncomm_direction": "increasing_long",
                "extreme_reading": False,
                "total_oi": 371_776,
                "source_refs": [{"source": "cftc", "raw_path": "raw/cot.json"}],
            },
        },
    }

    result = analyze_positioning(
        snapshot,
        created_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
    )

    findings = "\n".join(result.key_findings)
    assert result.status is AgentStatus.SUCCESS
    assert result.bias is AgentBias.BEARISH
    assert "Producer/Merchant net position: -20,986 contracts." in findings
    assert "Swap Dealer net position: -201,296 contracts." in findings
    assert "Commercial aggregate proxy" in findings
    assert "producer hedging" not in findings.lower()
    assert "reduced producer" not in findings.lower()


def test_positioning_agent_marks_legacy_aggregate_only_snapshot_partial() -> None:
    snapshot = {
        "snapshot_id": "legacy-positioning-snapshot",
        "positioning": {
            "status": "available",
            "data": {
                "commercial_net": -100_000,
                "noncomm_net": 50_000,
                "commercial_direction": "flat",
                "noncomm_direction": "flat",
                "total_oi": 300_000,
            },
        },
    }

    result = analyze_positioning(snapshot)

    assert result.status is AgentStatus.PARTIAL
    assert any("Producer/Merchant and Swap Dealer breakdown" in item for item in result.invalid_conditions)


def test_positioning_feature_preserves_missing_breakdown_for_agent_degradation() -> None:
    points = [
        {
            "symbol": symbol,
            "date": "2026-07-14",
            "value": value,
            "source": "cftc",
            "source_url": "https://example.test/cot",
            "raw_path": "raw/cot.json",
        }
        for symbol, value in (
            ("COT_GOLD_commercial_net", -100_000),
            ("COT_GOLD_noncomm_net", 50_000),
            ("COT_GOLD_open_interest", 300_000),
        )
    ]
    positioning = build_positioning_snapshot(points)

    assert positioning.producer_net is None
    assert positioning.swap_net is None

    result = analyze_positioning(
        {
            "snapshot_id": "legacy-feature-snapshot",
            "positioning": {"status": "available", "data": positioning.to_dict()},
        }
    )

    assert result.status is AgentStatus.PARTIAL
    assert any("breakdown is missing" in item for item in result.invalid_conditions)
