from __future__ import annotations

from apps.analysis.agents.quality_gate import evaluate_agent_quality_gate
from apps.analysis.agents.quality_gate_evaluator import QualityGateAction, QualityGateDecision
from apps.gold_runtime_orchestration import build_gold_runtime_execution_summary


def _decision(action: QualityGateAction) -> QualityGateDecision:
    return QualityGateDecision(
        action=action,
        review_status="pass" if action is QualityGateAction.PASS else ("blocked" if action is QualityGateAction.BLOCK_PUBLISH else "needs_review"),
        publish_allowed=action is QualityGateAction.PASS,
        fallback_recommended=action is QualityGateAction.FALLBACK,
        findings=[],
        fallback_actions=["fallback_cross_check"] if action is QualityGateAction.FALLBACK else [],
        source_ref_count=1,
        evidence_item_count=1,
        max_confidence=0.72,
    )


def test_runtime_summary_rejects_unvalidated_fallback_outputs() -> None:
    primary = _decision(QualityGateAction.FALLBACK)
    fallback = _decision(QualityGateAction.PASS)
    agent_loop = evaluate_agent_quality_gate(
        agent_outputs=[{"agent_name": "coordinator_agent", "snapshot_id": "primary"}],
        primary_quality_gate_decision=primary,
        fallback_outputs={
            "final_report_paths": ["/tmp/fallback/final_report.md"],
            "strategy_card_paths": ["/tmp/fallback/strategy_card.json"],
        },
        fallback_quality_gate_decision=fallback,
        corrective_fallback_succeeded=True,
        unresolved_reason_codes=[],
    )

    summary = build_gold_runtime_execution_summary(
        run_mode="premarket_full_run",
        quality_gate_decision=primary,
        agent_loop_decision=agent_loop,
        accepted_outputs={
            "final_report_paths": ["/tmp/primary/final_report.md"],
            "strategy_card_paths": ["/tmp/primary/strategy_card.json"],
        },
    )

    assert summary["quality_gate_status"] == "fallback_required"
    assert summary["accepted_outputs"] == {}
    assert summary["writes"] == []
    assert summary["agent_loop_decision"]["fallback_trace"]["accepted_output"] is None
    assert summary["no_strong_conclusion"] is True


def test_runtime_summary_blocks_strong_conclusion_when_fallback_quality_gate_fails() -> None:
    primary = _decision(QualityGateAction.FALLBACK)
    fallback = _decision(QualityGateAction.BLOCK_PUBLISH)
    agent_loop = evaluate_agent_quality_gate(
        agent_outputs=[{"agent_name": "coordinator_agent", "snapshot_id": "primary"}],
        primary_quality_gate_decision=primary,
        fallback_outputs={"final_report_paths": ["/tmp/fallback/final_report.md"]},
        fallback_quality_gate_decision=fallback,
    )

    summary = build_gold_runtime_execution_summary(
        run_mode="premarket_full_run",
        quality_gate_decision=primary,
        agent_loop_decision=agent_loop,
        accepted_outputs={"final_report_paths": ["/tmp/primary/final_report.md"]},
    )

    assert summary["accepted_outputs"] == {}
    assert summary["no_strong_conclusion"] is True
    assert summary["strategy_card_override"] == {
        "bias": "neutral",
        "action": "observe_wait",
        "reason": "fallback_failed_or_needs_review",
    }
    assert summary["agent_loop_decision"]["fallback_trace"]["accepted_output"] is None
