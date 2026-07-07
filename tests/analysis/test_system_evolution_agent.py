from __future__ import annotations

from apps.analysis.agents.system_evolution import evaluate_system_evolution


def test_system_evolution_flags_mixed_without_driver_decomposition_as_critical() -> None:
    review = evaluate_system_evolution(
        gold_macro_overview={
            "net_bias": "mixed",
            "driver_conflict": {},
            "source_refs": [{"source": "event_flow", "source_ref": "event:hormuz"}],
        }
    )

    assert review.review_status == "blocked"
    assert review.blocked is True
    finding = next(item for item in review.findings if item.code == "mixed_without_driver_decomposition")
    assert finding.severity == "critical"


def test_system_evolution_flags_missing_war_oil_rate_chain_as_high() -> None:
    review = evaluate_system_evolution(
        gold_macro_overview={
            "net_bias": "mixed_bearish",
            "dominant_mainline": "geopolitical_war_risk",
            "driver_conflict": {
                "bullish_drivers": ["safe_haven_bid"],
                "bearish_drivers": ["oil_inflation_rate_pressure"],
                "dominant_driver": "oil_inflation_rate_pressure",
                "verification_needed": ["oil_price_reaction_needed"],
            },
            "theme_rankings": [
                {"mainline_id": "geopolitical_war_risk", "coverage_status": "covered"},
                {"mainline_id": "oil_prices", "coverage_status": "covered"},
            ],
        }
    )

    assert review.review_status == "needs_change"
    finding = next(item for item in review.findings if item.code == "war_oil_rate_chain_missing")
    assert finding.severity == "high"


def test_system_evolution_blocks_dashboard_strong_conclusion_without_source_refs() -> None:
    review = evaluate_system_evolution(
        dashboard_summary={
            "one_line_conclusion": "Strong bullish breakout confirmed.",
            "source_refs": [],
        }
    )

    assert review.review_status == "blocked"
    finding = next(item for item in review.findings if item.code == "dashboard_strong_conclusion_without_source_refs")
    assert finding.severity == "critical"


def test_system_evolution_blocks_p0_gap_with_strong_gold_macro_overview() -> None:
    review = evaluate_system_evolution(
        gold_macro_overview={
            "net_bias": "strong_bullish",
            "one_line_conclusion": "Strong bullish breakout.",
        },
        source_health={
            "p0_missing": ["xauusd_price"],
            "can_build_gold_macro_overview": False,
        },
    )

    assert review.review_status == "blocked"
    assert "p0_gap_strong_conclusion" in review.required_followups


def test_system_evolution_improvement_proposals_include_required_review_fields() -> None:
    review = evaluate_system_evolution(
        gold_macro_overview={
            "net_bias": "mixed",
            "driver_conflict": {},
            "source_refs": [{"source": "event_flow", "source_ref": "event:1"}],
        },
        quality_gate_decision={
            "action": "block_publish",
            "review_status": "blocked",
            "publish_allowed": False,
            "findings": [
                {
                    "code": "source_refs_missing",
                    "severity": "blocker",
                    "message": "Missing source refs.",
                    "evidence": {},
                }
            ],
        },
    )

    assert review.evolution_proposals
    for proposal in review.evolution_proposals:
        payload = proposal.model_dump()
        for field in (
            "rationale",
            "proposed_changes",
            "expected_impact",
            "risks",
            "rollback_plan",
            "test_plan",
        ):
            assert payload[field]


def test_system_evolution_outputs_issue_34_review_contract_fields() -> None:
    review = evaluate_system_evolution(
        gold_macro_overview={
            "net_bias": "mixed",
            "driver_conflict": {},
            "source_refs": [{"source": "event_flow", "source_ref": "event:1"}],
        },
    )

    finding = review.findings[0].model_dump()
    for field in (
        "finding_id",
        "category",
        "title",
        "description",
        "affected_entities",
        "confidence",
        "created_at",
    ):
        assert finding[field]
    assert finding["category"] == "driver_decomposition"

    proposal = review.evolution_proposals[0].model_dump()
    for field in (
        "proposal_id",
        "proposal_type",
        "title",
        "rationale",
        "proposed_changes",
        "expected_impact",
        "risks",
        "rollback_plan",
        "test_plan",
        "status",
    ):
        assert proposal[field]
    assert proposal["status"] == "pending_review"
