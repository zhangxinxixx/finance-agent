from __future__ import annotations

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
        session.query(TaskStep)
        .filter(TaskStep.task_run_id == uuid.UUID(run_id))
        .order_by(TaskStep.step_order)
        .all()
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
        step.status
        for step in session.query(TaskStep).filter(TaskStep.task_run_id == uuid.UUID(run_id)).all()
    } == {StepStatus.success}
    assert session.query(TaskRun).filter(TaskRun.id == uuid.UUID(run_id)).count() == 1
