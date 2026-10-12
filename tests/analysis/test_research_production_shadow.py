import pytest
from copy import deepcopy
from apps.analysis.research_shadow import SKILLS, archive_research_versions, evaluate_shadow_readiness
from apps.features.research.production_shadow import apply_production_shadow_features
from apps.features.research.source_health import build_core_source_health
from apps.features.research.state import build_state_proposal
from apps.features.research.workflow import build_gold_workflow
from apps.analysis.agents.research_context import build_research_assessment
from apps.renderer.markdown.final_report import build_structured_report
from tests.analysis.test_daily_research import _snapshot


def test_core_health_published_miss_waiting_and_fedwatch_are_distinct():
    row = {"collector_status": "success", "retrieved_at": "2026-09-08T08:00:00Z", "actual_latest_date": "2026-09-01", "official_latest_date": "2026-09-03"}
    s = {"snapshot_time": "2026-09-08T08:01:00Z", "macro": {"data": {"collector_health": {"gdp_now": row}}}}
    health = build_core_source_health(s)
    assert health["items"][0]["source_health"] == "FAILED"
    assert "newer_than_local" in health["items"][0]["reason"]
    assert "not_configured" in health["items"][-1]["reason"]
    row.update(collector_status="not_published", actual_latest_date=None, official_latest_date=None, expected_release_time="2026-09-09T08:00:00Z")
    assert build_core_source_health(s)["items"][0]["source_health"] == "WAITING_RELEASE"
    row["expected_release_time"] = "2026-09-07T08:00:00Z"
    assert build_core_source_health(s)["items"][0]["source_health"] == "FAILED"


def test_new_shadow_report_has_state_health_and_coarse_scores():
    s = _snapshot()
    s["trade_date"] = "2026-09-08"
    s["asset"] = "XAUUSD"
    s["technical"] = {"status": "available", "data": {"as_of": "2026-09-07", "price": 4420, "atr14": 45, "source_refs": s["source_refs"]}}
    flow = build_gold_workflow(s)
    for item, value in zip(flow['scenario_engine']['scenarios'], (24.35,20.73,54.92)):
        item['weight_pct'] = value
    shadow = apply_production_shadow_features(s,flow)
    assert "production_shadow" not in flow
    assert shadow["price_anchor"]["session_quality"]["session_class"] == "HOLIDAY"
    assert shadow["report_session_quality"]["session_class"] == "NORMAL"
    shadow["state_record"] = build_state_proposal(s,shadow)
    s["gold_workflow"] = shadow
    with pytest.raises(ValueError, match="research report blocked"):
        build_structured_report(snapshot=s,macro_output=None,options_output=None,risk_output=None,coordinator_output=None,research_assessment=build_research_assessment(s))
    assert s["gold_workflow"]["reader_report_version"] == "gold_reader.v3"
    from apps.renderer.markdown.gold_workflow import gold_workflow_sections
    sections={x['section_id']:x['body'] for x in gold_workflow_sections(s, {}, build_research_assessment(s))}
    assert "HOLIDAY" in sections["data_passport"]
    assert "最新完整日线" not in sections["data_passport"]
    assert "INITIALIZATION_REQUIRED" in sections["current_state"]
    assert "fedwatch_collector_not_configured" in sections["macro_diagnosis"]
    display=shadow["scenario_display"]
    assert display["display_weights_sum"] == 100
    assert all(x["display_weight_pct"] % 5 == 0 for x in display["scenarios"])
    assert "Score Share" in sections["three_scenarios"]


def test_shadow_days_do_not_count_reruns_replays_or_future_event_schedule():
    model = {"status":"success", "generated_by":"llm", "provenance_complete":True}
    base = {"run_id":"first", "trade_date":"2026-09-08", "analysis_time":"2026-09-08T08:00:00Z", "run_mode":"live_shadow", "task_status":"success", "artifacts_verified":True, "model":model, "report_output":{"selection_kind":"model_coordinator"}, "session_quality":{"session_type":"NORMAL"},
            "event_observations":[{"event_type":"CPI","released_at":"2026-09-11T12:30:00Z","verified":True,"source_refs":[{"source":"BLS"}]}]}
    replay={**base,"run_id":"replay","run_mode":"replay","trade_date":"2026-09-09"}
    holiday={**base,"run_id":"holiday","session_quality":{"session_type":"HOLIDAY"}}
    result=evaluate_shadow_readiness([base,deepcopy(base),replay,holiday])
    assert result["verified_trading_days"] == 1
    assert result["covered_events"] == []
    assert not result["time_and_event_gate_passed"]


def test_shadow_uses_session_day_and_rejects_invalid_or_future_dates():
    friday = {"run_id": "friday", "trade_date": "2026-09-04", "analysis_time": "2026-09-05T00:30:00Z", "run_mode": "live_shadow",
              "task_status": "success", "artifacts_verified": True, "model": {"status": "success", "generated_by": "llm", "provenance_complete": True},
              "report_output": {"selection_kind": "model_coordinator"}, "session_quality": {"session_type": "NORMAL"}}
    future = {**friday, "run_id": "future", "trade_date": "2026-10-05"}
    invalid = {**friday, "run_id": "invalid", "trade_date": "20260904"}
    result = evaluate_shadow_readiness([friday, future, invalid])
    assert result["verified_trading_days"] == 1
    assert result["rejected_run_ids"] == ["future", "invalid"]
    fallback = {**friday, "model": {"status": "rule_fallback"}}
    assert evaluate_shadow_readiness([fallback])["verified_trading_days"] == 0
    incomplete = {**friday, "model": {"status": "success", "generated_by": "llm", "provenance_complete": False}}
    assert evaluate_shadow_readiness([incomplete])["verified_trading_days"] == 0


def test_version_archive_records_dirty_code_and_preserves_old_blobs(tmp_path):
    root = tmp_path / "repo"
    storage = tmp_path / "storage"
    for name in SKILLS:
        path = root / ".agents" / "skills" / name / "SKILL.md"
        path.parent.mkdir(parents=True)
        path.write_text(name)
    source = root / "apps" / "features" / "formula.py"
    source.parent.mkdir(parents=True)
    source.write_text("answer = 1\n")
    first = archive_research_versions(storage, repo_root=root)
    old = (storage / first["artifact_ref"]).read_bytes()
    source.write_text("answer = 2\n")
    second = archive_research_versions(storage, repo_root=root)
    assert first["manifest_id"] != second["manifest_id"]
    assert (storage / first["artifact_ref"]).read_bytes() == old
