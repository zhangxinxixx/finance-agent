from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
    assert contracts["cme_download"].fallback_policy == "block_if_unavailable"
    assert contracts["option_wall"].required_sources == ("cme_options",)
    assert contracts["news_collect"].required_sources == ("jin10_news", "jin10_flash", "jin10_mcp_calendar")
    assert contracts["strategy_card"].fallback_policy == "depends_on_upstream_status"


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
    assert step_by_name["cme_download"]["fallback_policy"] == "block_if_unavailable"
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


# --- Issue #15: contract read-model metadata fields ---


def test_premarket_contract_exposes_issue15_metadata_fields() -> None:
    """Each step in the contract exposes criticality, freshness_sla, quality_weight, artifact_types."""
    contracts = {step.name: step for step in get_premarket_step_contracts()}

    expected = {
        "macro_collect":   ("critical",  3600,  0.20, ("macro_snapshot",)),
        "macro_feature":   ("critical",  3600,  0.20, ("macro_feature_snapshot",)),
        "cme_download":    ("critical",  86400, 0.12, ("cme_daily_bulletin_pdf",)),
        "cme_parse":       ("critical",  86400, 0.12, ("cme_parsed_data",)),
        "cme_ingest":      ("critical",  86400, 0.12, ("cme_options_snapshot",)),
        "option_wall":     ("important", 86400, 0.10, ("option_wall_analysis",)),
        "report_render":   ("important", 3600,  0.05, ("daily_report_markdown",)),
        "news_collect":    ("optional",  1800,  0.03, ("jin10_news_raw", "jin10_flash_cache", "jin10_calendar_cache")),
        "news_feature":    ("optional",  1800,  0.03, ("news_feature_snapshot",)),
        "news_brief":      ("optional",  1800,  0.03, ("daily_market_brief",)),
        "strategy_card":   ("important", None,  0.00, ("strategy_card_markdown",)),
    }

    for name, (crit, sla, weight, artifacts) in expected.items():
        c = contracts[name]
        assert c.criticality == crit, f"{name}.criticality"
        assert c.freshness_sla_seconds == sla, f"{name}.freshness_sla_seconds"
        assert c.quality_weight == weight, f"{name}.quality_weight"
        assert c.expected_artifact_types == artifacts, f"{name}.expected_artifact_types"

    # Verify to_dict serializes expected_artifact_types as a list
    d = contracts["news_collect"].to_dict()
    assert isinstance(d["expected_artifact_types"], list)
    assert d["expected_artifact_types"] == ["jin10_news_raw", "jin10_flash_cache", "jin10_calendar_cache"]


def test_premarket_contract_quality_score_penalizes_blocked_and_degraded_steps() -> None:
    """Quality score starts at 1.0 and is penalised by blocked (full weight) and degraded (half weight)."""
    now = datetime.now(timezone.utc)
    fresh_iso = (now - timedelta(seconds=60)).isoformat()
    # cme_daily_bulletin is blocked -> full penalty for cme_download/cme_parse/cme_ingest (3 * 0.12 = 0.36)
    # fred is degraded -> macro_collect (0.20*0.5=0.10), macro_feature (0.20*0.5=0.10), report_render (0.05*0.5=0.025)
    # cme_options is degraded -> option_wall degraded_allowed (0.10*0.5=0.05)
    # news: all ready
    source_status_index = {
        "fred": {"readiness_state": "degraded", "raw_ingested": True, "latest_update_time": fresh_iso},
        "fed": {"readiness_state": "ready", "raw_ingested": True, "latest_update_time": fresh_iso},
        "treasury": {"readiness_state": "ready", "raw_ingested": True, "latest_update_time": fresh_iso},
        "dxy": {"readiness_state": "ready", "raw_ingested": True, "latest_update_time": fresh_iso},
        "cme_daily_bulletin": {"readiness_state": "blocked", "error_message": "download failed"},
        "cme_options": {"readiness_state": "degraded", "raw_ingested": True, "latest_update_time": fresh_iso},
        "jin10_news": {"readiness_state": "ready", "raw_ingested": True, "latest_update_time": fresh_iso},
        "jin10_flash": {"readiness_state": "ready", "raw_ingested": True, "latest_update_time": fresh_iso},
        "jin10_mcp_calendar": {"readiness_state": "ready", "raw_ingested": True, "latest_update_time": fresh_iso},
    }

    with patch("apps.api.services.pipeline_contract_service.get_data_source_status_index", return_value=source_status_index):
        result = build_premarket_pipeline_source_readiness()

    summary = result["source_readiness_summary"]
    score = summary["quality_score"]
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0

    # Verify critical_blocked_steps are tracked
    critical_blocked = summary["critical_blocked_steps"]
    assert "cme_download" in critical_blocked
    assert "cme_parse" in critical_blocked
    assert "cme_ingest" in critical_blocked
    # macro_collect is degraded_allowed, not blocked, so not critical_blocked
    assert "macro_collect" not in critical_blocked

    # Verify quality score is less than 1.0 (penalties applied)
    assert score < 1.0

    # Recalculate expected score manually:
    # blocked: cme_download(0.12) + cme_parse(0.12) + cme_ingest(0.12) = 0.36
    #   (option_wall fallback_policy=stale_allowed_1d -> degraded_allowed, not blocked)
    # degraded_allowed: macro_collect(0.20*0.5) + macro_feature(0.20*0.5)
    #   + report_render(0.05*0.5) + option_wall(0.10*0.5) = 0.275
    # strategy_card is ready (no required sources) -> no penalty
    # news steps: all ready -> no penalty
    # expected = 1.0 - 0.36 - 0.275 = 0.365
    assert score == 0.365


def test_premarket_contract_freshness_annotation_uses_step_sla() -> None:
    """Freshness annotation reflects per-step SLA against source timestamps."""
    now = datetime.now(timezone.utc)
    fresh_iso = (now - timedelta(seconds=60)).isoformat()
    stale_macro_iso = (now - timedelta(seconds=7200)).isoformat()  # 2h > 3600 SLA
    stale_cme_iso = (now - timedelta(seconds=90000)).isoformat()   # 25h > 86400 SLA
    fresh_news_iso = (now - timedelta(seconds=300)).isoformat()    # 5m < 1800 SLA

    source_status_index = {
        "fred": {"readiness_state": "ready", "raw_ingested": True, "latest_update_time": stale_macro_iso},
        "fed": {"readiness_state": "ready", "raw_ingested": True, "latest_update_time": fresh_iso},
        "treasury": {"readiness_state": "ready", "raw_ingested": True, "latest_update_time": fresh_iso},
        "dxy": {"readiness_state": "ready", "raw_ingested": True, "latest_update_time": fresh_iso},
        "cme_daily_bulletin": {"readiness_state": "ready", "raw_ingested": True, "latest_update_time": stale_cme_iso},
        "cme_options": {"readiness_state": "ready", "raw_ingested": True, "latest_update_time": fresh_iso},
        "jin10_news": {"readiness_state": "ready", "raw_ingested": True, "latest_update_time": fresh_news_iso},
        "jin10_flash": {"readiness_state": "ready", "raw_ingested": True, "latest_update_time": fresh_news_iso},
        "jin10_mcp_calendar": {"readiness_state": "ready", "raw_ingested": True, "latest_update_time": fresh_news_iso},
    }

    with patch("apps.api.services.pipeline_contract_service.get_data_source_status_index", return_value=source_status_index):
        result = build_premarket_pipeline_source_readiness()

    step_by_name = {step["name"]: step for step in result["steps"]}

    # macro_collect: SLA=3600, fred is stale (2h old) -> stale
    assert step_by_name["macro_collect"]["source_readiness"]["freshness_annotation"] == "stale"
    # macro_feature: same sources, fred stale -> stale
    assert step_by_name["macro_feature"]["source_readiness"]["freshness_annotation"] == "stale"
    # cme_download: SLA=86400, cme_daily_bulletin stale (25h old) -> stale
    assert step_by_name["cme_download"]["source_readiness"]["freshness_annotation"] == "stale"
    # cme_parse: same source as cme_download -> stale
    assert step_by_name["cme_parse"]["source_readiness"]["freshness_annotation"] == "stale"
    # cme_ingest: same source -> stale
    assert step_by_name["cme_ingest"]["source_readiness"]["freshness_annotation"] == "stale"
    # option_wall: SLA=86400, cme_options fresh -> fresh
    assert step_by_name["option_wall"]["source_readiness"]["freshness_annotation"] == "fresh"
    # report_render: SLA=3600, has fred stale -> stale
    assert step_by_name["report_render"]["source_readiness"]["freshness_annotation"] == "stale"
    # news_collect: SLA=1800, all fresh (5m old) -> fresh
    assert step_by_name["news_collect"]["source_readiness"]["freshness_annotation"] == "fresh"
    # news_feature: SLA=1800, jin10_news fresh -> fresh
    assert step_by_name["news_feature"]["source_readiness"]["freshness_annotation"] == "fresh"
    # news_brief: SLA=1800, jin10_news fresh -> fresh
    assert step_by_name["news_brief"]["source_readiness"]["freshness_annotation"] == "fresh"
    # strategy_card: no SLA -> not_applicable
    assert step_by_name["strategy_card"]["source_readiness"]["freshness_annotation"] == "not_applicable"

    # Verify stale_steps summary
    stale_steps = result["source_readiness_summary"]["stale_steps"]
    assert "macro_collect" in stale_steps
    assert "cme_download" in stale_steps
    assert "option_wall" not in stale_steps
    assert "strategy_card" not in stale_steps

    # Verify unknown when timestamps are missing
    source_status_index_no_ts = {
        "fred": {"readiness_state": "ready", "raw_ingested": True},
        "fed": {"readiness_state": "ready", "raw_ingested": True},
        "treasury": {"readiness_state": "ready", "raw_ingested": True},
        "dxy": {"readiness_state": "ready", "raw_ingested": True},
    }
    with patch("apps.api.services.pipeline_contract_service.get_data_source_status_index", return_value=source_status_index_no_ts):
        result_no_ts = build_premarket_pipeline_source_readiness()
    step_no_ts = {step["name"]: step for step in result_no_ts["steps"]}
    assert step_no_ts["macro_collect"]["source_readiness"]["freshness_annotation"] == "unknown"
