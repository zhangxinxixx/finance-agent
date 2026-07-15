"""Bridge Dagster run lifecycle into the canonical task_runs read model."""

from __future__ import annotations

import uuid
from typing import Any

from dagster import In, Nothing, Out, failure_hook, op

from apps.premarket import materialize_premarket_task_steps
from apps.runtime.state_machine import transition_task_run, transition_task_step
from database.models.task import StepStatus, TaskRun, TaskStatus, TaskStep


@op(
    required_resource_keys={"db_session"},
    out=Out(Nothing),
    tags={"pipeline": "premarket", "step": "task_run_init"},
)
def premarket_task_run_init_op(context) -> None:
    """Create the TaskRun before any collector can register run artifacts."""

    _, missing_step_count = ensure_premarket_task_run(
        context.resources.db_session,
        run_id=context.run_id,
    )
    context.log.info(
        "TaskRun initialized before collectors: run_id=%s steps_added=%s",
        context.run_id,
        missing_step_count,
    )


def ensure_premarket_task_run(db: Any, *, run_id: str) -> tuple[TaskRun, int]:
    """Idempotently materialize the canonical DB lineage for one Dagster run."""

    run_uuid = uuid.UUID(run_id)
    run = db.query(TaskRun).filter(TaskRun.id == run_uuid).first()
    if run is None:
        run = TaskRun(
            id=run_uuid,
            name="premarket",
            task_type="premarket",
            status=TaskStatus.pending,
        )
        db.add(run)
        db.flush()

    existing_steps = {
        step.name
        for step in db.query(TaskStep).filter(TaskStep.task_run_id == run_uuid).all()
    }
    missing_steps = [
        step
        for step in materialize_premarket_task_steps(run_uuid)
        if step.name not in existing_steps
    ]
    db.add_all(missing_steps)
    if run.status in {TaskStatus.pending, TaskStatus.running}:
        transition_task_run(
            db,
            run,
            TaskStatus.running,
            source="dagster",
            reason="premarket_job_started",
            progress=0.0,
        )
    db.commit()
    return run, len(missing_steps)


@op(
    required_resource_keys={"db_session"},
    ins={"analysis_result": In(Any)},
    out=Out(Nothing),
    tags={"pipeline": "premarket", "step": "task_run_complete"},
)
def premarket_task_run_complete_op(context, analysis_result: Any) -> None:
    """Close the TaskRun after every canonical Dagster dependency succeeded."""

    del analysis_result
    complete_premarket_task_run(context.resources.db_session, run_id=context.run_id)
    context.log.info("TaskRun completed: run_id=%s", context.run_id)


def complete_premarket_task_run(db: Any, *, run_id: str) -> TaskRun:
    """Mark the canonical TaskRun and steps successful after graph completion."""

    run_uuid = uuid.UUID(run_id)
    run = db.query(TaskRun).filter(TaskRun.id == run_uuid).first()
    if run is None:
        raise RuntimeError(f"TaskRun missing at premarket completion: {run_id}")

    steps = db.query(TaskStep).filter(TaskStep.task_run_id == run_uuid).all()
    for step in steps:
        if step.status in {StepStatus.pending, StepStatus.running, StepStatus.blocked}:
            transition_task_step(
                db,
                step,
                StepStatus.success,
                source="dagster",
                reason="premarket_job_completed",
            )
    transition_task_run(
        db,
        run,
        TaskStatus.success,
        source="dagster",
        reason="premarket_job_completed",
        progress=1.0,
    )
    db.commit()
    return run


@failure_hook(required_resource_keys={"db_session"})
def premarket_task_run_failure_hook(context) -> None:
    """Mirror a Dagster op failure into TaskRun without masking the root error."""

    db = context.resources.db_session
    try:
        run_uuid = uuid.UUID(context.run_id)
        run = db.query(TaskRun).filter(TaskRun.id == run_uuid).first()
        if run is None or run.status not in {TaskStatus.pending, TaskStatus.running}:
            return
        error_message = str(context.op_exception or "Dagster premarket op failed")
        transition_task_run(
            db,
            run,
            TaskStatus.failed,
            source="dagster",
            reason=f"op_failed:{context.op.name}",
            error_message=error_message,
        )
        db.commit()
    except Exception:
        db.rollback()
        context.log.exception("Failed to mirror Dagster failure into TaskRun")
