from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.contracts.gold import GOLD_MAINLINE_IDS, GOLD_TRANSMISSION_CHAIN_IDS
from apps.gold_runtime_orchestration import (
    build_gold_runtime_execution_summary,
    build_gold_runtime_orchestration_contract,
    build_gold_runtime_summary_preview,
)

client = TestClient(app)


def test_gold_runtime_orchestration_contract_declares_required_run_modes() -> None:
    contract = build_gold_runtime_orchestration_contract()

    assert contract["source"] == "gold_runtime_orchestration_contract"
    assert contract["scheduler_boundary"] == "api -> scheduler -> worker -> collectors -> parsers -> features -> analysis -> renderer -> output"
    modes = {mode["run_mode"]: mode for mode in contract["run_modes"]}
    assert set(modes) == {
        "premarket_full_run",
        "intraday_event_update",
        "major_event_reprice",
        "postmarket_report_run",
        "system_evolution_check",
        "version_change_validation",
    }

    premarket = modes["premarket_full_run"]
    assert premarket["gold_macro_overview_updated"] is True
    assert premarket["report_rendered"] is True
    assert premarket["affected_mainlines"] == list(GOLD_MAINLINE_IDS)
    assert premarket["affected_chains"] == list(GOLD_TRANSMISSION_CHAIN_IDS)
    assert "source_health_agent" in premarket["planned_agents_executed"]
    assert "gold_macro_overview_agent" in premarket["planned_agents_executed"]
    assert "review_gate_agent" in premarket["planned_agents_executed"]
    assert "report_render_agent" in premarket["planned_agents_executed"]
    assert premarket["runtime_contract_only"] is True
    assert premarket["artifact_execution_enabled"] is False
    assert premarket["pipeline_materialized_outputs"] is False
    assert premarket["declared_agents"] == premarket["planned_agents_executed"]
    assert premarket["materialized_stage_envelopes"] == []
    assert premarket["executed_agents"] == []


def test_intraday_mode_is_incremental_and_mixed_capable() -> None:
    summary = build_gold_runtime_summary_preview(run_mode="intraday_event_update", trigger_reason="jin10_high_impact_flash")

    assert summary["trigger_reason"] == "jin10_high_impact_flash"
    assert summary["gold_macro_overview_updated"] is True
    assert "agents_executed" not in summary
    assert "agents_skipped" not in summary
    assert "report_render_agent" in summary["planned_agents_skipped"]
    assert "driver_decomposition_agent" in summary["planned_agents_executed"]
    assert "skip_low_frequency_mainlines_when_unaffected" in summary["warnings"]
    assert summary["writes"] == []
    assert summary["runtime_contract_only"] is True
    assert summary["artifact_execution_enabled"] is False
    assert summary["pipeline_materialized_outputs"] is False
    assert summary["executed_agents"] == []


def test_gold_runtime_execution_summary_maps_quality_gate_fallback() -> None:
    summary = build_gold_runtime_execution_summary(
        run_mode="premarket_full_run",
        trigger_reason="manual_premarket",
        quality_gate_decision={
            "action": "fallback",
            "review_status": "needs_review",
            "publish_allowed": True,
            "fallback_recommended": True,
        },
        accepted_outputs={"final_report_paths": ["/tmp/final_report.md"]},
        declared_agents=["source_health_agent", "review_gate_agent"],
        materialized_stage_envelopes=["source_health_agent", "review_gate_agent"],
    )

    assert summary["source"] == "gold_runtime_execution_summary"
    assert summary["runtime_contract_only"] is True
    assert summary["artifact_execution_enabled"] is False
    assert summary["pipeline_materialized_outputs"] is True
    assert summary["declared_agents"] == ["source_health_agent", "review_gate_agent"]
    assert summary["materialized_stage_envelopes"] == [
        "source_health_agent",
        "review_gate_agent",
    ]
    assert summary["executed_agents"] == []
    assert summary["quality_gate_status"] == "fallback_required"
    assert summary["review_status"] == "needs_review"
    assert summary["fallback_attempts"] == 0
    assert summary["fallback_tasks_created"] == []
    assert summary["accepted_outputs"] == {"final_report_paths": ["/tmp/final_report.md"]}
    assert summary["writes"] == ["/tmp/final_report.md"]


def test_gold_runtime_execution_summary_reports_only_materialized_agents() -> None:
    summary = build_gold_runtime_execution_summary(
        run_mode="premarket_full_run",
        executed_agents=["source_health_agent", "review_gate_agent"],
        failed_agents=[],
        skipped_agents=["report_render_agent"],
        accepted_outputs={"gold_macro_overview_path": "analysis/gold/overview.json"},
    )

    assert summary["runtime_contract_only"] is False
    assert summary["artifact_execution_enabled"] is True
    assert summary["executed_agents"] == ["source_health_agent", "review_gate_agent"]
    assert summary["failed_agents"] == []
    assert summary["skipped_agents"] == ["report_render_agent"]


def test_gold_runtime_execution_summary_does_not_override_typed_none_accepted_output() -> None:
    summary = build_gold_runtime_execution_summary(
        run_mode="premarket_full_run",
        quality_gate_decision={
            "action": "fallback",
            "review_status": "needs_review",
            "publish_allowed": False,
        },
        agent_loop_decision={
            "decision": "needs_review",
            "review_status": "needs_review",
            "publish_allowed": False,
            "accepted_output": {
                "source": "none",
                "agent_name": None,
                "snapshot_id": None,
                "artifact_ref": None,
            },
            "accepted_outputs": {},
        },
        accepted_outputs={"final_report_paths": ["/tmp/stale-final-report.md"]},
    )

    assert summary["accepted_outputs"] == {}
    assert summary["writes"] == []


def test_major_event_reprice_routes_geopolitical_oil_events_to_war_oil_rate_chain() -> None:
    summary = build_gold_runtime_summary_preview(run_mode="major_event_reprice", trigger_reason="hormuz_brent_shock")

    assert "war_oil_rate_chain" in summary["affected_chains"]
    assert "oil_prices" in summary["affected_mainlines"]
    assert "geopolitical_war_risk" in summary["affected_mainlines"]
    assert "real_rates_dollar" not in summary["affected_mainlines"]
    assert "changed_dominant_theme_must_be_marked_when_detected" in summary["warnings"]
    assert "review_gate_agent" in summary["planned_agents_executed"]


def test_postmarket_mode_runs_report_and_system_evolution() -> None:
    summary = build_gold_runtime_summary_preview(run_mode="postmarket_report_run")

    assert summary["trigger_reason"] == "daily_postmarket_review"
    assert summary["gold_macro_overview_updated"] is True
    assert "report_render_agent" in summary["planned_agents_executed"]
    assert "system_evolution_agent" in summary["planned_agents_executed"]
    assert summary["review_status"] == "needs_review"


def test_version_change_validation_runs_schema_dag_and_test_validation_agents() -> None:
    summary = build_gold_runtime_summary_preview(run_mode="version_change_validation", trigger_reason="dag_edge_changed")

    assert summary["trigger_reason"] == "dag_edge_changed"
    assert summary["gold_macro_overview_updated"] is False
    assert "schema_agent" in summary["planned_agents_executed"]
    assert "dag_lineage_agent" in summary["planned_agents_executed"]
    assert "test_validation_agent" in summary["planned_agents_executed"]
    assert not set(summary["planned_agents_executed"]) & set(summary["planned_agents_skipped"])
    assert "frontend_binding_chain" in summary["affected_chains"]


def test_gold_runtime_summary_preview_rejects_unknown_mode() -> None:
    resp = client.get("/api/gold/runtime-orchestration/summary-preview?run_mode=unknown_mode")

    assert resp.status_code == 400
    assert "Unknown Gold runtime mode" in resp.json()["detail"]


def test_gold_runtime_orchestration_api_routes_return_contract_and_summary() -> None:
    contract_resp = client.get("/api/gold/runtime-orchestration/contract")
    summary_resp = client.get(
        "/api/gold/runtime-orchestration/summary-preview"
        "?run_mode=major_event_reprice&trigger_reason=fomc_release"
    )

    assert contract_resp.status_code == 200
    assert summary_resp.status_code == 200
    assert contract_resp.json()["source"] == "gold_runtime_orchestration_contract"
    summary = summary_resp.json()
    assert summary["run_mode"] == "major_event_reprice"
    assert summary["trigger_reason"] == "fomc_release"
    assert summary["writes"] == []
