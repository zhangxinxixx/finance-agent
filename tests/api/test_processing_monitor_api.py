from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.services.processing_monitor_service import (
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
    source_refs = [{"source": "jin10_flash", "source_ref": "jin10:flash:001"}]
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
                        "fallback_tasks": [
                            {
                                "task_type": "fallback_reanalyze",
                                "reason": "quality_gate_finding",
                                "source": "agent_quality_gate",
                            }
                        ],
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


def test_get_processing_overview_derives_monitoring_read_model(tmp_path: Path) -> None:
    _write_gold_processing_artifacts(tmp_path)

    with _patch_source_statuses():
        payload = get_processing_overview(project_root=tmp_path)

    assert payload["status"] == "partial"
    assert payload["date"] == "2026-06-25"
    assert payload["run_id"] == "run-processing"
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


def test_api_processing_overview_route_returns_read_model(tmp_path: Path) -> None:
    _write_gold_processing_artifacts(tmp_path)

    with mock.patch("apps.api.services.processing_monitor_service._PROJECT_ROOT", tmp_path), _patch_source_statuses():
        response = client.get("/api/processing/overview")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "partial"
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
        assert payload["source_refs"] == [{"source": "jin10_flash", "source_ref": "jin10:flash:001"}]
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
