from __future__ import annotations

from apps.analysis.agents.quality_gate import evaluate_agent_quality_gate
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
