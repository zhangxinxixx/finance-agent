from __future__ import annotations

from apps.analysis.agents.gold_v3_prompts import build_prompt_evolution_governance_prompt_template
from apps.analysis.agents import prompt_evolution
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


def test_prompt_evolution_builds_evaluation_cases_from_governance_failures() -> None:
    assert hasattr(prompt_evolution, "build_prompt_evaluation_cases")
    build_prompt_evaluation_cases = prompt_evolution.build_prompt_evaluation_cases
    cases = [
        item.to_dict()
        for item in build_prompt_evaluation_cases(
            agent_name="gold_macro_overview_agent",
            failures=[
                {
                    "code": "mixed_without_driver_decomposition",
                    "description": "Mixed output did not decompose bullish and bearish drivers.",
                    "source_refs": [{"artifact_type": "system_evolution", "file_path": "findings.json"}],
                },
                {
                    "code": "war_oil_rate_chain_missing",
                    "description": "War risk conclusion omitted oil inflation and real-rate chain.",
                    "source_refs": [{"artifact_type": "review_gate", "file_path": "review.json"}],
                },
            ],
            created_from="system_evolution",
        )
    ]

    assert cases[0]["case_id"] == "gold_macro_overview_agent:mixed_decomposition:mixed_without_driver_decomposition"
    assert cases[0]["case_type"] == "mixed_decomposition"
    assert cases[0]["input_payload"]["failure_code"] == "mixed_without_driver_decomposition"
    assert "mixed_must_be_decomposed" in cases[0]["expected_assertions"]
    assert "no_direct_prompt_mutation" in cases[0]["expected_assertions"]
    assert cases[0]["source_refs"][0]["file_path"] == "findings.json"
    assert cases[0]["created_from"] == "system_evolution"
    assert cases[1]["case_type"] == "war_oil_rate_chain"
    assert "war_oil_rate_chain_required" in cases[1]["expected_assertions"]


def test_prompt_evolution_runs_ab_validation_without_prompt_activation() -> None:
    assert hasattr(prompt_evolution, "run_prompt_ab_validation")
    run_prompt_ab_validation = prompt_evolution.run_prompt_ab_validation
    cases = build_prompt_evolution_cases_for_test()

    result = run_prompt_ab_validation(
        agent_name="gold_macro_overview_agent",
        active_prompt_version={"version": "v1", "prompt_sha256": "active"},
        candidate_prompt_version={"version": "v2", "prompt_sha256": "candidate"},
        cases=cases,
        active_results={
            cases[0].case_id: {
                "passed_assertions": ["no_direct_prompt_mutation"],
                "failed_assertions": ["mixed_must_be_decomposed"],
            }
        },
        candidate_results={
            cases[0].case_id: {
                "passed_assertions": ["no_direct_prompt_mutation", "mixed_must_be_decomposed"],
                "failed_assertions": [],
            }
        },
    ).to_dict()

    assert result["agent_name"] == "gold_macro_overview_agent"
    assert result["validation_status"] == "pass"
    assert result["improvement_count"] == 1
    assert result["regression_count"] == 0
    assert result["active_prompt_result"]["version"] == "v1"
    assert result["candidate_prompt_result"]["version"] == "v2"
    assert result["case_results"][0]["status"] == "improved"
    assert result["proposal_only"] is True
    assert result["activated_prompt"] is False


def build_prompt_evolution_cases_for_test():
    build_prompt_evaluation_cases = prompt_evolution.build_prompt_evaluation_cases
    return build_prompt_evaluation_cases(
        agent_name="gold_macro_overview_agent",
        failures=[
            {
                "code": "mixed_without_driver_decomposition",
                "description": "Mixed output did not decompose bullish and bearish drivers.",
                "source_refs": [{"artifact_type": "system_evolution", "file_path": "findings.json"}],
            }
        ],
        created_from="system_evolution",
    )
