"""Real merge-op orchestration with isolated registry and mocked network IO."""
from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.analysis.snapshots.input_validation import prepare_analysis_inputs
from apps.analysis.agents.research_input import RESEARCH_PRESENTATION_VERSION
from apps.analysis.agents.research_synthesis import _build_prompt_payload
from apps.worker.adaptive_research import plan_research
from database.models.report import ensure_report_tables
from tests.analysis.test_input_validation import valid_snapshot
from tests.analysis.test_report_continuity import register
from tests.analysis.test_research_synthesis import _output


def test_merge_loads_prior_bodies_before_research_and_persists_new_reader(tmp_path, monkeypatch):
    from dagster_finance.graphs import premarket

    engine = create_engine("sqlite://")
    ensure_report_tables(engine)
    monkeypatch.setattr(premarket, "jin10_disabled", lambda: True)
    monkeypatch.setattr(premarket, "_load_formal_market_snapshot_bundle", lambda **kwargs:
                        (SimpleNamespace(market_prices=None, market_context=None, oil=None), None))
    monkeypatch.setattr("apps.analysis.snapshots.builder.build_analysis_snapshot",
                        lambda **kwargs: valid_snapshot(tmp_path))
    # Only acquisition, state authority and audit-version IO are replaced.
    # The context loader, validators, planner projection, synthesis projection
    # and snapshot writer execute their real implementations.
    for name in ("fedwatch.enrich_fedwatch_snapshot", "cross_asset_research.enrich_cross_asset_snapshot",
                 "mainstream_news.enrich_mainstream_news_snapshot", "execution_research.refresh_execution_snapshot"):
        monkeypatch.setattr("apps.worker." + name, lambda snapshot, **kwargs: snapshot)
    monkeypatch.setattr("apps.analysis.snapshots.research_previous.load_previous_research",
                        lambda *args, **kwargs: {"status": "unavailable"})
    monkeypatch.setattr("database.queries.market_state.load_accepted_state", lambda *args, **kwargs: {})
    monkeypatch.setattr("database.queries.market_state.stage_state_proposal", Mock())
    monkeypatch.setattr("apps.runtime.premarket_snapshot_authority.stage_premarket_snapshot_authority", Mock())
    monkeypatch.setattr("database.queries.data_source_status.upsert_data_source_status", Mock())
    monkeypatch.setattr("apps.analysis.research_shadow.archive_research_versions", lambda *args: {})
    seen = []
    bodies = {}

    def gateway(**kwargs):
        packed = json.loads(kwargs["messages"][1]["content"])
        prior = packed["prior_report_contexts"]["contexts"]
        for cadence in ("daily", "weekly"):
            assert prior[cadence]["body"] == bodies[cadence]
            assert prior[cadence]["formal_state_authority"] is False
        seen.append("planner")
        return SimpleNamespace(content=json.dumps({
            "action": "finish", "question": "旧假设是否仍成立？", "hypothesis": "必须用当前证据重验。",
            "driver_assessment": "当天主线尚待观察。", "competing_hypotheses": ["另一传导渠道"],
            "falsifier": "价格与当期利率不再同向。", "why_these_requests": "本轮无需补采。",
            "evidence_assessment": "两份旧正文已读取。", "data_requests": [], "unavailable_data_needs": [],
            "finish_reason": "evidence_sufficient",
        }), audit_id="test-planner", model="fixture")

    def research(snapshot, **kwargs):
        assert snapshot["prior_report_contexts"]["status"] == "verified"
        assert plan_research(snapshot, gateway)["action"] == "finish"
        return snapshot

    monkeypatch.setattr("apps.worker.adaptive_research.enrich_research_snapshot", research)
    with Session(engine) as db:
        for cadence, day in (("daily", "2026-10-05"), ("weekly", "2026-10-03")):
            _, _, bodies[cadence] = register(db, tmp_path, name=cadence, trade_date=day, cadence=cadence,
                generated_at=datetime.fromisoformat(day + "T04:00:00+00:00"))
        context = SimpleNamespace(run_id="test-run", resources=SimpleNamespace(db_session=db), log=Mock())
        result = premarket.merge_analysis_snapshot_op.compute_fn.decorated_fn(
            context, premarket.MergeSnapshotConfig(storage_root=str(tmp_path)),
            SimpleNamespace(all_points=[], all_source_refs=[]), SimpleNamespace(), None,
        )
        assert seen == ["planner"]
        assert result["gold_workflow"]["reader_presentation"] == RESEARCH_PRESENTATION_VERSION
        assert result["prior_report_contexts"]["status"] == "verified"
        assert result["input_snapshot_ids"]["prior_report_daily"] == "snapshot-daily"
        assert result["input_snapshot_ids"]["prior_report_weekly"] == "snapshot-weekly"
        prepared = prepare_analysis_inputs(result, storage_root=tmp_path)
        payload = _build_prompt_payload(prepared, _output())
        assert payload["prior_report_contexts"]["contexts"]["daily"]["body"] == bodies["daily"]
        assert payload["prior_report_contexts"]["contexts"]["weekly"]["body"] == bodies["weekly"]
        persisted = list((tmp_path / "features").rglob("premarket_snapshot.json"))
        assert len(persisted) == 1
        saved = json.loads(persisted[0].read_text())
        assert saved["prior_report_contexts"] == result["prior_report_contexts"]
        assert saved["gold_workflow"]["reader_presentation"] == RESEARCH_PRESENTATION_VERSION
    engine.dispose()
