from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.services.processing_monitor_service import (
    _resolve_project_artifact_path,
    get_processing_overview,
    get_processing_trace,
    get_processing_trace_by_event,
    get_processing_trace_by_input,
    get_processing_trace_by_mainline,
    get_processing_trace_by_source_ref,
    get_processing_trace_by_transmission_chain,
)

client = TestClient(app)


def _gold_v3_source_status_payload() -> dict[str, list[dict[str, object]]]:
    p0_sources = [
        "xauusd_price",
        "dxy",
        "treasury_2y",
        "treasury_10y",
        "tips_10y",
        "fed_macro_events",
        "brent_wti",
        "geopolitical_news",
        "technical_levels",
    ]
    return {
        "sources": [
            {
                "source_key": source_key,
                "status": "ok",
                "health_state": "healthy",
                "readiness_state": "ready",
                "latest_health_at": "2026-06-25T12:00:00+00:00",
                "source_refs": [{"source_ref": f"storage/{source_key}.json"}],
            }
            for source_key in p0_sources
        ]
    }


def _patch_source_statuses():
    return mock.patch(
        "apps.api.services.gold_mainline_service.get_data_source_statuses",
        return_value=_gold_v3_source_status_payload(),
    )


def _write_gold_processing_artifacts(root: Path) -> None:
    date = "2026-06-25"
    run_id = "run-processing"
    storage_root = root / "storage"
    mainlines_path = storage_root / "features" / "news" / date / run_id / "gold_event_mainlines.json"
    overview_path = storage_root / "analysis" / "gold_mainlines" / date / run_id / "gold_macro_overview.json"
    mainlines_path.parent.mkdir(parents=True, exist_ok=True)
    overview_path.parent.mkdir(parents=True, exist_ok=True)
    source_refs = [
        {
            "source": "jin10_flash",
            "source_ref": "jin10:flash:001",
            "raw_path": "raw/news/jin10/2026-06-25/flash-001.json",
            "parsed_path": "parsed/news/jin10/2026-06-25/flash-001.json",
        }
    ]
    mainlines_path.write_text(
        json.dumps(
            {
                "status": "partial",
                "as_of": "2026-06-25T12:00:00+00:00",
                "mainlines": [
                    {
                        "mainline_id": "fed_policy_path",
                        "event_ids": ["event:fed"],
                        "source_refs": source_refs,
                    },
                    {
                        "mainline_id": "oil_prices",
                        "event_ids": ["event:oil"],
                        "source_refs": source_refs,
                    },
                ],
                "event_links": [
                    {
                        "event_id": "event:oil",
                        "input_id": "input:oil",
                        "processing_trace_id": "trace:oil",
                        "primary_mainline": "oil_prices",
                        "mainline_ids": ["oil_prices", "geopolitical_war_risk"],
                        "transmission_path_ids": ["geopolitics_to_oil_to_rates", "haven_bid"],
                        "source_refs": source_refs,
                    }
                ],
                "source_refs": source_refs,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    overview_path.write_text(
        json.dumps(
            {
                "status": "partial",
                "retrieved_date": date,
                "run_id": run_id,
                "input_snapshot_ids": {
                    "gold_event_mainlines": f"features/news/{date}/{run_id}/gold_event_mainlines.json",
                },
                "asset": "XAUUSD",
                "as_of": "2026-06-25T12:00:00+00:00",
                "theme_rankings": [
                    {
                        "mainline_id": "fed_policy_path",
                        "summary": "fed policy",
                        "source_refs": source_refs,
                        "event_ids": ["event:fed"],
                    },
                    {
                        "mainline_id": "oil_prices",
                        "summary": "oil shock",
                        "source_refs": source_refs,
                        "event_ids": ["event:oil"],
                    },
                    {
                        "mainline_id": "etf_flows",
                        "summary": "ETF stale",
                        "missing_data": ["etf_flow"],
                    },
                ],
                "driver_conflict": {
                    "status": "mixed",
                    "bullish_drivers": ["safe_haven_bid"],
                    "bearish_drivers": ["oil_inflation_rate_pressure"],
                    "dominant_driver": "oil_inflation_rate_pressure",
                    "verification_needed": ["oil_price_reaction_needed"],
                },
                "war_oil_rate_chain": {
                    "status": "partial",
                    "steps": [
                        {"id": "war", "status": "available"},
                        {"id": "oil", "status": "partial"},
                        {"id": "rates", "status": "partial"},
                    ],
                    "verification_needed": ["oil_price_reaction_needed"],
                    "source_refs": source_refs,
                },
                "verification_matrix": [
                    {
                        "id": "verify-oil",
                        "mainline_id": "oil_prices",
                        "required_source": "oil_price",
                        "status": "pending",
                    }
                ],
                "source_health": {
                    "overall_status": "ready",
                    "as_of": "2026-06-25T12:00:00+00:00",
                    "p0_missing": [],
                    "p1_missing": [],
                    "p2_missing": [],
                    "stale_sources": [],
                    "fresh_sources": ["xauusd_price"],
                    "source_freshness": {},
                    "mainline_impact": {},
                    "can_build_gold_macro_overview": True,
                    "can_emit_strong_conclusion": True,
                    "blocked_mainlines": [],
                    "degraded_mainlines": [],
                    "blocking_reasons": [],
                    "warnings": [],
                },
                "review_gate": {
                    "agent_id": "review_gate_agent",
                    "dag_node_id": "review_gate",
                    "review_status": "needs_review",
                    "quality_gate_action": "manual_review",
                    "publish_allowed": True,
                    "manual_review_required": True,
                    "fallback_recommended": False,
                    "retry_recommended": False,
                    "quality_gate_decision": {
                        "fallback_actions": ["fallback_reanalyze"],
                    },
                    "agent_loop_decision": {
                        "decision": "fallback_required",
                        "reasons": ["unsupported_claim"],
                        "fallback_of": ["coordinator_agent:snap-primary"],
                        "fallback_tasks": [
                            {
                                "task_type": "fallback_reanalyze",
                                "reason": "quality_gate_finding",
                                "source": "agent_quality_gate",
                            }
                        ],
                        "accepted_outputs": {
                            "final_report_paths": ["storage/outputs/fallback/final_report.md"],
                            "strategy_card_paths": ["storage/outputs/fallback/strategy_card.json"],
                        },
                        "fallback_trace": {
                            "fallback_used": True,
                            "accepted_output": "fallback",
                            "reason": ["unsupported_claim"],
                            "review_items": [{"review_id": "review-1", "reason": "unsupported_claim"}],
                        },
                    },
                    "fallback_task_results": [
                        {
                            "task_type": "fallback_reanalyze",
                            "reason": "quality_gate_finding",
                            "status": "success",
                            "fallback_output_agent": "fallback_synthesis_agent",
                            "fallback_of": "coordinator_agent:snap-primary",
                        }
                    ],
                    "fallback_outputs": {
                        "fallback_synthesis_agent": {
                            "agent_name": "fallback_synthesis_agent",
                            "snapshot_id": "snap-primary:fallback",
                            "bias": "neutral",
                            "confidence": 0.55,
                            "summary": "No strong conclusion: fallback conservative synthesis is in effect.",
                        }
                    },
                    "blocking_reasons": [],
                    "warnings": ["mixed drivers require verification"],
                },
                "source_refs": source_refs,
                "artifact_refs": [{"artifact_type": "json", "file_path": "analysis/gold_mainlines/overview.json"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    agent_outputs_dir = overview_path.parent / "agent_outputs"
    agent_outputs_dir.mkdir(parents=True, exist_ok=True)
    input_snapshot_ids = {
        "analysis_snapshot": "analysis:snapshot:processing",
        "gold_event_mainlines": f"features/news/{date}/{run_id}/gold_event_mainlines.json",
    }
    feature_artifact_refs = [
        {
            "artifact_type": "gold_event_mainlines",
            "path": f"features/news/{date}/{run_id}/gold_event_mainlines.json",
        }
    ]
    agent_specs = (
        (
            "source_health_agent",
            "source_health_output.json",
            "success",
            [
                {
                    "artifact_type": "source_health",
                    "path": f"analysis/gold_mainlines/{date}/{run_id}/source_health.json",
                }
            ],
        ),
        ("event_attribution_agent", "event_attribution_output.json", "success", feature_artifact_refs),
        ("transmission_chain_agent", "transmission_chain_output.json", "success", feature_artifact_refs),
        ("driver_decomposition_agent", "driver_decomposition_output.json", "success", feature_artifact_refs),
        ("mainline_ranking_agent", "mainline_ranking_output.json", "success", feature_artifact_refs),
        (
            "gold_macro_overview_agent",
            "gold_macro_overview_output.json",
            "partial",
            [
                {
                    "artifact_type": "gold_macro_overview",
                    "path": f"analysis/gold_mainlines/{date}/{run_id}/gold_macro_overview.json",
                }
            ],
        ),
        (
            "review_gate_agent",
            "review_gate_output.json",
            "partial",
            [
                {
                    "artifact_type": "quality_gate_result",
                    "path": f"analysis/gold_mainlines/{date}/{run_id}/quality_gate_result.json",
                }
            ],
        ),
        (
            "report_render_agent",
            "report_render_output.json",
            "success",
            [
                {"artifact_type": "final_report", "path": f"outputs/{date}/{run_id}/final_report.md"},
                {"artifact_type": "strategy_card", "path": f"outputs/{date}/{run_id}/strategy_card.json"},
            ],
        ),
    )
    for agent_name, filename, status, artifact_refs in agent_specs:
        evidence_refs = (
            [{"evidence_ref": "evidence:gold-overview"}]
            if agent_name == "gold_macro_overview_agent"
            else []
        )
        evidence_items = (
            [{"evidence_id": "evidence-item:gold-overview", "kind": "derived_feature"}]
            if agent_name == "gold_macro_overview_agent"
            else []
        )
        (agent_outputs_dir / filename).write_text(
            json.dumps(
                {
                    "agent_name": agent_name,
                    "run_id": run_id,
                    "snapshot_id": "gold-snapshot-processing",
                    "input_snapshot_ids": input_snapshot_ids,
                    "source_refs": source_refs,
                    "artifact_refs": artifact_refs,
                    "evidence_refs": evidence_refs,
                    "evidence_items": evidence_items,
                    "data_quality": [],
                    "confidence": 0.8,
                    "status": status,
                    "created_at": "2026-06-25T12:00:00+00:00",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )


def test_get_processing_overview_derives_monitoring_read_model(tmp_path: Path) -> None:
    _write_gold_processing_artifacts(tmp_path)

    with _patch_source_statuses():
        payload = get_processing_overview(project_root=tmp_path)

    assert payload["status"] == "accepted"
    assert payload["analysis_status"] == "partial"
    assert payload["date"] == "2026-06-25"
    assert payload["run_id"] == "run-processing"
    assert payload["execution_summary"] == {
        "status": "partial",
        "failed_steps": [],
        "used_data": {
            "input_snapshot_ids": {
                "analysis_snapshot": "analysis:snapshot:processing",
                "gold_event_mainlines": "features/news/2026-06-25/run-processing/gold_event_mainlines.json",
            },
            "source_refs": [
                {
                    "source": "jin10_flash",
                    "source_ref": "jin10:flash:001",
                    "raw_path": "raw/news/jin10/2026-06-25/flash-001.json",
                    "parsed_path": "parsed/news/jin10/2026-06-25/flash-001.json",
                }
            ],
            "agent_artifact_refs": [
                {
                    "agent_name": agent_name,
                    "status": status,
                    "file_path": f"storage/analysis/gold_mainlines/2026-06-25/run-processing/agent_outputs/{filename}",
                }
                for agent_name, filename, status in (
                    ("source_health_agent", "source_health_output.json", "success"),
                    ("event_attribution_agent", "event_attribution_output.json", "success"),
                    ("transmission_chain_agent", "transmission_chain_output.json", "success"),
                    ("driver_decomposition_agent", "driver_decomposition_output.json", "success"),
                    ("mainline_ranking_agent", "mainline_ranking_output.json", "success"),
                    ("gold_macro_overview_agent", "gold_macro_overview_output.json", "partial"),
                    ("review_gate_agent", "review_gate_output.json", "partial"),
                    ("report_render_agent", "report_render_output.json", "success"),
                )
            ],
        },
        "final_output": {
            "mode": "accepted",
            "publish_allowed": True,
            "review_status": "needs_review",
            "report_artifact_refs": [
                {
                    "artifact_type": "final_report",
                    "path": "outputs/2026-06-25/run-processing/final_report.md",
                }
            ],
            "strategy_card_artifact_refs": [
                {
                    "artifact_type": "strategy_card",
                    "path": "outputs/2026-06-25/run-processing/strategy_card.json",
                }
            ],
        },
    }
    assert payload["trace_modes"] == [
        "source_ref",
        "event_id",
        "input_id",
        "processing_trace_id",
        "mainline",
        "transmission_chain",
    ]
    assert payload["input_coverage"]["news_input_count"] == 1
    assert payload["input_coverage"]["source_ref_count"] == 1
    assert payload["input_coverage"]["artifact_ref_count"] == 1
    assert payload["input_coverage"]["without_source_ref_count"] == 0

    mainline_status = {item["mainline_id"]: item["status"] for item in payload["mainline_coverage"]}
    assert len(mainline_status) == 9
    assert mainline_status["fed_policy_path"] == "covered"
    assert mainline_status["oil_prices"] == "covered"
    assert mainline_status["etf_flows"] == "degraded"
    assert mainline_status["china_asia_demand"] == "missing"

    chain_status = {item["chain_id"]: item["status"] for item in payload["transmission_chain_coverage"]}
    assert len(chain_status) == 8
    assert chain_status["war_oil_rate_chain"] == "degraded"
    assert chain_status["safe_haven_chain"] == "covered"
    assert payload["mixed_health"]["mixed_events_total"] == 1
    assert payload["mixed_health"]["mixed_without_bullish_drivers"] == 0
    assert payload["mixed_health"]["mixed_without_bearish_drivers"] == 0
    assert payload["mixed_health"]["mixed_without_dominant_driver"] == 0
    assert payload["mixed_health"]["status"] == "needs_review"

    bindings = {item["view"]: item["status"] for item in payload["view_bindings"]}
    assert bindings["Dashboard"] == "bound"
    assert bindings["GoldMainlinesPage"] == "bound"
    assert bindings["OilGeopoliticsPage"] == "bound"
    assert bindings["SourceTrace"] == "bound"
    assert payload["source_health"]["overall_status"] == "ready"
    assert payload["source_health"]["can_build_gold_macro_overview"] is True
    assert payload["quality_gate"]["status"] == "needs_review"
    assert payload["quality_gate"]["quality_gate_action"] == "manual_review"
    assert payload["quality_gate"]["manual_review_required"] is True
    assert payload["quality_gate"]["fallback_reasons"] == ["unsupported_claim"]
    assert payload["quality_gate"]["fallback_actions"] == ["fallback_reanalyze"]
    assert payload["quality_gate"]["agent_loop_decision"]["decision"] == "fallback_required"
    assert payload["quality_gate"]["fallback_review"] == {
        "status": "needs_review",
        "fallback_used": True,
        "accepted_output": "fallback",
        "manual_review_required": True,
        "primary_outputs": ["coordinator_agent:snap-primary"],
        "fallback_outputs": [
            {
                "agent_name": "fallback_synthesis_agent",
                "snapshot_id": "snap-primary:fallback",
                "bias": "neutral",
                "confidence": 0.55,
                "summary": "No strong conclusion: fallback conservative synthesis is in effect.",
            }
        ],
        "accepted_outputs": {
            "final_report_paths": ["storage/outputs/fallback/final_report.md"],
            "strategy_card_paths": ["storage/outputs/fallback/strategy_card.json"],
        },
        "fallback_tasks": [
            {
                "task_type": "fallback_reanalyze",
                "reason": "quality_gate_finding",
                "source": "agent_quality_gate",
            }
        ],
        "task_results": [
            {
                "task_type": "fallback_reanalyze",
                "reason": "quality_gate_finding",
                "status": "success",
                "fallback_output_agent": "fallback_synthesis_agent",
                "fallback_of": "coordinator_agent:snap-primary",
            }
        ],
        "reasons": ["unsupported_claim"],
        "review_items": [{"review_id": "review-1", "reason": "unsupported_claim"}],
        "fallback_quality_gate_decision": {},
        "no_strong_conclusion": False,
        "strategy_card_override": {},
    }
    assert payload["read_time_source_health"]["overall_status"] == "degraded"
    assert "fedwatch_ois" in payload["read_time_source_health"]["p1_missing"]
    assert payload["read_time_generated_at"]
    assert payload["trace_path"][0]["node_id"] == "source_health_check"
    assert payload["trace_path"][0]["status"] == "covered"
    assert payload["trace_path"][1]["node_id"] == "jin10_message_raw"
    assert payload["trace_path"][1]["status"] == "covered"
    assert payload["trace_path"][1]["source_ref_count"] == 1
    assert payload["trace_path"][4]["node_id"] == "mainline_attribution"
    assert payload["trace_path"][4]["status"] == "covered"
    assert payload["trace_path"][6]["node_id"] == "driver_decomposition"
    assert payload["trace_path"][6]["status"] == "needs_review"
    assert payload["trace_path"][7]["node_id"] == "gold_macro_overview"
    assert payload["trace_path"][7]["artifact_ref_count"] == 1
    assert payload["trace_path"][8]["node_id"] == "review_gate"
    assert payload["trace_path"][8]["status"] == "needs_review"
    assert payload["trace_path"][-1]["node_id"] == "source_trace"


def test_processing_monitor_prefers_latest_final_gate_over_newer_preliminary_overview(tmp_path: Path) -> None:
    _write_gold_processing_artifacts(tmp_path)
    preliminary_dir = (
        tmp_path
        / "storage"
        / "analysis"
        / "gold_mainlines"
        / "2026-06-25"
        / "run-preliminary"
    )
    preliminary_dir.mkdir(parents=True)
    (preliminary_dir / "gold_macro_overview.json").write_text(
        json.dumps(
            {
                "schema_version": "gold_macro_overview.v1",
                "status": "blocked",
                "retrieved_date": "2026-06-25",
                "run_id": "run-preliminary",
            }
        ),
        encoding="utf-8",
    )

    with _patch_source_statuses():
        payload = get_processing_overview(project_root=tmp_path)

    assert payload["run_id"] == "run-processing"
    assert payload["status"] == "accepted"


def test_processing_monitor_resolves_storage_relative_overview_path(tmp_path: Path) -> None:
    overview_path = tmp_path / "storage" / "analysis" / "gold_mainlines" / "2026-06-25" / "run" / "gold_macro_overview.json"
    overview_path.parent.mkdir(parents=True)
    overview_path.write_text("{}", encoding="utf-8")

    resolved = _resolve_project_artifact_path(
        root=tmp_path,
        value="analysis/gold_mainlines/2026-06-25/run/gold_macro_overview.json",
    )

    assert resolved == overview_path
    assert _resolve_project_artifact_path(root=tmp_path, value="../../etc/passwd") is None
    assert _resolve_project_artifact_path(root=tmp_path, value="/etc/passwd") is None


def test_processing_monitor_reports_only_explicit_failed_agent_steps(tmp_path: Path) -> None:
    _write_gold_processing_artifacts(tmp_path)
    agent_outputs = (
        tmp_path
        / "storage"
        / "analysis"
        / "gold_mainlines"
        / "2026-06-25"
        / "run-processing"
        / "agent_outputs"
    )
    failed_path = agent_outputs / "transmission_chain_output.json"
    failed_payload = json.loads(failed_path.read_text(encoding="utf-8"))
    failed_payload["status"] = "failed"
    failed_path.write_text(json.dumps(failed_payload), encoding="utf-8")
    unavailable_path = agent_outputs / "driver_decomposition_output.json"
    unavailable_payload = json.loads(unavailable_path.read_text(encoding="utf-8"))
    unavailable_payload["status"] = "unavailable"
    unavailable_path.write_text(json.dumps(unavailable_payload), encoding="utf-8")

    with _patch_source_statuses():
        payload = get_processing_overview(project_root=tmp_path)

    summary = payload["execution_summary"]
    assert payload["status"] == "failed"
    assert summary["status"] == "failed"
    assert summary["failed_steps"] == ["transmission_chain_agent"]


def test_processing_monitor_exposes_blocked_observe_output(tmp_path: Path) -> None:
    _write_gold_processing_artifacts(tmp_path)
    run_path = (
        tmp_path
        / "storage"
        / "analysis"
        / "gold_mainlines"
        / "2026-06-25"
        / "run-processing"
    )
    render_path = run_path / "agent_outputs" / "report_render_output.json"
    render = json.loads(render_path.read_text(encoding="utf-8"))
    render["artifact_refs"] = [
        {
            "artifact_type": "observation_report",
            "path": "outputs/observation_report/2026-06-25/run-processing/final_report.md",
        },
        {
            "artifact_type": "observation_strategy_card",
            "path": "outputs/observation_strategy_card/2026-06-25/run-processing/strategy_card.json",
        },
    ]
    render_path.write_text(json.dumps(render), encoding="utf-8")
    (run_path / "quality_gate_result.json").write_text(
        json.dumps(
            {
                "publish_allowed": False,
                "quality_gate_decision": {
                    "action": "manual_review",
                    "review_status": "needs_review",
                    "publish_allowed": False,
                    "manual_review_required": True,
                },
                "agent_loop_decision": {
                    "decision": "blocked",
                    "review_status": "blocked",
                    "publish_allowed": False,
                    "reasons": ["fallback_output_rejected"],
                    "accepted_output": {"source": "none"},
                },
            }
        ),
        encoding="utf-8",
    )

    with _patch_source_statuses():
        payload = get_processing_overview(project_root=tmp_path)

    summary = payload["execution_summary"]
    assert payload["status"] == "observe"
    assert summary["status"] == "blocked"
    assert summary["failed_steps"] == []
    assert summary["final_output"]["mode"] == "observe"
    assert summary["final_output"]["publish_allowed"] is False
    assert summary["final_output"]["review_status"] == "blocked"
    assert summary["final_output"]["report_artifact_refs"][0]["artifact_type"] == "observation_report"
    assert (
        summary["final_output"]["strategy_card_artifact_refs"][0]["artifact_type"]
        == "observation_strategy_card"
    )
    assert payload["quality_gate"]["fallback_reasons"] == ["fallback_output_rejected"]


def test_processing_monitor_does_not_accept_output_without_publish_decision(tmp_path: Path) -> None:
    _write_gold_processing_artifacts(tmp_path)
    overview_path = (
        tmp_path
        / "storage"
        / "analysis"
        / "gold_mainlines"
        / "2026-06-25"
        / "run-processing"
        / "gold_macro_overview.json"
    )
    overview = json.loads(overview_path.read_text(encoding="utf-8"))
    overview["review_gate"].pop("publish_allowed")
    overview_path.write_text(json.dumps(overview), encoding="utf-8")

    with _patch_source_statuses():
        payload = get_processing_overview(project_root=tmp_path)

    summary = payload["execution_summary"]
    assert payload["status"] == "unavailable"
    assert summary["status"] == "partial"
    assert summary["final_output"]["mode"] == "unavailable"
    assert summary["final_output"]["publish_allowed"] is None


def test_api_processing_overview_route_returns_read_model(tmp_path: Path) -> None:
    _write_gold_processing_artifacts(tmp_path)

    with mock.patch("apps.api.services.processing_monitor_service._PROJECT_ROOT", tmp_path), _patch_source_statuses():
        response = client.get("/api/processing/overview")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "accepted"
    assert data["mainline_coverage"][0]["mainline_id"] == "fed_policy_path"


def test_processing_trace_lookup_by_trace_event_and_source_ref(tmp_path: Path) -> None:
    _write_gold_processing_artifacts(tmp_path)

    with _patch_source_statuses():
        by_trace = get_processing_trace("trace:oil", project_root=tmp_path)
        by_event = get_processing_trace_by_event("event:oil", project_root=tmp_path)
        by_source = get_processing_trace_by_source_ref("jin10:flash:001", project_root=tmp_path)

    for payload in (by_trace, by_event, by_source):
        assert payload["status"] == "matched"
        assert payload["date"] == "2026-06-25"
        assert payload["run_id"] == "run-processing"
        assert payload["query"]["processing_trace_id"] == "trace:oil"
        assert payload["matched_event"]["event_id"] == "event:oil"
        assert payload["matched_event"]["primary_mainline"] == "oil_prices"
        assert payload["mainlines"] == ["oil_prices", "geopolitical_war_risk"]
        assert payload["transmission_chains"] == ["war_oil_rate_chain", "safe_haven_chain"]
        assert payload["accepted_output_source"] == "fallback"
        assert payload["accepted_output"] == {
            "final_report_paths": ["storage/outputs/fallback/final_report.md"],
            "strategy_card_paths": ["storage/outputs/fallback/strategy_card.json"],
        }
        assert payload["primary_output"]["agent_name"] == "report_render_agent"
        assert payload["primary_output"]["scope"] == "run"
        assert payload["primary_output"]["status"] == "success"
        assert payload["primary_output"]["artifact_refs"] == [
            {
                "artifact_type": "final_report",
                "path": "outputs/2026-06-25/run-processing/final_report.md",
            },
            {
                "artifact_type": "strategy_card",
                "path": "outputs/2026-06-25/run-processing/strategy_card.json",
            },
        ]
        assert payload["fallback_outputs"][0]["agent_name"] == "fallback_synthesis_agent"
        assert len(payload["agent_envelopes"]) == 8
        assert all(item["scope"] == "run" for item in payload["agent_envelopes"])
        assert payload["input_snapshot_ids"]["analysis_snapshot"] == "analysis:snapshot:processing"
        assert payload["evidence_refs"] == [{"evidence_ref": "evidence:gold-overview"}]
        assert payload["evidence_items"] == [
            {"evidence_id": "evidence-item:gold-overview", "kind": "derived_feature"}
        ]
        assert "ProcessingMonitor" in payload["affected_views"]
        assert payload["source_refs"] == [
            {
                "source": "jin10_flash",
                "source_ref": "jin10:flash:001",
                "raw_path": "raw/news/jin10/2026-06-25/flash-001.json",
                "parsed_path": "parsed/news/jin10/2026-06-25/flash-001.json",
            }
        ]
        assert payload["trace_path"][0]["node_id"] == "source_health_check"
        assert payload["trace_path"][0]["status"] == "covered"
        assert payload["trace_path"][1]["node_id"] == "jin10_message_raw"
        assert payload["trace_path"][1]["status"] == "covered"
        assert payload["trace_path"][1]["source_ref_count"] == 1
        assert payload["trace_path"][5]["node_id"] == "transmission_chain_detection"
        assert payload["trace_path"][5]["status"] == "covered"
        assert any(item["node_id"] == "review_gate" and item["status"] == "needs_review" for item in payload["trace_path"])
        assert payload["quality_gate"]["quality_gate_action"] == "manual_review"
        assert payload["trace_path"][-1]["node_id"] == "source_trace"
        assert payload["trace_path"][-1]["source_ref_count"] == 1
        assert any(item["view"] == "OilGeopoliticsPage" and item["status"] == "bound" for item in payload["view_bindings"])

    assert by_trace["trace_header"] == {
        "trace_id": "trace:oil",
        "run_id": "run-processing",
        "entity_type": "event",
        "entity_id": "event:oil",
        "status": "matched",
        "review_status": "needs_review",
        "publish_allowed": True,
        "as_of": "2026-06-25T12:00:00+00:00",
    }
    assert by_event["trace_header"]["entity_type"] == "event"
    assert by_event["trace_header"]["entity_id"] == "event:oil"
    assert by_source["trace_header"]["entity_type"] == "event"
    assert by_source["trace_header"]["entity_id"] == "event:oil"

    stages = {item["node_id"]: item for item in by_trace["trace_path"]}
    event_source_refs = [{"source_ref": "jin10:flash:001", "source": "jin10_flash"}]
    feature_artifact_refs = [
        {
            "artifact_type": "gold_event_mainlines",
            "path": "features/news/2026-06-25/run-processing/gold_event_mainlines.json",
        }
    ]
    assert stages["jin10_message_raw"]["source_refs"] == event_source_refs
    assert stages["jin10_message_raw"]["artifact_refs"] == [
        {
            "artifact_type": "raw_input",
            "path": "raw/news/jin10/2026-06-25/flash-001.json",
        }
    ]
    assert stages["jin10_message_raw"]["scope"] == "event"
    assert stages["jin10_flash_parse"]["source_refs"] == event_source_refs
    assert stages["jin10_flash_parse"]["artifact_refs"] == [
        {
            "artifact_type": "parsed_event",
            "path": "parsed/news/jin10/2026-06-25/flash-001.json",
        }
    ]
    assert stages["jin10_flash_parse"]["scope"] == "event"
    assert stages["event_flow_feature"]["source_refs"] == event_source_refs
    assert stages["event_flow_feature"]["artifact_refs"] == feature_artifact_refs
    assert stages["event_flow_feature"]["scope"] == "run"
    assert stages["mainline_attribution"]["artifact_refs"] == feature_artifact_refs
    assert stages["transmission_chain_detection"]["artifact_refs"] == feature_artifact_refs
    assert stages["driver_decomposition"]["artifact_refs"] == feature_artifact_refs
    assert stages["gold_macro_overview"]["artifact_refs"] == [
        {
            "artifact_type": "gold_macro_overview",
            "path": "analysis/gold_mainlines/2026-06-25/run-processing/gold_macro_overview.json",
        }
    ]
    assert stages["review_gate"]["artifact_refs"] == [
        {
            "artifact_type": "quality_gate_result",
            "path": "analysis/gold_mainlines/2026-06-25/run-processing/quality_gate_result.json",
        }
    ]
    assert stages["reports"]["artifact_refs"] == [
        {
            "artifact_type": "final_report",
            "path": "outputs/2026-06-25/run-processing/final_report.md",
        }
    ]
    assert stages["strategy"]["artifact_refs"] == [
        {
            "artifact_type": "strategy_card",
            "path": "outputs/2026-06-25/run-processing/strategy_card.json",
        }
    ]
    assert stages["source_trace"]["scope"] == "event"
    assert stages["source_trace"]["source_refs"] == event_source_refs
    assert stages["source_trace"]["artifact_refs"] == []
    assert not {
        "final_report",
        "strategy_card",
        "gold_macro_overview",
        "quality_gate_result",
    } & {ref.get("artifact_type") for ref in stages["source_trace"]["artifact_refs"]}
    assert all(stage["source_ref_count"] == len(stage["source_refs"]) for stage in stages.values())
    assert all(stage["artifact_ref_count"] == len(stage["artifact_refs"]) for stage in stages.values())
    assert stages["mainline_attribution"]["scope"] == "run"
    assert [
        item["agent_name"]
        for item in stages["mainline_attribution"]["agent_artifact_refs"]
    ] == ["event_attribution_agent", "mainline_ranking_agent"]
    assert stages["review_gate"]["warnings"] == ["mixed drivers require verification"]
    assert stages["review_gate"]["missing_data"] == []
    assert stages["review_gate"]["agent_artifact_refs"][0]["agent_name"] == "review_gate_agent"
    assert stages["reports"]["scope"] == "run"
    assert stages["reports"]["agent_artifact_refs"][0]["agent_name"] == "report_render_agent"
    assert stages["strategy"]["scope"] == "run"
    assert stages["strategy"]["agent_artifact_refs"] == stages["reports"]["agent_artifact_refs"]
    assert stages["jin10_flash_parse"]["scope"] == "event"
    assert stages["jin10_flash_parse"]["warnings"] == []
    assert stages["jin10_flash_parse"]["missing_data"] == []
    assert stages["jin10_flash_parse"]["agent_artifact_refs"] == []


def test_api_processing_trace_routes_return_matched_trace(tmp_path: Path) -> None:
    _write_gold_processing_artifacts(tmp_path)

    with mock.patch("apps.api.services.processing_monitor_service._PROJECT_ROOT", tmp_path), _patch_source_statuses():
        trace_response = client.get("/api/processing/trace/trace%3Aoil")
        event_response = client.get("/api/processing/trace-by-event/event%3Aoil")
        source_response = client.get("/api/processing/trace-by-source-ref/jin10%3Aflash%3A001")

    assert trace_response.status_code == 200
    assert event_response.status_code == 200
    assert source_response.status_code == 200
    assert trace_response.json()["matched_event"]["event_id"] == "event:oil"
    assert event_response.json()["matched_event"]["event_id"] == "event:oil"
    assert source_response.json()["matched_event"]["event_id"] == "event:oil"


def test_processing_trace_lookup_by_input_mainline_and_chain(tmp_path: Path) -> None:
    _write_gold_processing_artifacts(tmp_path)

    with _patch_source_statuses():
        by_input = get_processing_trace_by_input("input:oil", project_root=tmp_path)
        by_mainline = get_processing_trace_by_mainline("geopolitical_war", project_root=tmp_path)
        by_chain = get_processing_trace_by_transmission_chain("war_oil_rate_chain", project_root=tmp_path)
        by_chain_alias = get_processing_trace_by_transmission_chain("geopolitics_to_oil_to_rates", project_root=tmp_path)

    for payload in (by_input, by_mainline, by_chain, by_chain_alias):
        assert payload["status"] == "matched"
        assert payload["matched_event"]["event_id"] == "event:oil"
        assert payload["matched_event"]["input_id"] == "input:oil"
        assert payload["query"]["processing_trace_id"] == "trace:oil"
        assert "geopolitical_war_risk" in payload["mainlines"]
        assert payload["transmission_chains"] == ["war_oil_rate_chain", "safe_haven_chain"]

    for payload in (by_input, by_mainline, by_chain, by_chain_alias):
        assert payload["trace_header"]["entity_type"] == "event"
        assert payload["trace_header"]["entity_id"] == "event:oil"


def test_api_processing_trace_filter_routes_return_matched_trace(tmp_path: Path) -> None:
    _write_gold_processing_artifacts(tmp_path)

    with mock.patch("apps.api.services.processing_monitor_service._PROJECT_ROOT", tmp_path), _patch_source_statuses():
        input_response = client.get("/api/processing/trace-by-input/input%3Aoil")
        mainline_response = client.get("/api/processing/trace-by-mainline/geopolitical_war")
        chain_response = client.get("/api/processing/trace-by-chain/war_oil_rate_chain")

    assert input_response.status_code == 200
    assert mainline_response.status_code == 200
    assert chain_response.status_code == 200
    assert input_response.json()["matched_event"]["event_id"] == "event:oil"
    assert mainline_response.json()["matched_event"]["event_id"] == "event:oil"
    assert chain_response.json()["matched_event"]["event_id"] == "event:oil"


def test_processing_trace_projects_primary_accepted_output(tmp_path: Path) -> None:
    _write_gold_processing_artifacts(tmp_path)
    overview_path = (
        tmp_path
        / "storage"
        / "analysis"
        / "gold_mainlines"
        / "2026-06-25"
        / "run-processing"
        / "gold_macro_overview.json"
    )
    overview = json.loads(overview_path.read_text(encoding="utf-8"))
    decision = overview["review_gate"]["agent_loop_decision"]
    decision["accepted_output"] = {
        "source": "primary",
        "agent_name": "coordinator_agent",
        "snapshot_id": "coordinator:run-processing",
        "artifact_ref": {
            "analysis_snapshot": "snapshot:run-processing",
            "final_report_paths": ["storage/outputs/primary/final_report.md"],
            "strategy_card_paths": ["storage/outputs/primary/strategy_card.json"],
        },
    }
    decision["accepted_outputs"] = {
        "final_report_paths": ["storage/outputs/primary/final_report.md"],
        "strategy_card_paths": ["storage/outputs/primary/strategy_card.json"],
    }
    decision["fallback_trace"] = {
        "fallback_used": False,
        "accepted_output": "primary",
        "reason": [],
        "review_items": [],
    }
    overview["review_gate"]["fallback_outputs"] = {}
    overview_path.write_text(json.dumps(overview), encoding="utf-8")

    with _patch_source_statuses():
        payload = get_processing_trace("trace:oil", project_root=tmp_path)

    assert payload["accepted_output_source"] == "primary"
    assert payload["accepted_output"] == payload["primary_output"]
    assert payload["primary_output"]["agent_name"] == "report_render_agent"
    assert {ref["artifact_type"] for ref in payload["primary_output"]["artifact_refs"]} == {
        "final_report",
        "strategy_card",
    }
    assert payload["fallback_outputs"] == []


def test_processing_trace_typed_none_cannot_be_overridden_by_legacy_fallback(
    tmp_path: Path,
) -> None:
    _write_gold_processing_artifacts(tmp_path)
    overview_path = (
        tmp_path
        / "storage"
        / "analysis"
        / "gold_mainlines"
        / "2026-06-25"
        / "run-processing"
        / "gold_macro_overview.json"
    )
    overview = json.loads(overview_path.read_text(encoding="utf-8"))
    decision = overview["review_gate"]["agent_loop_decision"]
    decision["publish_allowed"] = True
    decision["accepted_output"] = {
        "source": "none",
        "agent_name": None,
        "snapshot_id": None,
        "artifact_ref": None,
    }
    decision["accepted_outputs"] = {
        "final_report_paths": ["storage/outputs/fallback/final_report.md"]
    }
    decision["fallback_trace"]["accepted_output"] = "fallback"
    overview_path.write_text(json.dumps(overview), encoding="utf-8")

    with _patch_source_statuses():
        payload = get_processing_trace("trace:oil", project_root=tmp_path)

    assert payload["accepted_output_source"] == "none"
    assert payload["accepted_output"] == {}


def test_processing_trace_rejected_fallback_is_not_accepted(tmp_path: Path) -> None:
    _write_gold_processing_artifacts(tmp_path)
    overview_path = (
        tmp_path
        / "storage"
        / "analysis"
        / "gold_mainlines"
        / "2026-06-25"
        / "run-processing"
        / "gold_macro_overview.json"
    )
    overview = json.loads(overview_path.read_text(encoding="utf-8"))
    review_gate = overview["review_gate"]
    review_gate["review_status"] = "blocked"
    review_gate["publish_allowed"] = False
    decision = review_gate["agent_loop_decision"]
    decision["accepted_outputs"] = {}
    decision["fallback_trace"]["accepted_output"] = None
    decision["no_strong_conclusion"] = True
    decision["strategy_card_override"] = {
        "bias": "neutral",
        "action": "observe_wait",
        "reason": "fallback_failed_or_needs_review",
    }
    overview_path.write_text(json.dumps(overview), encoding="utf-8")

    with _patch_source_statuses():
        payload = get_processing_trace("trace:oil", project_root=tmp_path)

    assert payload["accepted_output_source"] == "none"
    assert payload["accepted_output"] == {}
    assert payload["primary_output"]["agent_name"] == "report_render_agent"
    assert payload["fallback_outputs"][0]["agent_name"] == "fallback_synthesis_agent"
    assert payload["fallback_review"]["no_strong_conclusion"] is True
    assert payload["fallback_review"]["strategy_card_override"]["action"] == "observe_wait"


def test_processing_trace_ignores_invalid_and_run_mismatched_envelopes(tmp_path: Path) -> None:
    _write_gold_processing_artifacts(tmp_path)
    agent_outputs = (
        tmp_path
        / "storage"
        / "analysis"
        / "gold_mainlines"
        / "2026-06-25"
        / "run-processing"
        / "agent_outputs"
    )
    mismatched_path = agent_outputs / "event_attribution_output.json"
    mismatched = json.loads(mismatched_path.read_text(encoding="utf-8"))
    mismatched["run_id"] = "other-run"
    mismatched_path.write_text(json.dumps(mismatched), encoding="utf-8")
    invalid_path = agent_outputs / "report_render_output.json"
    invalid = json.loads(invalid_path.read_text(encoding="utf-8"))
    invalid["evidence_refs"] = {"evidence_ref": "not-a-list"}
    invalid_path.write_text(json.dumps(invalid), encoding="utf-8")

    with _patch_source_statuses():
        payload = get_processing_trace("trace:oil", project_root=tmp_path)

    names = {item["agent_name"] for item in payload["agent_envelopes"]}
    assert "event_attribution_agent" not in names
    assert "report_render_agent" not in names
    assert payload["primary_output"] == {}
    assert len(payload["agent_envelopes"]) == 6
    stages = {item["node_id"]: item for item in payload["trace_path"]}
    assert [
        item["agent_name"]
        for item in stages["mainline_attribution"]["agent_artifact_refs"]
    ] == ["mainline_ranking_agent"]
    assert stages["reports"]["scope"] == "run"
    assert stages["reports"]["agent_artifact_refs"] == []
    assert stages["strategy"]["scope"] == "run"
    assert stages["strategy"]["agent_artifact_refs"] == []


def test_processing_trace_missing_selected_payload_downgrades_to_none(tmp_path: Path) -> None:
    _write_gold_processing_artifacts(tmp_path)
    overview_path = (
        tmp_path
        / "storage"
        / "analysis"
        / "gold_mainlines"
        / "2026-06-25"
        / "run-processing"
        / "gold_macro_overview.json"
    )
    overview = json.loads(overview_path.read_text(encoding="utf-8"))
    decision = overview["review_gate"]["agent_loop_decision"]
    decision["accepted_outputs"] = {}
    decision["fallback_trace"]["accepted_output"] = "fallback"
    overview["review_gate"]["fallback_outputs"] = {}
    overview_path.write_text(json.dumps(overview), encoding="utf-8")

    with _patch_source_statuses():
        payload = get_processing_trace("trace:oil", project_root=tmp_path)

    assert payload["accepted_output_source"] == "none"
    assert payload["accepted_output"] == {}


def test_processing_trace_rejects_unsafe_raw_and_parsed_paths(tmp_path: Path) -> None:
    _write_gold_processing_artifacts(tmp_path)
    mainlines_path = (
        tmp_path
        / "storage"
        / "features"
        / "news"
        / "2026-06-25"
        / "run-processing"
        / "gold_event_mainlines.json"
    )
    mainlines = json.loads(mainlines_path.read_text(encoding="utf-8"))
    mainlines["event_links"][0]["source_refs"] = [
        {
            "source_ref": "unsafe:traversal",
            "raw_path": "../raw.json",
            "parsed_path": "/tmp/parsed.json",
        },
        {"source_ref": "missing:paths"},
        {
            "source_ref": "unsafe:wrong-root",
            "raw_path": "parsed/not-raw.json",
            "parsed_path": "raw/not-parsed.json",
        },
    ]
    mainlines_path.write_text(json.dumps(mainlines), encoding="utf-8")
    agent_outputs = (
        tmp_path
        / "storage"
        / "analysis"
        / "gold_mainlines"
        / "2026-06-25"
        / "run-processing"
        / "agent_outputs"
    )
    for envelope_path in agent_outputs.glob("*.json"):
        envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
        envelope["input_snapshot_ids"]["gold_event_mainlines"] = "features//unsafe.json"
        envelope_path.write_text(json.dumps(envelope), encoding="utf-8")

    with _patch_source_statuses():
        payload = get_processing_trace("trace:oil", project_root=tmp_path)

    stages = {item["node_id"]: item for item in payload["trace_path"]}
    assert len(stages["jin10_message_raw"]["source_refs"]) == 3
    assert stages["jin10_message_raw"]["artifact_refs"] == []
    assert stages["jin10_message_raw"]["artifact_ref_count"] == 0
    assert stages["jin10_flash_parse"]["artifact_refs"] == []
    assert stages["jin10_flash_parse"]["artifact_ref_count"] == 0
    assert stages["event_flow_feature"]["artifact_refs"] == []
    assert stages["event_flow_feature"]["artifact_ref_count"] == 0


def test_processing_trace_not_found_has_stable_empty_detail_shape(tmp_path: Path) -> None:
    _write_gold_processing_artifacts(tmp_path)

    with _patch_source_statuses():
        payload = get_processing_trace("trace:missing", project_root=tmp_path)

    assert payload["status"] == "not_found"
    assert payload["asset"] == "XAUUSD"
    assert payload["mainlines"] == []
    assert payload["transmission_chains"] == []
    assert payload["primary_output"] == {}
    assert payload["fallback_outputs"] == []
    assert payload["accepted_output"] == {}
    assert payload["accepted_output_source"] == "none"
    assert payload["agent_envelopes"] == []
    assert payload["input_snapshot_ids"] == {}
    assert payload["evidence_refs"] == []
    assert payload["evidence_items"] == []
    assert payload["affected_views"] == []
    assert payload["fallback_review"]["accepted_output"] is None
    assert payload["trace_header"] == {
        "trace_id": "trace:missing",
        "run_id": "run-processing",
        "entity_type": "unknown",
        "entity_id": "trace:missing",
        "status": "not_found",
        "review_status": "needs_review",
        "publish_allowed": True,
        "as_of": "2026-06-25T12:00:00+00:00",
    }
    assert all(
        set(
            (
                "warnings",
                "missing_data",
                "agent_artifact_refs",
                "source_refs",
                "artifact_refs",
                "scope",
            )
        )
        <= set(stage)
        for stage in payload["trace_path"]
    )
    assert all(stage["source_refs"] == [] for stage in payload["trace_path"])
    assert all(stage["artifact_refs"] == [] for stage in payload["trace_path"])
    assert all(stage["source_ref_count"] == 0 for stage in payload["trace_path"])
    assert all(stage["artifact_ref_count"] == 0 for stage in payload["trace_path"])

    with mock.patch("apps.api.services.processing_monitor_service._PROJECT_ROOT", tmp_path), _patch_source_statuses():
        response = client.get("/api/processing/trace/trace%3Amissing")

    assert response.status_code == 200
    assert response.json()["accepted_output_source"] == "none"
