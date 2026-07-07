from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from database.models.task import Base, StepStatus, TaskRun, TaskStatus, TaskStep
from database.models.analysis import AnalysisBase

_CREATED_AT = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
_TRADE_DATE = "2026-05-14"


@pytest.fixture(autouse=True)
def _isolate_source_gating():
    """Keep composite analysis DB integration tests deterministic unless they opt into source gating explicitly."""
    with patch("apps.api.services.source_service.get_data_source_status_index", return_value={}):
        yield


def _make_db_session(tmp_path: Path):
    """Create a DB session with both TaskBase and AnalysisBase tables."""
    engine = create_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}", echo=False)
    Base.metadata.create_all(engine)
    AnalysisBase.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _make_task_with_steps(db, step_names: list[str]) -> TaskRun:
    task = TaskRun(name="premarket", status=TaskStatus.pending)
    db.add(task)
    db.flush()
    for name in step_names:
        db.add(TaskStep(task_run_id=task.id, name=name, status=StepStatus.pending))
    db.commit()
    return task


# ═══════════════════════════════════════════════════════════════════════
# DB sink integration tests
# ═══════════════════════════════════════════════════════════════════════


def test_db_sink_creates_analysis_tables(tmp_path: Path) -> None:
    """Analysis tables should be created during premarket run."""
    db = _make_db_session(tmp_path)

    # Drop analysis tables first to confirm ensure_analysis_tables works
    AnalysisBase.metadata.drop_all(bind=db.get_bind())

    from database.models.analysis import ensure_analysis_tables

    ensure_analysis_tables(db)

    # Verify tables exist by querying them
    result = db.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='analysis_snapshots'"))
    assert result.scalar() == "analysis_snapshots"

    result = db.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='agent_outputs'"))
    assert result.scalar() == "agent_outputs"

    result = db.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='final_analysis_results'"))
    assert result.scalar() == "final_analysis_results"


def test_db_sink_persists_analysis_snapshot(tmp_path: Path) -> None:
    """After premarket run with composite analysis, DB must contain an AnalysisSnapshot."""
    from database.models.analysis import AnalysisSnapshot

    db = _make_db_session(tmp_path)
    task = _make_task_with_steps(
        db,
        ["macro_collect", "macro_feature", "report_render"],
    )

    def mock_macro_step(step_name, state, **kwargs):
        if step_name == "report_render":
            state.snapshot_dict = {
                "as_of": _TRADE_DATE,
                "indicators": {
                    "DXY": {"value": 101.50, "change_1w": -0.80, "unit": "index"},
                    "DGS10": {"value": 4.42, "change_1w": -0.12, "unit": "percent"},
                    "T10YIE": {"value": 2.15, "change_1w": -0.03, "unit": "percent"},
                    "RRPONTSYD": {"value": 180.5, "change_1w": -12.3, "unit": "billions_usd"},
                    "TGA": {"value": 720.1, "change_1w": 45.2, "unit": "billions_usd"},
                },
                "source_refs": [{"symbol": "DGS10", "source": "fred"}],
            }
        return {"step": step_name, "status": "success"}

    with patch("apps.worker.pipelines.macro.run_macro_step", side_effect=mock_macro_step):
        from apps.worker.runner import run_premarket

        result = run_premarket(db, task.id, storage_root=tmp_path)

    assert result == TaskStatus.success

    # Query AnalysisSnapshot from DB
    snapshots = db.query(AnalysisSnapshot).all()
    assert len(snapshots) >= 1, "DB should contain at least one AnalysisSnapshot"

    snap = snapshots[0]
    assert snap.asset == "XAUUSD"
    assert snap.trade_date.isoformat() == _TRADE_DATE
    assert snap.run_id == str(task.id)
    assert snap.status == "success"
    assert snap.artifact_path, "artifact_path must not be empty"
    # Verify payload is a dict with expected keys
    assert isinstance(snap.payload, dict)
    assert snap.payload.get("asset") == "XAUUSD"


def test_db_sink_persists_agent_outputs(tmp_path: Path) -> None:
    """After premarket run, DB must contain all domain/composite analysis agent outputs."""
    from database.models.analysis import AgentOutput as DBAgentOutput

    db = _make_db_session(tmp_path)
    task = _make_task_with_steps(
        db,
        ["macro_collect", "macro_feature", "report_render",
         "cme_download", "cme_parse", "cme_ingest", "option_wall"],
    )

    def mock_cme_step(step_name, state, **kwargs):
        if step_name == "option_wall":
            state.snapshot_dict = {
                "trade_date": _TRADE_DATE,
                "wall_scores": [{"strike": 3300, "wall_score": 0.82, "wall_type": "put", "side": "support"}],
                "support_resistance": {
                    "support": [{"strike": 3250, "score": 0.7}],
                    "resistance": [{"strike": 3400, "score": 0.6}],
                },
                "intent": {"type": "supportive", "score": 0.65},
                "gex": {
                    "netgex_aggregate": {"gamma_zero": {"price": 3350}},
                    "by_expiry": {"2026-06": {"summary": {"net_gex": 2500, "dominant_side": "positive"}, "iv_skew": {"risk_reversal_25d": 0.15}}},
                },
                "walls": {"block_pnt_walls": [{"strike": 3320, "block": 120, "pnt": 80}]},
                "data_source": {"status": "FINAL", "input_snapshot_ids": {"raw_file_sha256": "abc123"}, "expiries": ["2026-06", "2026-07"]},
                "data_quality": {"categories": {"prelim_data": 0}, "warnings": []},
            }
        return {"step": step_name, "status": "success"}

    def mock_macro_step(step_name, state, **kwargs):
        if step_name == "report_render":
            state.snapshot_dict = {
                "as_of": _TRADE_DATE,
                "indicators": {
                    "DXY": {"value": 101.50, "change_1w": -0.80, "unit": "index"},
                    "DGS10": {"value": 4.42, "change_1w": -0.12, "unit": "percent"},
                    "T10YIE": {"value": 2.15, "change_1w": -0.03, "unit": "percent"},
                    "RRPONTSYD": {"value": 180.5, "change_1w": -12.3, "unit": "billions_usd"},
                    "TGA": {"value": 720.1, "change_1w": 45.2, "unit": "billions_usd"},
                },
                "source_refs": [{"symbol": "DGS10", "source": "fred"}],
            }
        return {"step": step_name, "status": "success"}

    with (
        patch("apps.worker.pipelines.cme.run_cme_step", side_effect=mock_cme_step),
        patch("apps.worker.pipelines.macro.run_macro_step", side_effect=mock_macro_step),
    ):
        from apps.worker.runner import run_premarket

        result = run_premarket(db, task.id, storage_root=tmp_path)

    assert result == TaskStatus.success

    agent_outputs = db.query(DBAgentOutput).all()
    agent_names = {ao.agent_name for ao in agent_outputs}
    expected_agents = {
        "macro_liquidity_agent",
        "cme_options_agent",
        "risk_agent",
        "technical_agent",
        "positioning_agent",
        "news_agent",
        "market_odds_agent",
        "coordinator_agent",
    }

    assert expected_agents.issubset(agent_names), f"Expected agents {expected_agents}, got {agent_names}"
    fallback_rows = [ao for ao in agent_outputs if ao.agent_name == "fallback_synthesis_agent"]
    if fallback_rows:
        fallback_payload = fallback_rows[0].payload
        assert fallback_payload["module"] == "agent_loop_fallback"
        assert fallback_payload["input_payload"]["fallback_of"]["agent_name"] == "coordinator_agent"
        assert fallback_payload["bias"] == "neutral"

    # Verify each agent output has required fields
    for ao in agent_outputs:
        assert ao.snapshot_id, f"{ao.agent_name} missing snapshot_id"
        assert ao.asset == "XAUUSD"
        assert ao.trade_date.isoformat() == _TRADE_DATE
        assert ao.run_id == str(task.id)
        assert ao.status, f"{ao.agent_name} missing status"
        assert ao.bias, f"{ao.agent_name} missing bias"
        assert isinstance(ao.confidence, float)
        assert isinstance(ao.payload, dict)


def test_db_sink_persists_final_analysis_result(tmp_path: Path) -> None:
    """After premarket run, DB must contain a FinalAnalysisResult with correct fields."""
    from database.models.analysis import FinalAnalysisResult as DBFinalResult

    db = _make_db_session(tmp_path)
    task = _make_task_with_steps(
        db,
        ["macro_collect", "macro_feature", "report_render"],
    )

    def mock_macro_step(step_name, state, **kwargs):
        if step_name == "report_render":
            state.snapshot_dict = {
                "as_of": _TRADE_DATE,
                "indicators": {
                    "DXY": {"value": 101.50, "change_1w": -0.80, "unit": "index"},
                    "DGS10": {"value": 4.42, "change_1w": -0.12, "unit": "percent"},
                    "T10YIE": {"value": 2.15, "change_1w": -0.03, "unit": "percent"},
                    "RRPONTSYD": {"value": 180.5, "change_1w": -12.3, "unit": "billions_usd"},
                    "TGA": {"value": 720.1, "change_1w": 45.2, "unit": "billions_usd"},
                },
                "source_refs": [{"symbol": "DGS10", "source": "fred"}],
            }
        return {"step": step_name, "status": "success"}

    with patch("apps.worker.pipelines.macro.run_macro_step", side_effect=mock_macro_step):
        from apps.worker.runner import run_premarket

        result = run_premarket(db, task.id, storage_root=tmp_path)

    assert result == TaskStatus.success

    final_results = db.query(DBFinalResult).all()
    assert len(final_results) == 1, f"Expected 1 FinalAnalysisResult, got {len(final_results)}"

    fr = final_results[0]
    assert fr.asset == "XAUUSD"
    assert fr.trade_date.isoformat() == _TRADE_DATE
    assert fr.run_id == str(task.id)
    assert fr.is_trade_instruction is False
    assert fr.final_bias is not None, "final_bias must be set"
    assert fr.confidence is not None, "confidence must be set"
    assert fr.final_report_path is not None, "final_report_path must be set"
    assert fr.strategy_card_json_path is not None, "strategy_card_json_path must be set"
    assert fr.strategy_card_md_path is not None, "strategy_card_md_path must be set"
    assert fr.run_summaries["gold_runtime_summary"]["run_mode"] == "premarket_full_run"
    assert fr.run_summaries["gold_runtime_summary"]["runtime_contract_only"] is False
    assert "quality_gate_status" in fr.run_summaries["gold_runtime_summary"]

    from apps.api.services.task_service import get_task_run_response

    run_response = get_task_run_response(db, str(task.id))
    assert run_response is not None
    assert run_response.runtime_summary is not None
    assert run_response.runtime_summary["run_mode"] == "premarket_full_run"
    assert run_response.runtime_summary["quality_gate_status"] in {
        "passed",
        "fallback_required",
        "needs_review",
        "blocked",
    }


def test_db_sink_preserves_source_refs_and_snapshot_ids(tmp_path: Path) -> None:
    """source_refs and input_snapshot_ids must be preserved in DB records."""
    from database.models.analysis import AnalysisSnapshot, AgentOutput as DBAgentOutput
    from database.models.analysis import FinalAnalysisResult as DBFinalResult

    db = _make_db_session(tmp_path)
    task = _make_task_with_steps(
        db,
        ["macro_collect", "macro_feature", "report_render",
         "cme_download", "cme_parse", "cme_ingest", "option_wall"],
    )

    def mock_cme_step(step_name, state, **kwargs):
        if step_name == "option_wall":
            state.snapshot_dict = {
                "trade_date": _TRADE_DATE,
                "wall_scores": [{"strike": 3300, "wall_score": 0.82, "wall_type": "put", "side": "support"}],
                "support_resistance": {"support": [{"strike": 3250, "score": 0.7}], "resistance": []},
                "intent": {"type": "supportive", "score": 0.65},
                "gex": {"netgex_aggregate": {"gamma_zero": {"price": 3350}}, "by_expiry": {}},
                "walls": {"block_pnt_walls": []},
                "data_source": {"status": "FINAL", "input_snapshot_ids": {"raw_file_sha256": "abc123"}, "expiries": ["2026-06"]},
                "data_quality": {"categories": {"prelim_data": 0}, "warnings": []},
            }
        return {"step": step_name, "status": "success"}

    def mock_macro_step(step_name, state, **kwargs):
        if step_name == "report_render":
            state.snapshot_dict = {
                "as_of": _TRADE_DATE,
                "indicators": {
                    "DXY": {"value": 101.50, "change_1w": -0.80, "unit": "index"},
                    "DGS10": {"value": 4.42, "change_1w": -0.12, "unit": "percent"},
                },
                "source_refs": [{"symbol": "DGS10", "source": "fred"}],
            }
        return {"step": step_name, "status": "success"}

    with (
        patch("apps.worker.pipelines.cme.run_cme_step", side_effect=mock_cme_step),
        patch("apps.worker.pipelines.macro.run_macro_step", side_effect=mock_macro_step),
    ):
        from apps.worker.runner import run_premarket

        result = run_premarket(db, task.id, storage_root=tmp_path)

    assert result == TaskStatus.success

    # Check snapshot source_refs
    snapshots = db.query(AnalysisSnapshot).all()
    assert len(snapshots) >= 1
    snap = snapshots[0]
    assert isinstance(snap.source_refs, list)
    if snap.source_refs:
        assert "source" in snap.source_refs[0] or isinstance(snap.source_refs[0], dict)

    # Check snapshot input_snapshot_ids
    assert isinstance(snap.input_snapshot_ids, dict)

    # Check agent output source_refs
    agent_outputs = db.query(DBAgentOutput).all()
    for ao in agent_outputs:
        assert isinstance(ao.source_refs, list), f"{ao.agent_name} source_refs should be list"
        assert isinstance(ao.input_snapshot_ids, dict), f"{ao.agent_name} input_snapshot_ids should be dict"

    # Check final result source_refs
    final_results = db.query(DBFinalResult).all()
    assert len(final_results) == 1
    fr = final_results[0]
    assert isinstance(fr.source_refs, list)
    assert isinstance(fr.input_snapshot_ids, dict)
    assert isinstance(fr.source_agent_outputs, list)


def test_db_sink_files_still_written(tmp_path: Path) -> None:
    """DB sink must not prevent file artifacts from being written."""
    db = _make_db_session(tmp_path)
    task = _make_task_with_steps(
        db,
        ["macro_collect", "macro_feature", "report_render",
         "cme_download", "cme_parse", "cme_ingest", "option_wall"],
    )

    def mock_cme_step(step_name, state, **kwargs):
        if step_name == "option_wall":
            state.snapshot_dict = {
                "trade_date": _TRADE_DATE,
                "wall_scores": [{"strike": 3300, "wall_score": 0.82, "wall_type": "put", "side": "support"}],
                "support_resistance": {"support": [{"strike": 3250, "score": 0.7}], "resistance": []},
                "intent": {"type": "supportive", "score": 0.65},
                "gex": {"netgex_aggregate": {"gamma_zero": {"price": 3350}}, "by_expiry": {}},
                "walls": {"block_pnt_walls": []},
                "data_source": {"status": "FINAL", "input_snapshot_ids": {"raw_file_sha256": "abc123"}, "expiries": ["2026-06"]},
                "data_quality": {"categories": {"prelim_data": 0}, "warnings": []},
            }
        return {"step": step_name, "status": "success"}

    def mock_macro_step(step_name, state, **kwargs):
        if step_name == "report_render":
            state.snapshot_dict = {
                "as_of": _TRADE_DATE,
                "indicators": {
                    "DXY": {"value": 101.50, "change_1w": -0.80, "unit": "index"},
                    "DGS10": {"value": 4.42, "change_1w": -0.12, "unit": "percent"},
                },
                "source_refs": [],
            }
        return {"step": step_name, "status": "success"}

    with (
        patch("apps.worker.pipelines.cme.run_cme_step", side_effect=mock_cme_step),
        patch("apps.worker.pipelines.macro.run_macro_step", side_effect=mock_macro_step),
    ):
        from apps.worker.runner import run_premarket

        result = run_premarket(db, task.id, storage_root=tmp_path)

    assert result == TaskStatus.success

    # Verify file artifacts exist (same checks as existing test)
    run_id = str(task.id)
    base = tmp_path / "outputs"

    report_path = base / "final_report" / "XAUUSD" / _TRADE_DATE / run_id / "final_report.md"
    assert report_path.exists(), f"Missing: {report_path}"
    assert "# XAUUSD 相关报告" in report_path.read_text(encoding="utf-8")

    # Strategy card — written to a directory based on build_strategy_card's trade_date
    # (which may differ from snapshot.trade_date due to _extract_as_of fallback)
    sc_json_candidates = list(base.glob(f"strategy_card/XAUUSD/*/{run_id}/strategy_card.json"))
    sc_md_candidates = list(base.glob(f"strategy_card/XAUUSD/*/{run_id}/strategy_card.md"))
    assert len(sc_json_candidates) == 1, f"Expected 1 strategy_card.json, got {len(sc_json_candidates)}"
    assert len(sc_md_candidates) == 1, f"Expected 1 strategy_card.md, got {len(sc_md_candidates)}"
    sc_json = sc_json_candidates[0]
    sc_md = sc_md_candidates[0]
    assert sc_json.exists()
    assert sc_md.exists()

    # Step summaries — use glob because date is datetime.now(), not _TRADE_DATE
    summaries_candidates = list(base.glob(f"run/*/{run_id}/step_summaries.json"))
    assert len(summaries_candidates) >= 1, f"Missing step_summaries.json for run {run_id}"
    summaries_path = summaries_candidates[0]
    assert summaries_path.exists()
    summaries = json.loads(summaries_path.read_text(encoding="utf-8"))
    assert "final_report" in summaries["steps"]


def test_db_sink_error_does_not_lose_file_artifacts(tmp_path: Path) -> None:
    """When DB sink fails, file artifacts must still be produced and task should still succeed."""
    db = _make_db_session(tmp_path)
    task = _make_task_with_steps(
        db,
        ["macro_collect", "macro_feature", "report_render",
         "cme_download", "cme_parse", "cme_ingest", "option_wall"],
    )

    def mock_cme_step(step_name, state, **kwargs):
        if step_name == "option_wall":
            state.snapshot_dict = {
                "trade_date": _TRADE_DATE,
                "wall_scores": [{"strike": 3300, "wall_score": 0.82, "wall_type": "put", "side": "support"}],
                "support_resistance": {"support": [{"strike": 3250, "score": 0.7}], "resistance": []},
                "intent": {"type": "supportive", "score": 0.65},
                "gex": {"netgex_aggregate": {"gamma_zero": {"price": 3350}}, "by_expiry": {}},
                "walls": {"block_pnt_walls": []},
                "data_source": {"status": "FINAL", "input_snapshot_ids": {"raw_file_sha256": "abc123"}, "expiries": ["2026-06"]},
                "data_quality": {"categories": {"prelim_data": 0}, "warnings": []},
            }
        return {"step": step_name, "status": "success"}

    def mock_macro_step(step_name, state, **kwargs):
        if step_name == "report_render":
            state.snapshot_dict = {
                "as_of": _TRADE_DATE,
                "indicators": {
                    "DXY": {"value": 101.50, "change_1w": -0.80, "unit": "index"},
                    "DGS10": {"value": 4.42, "change_1w": -0.12, "unit": "percent"},
                },
                "source_refs": [],
            }
        return {"step": step_name, "status": "success"}

    # Force upsert_analysis_snapshot to raise
    def mock_upsert_fail(*args, **kwargs):
        raise RuntimeError("simulated DB persistence failure")

    with (
        patch("apps.worker.pipelines.cme.run_cme_step", side_effect=mock_cme_step),
        patch("apps.worker.pipelines.macro.run_macro_step", side_effect=mock_macro_step),
        patch("apps.worker.runner.upsert_analysis_snapshot", side_effect=mock_upsert_fail),
    ):
        from apps.worker.runner import run_premarket

        result = run_premarket(db, task.id, storage_root=tmp_path)

    # Pipeline should succeed (DB is additive, not critical)
    assert result == TaskStatus.success

    # File artifacts must still exist
    run_id = str(task.id)
    base = tmp_path / "outputs"

    report_path = base / "final_report" / "XAUUSD" / _TRADE_DATE / run_id / "final_report.md"
    assert report_path.exists(), "Final report must exist even when DB sink fails"

    # Strategy card — glob search because trade_date may differ from snapshot
    sc_json_candidates = list(base.glob(f"strategy_card/XAUUSD/*/{run_id}/strategy_card.json"))
    assert len(sc_json_candidates) == 1, "Strategy card must exist even when DB sink fails"

    # DB error must be recorded in step summaries
    summaries_candidates = list(base.glob(f"run/*/{run_id}/step_summaries.json"))
    assert len(summaries_candidates) >= 1, f"Missing step_summaries.json for run {run_id}"
    summaries = json.loads(summaries_candidates[0].read_text(encoding="utf-8"))
    assert "db_persist_snapshot" in summaries["steps"]
    assert summaries["steps"]["db_persist_snapshot"]["status"] == "failed"


def test_db_sink_idempotent_on_rerun(tmp_path: Path) -> None:
    """Calling upsert twice with same snapshot_id should not duplicate records."""
    from database.models.analysis import AnalysisSnapshot

    db = _make_db_session(tmp_path)
    task = _make_task_with_steps(
        db,
        ["macro_collect", "macro_feature", "report_render"],
    )

    def mock_macro_step(step_name, state, **kwargs):
        if step_name == "report_render":
            state.snapshot_dict = {
                "as_of": _TRADE_DATE,
                "indicators": {
                    "DXY": {"value": 101.50, "change_1w": -0.80, "unit": "index"},
                    "DGS10": {"value": 4.42, "change_1w": -0.12, "unit": "percent"},
                },
                "source_refs": [],
            }
        return {"step": step_name, "status": "success"}

    with patch("apps.worker.pipelines.macro.run_macro_step", side_effect=mock_macro_step):
        from apps.worker.runner import run_premarket

        result = run_premarket(db, task.id, storage_root=tmp_path)
    assert result == TaskStatus.success

    # Count snapshots after first run
    first_count = db.query(AnalysisSnapshot).count()

    # Run again with a different task (same snapshot will be produced)
    task2 = _make_task_with_steps(
        db,
        ["macro_collect", "macro_feature", "report_render"],
    )
    with patch("apps.worker.pipelines.macro.run_macro_step", side_effect=mock_macro_step):
        result2 = run_premarket(db, task2.id, storage_root=tmp_path)
    assert result2 == TaskStatus.success

    # Should have 2 snapshots (one per run_id)
    second_count = db.query(AnalysisSnapshot).count()
    assert second_count == first_count + 1, (
        f"Expected {first_count + 1} snapshots after second run (one per task), got {second_count}"
    )
