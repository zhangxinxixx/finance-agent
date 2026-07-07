from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.services.pipeline_contract_service import (
    build_premarket_pipeline_contract,
    build_premarket_pipeline_source_readiness,
)
from apps.premarket import (
    PREMARKET_STEP_ORDER,
    PremarketStepContract,
    evaluate_premarket_step_readiness,
    get_premarket_step_contracts,
    materialize_premarket_task_steps,
)

client = TestClient(app)


def _make_step_contract(
    *,
    required_sources: tuple[str, ...] = ("fred",),
    fallback_policy: str = "degraded_allowed",
) -> PremarketStepContract:
    return PremarketStepContract(
        name="test_step",
        order=0,
        pipeline_group="macro",
        stage="collect",
        type="collector",
        required_sources=required_sources,
        fallback_policy=fallback_policy,
    )


def _source_index(**sources: dict[str, object]) -> dict[str, dict[str, object]]:
    return {key: dict(value) for key, value in sources.items()}


def test_premarket_step_readiness_ready_when_required_source_ready() -> None:
    contract = _make_step_contract()

    result = evaluate_premarket_step_readiness(
        contract,
        _source_index(fred={"readiness_state": "ready"}),
    )

    assert result.decision == "ready"
    assert result.required_sources == ("fred",)
    assert result.degraded_sources == ()
    assert result.blocked_sources == ()
    assert result.gating_reason == "ready"


def test_premarket_step_readiness_degraded_when_policy_allows() -> None:
    contract = _make_step_contract(fallback_policy="degraded_allowed")

    result = evaluate_premarket_step_readiness(
        contract,
        _source_index(fred={"readiness_state": "degraded"}),
    )

    assert result.decision == "degraded_allowed"
    assert result.required_sources == ("fred",)
    assert result.degraded_sources == ("fred",)
    assert result.blocked_sources == ()
    assert result.gating_reason == "required_source_degraded_allowed"


def test_premarket_step_readiness_blocks_when_policy_disallows_degraded_source() -> None:
    contract = _make_step_contract(fallback_policy="block_if_unavailable")

    result = evaluate_premarket_step_readiness(
        contract,
        _source_index(fred={"readiness_state": "degraded"}),
    )

    assert result.decision == "blocked"
    assert result.required_sources == ("fred",)
    assert result.degraded_sources == ("fred",)
    assert result.blocked_sources == ("fred",)
    assert result.gating_reason == "required_source_degraded_blocked"


def test_premarket_step_readiness_blocks_when_required_source_blocked_or_not_configured() -> None:
    blocked_result = evaluate_premarket_step_readiness(
        _make_step_contract(),
        _source_index(fred={"readiness_state": "blocked"}),
    )
    not_configured_result = evaluate_premarket_step_readiness(
        _make_step_contract(),
        _source_index(fred={"readiness_state": "not_configured"}),
    )

    assert blocked_result.decision == "blocked"
    assert blocked_result.blocked_sources == ("fred",)
    assert blocked_result.gating_reason == "required_source_blocked"

    assert not_configured_result.decision == "blocked"
    assert not_configured_result.blocked_sources == ("fred",)
    assert not_configured_result.gating_reason == "required_source_not_configured"


def test_premarket_step_readiness_blocks_when_required_source_status_missing() -> None:
    result = evaluate_premarket_step_readiness(
        _make_step_contract(),
        _source_index(),
    )

    assert result.decision == "blocked"
    assert result.required_sources == ("fred",)
    assert result.degraded_sources == ()
    assert result.blocked_sources == ("fred",)
    assert result.gating_reason == "missing_source_status"


def test_premarket_step_readiness_ready_when_no_required_sources() -> None:
    result = evaluate_premarket_step_readiness(
        _make_step_contract(required_sources=()),
        _source_index(),
    )

    assert result.decision == "ready"
    assert result.required_sources == ()
    assert result.degraded_sources == ()
    assert result.blocked_sources == ()
    assert result.gating_reason == "ready"


def test_premarket_contract_keeps_canonical_order() -> None:
    contract = build_premarket_pipeline_contract()
    assert contract["step_order"] == list(PREMARKET_STEP_ORDER)
    assert [step["name"] for step in contract["steps"]] == list(PREMARKET_STEP_ORDER)
    assert [step["order"] for step in contract["steps"]] == list(range(len(PREMARKET_STEP_ORDER)))


def test_premarket_contract_classifies_pipeline_groups() -> None:
    contract = build_premarket_pipeline_contract()
    assert contract["pipeline_groups"] == {
        "macro": ["macro_collect", "macro_feature", "report_render"],
        "cme": ["cme_download", "cme_parse", "cme_ingest", "option_wall"],
        "news": ["news_collect", "news_feature", "news_brief"],
        "other": ["strategy_card"],
    }


def test_premarket_contract_keeps_same_pipeline_dependencies_isolated() -> None:
    contracts = {step.name: step for step in get_premarket_step_contracts()}

    same_pipeline_steps = {
        "macro": {"macro_collect", "macro_feature", "report_render"},
        "cme": {"cme_download", "cme_parse", "cme_ingest", "option_wall"},
        "news": {"news_collect", "news_feature", "news_brief"},
    }

    for pipeline, step_names in same_pipeline_steps.items():
        for step_name in step_names:
            step = contracts[step_name]
            assert step.pipeline_group == pipeline
            assert step.blocked_scope == pipeline
            assert set(step.upstream_dependencies).issubset(step_names)

    strategy_card = contracts["strategy_card"]
    assert strategy_card.pipeline_group == "other"
    assert strategy_card.stage == "summary"
    assert strategy_card.type == "summary"
    assert strategy_card.blocked_scope == "none"
    assert strategy_card.upstream_dependencies == ("report_render", "option_wall", "news_brief")


def test_premarket_contract_declares_source_gating_inputs() -> None:
    contracts = {step.name: step for step in get_premarket_step_contracts()}

    assert contracts["macro_collect"].required_sources == ("fred", "fed", "treasury", "dxy")
    assert contracts["macro_collect"].fallback_policy == "openbb_macro_or_stale_allowed"
    assert contracts["cme_download"].required_sources == ("cme_daily_bulletin",)
    assert contracts["cme_download"].fallback_policy == "stale_allowed_1d"
    assert contracts["cme_parse"].fallback_policy == "stale_allowed_1d"
    assert contracts["cme_ingest"].fallback_policy == "stale_allowed_1d"
    assert contracts["option_wall"].required_sources == ("cme_options",)
    assert contracts["news_collect"].required_sources == ("jin10_news", "jin10_flash", "jin10_mcp_calendar")
    assert contracts["strategy_card"].fallback_policy == "depends_on_upstream_status"


def test_premarket_contract_allows_latest_available_cme_bulletin() -> None:
    source_status_index = {
        "fred": {"readiness_state": "ready", "raw_ingested": True},
        "fed": {"readiness_state": "ready", "raw_ingested": True},
        "treasury": {"readiness_state": "ready", "raw_ingested": True},
        "dxy": {"readiness_state": "ready", "raw_ingested": True},
        "cme_daily_bulletin": {
            "readiness_state": "degraded",
            "raw_ingested": True,
            "parsed": True,
            "gating_reason": "freshness_stale",
            "metadata": {"latest_data_date": "2026-07-08"},
        },
        "cme_options": {"readiness_state": "ready", "analysis_ready": True, "metadata": {"latest_data_date": "2026-07-08"}},
        "jin10_news": {"readiness_state": "ready", "raw_ingested": True},
        "jin10_flash": {"readiness_state": "ready", "raw_ingested": True},
        "jin10_mcp_calendar": {"readiness_state": "ready", "raw_ingested": True},
    }

    with patch("apps.api.services.pipeline_contract_service.get_data_source_status_index", return_value=source_status_index):
        contract = build_premarket_pipeline_contract()

    step_by_name = {step["name"]: step for step in contract["steps"]}
    for step_name in ("cme_download", "cme_parse", "cme_ingest"):
        readiness = step_by_name[step_name]["source_readiness"]
        assert readiness["decision"] == "degraded_allowed"
        assert readiness["degraded_sources"] == ["cme_daily_bulletin"]
        assert readiness["blocked_sources"] == []
    assert step_by_name["option_wall"]["source_readiness"]["decision"] == "ready"

    summary = contract["source_readiness_summary"]
    assert "cme_download" not in summary["blocked_steps"]
    assert "cme_daily_bulletin" not in summary["blocked_sources"]
    assert "cme_daily_bulletin" in summary["degraded_sources"]


def test_premarket_contract_can_materialize_task_steps_from_canonical_nodes() -> None:
    run_id = "11111111-1111-1111-1111-111111111111"

    steps = materialize_premarket_task_steps(run_id)
    contracts = {step.name: step for step in get_premarket_step_contracts()}

    assert [step.name for step in steps] == list(PREMARKET_STEP_ORDER)
    assert [step.step_order for step in steps] == list(range(len(PREMARKET_STEP_ORDER)))
    assert all(str(step.task_run_id) == run_id for step in steps)
    assert all(step.status.value == "pending" for step in steps)
    for step in steps:
        contract = contracts[step.name]
        assert step.stage == contract.stage
        assert step.task_kind == contract.type


def test_premarket_contract_build_exposes_source_readiness_summary() -> None:
    source_status_index = {
        "fred": {"readiness_state": "degraded", "raw_ingested": True},
        "fed": {"readiness_state": "ready", "raw_ingested": True},
        "treasury": {"readiness_state": "ready", "raw_ingested": True},
        "dxy": {"readiness_state": "ready", "raw_ingested": True},
        "cme_daily_bulletin": {"readiness_state": "blocked", "error_message": "download failed"},
        "cme_options": {"readiness_state": "degraded", "raw_ingested": True},
        "jin10_news": {"readiness_state": "ready", "raw_ingested": True},
        "jin10_flash": {"readiness_state": "ready", "raw_ingested": True},
        "jin10_mcp_calendar": {"readiness_state": "ready", "raw_ingested": True},
    }

    with patch("apps.api.services.pipeline_contract_service.get_data_source_status_index", return_value=source_status_index):
        contract = build_premarket_pipeline_contract()

    step_by_name = {step["name"]: step for step in contract["steps"]}
    assert step_by_name["macro_collect"]["source_readiness"]["decision"] == "degraded_allowed"
    assert step_by_name["macro_collect"]["source_readiness"]["gating_reason"] == "required_source_degraded_allowed"
    assert step_by_name["cme_download"]["source_readiness"]["decision"] == "blocked"
    assert step_by_name["cme_download"]["source_readiness"]["blocked_sources"] == ["cme_daily_bulletin"]
    assert step_by_name["news_collect"]["source_readiness"]["decision"] == "ready"
    assert step_by_name["strategy_card"]["source_readiness"]["decision"] == "ready"

    summary = contract["source_readiness_summary"]
    assert summary["decision_counts"]["ready"] > 0
    assert summary["decision_counts"]["degraded_allowed"] > 0
    assert summary["decision_counts"]["blocked"] > 0
    assert "cme_download" in summary["blocked_steps"]
    assert "macro_collect" in summary["degraded_steps"]
    assert "cme_daily_bulletin" in summary["blocked_sources"]
    assert "fred" in summary["degraded_sources"]


def test_premarket_contract_build_handles_source_status_lookup_failure() -> None:
    with patch("apps.api.services.pipeline_contract_service.get_data_source_status_index", side_effect=RuntimeError("boom")):
        contract = build_premarket_pipeline_contract()

    step_by_name = {step["name"]: step for step in contract["steps"]}
    assert step_by_name["macro_collect"]["source_readiness"]["decision"] == "blocked"
    assert step_by_name["macro_collect"]["source_readiness"]["gating_reason"] == "missing_source_status"

    summary = contract["source_readiness_summary"]
    assert summary["decision_counts"]["blocked"] > 0
    assert "macro_collect" in summary["blocked_steps"]


def test_premarket_source_readiness_build_returns_summary_without_contract_groups() -> None:
    source_status_index = {
        "fred": {"readiness_state": "degraded", "raw_ingested": True},
        "fed": {"readiness_state": "ready", "raw_ingested": True},
        "treasury": {"readiness_state": "ready", "raw_ingested": True},
        "dxy": {"readiness_state": "ready", "raw_ingested": True},
        "cme_daily_bulletin": {"readiness_state": "ready", "raw_ingested": True},
        "cme_options": {"readiness_state": "degraded", "raw_ingested": True},
        "jin10_news": {"readiness_state": "ready", "raw_ingested": True},
        "jin10_flash": {"readiness_state": "ready", "raw_ingested": True},
        "jin10_mcp_calendar": {"readiness_state": "ready", "raw_ingested": True},
    }

    with patch("apps.api.services.pipeline_contract_service.get_data_source_status_index", return_value=source_status_index):
        readiness = build_premarket_pipeline_source_readiness()

    assert readiness["step_order"] == list(PREMARKET_STEP_ORDER)
    assert "pipeline_groups" not in readiness
    step_by_name = {step["name"]: step for step in readiness["steps"]}
    assert step_by_name["macro_collect"]["source_readiness"]["decision"] == "degraded_allowed"
    assert step_by_name["option_wall"]["source_readiness"]["decision"] == "degraded_allowed"
    assert readiness["source_readiness_summary"]["decision_counts"]["blocked"] == 0
    assert "fred" in readiness["source_readiness_summary"]["degraded_sources"]


def test_premarket_contract_api_exposes_canonical_contract() -> None:
    source_status_index = {
        "fred": {"readiness_state": "ready", "raw_ingested": True},
        "fed": {"readiness_state": "ready", "raw_ingested": True},
        "treasury": {"readiness_state": "ready", "raw_ingested": True},
        "dxy": {"readiness_state": "ready", "raw_ingested": True},
        "cme_daily_bulletin": {"readiness_state": "ready", "raw_ingested": True},
        "cme_options": {"readiness_state": "ready", "raw_ingested": True},
        "jin10_news": {"readiness_state": "ready", "raw_ingested": True},
        "jin10_flash": {"readiness_state": "ready", "raw_ingested": True},
        "jin10_mcp_calendar": {"readiness_state": "ready", "raw_ingested": True},
    }

    with patch("apps.api.services.pipeline_contract_service.get_data_source_status_index", return_value=source_status_index):
        resp = client.get("/api/pipelines/premarket/contract")

    assert resp.status_code == 200
    body = resp.json()
    assert body["step_order"] == list(PREMARKET_STEP_ORDER)
    assert [step["name"] for step in body["steps"]] == list(PREMARKET_STEP_ORDER)
    assert body["pipeline_groups"]["cme"] == ["cme_download", "cme_parse", "cme_ingest", "option_wall"]
    step_by_name = {step["name"]: step for step in body["steps"]}
    assert step_by_name["macro_collect"]["required_sources"] == ["fred", "fed", "treasury", "dxy"]
    assert step_by_name["macro_collect"]["fallback_policy"] == "openbb_macro_or_stale_allowed"
    assert step_by_name["cme_download"]["required_sources"] == ["cme_daily_bulletin"]
    assert step_by_name["cme_download"]["fallback_policy"] == "stale_allowed_1d"
    assert step_by_name["macro_collect"]["source_readiness"]["decision"] == "ready"
    assert body["source_readiness_summary"]["decision_counts"]["blocked"] == 0


def test_premarket_readiness_api_exposes_launch_time_source_summary() -> None:
    source_status_index = {
        "fred": {"readiness_state": "ready", "raw_ingested": True},
        "fed": {"readiness_state": "ready", "raw_ingested": True},
        "treasury": {"readiness_state": "ready", "raw_ingested": True},
        "dxy": {"readiness_state": "ready", "raw_ingested": True},
        "cme_daily_bulletin": {"readiness_state": "blocked", "error_message": "download failed"},
        "cme_options": {"readiness_state": "blocked", "error_message": "upstream missing"},
        "jin10_news": {"readiness_state": "ready", "raw_ingested": True},
        "jin10_flash": {"readiness_state": "ready", "raw_ingested": True},
        "jin10_mcp_calendar": {"readiness_state": "degraded", "raw_ingested": True},
    }

    with patch("apps.api.services.pipeline_contract_service.get_data_source_status_index", return_value=source_status_index):
        resp = client.get("/api/pipelines/premarket/readiness")

    assert resp.status_code == 200
    body = resp.json()
    assert body["step_order"] == list(PREMARKET_STEP_ORDER)
    assert "pipeline_groups" not in body
    step_by_name = {step["name"]: step for step in body["steps"]}
    assert step_by_name["cme_download"]["source_readiness"]["decision"] == "blocked"
    assert step_by_name["news_collect"]["source_readiness"]["decision"] == "degraded_allowed"
    summary = body["source_readiness_summary"]
    assert "cme_download" in summary["blocked_steps"]
    assert "news_collect" in summary["degraded_steps"]
    assert "cme_daily_bulletin" in summary["blocked_sources"]
    assert "jin10_mcp_calendar" in summary["degraded_sources"]
