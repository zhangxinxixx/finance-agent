from __future__ import annotations

from apps.analysis.agents.quality_gate_evaluator import preserve_unresolved_pre_gate
from apps.api.services.quality_gate_service import QualityGateAction, QualityGateDecision, evaluate_quality_gate


def _agent_output(
    *,
    agent_name: str = "gold_macro_overview_agent",
    confidence: float = 0.82,
    bias: str = "bullish",
    source_refs: list[dict] | None = None,
    evidence_items: list[dict] | None = None,
    data_quality: list[str] | None = None,
    invalid_conditions: list[str] | None = None,
    invalidation_conditions: list[str] | None = None,
    active_blockers: list[str] | None = None,
    data_gaps: list[dict] | None = None,
    review_triggers: list[str] | None = None,
) -> dict:
    return {
        "version": "1.0",
        "agent_name": agent_name,
        "module": "gold_v3",
        "snapshot_id": "XAUUSD:2026-07-06:run-001",
        "input_snapshot_ids": {"gold_macro_overview": "analysis/gold_mainlines/2026-07-06/run/gold_macro_overview.json"},
        "bias": bias,
        "confidence": confidence,
        "key_findings": ["Gold macro overview is directional."],
        "risk_points": [],
        "watchlist": [],
        "invalid_conditions": list(invalid_conditions or []),
        "invalidation_conditions": list(invalidation_conditions or []),
        "active_blockers": list(active_blockers or []),
        "data_gaps": list(data_gaps or []),
        "review_triggers": list(review_triggers or []),
        "summary": "Directional gold macro overview.",
        "source_refs": list(
            source_refs
            if source_refs is not None
            else [{"source": "fred", "source_ref": "DGS10:2026-07-06"}]
        ),
        "status": "success",
        "created_at": "2026-07-06T09:30:00+00:00",
        "evidence_items": list(
            evidence_items
            if evidence_items is not None
            else [
                {
                    "factor": "real_rates",
                    "direction": bias,
                    "strength": 0.7,
                    "confidence": confidence,
                    "source_tier": "official",
                    "source_refs": [{"source": "fred", "source_ref": "DGS10:2026-07-06"}],
                }
            ]
        ),
        "data_quality": list(data_quality or []),
    }


def test_quality_gate_blocks_p0_gap_with_strong_conclusion() -> None:
    decision = evaluate_quality_gate(
        agent_outputs=[_agent_output()],
        gold_macro_overview={
            "net_bias": "strong_bullish",
            "one_line_conclusion": "Strong bullish breakout.",
            "source_refs": [{"source": "fred", "source_ref": "DGS10"}],
        },
        source_health={
            "overall_status": "blocked",
            "p0_missing": ["xauusd_price"],
            "can_build_gold_macro_overview": False,
        },
    )

    assert decision.action is QualityGateAction.BLOCK_PUBLISH
    assert decision.review_status == "blocked"
    assert decision.publish_allowed is False
    assert {finding.code for finding in decision.findings} == {"p0_gap_strong_conclusion"}


def test_quality_gate_honors_source_health_strong_conclusion_blocker() -> None:
    decision = evaluate_quality_gate(
        agent_outputs=[],
        gold_macro_overview={
            "net_bias": "mixed",
            "source_refs": [{"source": "event_flow", "source_ref": "gold_macro_overview"}],
        },
        source_health={
            "overall_status": "blocked",
            "p0_missing": ["xauusd_price"],
            "can_build_gold_macro_overview": False,
            "blocking_reasons": ["P0 source gap conflicts with strong GoldMacroOverview conclusion"],
        },
    )

    assert decision.action is QualityGateAction.BLOCK_PUBLISH
    assert decision.publish_allowed is False
    assert any(finding.code == "p0_gap_strong_conclusion" for finding in decision.findings)


def test_quality_gate_blocks_missing_source_refs() -> None:
    decision = evaluate_quality_gate(
        agent_outputs=[_agent_output(source_refs=[], evidence_items=[{"factor": "option_wall", "source_tier": "exchange"}])],
        gold_macro_overview={"net_bias": "bullish", "source_refs": []},
        source_health={"overall_status": "ready", "p0_missing": [], "can_build_gold_macro_overview": True},
    )

    assert decision.action is QualityGateAction.BLOCK_PUBLISH
    assert decision.source_ref_count == 0
    assert any(finding.code == "source_refs_missing" for finding in decision.findings)


def test_quality_gate_requires_manual_review_for_high_confidence_without_evidence_items() -> None:
    decision = evaluate_quality_gate(
        agent_outputs=[_agent_output(confidence=0.86, evidence_items=[])],
        gold_macro_overview={"net_bias": "bullish"},
        source_health={"overall_status": "ready", "p0_missing": [], "can_build_gold_macro_overview": True},
    )

    assert decision.action is QualityGateAction.MANUAL_REVIEW
    assert decision.manual_review_required is True
    assert any(finding.code == "high_confidence_without_evidence_items" for finding in decision.findings)


def test_quality_gate_requires_manual_review_for_mixed_without_driver_decomposition() -> None:
    decision = evaluate_quality_gate(
        agent_outputs=[_agent_output(confidence=0.62, bias="mixed")],
        gold_macro_overview={"net_bias": "mixed", "driver_conflict": {}},
        source_health={"overall_status": "ready", "p0_missing": [], "can_build_gold_macro_overview": True},
    )

    assert decision.action is QualityGateAction.MANUAL_REVIEW
    assert any(finding.code == "mixed_without_driver_decomposition" for finding in decision.findings)


def test_quality_gate_recommends_fallback_for_single_source_important_conclusion() -> None:
    decision = evaluate_quality_gate(
        agent_outputs=[
            _agent_output(
                confidence=0.76,
                data_quality=["single_source"],
                evidence_items=[
                    {
                        "factor": "geopolitical_war",
                        "direction": "bullish",
                        "confidence": 0.76,
                        "verification_status": "single_source",
                    }
                ],
            )
        ],
        gold_macro_overview={"net_bias": "bullish"},
        source_health={"overall_status": "ready", "p0_missing": [], "can_build_gold_macro_overview": True},
    )

    assert decision.action is QualityGateAction.FALLBACK
    assert decision.fallback_recommended is True
    assert "cross_check_with_independent_source" in decision.fallback_actions
    assert any(finding.code == "single_source_important_conclusion" for finding in decision.findings)


def test_quality_gate_stops_fact_review_needs_review_from_strong_publication() -> None:
    decision = evaluate_quality_gate(
        agent_outputs=[_agent_output(confidence=0.71, bias="neutral")],
        gold_macro_overview={
            "net_bias": "bullish",
            "fact_review_status": "needs_review",
            "source_refs": [{"source": "event_flow", "source_ref": "event:1"}],
        },
        source_health={"overall_status": "ready", "p0_missing": [], "can_build_gold_macro_overview": True},
    )

    assert decision.action is QualityGateAction.MANUAL_REVIEW
    assert decision.publish_allowed is False
    assert any(finding.code == "fact_review_needs_review" for finding in decision.findings)


def test_quality_gate_fallbacks_unsupported_claims_and_blocks_contradicted_claims() -> None:
    unsupported = evaluate_quality_gate(
        agent_outputs=[_agent_output(invalid_conditions=["unsupported_claim"])],
        gold_macro_overview={"net_bias": "bullish", "source_refs": [{"source": "wire", "source_ref": "event:1"}]},
        source_health={"overall_status": "ready", "p0_missing": [], "can_build_gold_macro_overview": True},
    )
    contradicted = evaluate_quality_gate(
        agent_outputs=[_agent_output(invalid_conditions=["contradicted_claim"])],
        gold_macro_overview={"net_bias": "bullish", "source_refs": [{"source": "wire", "source_ref": "event:1"}]},
        source_health={"overall_status": "ready", "p0_missing": [], "can_build_gold_macro_overview": True},
    )

    assert unsupported.action is QualityGateAction.FALLBACK
    assert "fallback_reanalyze" in unsupported.fallback_actions
    assert any(finding.code == "unsupported_claim" for finding in unsupported.findings)
    assert contradicted.action is QualityGateAction.BLOCK_PUBLISH
    assert contradicted.publish_allowed is False
    assert any(finding.code == "contradicted_claim" for finding in contradicted.findings)


def test_quality_gate_fallbacks_low_confidence_critical_agent_and_parse_gap() -> None:
    decision = evaluate_quality_gate(
        agent_outputs=[
            _agent_output(
                confidence=0.54,
                data_quality=["parse_suspect", "missing_required_fields"],
            )
        ],
        gold_macro_overview={"net_bias": "neutral", "source_refs": [{"source": "wire", "source_ref": "event:1"}]},
        source_health={"overall_status": "ready", "p0_missing": [], "can_build_gold_macro_overview": True},
    )

    assert decision.action is QualityGateAction.FALLBACK
    assert {"fallback_reanalyze", "fallback_reparse"}.issubset(set(decision.fallback_actions))
    assert {finding.code for finding in decision.findings} >= {
        "critical_agent_low_confidence",
        "parse_or_required_field_quality_gap",
    }


def test_quality_gate_passes_when_sources_and_structured_evidence_are_sufficient() -> None:
    decision = evaluate_quality_gate(
        agent_outputs=[_agent_output(confidence=0.68, bias="neutral")],
        gold_macro_overview={
            "net_bias": "neutral",
            "source_refs": [{"source": "fred", "source_ref": "DGS10"}],
        },
        source_health={"overall_status": "ready", "p0_missing": [], "can_build_gold_macro_overview": True},
    )

    assert decision.action is QualityGateAction.PASS
    assert decision.review_status == "pass"
    assert decision.publish_allowed is True
    assert decision.findings == []


def test_quality_gate_does_not_retry_future_invalidation_conditions() -> None:
    decision = evaluate_quality_gate(
        agent_outputs=[
            _agent_output(
                confidence=0.68,
                bias="neutral",
                invalidation_conditions=["Invalidate if real yields reverse next week."],
            )
        ],
        gold_macro_overview={
            "net_bias": "neutral",
            "source_refs": [{"source": "fred", "source_ref": "DGS10"}],
        },
        source_health={"overall_status": "ready", "p0_missing": [], "can_build_gold_macro_overview": True},
    )

    assert decision.action is QualityGateAction.PASS
    assert all(finding.code != "invalid_conditions_present" for finding in decision.findings)


def test_quality_gate_blocks_active_blockers_and_p0_data_gaps() -> None:
    decision = evaluate_quality_gate(
        agent_outputs=[
            _agent_output(
                confidence=0.68,
                bias="neutral",
                active_blockers=["canonical candle is unavailable"],
                data_gaps=[
                    {
                        "code": "missing_xauusd_price",
                        "message": "Canonical XAUUSD price is missing.",
                        "severity": "p0",
                    }
                ],
            )
        ],
        gold_macro_overview={
            "net_bias": "neutral",
            "source_refs": [{"source": "fred", "source_ref": "DGS10"}],
        },
        source_health={"overall_status": "ready", "p0_missing": [], "can_build_gold_macro_overview": True},
    )

    assert decision.action is QualityGateAction.BLOCK_PUBLISH
    assert {finding.code for finding in decision.findings} >= {
        "active_blockers_present",
        "p0_data_gaps_present",
    }


def test_quality_gate_routes_non_claim_review_triggers_to_manual_review() -> None:
    decision = evaluate_quality_gate(
        agent_outputs=[_agent_output(confidence=0.68, bias="neutral", review_triggers=["macro_options_conflict"])],
        gold_macro_overview={
            "net_bias": "neutral",
            "source_refs": [{"source": "fred", "source_ref": "DGS10"}],
        },
        source_health={"overall_status": "ready", "p0_missing": [], "can_build_gold_macro_overview": True},
    )

    assert decision.action is QualityGateAction.MANUAL_REVIEW
    assert any(finding.code == "review_triggers_present" for finding in decision.findings)


def test_quality_gate_checks_coordinator_evidence_independently_from_domain_evidence() -> None:
    decision = evaluate_quality_gate(
        agent_outputs=[
            _agent_output(agent_name="macro_liquidity_agent", confidence=0.68, bias="bullish"),
            _agent_output(
                agent_name="coordinator_agent",
                confidence=0.82,
                bias="bullish",
                source_refs=[],
                evidence_items=[],
            ),
        ],
        gold_macro_overview={
            "net_bias": "bullish",
            "source_refs": [{"source": "fred", "source_ref": "DGS10"}],
        },
        source_health={"overall_status": "ready", "p0_missing": [], "can_build_gold_macro_overview": True},
    )

    assert decision.action is QualityGateAction.BLOCK_PUBLISH
    assert {finding.code for finding in decision.findings} >= {
        "coordinator_source_refs_missing",
        "coordinator_high_confidence_without_evidence_items",
    }


def test_quality_gate_routes_coordinator_risk_conflict_to_manual_review() -> None:
    decision = evaluate_quality_gate(
        agent_outputs=[
            _agent_output(agent_name="risk_agent", confidence=0.68, bias="bearish"),
            _agent_output(agent_name="coordinator_agent", confidence=0.68, bias="bullish"),
        ],
        gold_macro_overview={
            "net_bias": "bullish",
            "source_refs": [{"source": "fred", "source_ref": "DGS10"}],
        },
        source_health={"overall_status": "ready", "p0_missing": [], "can_build_gold_macro_overview": True},
    )

    assert decision.action is QualityGateAction.MANUAL_REVIEW
    assert any(finding.code == "coordinator_risk_conflict" for finding in decision.findings)


def test_quality_gate_does_not_treat_neutral_risk_as_directional_conflict() -> None:
    decision = evaluate_quality_gate(
        agent_outputs=[
            _agent_output(agent_name="risk_agent", confidence=0.68, bias="neutral"),
            _agent_output(agent_name="coordinator_agent", confidence=0.68, bias="bullish"),
        ],
        gold_macro_overview={
            "net_bias": "bullish",
            "source_refs": [{"source": "fred", "source_ref": "DGS10"}],
        },
        source_health={"overall_status": "ready", "p0_missing": [], "can_build_gold_macro_overview": True},
    )

    assert all(finding.code != "coordinator_risk_conflict" for finding in decision.findings)


def test_post_gate_cannot_erase_unvalidated_pre_gate_failure() -> None:
    pre_gate = QualityGateDecision(
        action=QualityGateAction.FALLBACK,
        review_status="needs_review",
        publish_allowed=False,
        fallback_recommended=True,
        findings=[
            {
                "code": "unsupported_claim",
                "severity": "fallback",
                "message": "Domain claim is unsupported.",
                "evidence": {},
            }
        ],
        fallback_actions=["fallback_reanalyze"],
    )
    raw_post_gate = QualityGateDecision(
        action=QualityGateAction.PASS,
        review_status="pass",
        publish_allowed=True,
        findings=[],
    )

    decision = preserve_unresolved_pre_gate(
        pre_coordinator_decision=pre_gate,
        post_coordinator_decision=raw_post_gate,
    )

    assert decision.action is QualityGateAction.FALLBACK
    assert decision.publish_allowed is False
    assert [finding.code for finding in decision.findings] == ["unsupported_claim"]
    assert decision.fallback_actions == ["fallback_reanalyze"]
