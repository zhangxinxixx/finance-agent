import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.worker.composite_analysis_pipeline import run_composite_analysis_pipeline
from tests.analysis.test_input_validation import valid_snapshot


def test_direct_composite_missing_spot_only_writes_run_bound_diagnostic(tmp_path, monkeypatch):
    snapshot = valid_snapshot()
    snapshot["daily_research"]["execution_timeframes"] = {}
    before = deepcopy(snapshot)
    def forbidden(*args, **kwargs):
        raise AssertionError("model/domain analysis must not run")
    monkeypatch.setattr("apps.worker.composite_analysis_pipeline.analyze_macro_liquidity", forbidden)
    summaries, outputs = run_composite_analysis_pipeline(storage_root=tmp_path, snapshot=snapshot, run_id=snapshot["run_id"])
    assert snapshot == before
    assert outputs["report_result"] is outputs["card_result"] is outputs["strategy_card"] is None
    assert summaries["final_report"]["status"] == "blocked"
    assert not list(tmp_path.rglob("final_report.md"))
    assert not list(tmp_path.rglob("strategy_card.json"))
    diagnostic = json.loads(Path(outputs["diagnostic_result"]["paths"][0]).read_text())
    assert diagnostic["run_id"] == snapshot["run_id"]
    assert diagnostic["snapshot_id"] == snapshot["snapshot_id"]
    assert "no_trusted_current_spot_observation" in diagnostic["reason_codes"]
    assert "scenarios" not in diagnostic and "direction" not in diagnostic


def test_snapshot_agent_validation_and_diagnostic_persist_in_existing_tables(tmp_path):
    from apps.worker.db_persistence import db_persist_analysis_snapshot, db_persist_agent_outputs
    from apps.worker.artifact_registration import register_composite_output_artifacts
    from database.models.analysis import AnalysisBase, AnalysisSnapshot, AgentOutput
    from database.models.execution import RunArtifact, ensure_execution_tables
    from database.models.task import Base, TaskRun, TaskStep, StepStatus

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    AnalysisBase.metadata.create_all(engine)
    with Session(engine) as db:
        ensure_execution_tables(db)
        task = TaskRun(name="premarket")
        db.add(task)
        db.flush()
        step = TaskStep(task_run_id=task.id, name="report_render", status=StepStatus.blocked)
        db.add(step)
        db.commit()
        snapshot = valid_snapshot()
        snapshot["run_id"] = str(task.id)
        snapshot["daily_research"]["execution_timeframes"] = {}
        _, outputs = run_composite_analysis_pipeline(storage_root=tmp_path, snapshot=snapshot, run_id=str(task.id))
        derived = outputs["analysis_snapshot"]
        path = tmp_path / "derived_snapshot.json"
        path.write_text(json.dumps(derived))
        db_persist_analysis_snapshot(db, derived, path)
        db_persist_agent_outputs(db, derived, outputs["agents"], str(task.id))
        register_composite_output_artifacts(db, run_id=str(task.id), steps=[step], composite_outputs=outputs, analysis_snapshot=derived)
        db.commit()
        assert db.query(AnalysisSnapshot).one().payload["input_validation"]["status"] == "blocked"
        assert db.query(AgentOutput).one().payload["input_payload"]["input_validation"]["can_analyze"] is False
        artifacts = db.query(RunArtifact).all()
        assert len(artifacts) == 1
        assert Path(artifacts[0].file_path).name == "research_diagnostic.json"
        assert artifacts[0].artifact_metadata["output_mode"] == "diagnostic"
    engine.dispose()


def test_real_partial_spot_successful_model_can_generate_observation(tmp_path, monkeypatch):
    import apps.analysis.agents.research_synthesis as synthesis
    calls = []
    def fake_gateway(gateway, **kwargs):
        calls.append(kwargs)
        return {"content": json.dumps({"dominant_factor": "仅已收盘现货价格可用，其他依赖结论待验证。",
            "counter_evidence": [], "state_limitations": ["宏观模块缺失，不能确认宏观方向"],
            "convergence_transition": [], "evidence_ids": [kwargs["audit_context"]["input_payload"]["evidence_catalog"][0]["evidence_id"]]}), "model": "offline-fixture"}
    monkeypatch.setattr(synthesis, "_call_gateway", fake_gateway)
    snapshot = valid_snapshot(tmp_path)
    _, outputs = run_composite_analysis_pipeline(storage_root=tmp_path, snapshot=snapshot, run_id=snapshot["run_id"])
    assert calls
    assert outputs["report_result"] is not None
    assert outputs["strategy_card"] is not None
    assert any(Path(p).name == "final_report.md" for p in outputs["report_result"]["paths"])
    assert outputs["input_validation"]["domains"]["spot"]["completed_timeframes"] == ["15m"]


def test_registry_refuses_success_flag_with_failed_model_and_existing_file(tmp_path):
    from apps.worker.report_registry_sink import register_composite_report_registry_entries
    from database.models.report import ReportBase, ReportItem
    from tests.analysis.test_research_synthesis import _output
    engine = create_engine("sqlite://")
    ReportBase.metadata.create_all(engine)
    path = tmp_path / "final_report.md"
    path.write_text("historical report")
    with Session(engine) as db:
        register_composite_report_registry_entries(db, run_id="test-run", analysis_snapshot=valid_snapshot(),
            composite_outputs={"agents": {"coordinator_agent": _output(payload={"research_synthesis": {"status": "rule_fallback"}})},
                "agent_loop_decision": SimpleNamespace(publish_allowed=True), "report_result": {"paths": [str(path)]}})
        assert db.query(ReportItem).count() == 0
        assert path.read_text() == "historical report"
    engine.dispose()
