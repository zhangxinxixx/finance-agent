from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from apps.analysis.agents.quality_gate import AcceptedOutputReference, AgentLoopDecision
from apps.analysis.agents.schemas import AcceptedStateConclusion, AgentBias, AgentOutput, AgentStatus
from apps.worker.composite_analysis_pipeline import report_coordinator_output


def test_report_coordinator_output_clears_typed_conclusion_when_nothing_is_accepted() -> None:
    primary = AgentOutput(
        version="1.0",
        agent_name="coordinator_agent",
        module="coordinator",
        snapshot_id="snapshot-1",
        input_snapshot_ids={},
        bias=AgentBias.BULLISH,
        confidence=0.8,
        key_findings=["upside"],
        risk_points=[],
        watchlist=[],
        summary="Bullish conclusion",
        source_refs=[],
        status=AgentStatus.SUCCESS,
        created_at=datetime(2026, 7, 28, tzinfo=UTC),
        accepted_state_conclusion=AcceptedStateConclusion(
            direction=AgentBias.BULLISH,
            state_bias="strong_bullish",
            market_stage="direction_decision",
            core_thesis="Bullish conclusion",
            dominant_drivers=[],
        ),
    )
    decision = AgentLoopDecision(
        decision="needs_review",
        review_status="needs_review",
        publish_allowed=False,
        accepted_output=AcceptedOutputReference(),
    )

    selected = report_coordinator_output(
        primary=primary,
        fallback_execution=SimpleNamespace(fallback_agent_outputs={}),
        agent_loop_decision=decision,
    )

    assert selected.bias is AgentBias.NEUTRAL
    assert selected.accepted_state_conclusion is None
    assert primary.accepted_state_conclusion is not None
