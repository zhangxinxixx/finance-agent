from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.runtime.state_machine import (
    ACTIVE_DAGSTER_RUN_STATUSES,
    derive_task_run_status,
    map_dagster_status_to_task_status,
    transition_task_run,
    transition_task_step,
)
from database.models.execution import ExecutionEvent, ensure_execution_tables
from database.models.task import StepStatus, TaskRun, TaskStatus, TaskStep, ensure_task_tables


def _make_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_task_tables(engine)
    ensure_execution_tables(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return factory()


def test_map_dagster_status_to_task_status_uses_shared_active_set() -> None:
    for status in ACTIVE_DAGSTER_RUN_STATUSES:
        assert map_dagster_status_to_task_status(status) == TaskStatus.running.value
    assert map_dagster_status_to_task_status("SUCCESS") == TaskStatus.success.value
    assert map_dagster_status_to_task_status("FAILURE") == TaskStatus.failed.value
    assert map_dagster_status_to_task_status("OTHER") == TaskStatus.pending.value


def test_derive_task_run_status_handles_partial_and_blocked_rollups() -> None:
    assert derive_task_run_status([StepStatus.success, StepStatus.failed]) == TaskStatus.partial_success
    assert derive_task_run_status([StepStatus.blocked, StepStatus.blocked]) == TaskStatus.blocked
    assert derive_task_run_status([StepStatus.success, StepStatus.success], has_partial_signal=True) == (
        TaskStatus.partial_success
    )


def test_transition_helpers_emit_execution_events() -> None:
    session = _make_session()
    run = TaskRun(name="premarket", status=TaskStatus.pending)
    session.add(run)
    session.flush()
    step = TaskStep(task_run_id=run.id, name="collect_macro", status=StepStatus.pending, step_order=0)
    session.add(step)
    session.flush()

    transition_task_run(session, run, TaskStatus.running, source="worker", reason="worker_started")
    transition_task_step(
        session,
        step,
        StepStatus.blocked,
        source="worker",
        reason="upstream_failed",
        blocked_reason="macro source unavailable",
        retryable=False,
    )
    transition_task_run(
        session,
        run,
        TaskStatus.stale,
        source="api",
        reason="active_timeout_exceeded",
        error_message="run timed out",
    )
    session.commit()

    events = session.query(ExecutionEvent).order_by(ExecutionEvent.created_at.asc()).all()
    event_types = [event.event_type for event in events]

    assert "RUN_STARTED" in event_types
    assert "RUN_STATUS_CHANGED" in event_types
    assert "TASK_STATUS_CHANGED" in event_types
    assert "TASK_BLOCKED" in event_types
    assert "RUN_FINISHED" in event_types
    assert "RUN_MARKED_STALE" in event_types


def test_transition_helpers_emit_run_and_step_lifecycle_events() -> None:
    session = _make_session()
    run = TaskRun(name="premarket", status=TaskStatus.pending)
    session.add(run)
    session.flush()
    step = TaskStep(task_run_id=run.id, name="collect_macro", status=StepStatus.pending, step_order=0)
    session.add(step)
    session.flush()

    transition_task_run(session, run, TaskStatus.running, source="worker", reason="worker_started")
    transition_task_step(session, step, StepStatus.running, source="worker", reason="step_started")
    transition_task_step(session, step, StepStatus.success, source="worker", reason="step_finished")
    transition_task_run(session, run, TaskStatus.success, source="worker", reason="worker_finished")
    session.commit()

    events = session.query(ExecutionEvent).order_by(ExecutionEvent.created_at.asc()).all()
    event_types = [event.event_type for event in events]

    assert "RUN_STARTED" in event_types
    assert "TASK_STARTED" in event_types
    assert "TASK_FINISHED" in event_types
    assert "RUN_FINISHED" in event_types


def test_transition_helpers_do_not_repeat_terminal_lifecycle_events_for_reason_only_update() -> None:
    session = _make_session()
    run = TaskRun(name="premarket", status=TaskStatus.pending)
    session.add(run)
    session.flush()

    transition_task_run(session, run, TaskStatus.stale, source="scheduler", reason="timeout")
    transition_task_run(session, run, TaskStatus.stale, source="api", reason="operator_ack")
    session.commit()

    events = session.query(ExecutionEvent).order_by(ExecutionEvent.created_at.asc()).all()
    event_types = [event.event_type for event in events]

    assert event_types.count("RUN_STATUS_CHANGED") == 2
    assert event_types.count("RUN_FINISHED") == 1
    assert event_types.count("RUN_MARKED_STALE") == 2
