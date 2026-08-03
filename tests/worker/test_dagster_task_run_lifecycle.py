from __future__ import annotations

import json
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.premarket import PREMARKET_STEP_ORDER
from database.models.task import StepStatus, TaskRun, TaskStatus, TaskStep, ensure_task_tables
from dagster_finance.ops.task_run_lifecycle import (
    complete_premarket_task_run,
    ensure_premarket_task_run,
)


def test_dagster_task_run_lifecycle_materializes_lineage_before_completion() -> None:
    engine = create_engine("sqlite://")
    ensure_task_tables(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    run_id = str(uuid.uuid4())

    run, added = ensure_premarket_task_run(session, run_id=run_id)
    _, added_again = ensure_premarket_task_run(session, run_id=run_id)

    steps = (
        session.query(TaskStep).filter(TaskStep.task_run_id == uuid.UUID(run_id)).order_by(TaskStep.step_order).all()
    )
    assert run.status == TaskStatus.running
    assert added == len(PREMARKET_STEP_ORDER)
    assert added_again == 0
    assert [step.name for step in steps] == list(PREMARKET_STEP_ORDER)
    assert all(step.status == StepStatus.pending for step in steps)

    completed = complete_premarket_task_run(session, run_id=run_id)

    session.refresh(completed)
    assert completed.status == TaskStatus.success
    assert completed.progress == 1.0
    assert completed.ended_at is not None
    assert {
        step.status for step in session.query(TaskStep).filter(TaskStep.task_run_id == uuid.UUID(run_id)).all()
    } == {StepStatus.success}
    assert session.query(TaskRun).filter(TaskRun.id == uuid.UUID(run_id)).count() == 1


def test_dagster_task_run_lifecycle_preserves_blocked_composite_outcome() -> None:
    engine = create_engine("sqlite://")
    ensure_task_tables(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    run_id = str(uuid.uuid4())
    ensure_premarket_task_run(session, run_id=run_id)

    completed = complete_premarket_task_run(
        session,
        run_id=run_id,
        analysis_result={
            "output_mode": "blocked",
            "premarket_readiness_gate": {
                "decision": "block",
                "reason_code": "downstream_readiness_missing",
            },
        },
    )

    session.refresh(completed)
    steps = session.query(TaskStep).filter(TaskStep.task_run_id == uuid.UUID(run_id)).all()
    strategy_step = next(step for step in steps if step.name == "strategy_card")
    upstream_steps = [step for step in steps if step.name != "strategy_card"]

    assert completed.status == TaskStatus.blocked
    assert completed.error_summary == "downstream_readiness_missing"
    assert completed.progress == len(upstream_steps) / len(steps)
    assert all(step.status == StepStatus.success for step in upstream_steps)
    assert strategy_step.status == StepStatus.blocked
    assert strategy_step.blocked_reason == "downstream_readiness_missing"
    assert json.loads(strategy_step.output_json) == {
        "output_mode": "blocked",
        "publish_allowed": False,
        "reason_code": "downstream_readiness_missing",
    }


def test_dagster_task_run_lifecycle_persists_limited_gold_daily_report_authority() -> None:
    engine = create_engine("sqlite://")
    ensure_task_tables(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    run_id = str(uuid.uuid4())
    run, _ = ensure_premarket_task_run(session, run_id=run_id)
    run.trade_date = "2026-08-12"
    run.snapshot_id = f"XAUUSD:2026-08-12:{run_id}"
    session.commit()

    completed = complete_premarket_task_run(
        session,
        run_id=run_id,
        analysis_result={
            "output_mode": "blocked",
            "premarket_readiness_gate": {
                "decision": "block",
                "readiness": "blocked",
                "reason_code": "downstream_readiness_not_ready",
                "can_run_daily_report": True,
                "can_run_full_analysis": False,
                "source_ref": "monitoring/2026-08-12/downstream_readiness.json",
                "observed_at": "2026-08-12T01:00:00+00:00",
            },
        },
    )

    strategy_step = session.query(TaskStep).filter_by(task_run_id=completed.id, name="strategy_card").one()
    output = json.loads(strategy_step.output_json)
    assert completed.status == TaskStatus.blocked
    assert output["publish_allowed"] is False
    assert output["gold_daily_report_authority"] == {
        "schema_version": "gold_daily_report_premarket_authority.v1",
        "authority_scope": "gold_daily_report_only",
        "run_id": run_id,
        "snapshot_id": f"XAUUSD:2026-08-12:{run_id}",
        "trade_date": "2026-08-12",
        "readiness_decision": "block",
        "readiness": "blocked",
        "reason_code": "downstream_readiness_not_ready",
        "can_run_daily_report": True,
        "can_run_full_analysis": False,
        "publish_allowed": False,
        "source_ref": "monitoring/2026-08-12/downstream_readiness.json",
        "observed_at": "2026-08-12T01:00:00+00:00",
    }


def test_dagster_task_run_lifecycle_does_not_issue_receipt_for_unbound_readiness() -> None:
    engine = create_engine("sqlite://")
    ensure_task_tables(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    run_id = str(uuid.uuid4())
    run, _ = ensure_premarket_task_run(session, run_id=run_id)
    run.trade_date = "2026-08-12"
    run.snapshot_id = f"XAUUSD:2026-08-12:{run_id}"
    session.commit()

    completed = complete_premarket_task_run(
        session,
        run_id=run_id,
        analysis_result={
            "output_mode": "blocked",
            "premarket_readiness_gate": {
                "decision": "block",
                "readiness": "blocked",
                "reason_code": "downstream_readiness_not_ready",
                "can_run_daily_report": True,
                "can_run_full_analysis": False,
                "source_ref": "monitoring/another-date/downstream_readiness.json",
                "observed_at": "2026-08-12T01:00:00+00:00",
            },
        },
    )

    strategy_step = session.query(TaskStep).filter_by(task_run_id=completed.id, name="strategy_card").one()
    assert "gold_daily_report_authority" not in json.loads(strategy_step.output_json)
