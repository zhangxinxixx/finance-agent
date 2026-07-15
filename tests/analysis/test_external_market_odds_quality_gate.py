from __future__ import annotations

from apps.analysis.agents.quality_gate_evaluator import QualityGateAction, evaluate_quality_gate


def _output(*, agent_name: str, bias: str, confidence: float, data_category: str, source_kind: str) -> dict:
    return {
        "version": "1.0",
        "agent_name": agent_name,
        "module": agent_name,
        "snapshot_id": f"snapshot:{agent_name}",
        "input_snapshot_ids": {"analysis_snapshot": "snapshot:root"},
        "bias": bias,
        "confidence": confidence,
        "key_findings": ["fixture"],
        "risk_points": [],
        "watchlist": [],
        "invalid_conditions": [],
        "summary": "fixture",
        "source_refs": [{"source_ref": f"fixture:{agent_name}", "source_kind": source_kind}],
        "status": "success",
        "created_at": "2026-07-16T00:00:00+00:00",
        "data_category": data_category,
        "evidence_items": [{"source_kind": source_kind, "factor": "fixture"}],
        "input_payload": {"source_kind": source_kind},
    }


def test_external_odds_alone_blocks_strong_directional_conclusion() -> None:
    decision = evaluate_quality_gate(
        agent_outputs=[
            _output(
                agent_name="jin10_report_analysis_agent",
                bias="bullish",
                confidence=0.90,
                data_category="external_opinion",
                source_kind="jin10_external_market_odds",
            )
        ],
        gold_macro_overview={"net_bias": "strong_bullish"},
        source_health={"overall_status": "ready", "p0_missing": [], "can_build_gold_macro_overview": True},
    )
    assert decision.action is QualityGateAction.BLOCK_PUBLISH
    assert decision.publish_allowed is False
    assert "external_market_odds_only_strong_conclusion" in {finding.code for finding in decision.findings}


def test_external_odds_do_not_block_neutral_watch_context() -> None:
    decision = evaluate_quality_gate(
        agent_outputs=[
            _output(
                agent_name="jin10_report_analysis_agent",
                bias="neutral",
                confidence=0.55,
                data_category="external_opinion",
                source_kind="jin10_external_market_odds",
            )
        ],
        gold_macro_overview={"net_bias": "neutral"},
        source_health={"overall_status": "ready", "p0_missing": [], "can_build_gold_macro_overview": True},
    )
    assert "external_market_odds_only_strong_conclusion" not in {finding.code for finding in decision.findings}


def test_internal_market_confirmation_allows_normal_quality_gate_evaluation() -> None:
    decision = evaluate_quality_gate(
        agent_outputs=[
            _output(
                agent_name="jin10_report_analysis_agent",
                bias="bullish",
                confidence=0.80,
                data_category="external_opinion",
                source_kind="jin10_external_market_odds",
            ),
            _output(
                agent_name="market_odds_agent",
                bias="bullish",
                confidence=0.80,
                data_category="system_inference",
                source_kind="market_derived_odds",
            ),
        ],
        gold_macro_overview={"net_bias": "bullish", "market_derived_odds": {"status": "available"}},
        source_health={"overall_status": "ready", "p0_missing": [], "can_build_gold_macro_overview": True},
    )
    assert "external_market_odds_only_strong_conclusion" not in {finding.code for finding in decision.findings}


def test_degraded_fixed_gold_context_requires_manual_review() -> None:
    decision = evaluate_quality_gate(
        agent_outputs=[_output(agent_name="coordinator_agent", bias="neutral", confidence=0.55, data_category="system_inference", source_kind="coordinator")],
        gold_macro_overview={
            "net_bias": "neutral",
            "gold_analysis_context": {
                "status": "degraded",
                "baseline_kind": "weekly_anchor",
                "freshness": {"analysis_baseline": {"status": "stale"}},
            },
        },
        source_health={"overall_status": "ready", "p0_missing": [], "can_build_gold_macro_overview": True},
    )

    assert decision.action is QualityGateAction.MANUAL_REVIEW
    assert "gold_analysis_context_degraded" in {finding.code for finding in decision.findings}
