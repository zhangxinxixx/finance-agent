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


def test_execute_agent_loop_fallback_tasks_runs_independent_source_cross_check() -> None:
    from apps.analysis.agents.schemas import AgentOutput

    primary = AgentOutput.model_validate(
        {
            "version": "1.0",
            "agent_name": "coordinator_agent",
            "module": "coordinator",
            "snapshot_id": "snap-primary",
            "input_snapshot_ids": {"analysis_snapshot": "snap-primary"},
            "bias": "bullish",
            "confidence": 0.76,
            "key_findings": ["Primary directional conclusion."],
            "risk_points": [],
            "watchlist": [],
            "invalid_conditions": [],
            "summary": "Strong bullish.",
            "source_refs": [{"source": "fred", "source_ref": "fred:DGS10"}],
            "status": "success",
            "created_at": "2026-07-06T09:30:00+00:00",
            "evidence_items": [{"factor": "real_rates", "source_tier": "official"}],
            "data_quality": [],
        }
    )
    secondary = AgentOutput.model_validate(
        {
            "version": "1.0",
            "agent_name": "cme_options_agent",
            "module": "cme_options",
            "snapshot_id": "snap-options",
            "input_snapshot_ids": {"analysis_snapshot": "snap-primary"},
            "bias": "mixed",
            "confidence": 0.62,
            "key_findings": ["Options evidence is mixed."],
            "risk_points": [],
            "watchlist": [],
            "invalid_conditions": [],
            "summary": "Mixed options evidence.",
            "source_refs": [{"source": "cme", "source_ref": "cme:bulletin"}],
            "status": "success",
            "created_at": "2026-07-06T09:30:00+00:00",
            "evidence_items": [{"factor": "option_wall", "source_tier": "exchange"}],
            "data_quality": [],
        }
    )
    primary_decision = QualityGateDecision(
        action=QualityGateAction.FALLBACK,
        review_status="needs_review",
        publish_allowed=True,
        fallback_recommended=True,
        manual_review_required=True,
        findings=[
            {
                "code": "single_source_important_conclusion",
                "severity": "fallback",
                "message": "Important directional conclusion depends on single-source evidence.",
                "evidence": {},
            }
        ],
        fallback_actions=["cross_check_with_independent_source"],
        source_ref_count=1,
        evidence_item_count=1,
        max_confidence=0.76,
    )

    execution = execute_agent_loop_fallback_tasks(
        agent_outputs=[primary, secondary],
        primary_quality_gate_decision=primary_decision,
        source_health={"overall_status": "ready", "p0_missing": [], "can_build_gold_macro_overview": True},
        created_at=datetime(2026, 7, 6, 9, 30, tzinfo=timezone.utc),
    )

    assert execution.task_results[0]["task_type"] == "cross_check_with_independent_source"
    assert execution.task_results[0]["status"] == "success"
    assert execution.task_results[0]["fallback_output_agent"] == "fallback_cross_check_agent"
    assert "fallback_cross_check_agent" in execution.fallback_agent_outputs
    cross_check = execution.fallback_agent_outputs["fallback_cross_check_agent"]
    assert cross_check.status is AgentStatus.SUCCESS
    assert cross_check.confidence == 0.6
    assert cross_check.input_payload["independent_source_count"] == 2
    assert cross_check.input_payload["checked_agents"] == ["coordinator_agent", "cme_options_agent"]
    assert cross_check.input_payload["fallback_of"]["agent_name"] == "coordinator_agent"


def test_execute_agent_loop_fallback_tasks_downgrades_single_source_context() -> None:
    from apps.analysis.agents.schemas import AgentOutput

    primary = AgentOutput.model_validate(
        {
            "version": "1.0",
            "agent_name": "gold_macro_overview_agent",
            "module": "gold_macro_overview",
            "snapshot_id": "snap-primary",
            "input_snapshot_ids": {"analysis_snapshot": "snap-primary"},
            "bias": "bearish",
            "confidence": 0.78,
            "key_findings": ["Single-source directional conclusion."],
            "risk_points": [],
            "watchlist": [],
            "invalid_conditions": [],
            "summary": "Strong bearish.",
            "source_refs": [{"source": "jin10", "source_ref": "jin10:article:1"}],
            "status": "success",
            "created_at": "2026-07-06T09:30:00+00:00",
            "evidence_items": [{"factor": "headline", "source_tier": "media"}],
            "data_quality": ["single_source"],
        }
    )
    primary_decision = QualityGateDecision(
        action=QualityGateAction.FALLBACK,
        review_status="needs_review",
        publish_allowed=True,
        fallback_recommended=True,
        manual_review_required=True,
        findings=[
            {
                "code": "single_source_important_conclusion",
                "severity": "fallback",
                "message": "Important directional conclusion depends on single-source evidence.",
                "evidence": {},
            }
        ],
        fallback_actions=["downgrade_to_single_source_context_until_confirmed"],
        source_ref_count=1,
        evidence_item_count=1,
        max_confidence=0.78,
    )

    execution = execute_agent_loop_fallback_tasks(
        agent_outputs=[primary],
        primary_quality_gate_decision=primary_decision,
        source_health={"overall_status": "ready", "p0_missing": [], "can_build_gold_macro_overview": True},
        created_at=datetime(2026, 7, 6, 9, 30, tzinfo=timezone.utc),
    )

    assert execution.task_results[0]["task_type"] == "downgrade_to_single_source_context_until_confirmed"
    assert execution.task_results[0]["status"] == "success"
    assert execution.task_results[0]["fallback_output_agent"] == "single_source_downgrade_agent"
    downgrade = execution.fallback_agent_outputs["single_source_downgrade_agent"]
    assert downgrade.bias is AgentBias.NEUTRAL
    assert downgrade.status is AgentStatus.PARTIAL
    assert downgrade.confidence == 0.5
    assert "single_source_downgrade" in downgrade.data_quality
    assert downgrade.input_payload["independent_source_count"] == 1
    assert downgrade.input_payload["fallback_task"] == "downgrade_to_single_source_context_until_confirmed"


def test_execute_agent_loop_fallback_tasks_does_not_mark_unimplemented_reparse_success() -> None:
    from apps.analysis.agents.schemas import AgentOutput

    primary = AgentOutput.model_validate(
        {
            "version": "1.0",
            "agent_name": "cme_options_agent",
            "module": "cme_options",
            "snapshot_id": "snap-primary",
            "input_snapshot_ids": {"analysis_snapshot": "snap-primary"},
            "bias": "bullish",
            "confidence": 0.58,
            "key_findings": ["Parsed options wall."],
            "risk_points": [],
            "watchlist": [],
            "invalid_conditions": [],
            "summary": "Parse-suspect options output.",
            "source_refs": [{"source": "cme", "source_ref": "cme:bulletin"}],
            "status": "partial",
            "created_at": "2026-07-06T09:30:00+00:00",
            "evidence_items": [{"factor": "gamma_wall", "source_tier": "exchange"}],
            "data_quality": ["parse_suspect"],
        }
    )
    primary_decision = QualityGateDecision(
        action=QualityGateAction.FALLBACK,
        review_status="needs_review",
        publish_allowed=True,
        fallback_recommended=True,
        retry_recommended=False,
        manual_review_required=True,
        findings=[
            {
                "code": "parse_or_required_field_quality_gap",
                "severity": "fallback",
                "message": "Parse gap.",
                "evidence": {},
            }
        ],
        fallback_actions=["fallback_reparse"],
        source_ref_count=1,
        evidence_item_count=1,
        max_confidence=0.58,
    )

    execution = execute_agent_loop_fallback_tasks(
        agent_outputs=[primary],
        primary_quality_gate_decision=primary_decision,
        source_health={"overall_status": "ready", "p0_missing": [], "can_build_gold_macro_overview": True},
        created_at=datetime(2026, 7, 6, 9, 30, tzinfo=timezone.utc),
    )

    assert execution.task_results[0]["task_type"] == "fallback_reparse"
    assert execution.task_results[0]["status"] == "queued_not_implemented"
    assert execution.task_results[0]["fallback_output_agent"] is None
    assert execution.task_results[1]["task_type"] == "fallback_conservative_synthesis"
    assert execution.task_results[1]["status"] == "success"


def test_execute_agent_loop_fallback_tasks_runs_cme_options_reparse_when_snapshot_available() -> None:
    from apps.analysis.agents.schemas import AgentOutput

    primary = AgentOutput.model_validate(
        {
            "version": "1.0",
            "agent_name": "cme_options_agent",
            "module": "cme_options",
            "snapshot_id": "snap-primary",
            "input_snapshot_ids": {"analysis_snapshot": "snap-primary"},
            "bias": "bullish",
            "confidence": 0.58,
            "key_findings": ["Parse suspect primary."],
            "risk_points": [],
            "watchlist": [],
            "invalid_conditions": [],
            "summary": "Parse-suspect options output.",
            "source_refs": [{"source": "cme", "source_ref": "cme:bulletin"}],
            "status": "partial",
            "created_at": "2026-07-06T09:30:00+00:00",
            "evidence_items": [{"factor": "gamma_wall", "source_tier": "exchange"}],
            "data_quality": ["parse_suspect"],
        }
    )
    primary_decision = QualityGateDecision(
        action=QualityGateAction.FALLBACK,
        review_status="needs_review",
        publish_allowed=True,
        fallback_recommended=True,
        retry_recommended=False,
        manual_review_required=True,
        findings=[
            {
                "code": "parse_or_required_field_quality_gap",
                "severity": "fallback",
                "message": "Parse gap.",
                "evidence": {},
            }
        ],
        fallback_actions=["fallback_reparse"],
        source_ref_count=1,
        evidence_item_count=1,
        max_confidence=0.58,
    )
    snapshot = {
        "snapshot_id": "snap-primary",
        "input_snapshot_ids": {"analysis_snapshot": "snap-primary"},
        "source_refs": [{"source": "cme", "source_ref": "cme:bulletin"}],
        "options": {
            "status": "available",
            "data": {
                "source_status": "FINAL",
                "intent": {"type": "call_buying", "score": 0.7},
                "wall_scores": [{"strike": 3450, "wall_score": 0.8, "side": "call"}],
                "support_resistance": {
                    "support": [{"strike": 3380}],
                    "resistance": [{"strike": 3500}],
                },
                "gex": {
                    "netgex_aggregate": {"gamma_zero": {"price": 3425}},
                    "by_expiry": {},
                },
                "data_quality": {"categories": {"prelim_data": 0}, "warnings": []},
            },
        },
    }

    execution = execute_agent_loop_fallback_tasks(
        agent_outputs=[primary],
        primary_quality_gate_decision=primary_decision,
        snapshot=snapshot,
        source_health={"overall_status": "ready", "p0_missing": [], "can_build_gold_macro_overview": True},
        created_at=datetime(2026, 7, 6, 9, 30, tzinfo=timezone.utc),
    )

    assert execution.task_results[0]["task_type"] == "fallback_reparse"
    assert execution.task_results[0]["status"] == "success"
    assert execution.task_results[0]["fallback_output_agent"] == "cme_options_reparse_agent"
    assert "cme_options_reparse_agent" in execution.fallback_agent_outputs
    reparse = execution.fallback_agent_outputs["cme_options_reparse_agent"]
    assert reparse.agent_name == "cme_options_reparse_agent"
    assert reparse.input_payload["fallback_of"]["agent_name"] == "cme_options_agent"
    assert reparse.input_payload["fallback_task"] == "fallback_reparse"
    assert execution.task_results[1]["task_type"] == "fallback_conservative_synthesis"
