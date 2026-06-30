from __future__ import annotations

import copy
import re
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from apps.analysis.agents.schemas import AgentBias, AgentOutput, AgentStatus
from apps.analysis.strategy.card import build_strategy_card
from apps.analysis.strategy.schemas import StrategyCardOutput

_CREATED_AT = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)


# ═══════════════════════════════════════════════════════════════════════
# fixtures
# ═══════════════════════════════════════════════════════════════════════


def _snapshot(*, unavailable_modules: list[str] | None = None) -> dict:
    return {
        "snapshot_id": "XAUUSD:2026-05-14:analysis",
        "run_id": "run-card-test",
        "input_snapshot_ids": {
            "analysis_snapshot": "XAUUSD:2026-05-14:analysis",
            "macro": "macro:2026-05-14",
            "options": "cme-options:2026-05-14",
        },
        "metadata": {
            "symbol": "XAUUSD",
            "as_of": "2026-05-14",
            "unavailable_modules": unavailable_modules or [],
        },
        "source_refs": [{"source": "analysis_snapshot", "snapshot_id": "XAUUSD:2026-05-14:analysis"}],
    }


def _coordinator_output(
    *,
    bias: AgentBias = AgentBias.BULLISH,
    confidence: float = 0.70,
    status: AgentStatus = AgentStatus.SUCCESS,
    key_findings: list[str] | None = None,
    risk_points: list[str] | None = None,
    invalid_conditions: list[str] | None = None,
    watchlist: list[str] | None = None,
    summary: str | None = None,
    source_refs: list[dict] | None = None,
    input_snapshot_ids: dict | None = None,
) -> AgentOutput:
    return AgentOutput(
        version="1.0",
        agent_name="coordinator_agent",
        module="coordinator",
        snapshot_id="XAUUSD:2026-05-14:analysis",
        input_snapshot_ids=input_snapshot_ids or {
            "analysis_snapshot": "XAUUSD:2026-05-14:analysis",
            "coordinator": "XAUUSD:2026-05-14:analysis",
            "macro": "macro:2026-05-14",
            "options": "cme-options:2026-05-14",
            "risk": "risk:2026-05-14",
        },
        bias=bias,
        confidence=confidence,
        key_findings=key_findings or [
            "Macro prior bias is bullish with status success and confidence 0.72.",
            "Macro prior finding: liquidity easing continues.",
            "Options prior bias is bullish with status success and confidence 0.74.",
            "Options prior finding: Call wall near 2450",
            "Options prior finding: Put support near 2350",
            "Risk prior bias is bullish with status success and confidence 0.68.",
        ],
        risk_points=risk_points or [
            "Coordinator: technical data unavailable limits precision.",
        ],
        watchlist=watchlist or ["DGS10", "CME option walls", "macro direction"],
        invalid_conditions=invalid_conditions or [
            "Coordinator: precise execution plan not produced.",
        ],
        summary=summary or "Bullish research view with constrained confidence.",
        source_refs=source_refs or [
            {"source": "coordinator", "snapshot_id": "XAUUSD:2026-05-14:analysis"},
        ],
        status=status,
        created_at=_CREATED_AT,
    )


def _risk_output(
    *,
    bias: AgentBias = AgentBias.BULLISH,
    confidence: float = 0.68,
    status: AgentStatus = AgentStatus.SUCCESS,
    risk_points: list[str] | None = None,
    invalid_conditions: list[str] | None = None,
    watchlist: list[str] | None = None,
) -> AgentOutput:
    return AgentOutput(
        version="1.0",
        agent_name="risk_agent",
        module="risk",
        snapshot_id="risk:2026-05-14",
        input_snapshot_ids={"risk": "risk:2026-05-14"},
        bias=bias,
        confidence=confidence,
        key_findings=["Risk assessment: moderate drawdown potential."],
        risk_points=risk_points or ["Risk prior: exposure to Fed surprise events."],
        watchlist=watchlist or ["VIX", "DXY"],
        invalid_conditions=invalid_conditions or [
            "Risk prior: invalid if VIX spikes above 25.",
        ],
        summary="Risk view: manageable.",
        source_refs=[{"source": "risk", "snapshot_id": "risk:2026-05-14"}],
        status=status,
        created_at=_CREATED_AT,
    )


def _macro_snapshot_section(*, market_phase: str = "trend_tailwind") -> dict[str, object]:
    if market_phase == "rate_pressure":
        indicators = {
            "REAL_10Y": {"value": 2.0, "daily_change": 0.15, "weekly_change": 0.30},
            "DXY": {"value": 106.0, "daily_change": 0.5, "weekly_change": 1.5},
            "DGS2": {"value": 5.0, "daily_change": 0.10},
            "DGS10": {"value": 4.8, "daily_change": 0.08},
            "T10YIE": {"value": 2.3, "daily_change": 0.05},
            "ON_RRP_USAGE": {"value": 500.0, "daily_change": 20.0},
            "TGA": {"value": 600.0, "daily_change": 30.0},
            "SOFR": {"value": 5.3, "daily_change": 0.01},
            "EFFR": {"value": 5.25, "daily_change": 0.01},
            "IORB": {"value": 5.4, "daily_change": 0.0},
        }
    else:
        indicators = {
            "REAL_10Y": {"value": 1.2, "daily_change": -0.20, "weekly_change": -0.40},
            "DXY": {"value": 100.0, "daily_change": -0.8, "weekly_change": -2.0},
            "DGS2": {"value": 3.8, "daily_change": -0.15},
            "DGS10": {"value": 3.5, "daily_change": -0.12},
            "T10YIE": {"value": 2.3, "daily_change": -0.05},
            "ON_RRP_USAGE": {"value": 200.0, "daily_change": -50.0},
            "TGA": {"value": 400.0, "daily_change": -30.0},
            "SOFR": {"value": 4.3, "daily_change": -0.02},
            "EFFR": {"value": 4.35, "daily_change": -0.02},
            "IORB": {"value": 4.4, "daily_change": 0.0},
        }

    return {"status": "available", "data": {"indicators": indicators}}


# ═══════════════════════════════════════════════════════════════════════
# happy path
# ═══════════════════════════════════════════════════════════════════════


def test_build_strategy_card_from_coordinator_and_risk_outputs():
    card = build_strategy_card(
        snapshot=_snapshot(),
        coordinator_output=_coordinator_output(),
        risk_output=_risk_output(),
        created_at=_CREATED_AT,
    )

    assert isinstance(card, StrategyCardOutput)
    assert card.version == "1.0"
    assert card.asset == "XAUUSD"
    assert card.trade_date == "2026-05-14"
    assert card.run_id == "run-card-test"
    assert card.bias == AgentBias.BULLISH
    assert card.confidence == 0.70
    assert card.is_trade_instruction is False
    # coordinator (1 risk_point) + risk (1 risk_point) = 2
    assert len(card.risk_points) >= 2
    # coordinator (1 invalid_condition) + risk (1 invalid_condition) = 2
    assert len(card.invalid_conditions) >= 2


def test_build_strategy_card_without_risk_output():
    card = build_strategy_card(
        snapshot=_snapshot(),
        coordinator_output=_coordinator_output(),
        risk_output=None,
        created_at=_CREATED_AT,
    )

    # coordinator was built with risk — its lineage carries risk reference
    assert card.input_snapshot_ids.get("risk") is not None
    assert any("coordinator" in rp.lower() for rp in card.risk_points)


def test_build_strategy_card_defaults_created_at_when_none():
    card = build_strategy_card(
        snapshot=_snapshot(),
        coordinator_output=_coordinator_output(),
    )

    assert card.created_at is not None
    assert abs((card.created_at - datetime.now(timezone.utc)).total_seconds()) < 10


def test_build_strategy_card_populates_market_regime_from_macro_snapshot():
    snapshot = _snapshot()
    snapshot["macro"] = _macro_snapshot_section(market_phase="trend_tailwind")

    card = build_strategy_card(
        snapshot=snapshot,
        coordinator_output=_coordinator_output(),
        created_at=_CREATED_AT,
    )

    assert card.market_regime == "trend_tailwind"


# ═══════════════════════════════════════════════════════════════════════
# is_trade_instruction
# ═══════════════════════════════════════════════════════════════════════


def test_build_strategy_card_is_never_trade_instruction():
    card = build_strategy_card(
        snapshot=_snapshot(),
        coordinator_output=_coordinator_output(bias=AgentBias.BULLISH),
    )

    assert card.is_trade_instruction is False
    assert card.model_dump(mode="json")["is_trade_instruction"] is False


def test_build_strategy_card_literal_false_field_cannot_be_true():
    card = build_strategy_card(
        snapshot=_snapshot(),
        coordinator_output=_coordinator_output(),
    )

    dump = card.model_dump()
    dump["is_trade_instruction"] = True
    with pytest.raises(ValidationError, match="is_trade_instruction"):
        StrategyCardOutput.model_validate(dump)


# ═══════════════════════════════════════════════════════════════════════
# no executable instructions
# ═══════════════════════════════════════════════════════════════════════


def test_build_strategy_card_contains_no_buy_sell_enter_stop_target():
    """Verify that the card output never contains executable trading language."""
    card = build_strategy_card(
        snapshot=_snapshot(),
        coordinator_output=_coordinator_output(
            key_findings=["Options prior finding: Potential buy zone near 2400"],
        ),
    )

    combined = " ".join(
        [card.scenario_summary]
        + card.risk_points
        + card.invalid_conditions
        + card.key_levels_from_options
    ).lower()

    # Original "buy" in key_findings should be stripped by the sanitizer
    for forbidden in ("buy", "sell", "enter", "stop", "target"):
        assert forbidden not in combined, f"forbidden word '{forbidden}' found in output"


def test_build_strategy_card_sanitizes_execution_language():
    card = build_strategy_card(
        snapshot=_snapshot(),
        coordinator_output=_coordinator_output(
            risk_points=["Risk: stop loss at 2300 would trigger downside."],
            invalid_conditions=["Invalidate if short entry signal appears."],
        ),
    )

    combined = " ".join(card.risk_points + card.invalid_conditions)
    assert "stop" not in combined.lower()
    assert "short entry" not in combined.lower()
    assert "research view only" in combined.lower()


# ═══════════════════════════════════════════════════════════════════════
# unavailable modules → incomplete markers
# ═══════════════════════════════════════════════════════════════════════


def test_build_strategy_card_marks_incomplete_when_technical_news_positioning_unavailable():
    card = build_strategy_card(
        snapshot=_snapshot(unavailable_modules=["technical", "news", "positioning"]),
        coordinator_output=_coordinator_output(status=AgentStatus.PARTIAL, confidence=0.55),
    )

    combined = " ".join(card.risk_points + card.invalid_conditions + [card.scenario_summary]).lower()
    assert card.status is AgentStatus.PARTIAL if hasattr(card, "status") else True  # card doesn't have status
    assert "technical" in combined
    assert "news" in combined
    assert "positioning" in combined
    assert "incomplete" in combined


def test_build_strategy_card_no_markers_when_all_modules_available():
    card = build_strategy_card(
        snapshot=_snapshot(unavailable_modules=[]),
        coordinator_output=_coordinator_output(),
    )

    combined = " ".join(card.risk_points + card.invalid_conditions).lower()
    assert "incomplete" not in combined


def test_build_strategy_card_partial_confidence_respected():
    card = build_strategy_card(
        snapshot=_snapshot(),
        coordinator_output=_coordinator_output(status=AgentStatus.PARTIAL, confidence=0.45),
    )

    assert card.confidence == 0.45
    assert "partial" in card.scenario_summary.lower()


def test_build_strategy_card_displays_confidence_kernel_breakdown():
    coordinator = _coordinator_output()
    coordinator = coordinator.model_copy(
        update={
            "input_payload": {
                "confidence_kernel": {
                    "version": "1.0",
                    "data_confidence": 0.84,
                    "freshness_confidence": 0.92,
                    "evidence_confidence": 0.78,
                    "cross_source_confidence": 0.50,
                    "conflict_penalty": 0.50,
                    "model_dependency_penalty": 0.0,
                    "regime_confidence": None,
                    "overall": 0.55,
                    "caps": ["macro_options_conflict"],
                    "reasons": ["macro/options directional conflict caps confidence."],
                }
            }
        }
    )

    card = build_strategy_card(
        snapshot=_snapshot(),
        coordinator_output=coordinator,
        created_at=_CREATED_AT,
    )

    assert card.confidence_kernel is not None
    assert card.confidence_kernel["overall"] == 0.55
    assert card.confidence_kernel["caps"] == ["macro_options_conflict"]


def test_build_strategy_card_uses_gold_macro_overview_as_conditional_signal():
    snapshot = _snapshot()
    snapshot["news"] = {
        "data": {
            "gold_macro_overview": {
                "asset": "XAUUSD",
                "as_of": "2026-06-30T00:00:00Z",
                "phase": "macro_verification",
                "dominant_mainline": "real_rates_usd",
                "net_bias": "mixed",
                "driver_conflict": {"verification_needed": ["real_rate_response_needed"]},
                "verification_matrix": [
                    {"label": "多源确认", "status": "pending"},
                    {"label": "实际利率确认", "status": "pending"},
                ],
            }
        }
    }

    card = build_strategy_card(
        snapshot=snapshot,
        coordinator_output=_coordinator_output(),
        created_at=_CREATED_AT,
    )

    assert card.gold_macro_conditions is not None
    assert card.gold_macro_conditions["dominant_mainline"] == "real_rates_usd"
    assert card.gold_macro_conditions["net_bias"] == "mixed"
    assert card.trigger_conditions == [
        "Gold macro context remains mixed with dominant mainline real_rates_usd."
    ]
    assert any("pending verification" in item for item in card.watchlist)
    assert any("GoldMacroOverview dominant mainline changes" in item for item in card.invalid_conditions)
    combined = " ".join(card.trigger_conditions + card.confirmation_conditions + card.invalid_conditions)
    assert not re.search(r"\b(buy|sell|enter|stop.loss|take.profit|long\s*entry|short\s*entry)\b", combined, re.IGNORECASE)


# ═══════════════════════════════════════════════════════════════════════
# source_refs / lineage
# ═══════════════════════════════════════════════════════════════════════


def test_build_strategy_card_binds_source_refs_and_input_snapshot_ids():
    card = build_strategy_card(
        snapshot=_snapshot(),
        coordinator_output=_coordinator_output(),
        risk_output=_risk_output(),
    )

    # input_snapshot_ids must include analysis_snapshot and coordinator
    assert "analysis_snapshot" in card.input_snapshot_ids
    assert "coordinator" in card.input_snapshot_ids
    assert card.input_snapshot_ids["analysis_snapshot"] == "XAUUSD:2026-05-14:analysis"
    assert card.input_snapshot_ids["coordinator"] == "XAUUSD:2026-05-14:analysis"

    # source_refs merged from snapshot, coordinator, risk
    assert len(card.source_refs) >= 2
    sources = {ref.get("source") for ref in card.source_refs}
    assert "analysis_snapshot" in sources
    assert "coordinator" in sources
    assert "risk" in sources


def test_build_strategy_card_source_refs_deduplicated():
    shared = {"source": "shared", "ref": "dup"}
    card = build_strategy_card(
        snapshot={**_snapshot(), "source_refs": [shared]},
        coordinator_output=_coordinator_output(source_refs=[shared, {"source": "unique", "ref": "x"}]),
        risk_output=_risk_output(),
    )

    count_shared = sum(1 for r in card.source_refs if r.get("source") == "shared")
    assert count_shared == 1


def test_build_strategy_card_input_snapshot_ids_merges_all_lineages():
    card = build_strategy_card(
        snapshot=_snapshot(),
        coordinator_output=_coordinator_output(),
        risk_output=_risk_output(),
    )

    assert card.input_snapshot_ids.get("macro") == "macro:2026-05-14"
    assert card.input_snapshot_ids.get("options") == "cme-options:2026-05-14"
    assert card.input_snapshot_ids.get("risk") == "risk:2026-05-14"


# ═══════════════════════════════════════════════════════════════════════
# risk_points / invalid_conditions merge
# ═══════════════════════════════════════════════════════════════════════


def test_build_strategy_card_merges_risk_points_from_coordinator_and_risk():
    card = build_strategy_card(
        snapshot=_snapshot(),
        coordinator_output=_coordinator_output(
            risk_points=["Coordinator risk: macro reversal."],
        ),
        risk_output=_risk_output(
            risk_points=["Risk agent: liquidity drain."],
        ),
    )

    assert any("macro reversal" in rp for rp in card.risk_points)
    assert any("liquidity drain" in rp for rp in card.risk_points)


def test_build_strategy_card_merges_invalid_conditions_from_coordinator_and_risk():
    card = build_strategy_card(
        snapshot=_snapshot(),
        coordinator_output=_coordinator_output(
            invalid_conditions=["Coordinator: invalid if macro flips."],
        ),
        risk_output=_risk_output(
            invalid_conditions=["Risk: invalid if DXY breaks 100."],
        ),
    )

    assert any("macro flips" in ic for ic in card.invalid_conditions)
    assert any("DXY breaks" in ic for ic in card.invalid_conditions)


# ═══════════════════════════════════════════════════════════════════════
# key_levels_from_options — extraction only, no price invention
# ═══════════════════════════════════════════════════════════════════════


def test_build_strategy_card_extracts_key_levels_from_coordinator_options_findings():
    card = build_strategy_card(
        snapshot=_snapshot(),
        coordinator_output=_coordinator_output(
            key_findings=[
                "Options prior finding: Call wall near 2450",
                "Options prior finding: Put support near 2350",
                "Macro prior finding: DXY weakening",
            ],
        ),
    )

    assert len(card.key_levels_from_options) == 2
    assert "Call wall near 2450" in card.key_levels_from_options
    assert "Put support near 2350" in card.key_levels_from_options
    assert "DXY weakening" not in card.key_levels_from_options  # not an options finding


def test_build_strategy_card_key_levels_empty_when_no_options_findings():
    card = build_strategy_card(
        snapshot=_snapshot(),
        coordinator_output=_coordinator_output(
            key_findings=["Macro prior finding: DXY weakening"],
        ),
    )

    assert card.key_levels_from_options == []


def test_build_strategy_card_key_levels_does_not_invent_prices():
    card = build_strategy_card(
        snapshot=_snapshot(),
        coordinator_output=_coordinator_output(
            key_findings=["Macro prior bias is bullish."],
            summary="No options levels available.",
        ),
    )

    assert card.key_levels_from_options == []


# ═══════════════════════════════════════════════════════════════════════
# unavailable coordinator
# ═══════════════════════════════════════════════════════════════════════


def test_build_strategy_card_handles_unavailable_coordinator():
    card = build_strategy_card(
        snapshot=_snapshot(),
        coordinator_output=_coordinator_output(
            bias=AgentBias.UNAVAILABLE,
            confidence=0.0,
            status=AgentStatus.UNAVAILABLE,
            key_findings=[],
        ),
    )

    assert card.bias == AgentBias.UNAVAILABLE
    assert card.confidence == 0.0
    assert "unavailable" in card.scenario_summary.lower()
    assert card.is_trade_instruction is False


# ═══════════════════════════════════════════════════════════════════════
# immutability
# ═══════════════════════════════════════════════════════════════════════


def test_build_strategy_card_does_not_mutate_inputs():
    snapshot = _snapshot()
    coordinator = _coordinator_output()
    risk = _risk_output()

    before_snapshot = copy.deepcopy(snapshot)
    before_coordinator = coordinator.model_copy(deep=True)
    before_risk = risk.model_copy(deep=True)

    build_strategy_card(
        snapshot=snapshot,
        coordinator_output=coordinator,
        risk_output=risk,
    )

    assert snapshot == before_snapshot
    assert coordinator == before_coordinator
    assert risk == before_risk


# ═══════════════════════════════════════════════════════════════════════
# edge: empty snapshot fields
# ═══════════════════════════════════════════════════════════════════════


def test_build_strategy_card_handles_minimal_snapshot():
    card = build_strategy_card(
        snapshot={"snapshot_id": "minimal:2026-05-14"},
        coordinator_output=_coordinator_output(),
    )

    assert card.asset == "XAUUSD"  # default
    assert card.input_snapshot_ids["analysis_snapshot"] == "minimal:2026-05-14"
    assert card.input_snapshot_ids["coordinator"] == "XAUUSD:2026-05-14:analysis"
    assert card.is_trade_instruction is False


def test_build_strategy_card_accepts_run_id_from_snapshot():
    card = build_strategy_card(
        snapshot={**_snapshot(), "run_id": "run-explicit-42"},
        coordinator_output=_coordinator_output(),
    )

    assert card.run_id == "run-explicit-42"
