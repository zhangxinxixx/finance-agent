from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from apps.analysis.agents import source_health
from apps.analysis.agents.gold_v3_prompts import GOLD_V3_MAINLINES, GOLD_V3_TRANSMISSION_CHAINS
from apps.analysis.agents.registry import get_agent_registry
from apps.analysis.gold_mainline_engine import build_gold_macro_overview
from apps.api.services import event_flow_service, report_service
from apps.api.services import gold_mainline_service
from apps.api.services import processing_monitor_service
from apps.features.news.gold_event_mainlines import MAINLINE_ORDER, build_gold_event_mainlines
from apps.contracts.gold import (
    GOLD_MAINLINE_IDS,
    GOLD_TRANSMISSION_CHAIN_IDS,
    GOLD_TRANSMISSION_PATH_IDS,
    MAINLINE_ALIAS_MAP,
    TRANSMISSION_CHAIN_ALIAS_MAP,
    normalize_gold_transmission_chain_id,
)
from apps.gold_runtime_orchestration import (
    build_gold_runtime_orchestration_contract,
    build_gold_runtime_summary_preview,
    get_gold_runtime_mode_contracts,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ANALYSIS_ROOT = PROJECT_ROOT / "apps/analysis"


def _quoted_strings(value: str) -> list[str]:
    return re.findall(r'"([^"]+)"', value)


def _frontend_gold_mainline_type_ids() -> set[str]:
    path = PROJECT_ROOT / "apps/frontend-web/src/generated/gold-contract.ts"
    text = path.read_text(encoding="utf-8")
    match = re.search(r"export const GOLD_MAINLINE_IDS = \[(?P<body>.*?)\] as const;", text, re.S)
    assert match is not None
    return set(_quoted_strings(match.group("body")))


def _frontend_gold_mainline_order_ids() -> list[str]:
    path = PROJECT_ROOT / "apps/frontend-web/src/components/shared/goldMainlineFormat.ts"
    text = path.read_text(encoding="utf-8")
    match = re.search(r"export const GOLD_MAINLINE_ORDER: GoldMainline\[] = \[(?P<body>.*?)\];", text, re.S)
    assert match is not None
    return _quoted_strings(match.group("body"))


def _frontend_transmission_path_type_ids() -> set[str]:
    path = PROJECT_ROOT / "apps/frontend-web/src/generated/gold-contract.ts"
    text = path.read_text(encoding="utf-8")
    match = re.search(r"export const GOLD_TRANSMISSION_PATH_IDS = \[(?P<body>.*?)\] as const;", text, re.S)
    assert match is not None
    return set(_quoted_strings(match.group("body")))


def _frontend_transmission_chain_type_ids() -> set[str]:
    path = PROJECT_ROOT / "apps/frontend-web/src/generated/gold-contract.ts"
    text = path.read_text(encoding="utf-8")
    match = re.search(r"export const GOLD_TRANSMISSION_CHAIN_IDS = \[(?P<body>.*?)\] as const;", text, re.S)
    assert match is not None
    return set(_quoted_strings(match.group("body")))


def _frontend_transmission_path_label_ids() -> set[str]:
    path = PROJECT_ROOT / "apps/frontend-web/src/components/shared/goldMainlineFormat.ts"
    text = path.read_text(encoding="utf-8")
    match = re.search(r"export const TRANSMISSION_PATH_LABELS: Record<TransmissionPath, string> = \{(?P<body>.*?)\};", text, re.S)
    assert match is not None
    return set(re.findall(r"^\s*([a-zA-Z0-9_]+):", match.group("body"), re.M))


def _frontend_type_file(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def _walk_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        strings: list[str] = []
        for key, item in value.items():
            strings.extend(_walk_strings(key))
            strings.extend(_walk_strings(item))
        return strings
    if isinstance(value, (list, tuple, set)):
        strings = []
        for item in value:
            strings.extend(_walk_strings(item))
        return strings
    return []


def test_analysis_layer_does_not_import_api_services() -> None:
    offenders: list[str] = []
    for path in sorted(ANALYSIS_ROOT.rglob("*.py")):
        relative = path.relative_to(PROJECT_ROOT)
        source = path.read_text(encoding="utf-8")
        if "apps.api.services" in source:
            offenders.append(str(relative))

    assert offenders == []


def test_automation_orchestration_uses_dagster_as_its_only_schedule_authority() -> None:
    scheduler_wrapper = _frontend_type_file("apps/scheduler/automation_orchestration.py")
    dagster_definitions = _frontend_type_file("dagster_finance/definitions.py")
    dagster_schedules = _frontend_type_file(
        "dagster_finance/schedules/automation_orchestration_schedule.py"
    )

    assert "def register_automation_orchestration_jobs" not in scheduler_wrapper
    assert ".add_job(" not in scheduler_wrapper
    for schedule_name in (
        "automation_hourly_schedule",
        "automation_event_sla_schedule",
        "automation_pre_analysis_schedule",
        "automation_notification_retry_schedule",
    ):
        assert schedule_name in dagster_definitions
        assert f"def {schedule_name}" in dagster_schedules


def test_quality_gate_fallback_executor_lives_in_dedicated_module() -> None:
    from apps.analysis.agents import fallback_executor
    from apps.analysis.agents.quality_gate import execute_agent_loop_fallback_tasks

    assert fallback_executor.execute_agent_loop_fallback_tasks is execute_agent_loop_fallback_tasks
    assert execute_agent_loop_fallback_tasks.__module__ == "apps.analysis.agents.fallback_executor"


def test_worker_source_readiness_gate_lives_in_dedicated_module() -> None:
    from apps.worker import runner, source_readiness_gate

    assert runner._load_premarket_source_status_index is source_readiness_gate.load_premarket_source_status_index
    assert runner._should_apply_source_readiness_gate is source_readiness_gate.should_apply_source_readiness_gate
    assert runner._format_source_readiness_blocked_reason is source_readiness_gate.format_source_readiness_blocked_reason
    assert runner._emit_source_readiness_events is source_readiness_gate.emit_source_readiness_events


def test_worker_error_policy_lives_in_dedicated_module() -> None:
    from apps.worker import error_policy, runner

    assert runner._classify_error_type is error_policy.classify_error_type
    assert runner._is_retryable_error_type is error_policy.is_retryable_error_type


def test_worker_artifact_registration_lives_in_dedicated_module() -> None:
    from apps.worker import artifact_registration, runner

    assert runner._register_runner_step_artifacts is artifact_registration.register_runner_step_artifacts
    assert runner._register_composite_output_artifacts is artifact_registration.register_composite_output_artifacts
    assert runner._register_run_support_artifacts is artifact_registration.register_run_support_artifacts
    assert runner._enrich_runner_artifact_metadata is artifact_registration.enrich_runner_artifact_metadata
    assert runner._coerce_lineage_source_refs is artifact_registration.coerce_lineage_source_refs
    assert runner._coerce_lineage_input_snapshot_ids is artifact_registration.coerce_lineage_input_snapshot_ids
    assert runner._merge_lineage_source_refs is artifact_registration.merge_lineage_source_refs
    assert runner._merge_lineage_input_snapshot_ids is artifact_registration.merge_lineage_input_snapshot_ids


def test_worker_report_registry_sink_lives_in_dedicated_module() -> None:
    from apps.worker import report_registry_sink, runner

    assert runner._register_composite_report_registry_entries is report_registry_sink.register_composite_report_registry_entries


def test_worker_composite_analysis_pipeline_lives_in_dedicated_module() -> None:
    from apps.worker import composite_analysis_pipeline, runner

    assert runner._run_composite_analysis_pipeline is composite_analysis_pipeline.run_composite_analysis_pipeline
    assert runner._accepted_coordinator_output is composite_analysis_pipeline.accepted_coordinator_output


def test_worker_db_persistence_lives_in_dedicated_module() -> None:
    from apps.worker import db_persistence, runner

    assert runner._db_persist_analysis_snapshot is db_persistence.db_persist_analysis_snapshot
    assert runner._db_persist_agent_outputs is db_persistence.db_persist_agent_outputs
    assert runner._db_persist_final_result is db_persistence.db_persist_final_result
    assert runner._ensure_review_items is db_persistence.ensure_review_items


def test_worker_step_dispatcher_lives_in_dedicated_module() -> None:
    from apps.worker import runner, step_dispatcher

    assert runner.CME_STEP_NAMES is step_dispatcher.CME_STEP_NAMES
    assert runner.MACRO_STEP_NAMES is step_dispatcher.MACRO_STEP_NAMES
    assert runner.NEWS_STEP_NAMES is step_dispatcher.NEWS_STEP_NAMES
    assert runner._create_step_dispatch_state is step_dispatcher.create_step_dispatch_state
    assert runner._dispatch_premarket_step is step_dispatcher.dispatch_premarket_step
    assert runner._has_blocked_upstream_in_same_pipeline is step_dispatcher.has_blocked_upstream_in_same_pipeline


def test_gold_mainline_ids_are_canonical_across_backend_runtime_prompt_source_health_and_frontend() -> None:
    canonical = list(GOLD_MAINLINE_IDS)

    assert MAINLINE_ORDER == canonical
    assert GOLD_V3_MAINLINES == canonical
    assert list(source_health.MAINLINE_REQUIRED_SOURCES) == canonical
    assert _frontend_gold_mainline_order_ids() == canonical
    assert _frontend_gold_mainline_type_ids() == set(canonical)


def test_gold_runtime_contract_and_prompt_payloads_do_not_emit_legacy_mainline_ids() -> None:
    legacy_ids = set(MAINLINE_ALIAS_MAP)
    payloads: list[Any] = [
        build_gold_runtime_orchestration_contract(),
        *(build_gold_runtime_summary_preview(run_mode=contract.run_mode) for contract in get_gold_runtime_mode_contracts()),
        GOLD_V3_MAINLINES,
    ]

    emitted_legacy_ids = {
        value
        for payload in payloads
        for value in _walk_strings(payload)
        if value in legacy_ids
    }

    assert emitted_legacy_ids == set()
    assert set(MAINLINE_ALIAS_MAP.values()).issubset(set(GOLD_MAINLINE_IDS))


def test_gold_transmission_chain_ids_are_canonical_across_prompts_monitor_and_frontend_paths() -> None:
    canonical_chains = list(GOLD_TRANSMISSION_CHAIN_IDS)
    canonical_paths = set(GOLD_TRANSMISSION_PATH_IDS)

    assert GOLD_V3_TRANSMISSION_CHAINS == canonical_chains
    assert processing_monitor_service.TRANSMISSION_CHAINS == canonical_chains
    assert _frontend_transmission_chain_type_ids() == set(canonical_chains)
    assert _frontend_transmission_path_type_ids() == canonical_paths
    assert _frontend_transmission_path_label_ids() == canonical_paths
    assert set(TRANSMISSION_CHAIN_ALIAS_MAP.values()).issubset(set(canonical_chains))
    assert normalize_gold_transmission_chain_id("geopolitics_to_oil_to_rates") == "war_oil_rate_chain"
    assert normalize_gold_transmission_chain_id("technical_confirmation") == "technical_chain"


def test_gold_v3_frontend_type_contract_exposes_processing_trace_models() -> None:
    gold_types = _frontend_type_file("apps/frontend-web/src/types/gold-mainlines.ts")
    event_types = _frontend_type_file("apps/frontend-web/src/types/event-flow.ts")
    processing_types = _frontend_type_file("apps/frontend-web/src/types/processing-monitor.ts")

    assert "import type { ProcessingTrace }" in gold_types
    assert "export type WarOilRateChain = TransmissionChainSummary;" in gold_types
    assert "export type DriverDecomposition = DriverConflict;" in gold_types
    assert re.search(r"transmission_chains\?:\s*Array<TransmissionPath\s*\|\s*TransmissionChain>;", event_types) is not None
    assert re.search(r"processing_traces\?:\s*ProcessingTrace\[];", gold_types) is not None
    assert re.search(r"processing_trace_id\?:\s*string\s*\|\s*null;", event_types) is not None
    assert "export interface ProcessingStage" in processing_types
    assert "export interface ProcessingTrace" in processing_types
    assert re.search(r"stages:\s*ProcessingStage\[];", processing_types) is not None
    assert re.search(r"current_status:\s*ProcessingStageStatus;", processing_types) is not None


def test_runtime_preview_uses_planned_agent_fields_and_never_claims_execution() -> None:
    contract_payload = build_gold_runtime_orchestration_contract()
    for mode_payload in contract_payload["run_modes"]:
        assert "agents_executed" not in mode_payload
        assert "agents_skipped" not in mode_payload
        assert "planned_agents_executed" in mode_payload
        assert "planned_agents_skipped" in mode_payload
        assert mode_payload["runtime_contract_only"] is True

    for contract in get_gold_runtime_mode_contracts():
        summary = build_gold_runtime_summary_preview(run_mode=contract.run_mode)
        assert "agents_executed" not in summary
        assert "agents_skipped" not in summary
        assert "planned_agents_executed" in summary
        assert "planned_agents_skipped" in summary
        assert summary["runtime_contract_only"] is True
        assert summary["writes"] == []
        assert set(summary["affected_mainlines"]).issubset(set(GOLD_MAINLINE_IDS))


def test_gold_mainline_outputs_cover_canonical_nine_mainlines() -> None:
    bundle = build_gold_event_mainlines([], as_of="2026-07-06T09:30:00+00:00").to_dict()
    overview = build_gold_macro_overview(bundle).to_dict()

    assert [row["mainline_id"] for row in bundle["mainlines"]] == list(GOLD_MAINLINE_IDS)
    assert [row["mainline_id"] for row in overview["theme_rankings"]] == list(GOLD_MAINLINE_IDS)


def test_source_health_output_mainline_impact_uses_canonical_mainlines() -> None:
    snapshot = source_health.build_gold_v3_source_health(
        {"sources": []},
        as_of="2026-07-06T09:30:00+00:00",
    ).to_dict()

    assert list(snapshot["mainline_impact"]) == list(GOLD_MAINLINE_IDS)


def test_runtime_agent_ids_resolve_in_registry_and_executed_skipped_sets_do_not_overlap() -> None:
    for contract in get_gold_runtime_mode_contracts():
        executed = set(contract.agents_executed)
        skipped = set(contract.agents_skipped)

        assert executed.isdisjoint(skipped), contract.run_mode
        for agent_id in sorted(executed | skipped):
            assert get_agent_registry(agent_id) is not None, f"{contract.run_mode}: {agent_id}"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "available"),
        ("status", "success"),
        ("health_state", "success"),
        ("readiness_state", "enabled"),
        ("readiness_state", "active"),
        ("readiness_state", "configured"),
        ("health_state", "connected"),
    ],
)
def test_source_health_common_available_status_values_are_ready(field: str, value: str) -> None:
    row = {
        "source_key": "xauusd_price",
        "status": "",
        "health_state": "",
        "readiness_state": "",
        "latest_health_at": "2026-07-06T09:30:00+00:00",
        "source_refs": [{"source_ref": "storage/xauusd_price.json"}],
    }
    row[field] = value

    assert source_health._source_status(row) == "ready"


def test_gold_mainline_read_time_source_health_is_overlay_and_does_not_mutate_artifact_status(monkeypatch: pytest.MonkeyPatch) -> None:
    overview = {
        "status": "partial",
        "review_status": "pass",
        "phase": "strong_uptrend",
        "one_line_conclusion": "strong bullish breakout",
        "as_of": "2026-07-06T09:30:00+00:00",
    }
    original = deepcopy(overview)

    class BlockingSnapshot:
        def to_dict(self) -> dict[str, Any]:
            return {
                "overall_status": "blocked",
                "as_of": "2026-07-06T09:30:00+00:00",
                "p0_missing": ["xauusd_price"],
                "p1_missing": [],
                "p2_missing": [],
                "stale_sources": [],
                "fresh_sources": [],
                "source_freshness": {},
                "mainline_impact": {},
                "can_build_gold_macro_overview": False,
                "can_emit_strong_conclusion": False,
                "blocked_mainlines": ["gold_technical_levels"],
                "degraded_mainlines": [],
                "blocking_reasons": ["P0 source gap conflicts with strong GoldMacroOverview conclusion"],
                "warnings": [],
            }

    monkeypatch.setattr(gold_mainline_service, "get_data_source_statuses", lambda: {"sources": []})
    monkeypatch.setattr(gold_mainline_service, "build_gold_v3_source_health", lambda *_, **__: BlockingSnapshot())

    read_time_source_health, read_time_warnings = gold_mainline_service._build_read_time_source_health(
        overview=overview
    )

    assert overview == original
    assert read_time_source_health["overall_status"] == "blocked"
    assert "read_time_source_health would block strong GoldMacroOverview conclusion" in read_time_warnings


def test_event_flow_report_input_title_inference_is_group_scoped() -> None:
    news_item = {
        "summary": "Fed repricing",
        "price": 3378.5,
        "range": "3370-3385",
    }
    technical_item = {
        "symbol": "XAUUSD",
        "level_type": "VAH",
        "price": 3378.5,
    }
    positioning_item = {
        "asset": "XAUUSD",
        "strike_or_level": "3350",
        "position_change": "increase",
    }

    assert event_flow_service._report_input_title(news_item, group_key="news_highlights") == "Fed repricing"
    assert event_flow_service._report_input_title(technical_item, group_key="technical_levels") == "XAUUSD / VAH / 3378.5"
    assert event_flow_service._report_input_title(positioning_item, group_key="positioning") == "XAUUSD / 3350 / increase"


def test_event_flow_report_input_verification_status_prefers_data_quality_contract() -> None:
    assert (
        event_flow_service._report_input_verification_status(
            {
                "verification_status": "unverified",
                "data_quality": {"verification_status": "single_source"},
            }
        )
        == "single_source"
    )
    assert event_flow_service._report_input_verification_status({"verification_status": "multi_source"}) == "multi_source"


def test_jin10_asset_audit_normalizes_equivalent_image_references() -> None:
    refs = {
        "./figures/fig_p1_001.png",
        "figures/fig_p1_001.png?raw=1",
        "/api/reports/223609/asset/fig_p1_001.png?raw=1",
        r"figures\fig_p1_001.png",
    }

    assert {report_service._normalize_jin10_image_ref(ref) for ref in refs} == {"figures/fig_p1_001.png"}


def test_jin10_chart_text_audit_does_not_flag_dense_chart_text_by_length_only() -> None:
    dense_chart_text = "A" * 121
    article_like_text = "黄金价格继续震荡。" * 24

    assert report_service._jin10_chart_text_issues([{"figure_id": "dense", "recognized_text": dense_chart_text}]) == []
    issues = report_service._jin10_chart_text_issues(
        [{"figure_id": "article", "recognized_text": article_like_text}]
    )
    assert issues[0]["figure_id"] == "article"


def test_processing_monitor_routes_do_not_import_api_main_callbacks() -> None:
    path = PROJECT_ROOT / "apps/api/routes/processing_monitor_routes.py"
    text = path.read_text(encoding="utf-8")

    assert "from apps.api import main" not in text
    assert "api_main." not in text
    assert "apps.api.services.processing_monitor_service" in text


def test_processing_monitor_uses_canonical_gold_mainline_ids() -> None:
    assert processing_monitor_service.MAINLINES == list(GOLD_MAINLINE_IDS)
    assert processing_monitor_service._canonical_mainline("oil_price") == "oil_prices"
    assert processing_monitor_service._canonical_mainline("geopolitical_war") == "geopolitical_war_risk"


def test_api_background_refresh_is_opt_in_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api import main as api_main

    monkeypatch.delenv("FINANCE_AGENT_DISABLE_BACKGROUND_JOBS", raising=False)
    monkeypatch.delenv("FINANCE_AGENT_ENABLE_API_BACKGROUND_REFRESH", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert api_main._should_skip_background_jobs() is True

    monkeypatch.setenv("FINANCE_AGENT_ENABLE_API_BACKGROUND_REFRESH", "1")
    from types import SimpleNamespace

    monkeypatch.setattr(api_main, "sys", SimpleNamespace(modules={}))
    assert api_main._should_skip_background_jobs() is False
