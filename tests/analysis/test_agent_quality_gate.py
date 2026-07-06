from __future__ import annotations

from datetime import datetime, timezone

from apps.analysis.agents.quality_gate import evaluate_agent_quality_gate, execute_agent_loop_fallback_tasks
from apps.analysis.agents.schemas import AgentBias, AgentStatus
from apps.api.services.quality_gate_service import QualityGateAction, QualityGateDecision


def _decision(action: QualityGateAction, *, findings: list[dict] | None = None) -> QualityGateDecision:
    return QualityGateDecision(
        action=action,
        review_status="pass" if action is QualityGateAction.PASS else ("blocked" if action is QualityGateAction.BLOCK_PUBLISH else "needs_review"),
        publish_allowed=action is not QualityGateAction.BLOCK_PUBLISH,
        fallback_recommended=action is QualityGateAction.FALLBACK,
        retry_recommended=action is QualityGateAction.RETRY,
        manual_review_required=action in {QualityGateAction.FALLBACK, QualityGateAction.MANUAL_REVIEW},
        findings=findings or [],
        fallback_actions=["fallback_reanalyze"] if action is QualityGateAction.FALLBACK else [],
        source_ref_count=1,
        evidence_item_count=1,
        max_confidence=0.72,
    )


def test_agent_loop_accepts_fallback_output_without_silently_overwriting_primary() -> None:
    primary = _decision(
        QualityGateAction.FALLBACK,
        findings=[{"code": "unsupported_claim", "severity": "fallback", "message": "Unsupported claim.", "evidence": {}}],
    )
    fallback = _decision(QualityGateAction.PASS)

    result = evaluate_agent_quality_gate(
        agent_outputs=[{"agent_name": "gold_macro_overview_agent", "snapshot_id": "primary-snap"}],
        primary_quality_gate_decision=primary,
        fallback_outputs={"final_report_paths": ["storage/outputs/fallback/final_report.md"]},
        fallback_quality_gate_decision=fallback,
        review_items=[{"review_id": "review-1", "reason": "unsupported_claim"}],
    )

    assert result.decision == "passed"
    assert result.accepted_outputs == {"final_report_paths": ["storage/outputs/fallback/final_report.md"]}
    assert result.fallback_of == ["gold_macro_overview_agent:primary-snap"]
    assert result.fallback_trace["fallback_used"] is True
    assert result.fallback_trace["accepted_output"] == "fallback"
    assert result.fallback_trace["review_items"] == [{"review_id": "review-1", "reason": "unsupported_claim"}]


def test_agent_loop_failed_fallback_degrades_to_observe_wait_and_no_strong_conclusion() -> None:
    primary = _decision(
        QualityGateAction.FALLBACK,
        findings=[{"code": "parse_or_required_field_quality_gap", "severity": "fallback", "message": "Parse gap.", "evidence": {}}],
    )
    fallback = _decision(
        QualityGateAction.BLOCK_PUBLISH,
        findings=[{"code": "contradicted_claim", "severity": "blocker", "message": "Contradicted.", "evidence": {}}],
    )

    result = evaluate_agent_quality_gate(
        agent_outputs=[{"agent_name": "cme_options_agent", "snapshot_id": "primary-snap"}],
        primary_quality_gate_decision=primary,
        fallback_outputs={"final_report_paths": ["storage/outputs/fallback/final_report.md"]},
        fallback_quality_gate_decision=fallback,
    )

    assert result.decision == "blocked"
    assert result.publish_allowed is False
    assert result.accepted_outputs == {}
    assert result.no_strong_conclusion is True
    assert result.strategy_card_override == {
        "bias": "neutral",
        "action": "observe_wait",
        "reason": "fallback_failed_or_needs_review",
    }


def test_execute_agent_loop_fallback_tasks_builds_conservative_synthesis_output() -> None:
    primary = {
        "version": "1.0",
        "agent_name": "coordinator_agent",
        "module": "coordinator",
        "snapshot_id": "snap-primary",
        "input_snapshot_ids": {"analysis_snapshot": "snap-primary"},
        "bias": "bullish",
        "confidence": 0.82,
        "key_findings": ["Primary strong conclusion."],
        "risk_points": [],
        "watchlist": [],
        "invalid_conditions": [],
        "summary": "Strong bullish.",
        "source_refs": [{"source": "fred", "source_ref": "DGS10"}],
        "status": "success",
        "created_at": "2026-07-06T09:30:00+00:00",
        "evidence_items": [{"factor": "real_rates", "source_tier": "official"}],
        "data_quality": [],
    }
    primary_decision = _decision(
        QualityGateAction.FALLBACK,
        findings=[{"code": "unsupported_claim", "severity": "fallback", "message": "Unsupported.", "evidence": {}}],
    )

    from apps.analysis.agents.schemas import AgentOutput

    execution = execute_agent_loop_fallback_tasks(
        agent_outputs=[AgentOutput.model_validate(primary)],
        primary_quality_gate_decision=primary_decision,
        source_health={"overall_status": "ready", "p0_missing": [], "can_build_gold_macro_overview": True},
        created_at=datetime(2026, 7, 6, 9, 30, tzinfo=timezone.utc),
    )

    fallback = execution.fallback_agent_outputs["fallback_synthesis_agent"]
    assert execution.attempted is True
    assert execution.task_results[0]["task_type"] == "fallback_reanalyze"
    assert fallback.bias is AgentBias.NEUTRAL
    assert fallback.status is AgentStatus.PARTIAL
    assert fallback.confidence == 0.55
    assert fallback.input_payload["fallback_of"]["agent_name"] == "coordinator_agent"
    assert execution.fallback_quality_gate_decision is not None
