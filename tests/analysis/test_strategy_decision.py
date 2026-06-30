from __future__ import annotations

from apps.analysis.agents.schemas import AgentBias, AgentStatus
from apps.analysis.confidence import compute_confidence_kernel
from apps.decision import StrategyDecision, build_strategy_card_from_decision, build_strategy_decision


def _market_state(*, technical_status: str = "available") -> dict:
    return {
        "snapshot_id": "XAUUSD:2026-05-14:analysis",
        "asset": "XAUUSD",
        "trade_date": "2026-05-14",
        "run_id": "run-decision-test",
        "bias": "bullish",
        "macro": {"status": "available"},
        "options": {"status": "available"},
        "technical": {"status": technical_status},
        "source_refs": [{"source": "analysis_snapshot", "snapshot_id": "XAUUSD:2026-05-14:analysis"}],
    }


def _confidence_kernel(market_state: dict, *, conflict: bool = False):
    return compute_confidence_kernel(
        market_state=market_state,
        evidence_items=[
            {"source_type": "official", "status": "confirmed", "bias": "bullish"},
            {"source_type": "structured", "status": "confirmed", "bias": "bearish" if conflict else "bullish"},
        ],
        agent_outputs=[],
    )


def test_strategy_decision_is_deterministic_and_research_only() -> None:
    market_state = _market_state()
    kernel = _confidence_kernel(market_state)
    evidence_items = [
        {"id": "macro-real-rates", "summary": "Real rates are easing", "source_refs": [{"source": "fred"}]},
        {"id": "options-wall", "summary": "Options wall supports watchlist view", "source_refs": [{"source": "cme"}]},
    ]

    first = build_strategy_decision(
        market_state=market_state,
        evidence_items=evidence_items,
        confidence_kernel=kernel,
        agent_outputs=[],
    )
    second = build_strategy_decision(
        market_state=market_state,
        evidence_items=evidence_items,
        confidence_kernel=kernel,
        agent_outputs=[],
    )

    assert isinstance(first, StrategyDecision)
    assert first == second
    assert first.asset == "XAUUSD"
    assert first.bias is AgentBias.BULLISH
    assert first.is_trade_instruction is False
    assert first.feasibility_label in {"watchlist_candidate", "high_conviction_research"}
    assert first.required_confirmations


def test_strategy_decision_feasibility_caps_conflicts_and_missing_technical() -> None:
    market_state = _market_state(technical_status="unavailable")
    kernel = _confidence_kernel(market_state, conflict=True)

    decision = build_strategy_decision(
        market_state=market_state,
        evidence_items=[{"id": "conflict", "summary": "Macro and options conflict", "bias": "mixed"}],
        confidence_kernel=kernel,
        agent_outputs=[],
    )

    assert decision.feasibility_label == "research_only"
    assert decision.feasibility_score <= 0.65
    assert "technical_unavailable" in decision.confidence_kernel.caps
    assert any("technical" in reason for reason in decision.feasibility_reasons)


def test_strategy_card_can_be_rendered_from_strategy_decision() -> None:
    market_state = _market_state()
    kernel = _confidence_kernel(market_state)
    decision = build_strategy_decision(
        market_state=market_state,
        evidence_items=[{"id": "macro", "summary": "Macro evidence", "source_refs": [{"source": "fred"}]}],
        confidence_kernel=kernel,
        agent_outputs=[],
    )

    card = build_strategy_card_from_decision(decision)

    assert card.asset == decision.asset
    assert card.bias is decision.bias
    assert card.confidence == decision.confidence
    assert card.is_trade_instruction is False
    assert card.input_snapshot_ids["analysis_snapshot"] == decision.snapshot_id
    assert card.input_snapshot_ids["coordinator"] == decision.snapshot_id
    assert card.confidence_kernel["overall"] == decision.confidence_kernel.overall
    assert any(decision.feasibility_label in item for item in card.risk_points)


def test_strategy_decision_unavailable_when_confidence_too_low() -> None:
    market_state = {
        **_market_state(technical_status="unavailable"),
        "macro": {"status": "unavailable"},
        "options": {"status": "unavailable"},
    }
    kernel = compute_confidence_kernel(market_state=market_state, evidence_items=[], agent_outputs=[])

    decision = build_strategy_decision(
        market_state=market_state,
        evidence_items=[],
        confidence_kernel=kernel,
        agent_outputs=[],
    )

    assert decision.bias is AgentBias.UNAVAILABLE
    assert decision.status is AgentStatus.UNAVAILABLE
    assert decision.feasibility_label == "not_actionable"
    assert decision.is_trade_instruction is False
