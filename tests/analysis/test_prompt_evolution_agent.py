from __future__ import annotations

from apps.analysis.agents.gold_v3_prompts import build_prompt_evolution_governance_prompt_template
from apps.analysis.agents.prompt_evolution import build_prompt_evolution_proposal


def test_prompt_evolution_requires_repeated_failures_before_prompt_update() -> None:
    proposal = build_prompt_evolution_proposal(
        agent_name="gold_macro_overview_agent",
        current_prompt={"agent_id": "gold_macro_overview_agent", "rules": ["keep conclusions conditional"]},
        recent_runs=[
            {
                "run_id": "run-1",
                "quality_issues": [
                    {
                        "issue_code": "overstated_one_line_conclusion",
                        "description": "one_line_conclusion was overstated once",
                        "likely_root_cause": "prompt",
                    }
                ],
            }
        ],
    ).to_dict()

    assert proposal["prompt_update_proposal"]["proposal_type"] == "insufficient_evidence"
    assert proposal["prompt_update_proposal"]["patch"] == ""
    assert proposal["manual_review_required"] is True
    assert proposal["failure_patterns"][0]["frequency"] == 1


def test_prompt_evolution_classifies_data_missing_without_prompt_patch() -> None:
    proposal = build_prompt_evolution_proposal(
        agent_name="mainline_ranking_agent",
        current_prompt={"agent_id": "mainline_ranking_agent", "rules": ["rank all mainlines"]},
        recent_runs=[
            {
                "run_id": "run-1",
                "review_gate": {
                    "blocking_issues": [
                        {
                            "issue_code": "p0_missing_xauusd",
                            "description": "P0 missing XAUUSD source_health blocked technical phase",
                            "likely_root_cause": "data_missing",
                        }
                    ]
                },
            },
            {
                "run_id": "run-2",
                "review_gate": {
                    "blocking_issues": [
                        {
                            "issue_code": "p0_missing_xauusd",
                            "description": "P0 missing XAUUSD source_health blocked technical phase",
                            "likely_root_cause": "data_missing",
                        }
                    ]
                },
            },
        ],
        data_source_health={"overall_status": "blocked"},
    ).to_dict()

    assert proposal["requires_data_source_change"] is True
    assert proposal["prompt_update_proposal"]["proposal_type"] == "data_source_change"
    assert proposal["prompt_update_proposal"]["patch"] == ""
    assert proposal["failure_patterns"][0]["likely_root_cause"] == "data_missing"


def test_prompt_evolution_generates_prompt_update_for_repeated_prompt_failure() -> None:
    proposal = build_prompt_evolution_proposal(
        agent_name="event_attribution_agent",
        current_prompt={"agent_id": "event_attribution_agent", "rules": ["classify mainlines"]},
        recent_runs=[
            {
                "run_id": "run-1",
                "quality_issues": [
                    {
                        "issue_code": "missing_oil_price_mainline",
                        "description": "Hormuz event missed oil_price mainline",
                        "likely_root_cause": "prompt",
                    }
                ],
            },
            {
                "run_id": "run-2",
                "quality_issues": [
                    {
                        "issue_code": "missing_oil_price_mainline",
                        "description": "Red Sea event missed oil_price mainline",
                        "likely_root_cause": "prompt",
                    }
                ],
            },
        ],
        review_gate_findings=[
            {
                "issue_code": "missing_oil_price_mainline",
                "description": "Repeated geopolitical events did not check oil_price",
                "likely_root_cause": "prompt",
            }
        ],
    ).to_dict()

    update = proposal["prompt_update_proposal"]
    assert proposal["requires_schema_change"] is False
    assert proposal["requires_data_source_change"] is False
    assert update["proposal_type"] == "prompt_update"
    assert update["patch"]
    assert update["rollback_plan"]
    assert update["test_cases"][0]["expected"]["no_direct_prompt_mutation"] is True
    assert proposal["failure_patterns"][0]["frequency"] == 3


def test_prompt_evolution_prompt_schema_matches_runtime_contract() -> None:
    template = build_prompt_evolution_governance_prompt_template()
    schema = template["output_schema"]

    assert template["proposal_only"] is True
    assert "raw" in template["forbidden_mutation_layers"]
    assert "failure_patterns" in schema
    assert "prompt_update_proposal" in schema
    assert "test_cases" in schema["prompt_update_proposal"]
    assert schema["manual_review_required"] is True
