from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import Mock

from dagster import build_op_context
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from database.models.analysis import AnalysisBase
from database.models.execution import ExecutionBase
from database.models.report import ReportItem, ensure_report_tables
from database.models.task import Base, TaskRun, TaskStatus
from dagster_finance.ops.agents import _persist_canonical_composite_outputs
from dagster_finance.ops.task_run_lifecycle import complete_premarket_task_run


def test_blocked_research_without_card_is_persisted_without_report_or_false_success(tmp_path):
    """A diagnostic-only composite must complete as blocked, without a fake card."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    AnalysisBase.metadata.create_all(engine)
    ExecutionBase.metadata.create_all(engine)
    ensure_report_tables(engine)
    run_id = str(uuid.uuid4())
    snapshot = {
        "asset": "XAUUSD", "trade_date": "2026-10-05", "run_id": run_id,
        "snapshot_id": f"XAUUSD:2026-10-05:{run_id}",
        "snapshot_time": "2026-10-05T04:42:33+00:00", "source_refs": [],
        "daily_research": {"schema_version": "daily_research.v1"},
        "input_validation": {"schema_version": "analysis_input_validation.v1",
                             "can_analyze": False, "status": "blocked"},
    }
    outputs = {
        "agents": {}, "strategy_card": None, "report_result": None, "card_result": None,
        "agent_loop_decision": {"publish_allowed": False},
    }
    with Session(engine) as db:
        run = TaskRun(id=uuid.UUID(run_id), name="premarket", task_type="premarket",
                      status=TaskStatus.running, trade_date="2026-10-05")
        db.add(run)
        db.commit()
        context = SimpleNamespace(run_id=run_id, resources=SimpleNamespace(db_session=db), log=Mock())
        _persist_canonical_composite_outputs(context, snapshot=snapshot, composite_outputs=outputs)
        complete_premarket_task_run(db, run_id=run_id, analysis_result={
            "output_mode": "blocked",
            "quality_gate_decision": {"reason_codes": ["no_trusted_current_spot_observation"]},
        })
        assert run.status == TaskStatus.blocked
        assert run.error_summary == "no_trusted_current_spot_observation"
        assert db.scalars(select(ReportItem)).all() == []


def test_diagnostic_output_is_returned_as_blocked_to_task_lifecycle(tmp_path, monkeypatch):
    from dagster_finance.ops import agents

    derived = {"input_validation": {"can_analyze": False}}
    outputs = {"analysis_snapshot": derived, "agents": {}, "report_result": None,
               "card_result": None, "quality_gate_decision": None, "agent_loop_decision": None,
               "diagnostic_result": {"status": "blocked"}}
    summaries = {"final_report": {"status": "blocked", "output_mode": "diagnostic",
                                  "reason_codes": ["no_trusted_current_spot_observation"]}}
    monkeypatch.setattr("apps.worker.composite_analysis_pipeline.run_composite_analysis_pipeline",
                        lambda **kw: (summaries, outputs))
    monkeypatch.setattr(agents, "_gold_policy_runtime_kwargs", lambda **kw: ({}, {}))
    persist = Mock()
    monkeypatch.setattr(agents, "_persist_canonical_composite_outputs", persist)
    with build_op_context(resources={"db_session": None}) as context:
        result = agents.canonical_composite_analysis_op(context,
            agents.AgentConfig(storage_root=str(tmp_path)),
            {"snapshot_time": "2026-10-05T04:42:33+00:00"}, {"decision": "allow"})
    assert result["output_mode"] == "blocked"
    assert result["quality_gate_decision"]["reason_codes"] == ["no_trusted_current_spot_observation"]
    assert result["input_validation"]["can_analyze"] is False
    assert result["report_result"] is None
    assert persist.call_args.kwargs["snapshot"] is derived
