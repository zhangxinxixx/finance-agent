from __future__ import annotations

import copy
from datetime import datetime, timezone

from apps.analysis.agents import AgentBias, AgentOutput, AgentStatus
from apps.analysis.agents.macro_liquidity import analyze_macro_liquidity
from apps.analysis.agents.registry import get_agent_registry


def _available_snapshot() -> dict:
    """手工 snapshot（后续迁移将逐步用 conftest fixture 替代）。"""
    return {
        "snapshot_id": "XAUUSD:2026-05-14:test-run",
        "input_snapshot_ids": {"macro": "macro:2026-05-14:test-run"},
        "macro": {
            "status": "available",
            "data": {
                "as_of": "2026-05-14",
                "indicators": {
                    "DGS10": {"value": 4.30, "change_1w": -0.05},
                    "T10YIE": {"value": 2.35, "change_1w": 0.02},
                    "REAL_YIELD_10Y": {"value": 1.95, "change_1w": -0.07},
                    "DXY": {"value": 97.8, "change_1w": -0.8},
                    "RRPONTSYD": {"value": 82.0},
                    "TGA": {"value": 510.0, "change_1w": -45.0},
                    "SOFR": {"value": 4.32},
                    "EFFR": {"value": 4.33},
                    "IORB": {"value": 4.40},
                },
            },
        },
        "source_refs": [
            {"symbol": "DGS10", "source": "fred"},
            {"symbol": "DXY", "source": "tradingview"},
        ],
    }


def test_available_macro_returns_schema_valid_agent_output__uses_conftest_fixture(
    sample_agent_input_snapshot: dict,
    fixed_utc_now: datetime,
) -> None:
    """使用 conftest 共享 fixture + 手工覆盖特定 ID（后续完全迁移后可去掉覆盖）。"""
    snapshot = copy.deepcopy(sample_agent_input_snapshot)
    snapshot["snapshot_id"] = "XAUUSD:2026-05-14:test-run"
    snapshot["input_snapshot_ids"] = {"macro": "macro:2026-05-14:test-run"}
    snapshot.pop("options", None)

    output = analyze_macro_liquidity(snapshot, created_at=fixed_utc_now)

    assert isinstance(output, AgentOutput)
    assert output.version == "1.0"
    assert output.agent_name == "macro_liquidity_agent"
    assert output.module == "macro"
    assert output.snapshot_id == "XAUUSD:2026-05-14:test-run"
    assert output.input_snapshot_ids == {
        "analysis_snapshot": "XAUUSD:2026-05-14:test-run",
        "macro": "macro:2026-05-14:test-run",
    }
    assert output.source_refs == snapshot["source_refs"]
    assert output.status is AgentStatus.SUCCESS
    assert output.bias is AgentBias.BULLISH
    assert 0.0 <= output.confidence <= 1.0
    assert output.created_at == fixed_utc_now
    assert "只读视图" not in output.summary
    assert "结论偏" in output.summary
    assert any("real yield" in finding.lower() for finding in output.key_findings)
    assert "DXY" in output.watchlist


def test_available_macro_emits_structured_evidence_items():
    output = analyze_macro_liquidity(_available_snapshot(), created_at=datetime(2026, 5, 14, tzinfo=timezone.utc))

    evidence_by_factor = {item.factor: item for item in output.evidence_items}

    assert {"real_yield_pressure", "dollar_pressure", "liquidity_condition"} <= set(evidence_by_factor)
    real_yield = evidence_by_factor["real_yield_pressure"]
    assert real_yield.direction == "bullish"
    assert 0.0 <= real_yield.strength <= 1.0
    assert 0.0 <= real_yield.confidence <= 1.0
    assert real_yield.source_refs
    assert real_yield.data_category == "confirmed_data"

    dollar = evidence_by_factor["dollar_pressure"]
    assert dollar.direction == "bullish"
    assert dollar.source_tier == "market"


def test_missing_dxy_lowers_confidence_and_records_risk_or_invalid_condition():
    snapshot = _available_snapshot()
    del snapshot["macro"]["data"]["indicators"]["DXY"]

    output = analyze_macro_liquidity(snapshot, created_at=datetime(2026, 5, 14, tzinfo=timezone.utc))

    assert output.status is AgentStatus.PARTIAL
    assert output.confidence < 0.7
    notes = output.risk_points + output.invalid_conditions
    assert any("DXY" in note for note in notes)


def test_missing_macro_section_returns_unavailable_without_exception():
    output = analyze_macro_liquidity(
        {
            "snapshot_id": "XAUUSD:2026-05-14:missing",
            "input_snapshot_ids": {"macro": "macro:2026-05-14:missing"},
            "source_refs": [],
        },
        created_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
    )

    assert output.status is AgentStatus.UNAVAILABLE
    assert output.bias is AgentBias.UNAVAILABLE
    assert output.confidence == 0.0
    assert output.key_findings == []
    assert output.risk_points
    assert output.invalid_conditions


def test_macro_status_not_available_returns_unavailable_without_fake_conclusion():
    snapshot = _available_snapshot()
    snapshot["macro"] = {"status": "unavailable", "reason": "input_not_available"}

    output = analyze_macro_liquidity(snapshot, created_at=datetime(2026, 5, 14, tzinfo=timezone.utc))

    assert output.status is AgentStatus.UNAVAILABLE
    assert output.bias is AgentBias.UNAVAILABLE
    assert output.confidence == 0.0
    assert output.summary == "Macro liquidity input is unavailable; no read-only conclusion was generated."


def test_analyze_macro_liquidity_does_not_mutate_input_snapshot():
    snapshot = _available_snapshot()
    before = copy.deepcopy(snapshot)

    analyze_macro_liquidity(snapshot, created_at=datetime(2026, 5, 14, tzinfo=timezone.utc))

    assert snapshot == before


def test_analyze_macro_liquidity_rejects_path_like_input_without_file_reads():
    output = analyze_macro_liquidity("storage/features/snapshots/XAUUSD/example/premarket_snapshot.json")  # type: ignore[arg-type]

    assert output.status is AgentStatus.UNAVAILABLE
    assert output.bias is AgentBias.UNAVAILABLE
    assert output.confidence == 0.0
    assert "analysis_snapshot" not in output.input_snapshot_ids


# ── P4-05: Macro regime fields in agent output ────────────────────────


def test_agent_output_includes_market_phase_and_regime_drivers():
    """P4-05: AgentOutput must include market_phase and regime_drivers fields when macro is available."""
    snapshot = _available_snapshot()
    output = analyze_macro_liquidity(snapshot)

    assert output.market_phase is not None, "market_phase should be set when macro is available"
    assert output.market_phase in (
        "rate_pressure", "transition_release", "trend_tailwind", "unavailable",
    ), f"Unexpected market_phase: {output.market_phase}"
    assert output.regime_drivers is not None, "regime_drivers should be set when macro is available"
    assert isinstance(output.regime_drivers, dict)

    for key in ("real_yield", "dxy", "us02y", "us10y", "breakeven", "liquidity_quantity", "liquidity_price"):
        assert key in output.regime_drivers["drivers"], f"regime_drivers.drivers missing key: {key}"


def test_agent_output_market_phase_unavailable_when_macro_unavailable():
    """When macro section is unavailable, market_phase should be 'unavailable'."""
    output = analyze_macro_liquidity(
        {"snapshot_id": "test", "macro": {"status": "unavailable"}},
    )
    assert output.market_phase == "unavailable"


def test_regime_key_findings_appear_in_output():
    """P4-05: Regime classification should appear in key_findings."""
    snapshot = _available_snapshot()
    output = analyze_macro_liquidity(snapshot)

    regime_findings = [
        f for f in output.key_findings if "Macro regime:" in f
    ]
    assert len(regime_findings) >= 1, f"Expected regime key_finding in: {output.key_findings}"
    finding = regime_findings[0]
    assert "macro regime" in finding.lower()


def test_macro_summary_reads_like_research_conclusion():
    snapshot = _available_snapshot()
    output = analyze_macro_liquidity(snapshot)

    assert "确信度" in output.summary
    assert "当前数据更支持这一方向" in output.summary
    assert "只读视图" not in output.summary


def test_macro_liquidity_registry_prompts_as_llm() -> None:
    agent = get_agent_registry("macro_liquidity_agent")
    assert agent is not None
    assert agent["prompt"]["kind"] == "llm"
    assert "宏观流动性分析" in agent["prompt"]["template"]


def test_agent_output_regime_fields_present_in_dict_form():
    """P4-05: When serialized to JSON, market_phase and regime_drivers survive."""
    snapshot = _available_snapshot()
    output = analyze_macro_liquidity(snapshot)

    data = output.model_dump(mode="json")
    assert "market_phase" in data
    assert "regime_drivers" in data
    assert isinstance(data["market_phase"], str)
    assert isinstance(data["regime_drivers"], dict)
