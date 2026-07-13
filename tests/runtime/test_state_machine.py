from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import apps.runtime.state_machine as state_machine
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


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        (TaskStatus.success, TaskStatus.running),
        (TaskStatus.success, TaskStatus.failed),
        (TaskStatus.partial_success, TaskStatus.pending),
        (TaskStatus.degraded, TaskStatus.running),
        (TaskStatus.cancelled, TaskStatus.success),
        (TaskStatus.failed, TaskStatus.running),
    ],
)
def test_transition_task_run_rejects_closed_terminal_state_rewrites(
    from_status: TaskStatus,
    to_status: TaskStatus,
) -> None:
    session = _make_session()
    run = TaskRun(name="premarket", status=from_status)
    session.add(run)
    session.flush()

    with pytest.raises(ValueError, match=f"{from_status.value} -> {to_status.value}"):
        transition_task_run(session, run, to_status, source="test")

    assert run.status == from_status
    assert run.started_at is None
    assert run.ended_at is None
    assert session.query(ExecutionEvent).count() == 0


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        (StepStatus.success, StepStatus.running),
        (StepStatus.success, StepStatus.failed),
        (StepStatus.skipped, StepStatus.running),
        (StepStatus.failed, StepStatus.running),
    ],
)
def test_transition_task_step_rejects_closed_terminal_state_rewrites(
    from_status: StepStatus,
    to_status: StepStatus,
) -> None:
    session = _make_session()
    run = TaskRun(name="premarket", status=TaskStatus.running)
    session.add(run)
    session.flush()
    step = TaskStep(task_run_id=run.id, name="collect_macro", status=from_status, step_order=0)
    session.add(step)
    session.flush()

    with pytest.raises(ValueError, match=f"{from_status.value} -> {to_status.value}"):
        transition_task_step(session, step, to_status, source="test")

    assert step.status == from_status
    assert step.started_at is None
    assert step.finished_at is None
    assert session.query(ExecutionEvent).count() == 0


def test_blocked_run_and_step_can_resume_running() -> None:
    session = _make_session()
    run = TaskRun(name="premarket", status=TaskStatus.blocked)
    session.add(run)
    session.flush()
    step = TaskStep(task_run_id=run.id, name="collect_macro", status=StepStatus.blocked, step_order=0)
    session.add(step)
    session.flush()

    assert transition_task_run(session, run, TaskStatus.running, source="test") == TaskStatus.running
    assert transition_task_step(session, step, StepStatus.running, source="test") == StepStatus.running


def test_retry_task_run_is_the_only_failed_run_recovery_path() -> None:
    session = _make_session()
    previous_started_at = datetime(2026, 7, 13, 1, 0, tzinfo=timezone.utc)
    previous_ended_at = datetime(2026, 7, 13, 1, 5, tzinfo=timezone.utc)
    run = TaskRun(
        name="premarket",
        status=TaskStatus.failed,
        started_at=previous_started_at,
        ended_at=previous_ended_at,
        progress=1.0,
        error="network timeout",
        error_summary="network timeout",
    )
    session.add(run)
    session.flush()

    status = state_machine.retry_task_run(session, run, source="api", reason="operator_retry")

    assert status == TaskStatus.running
    assert run.status == TaskStatus.running
    assert run.started_at is not None
    assert run.started_at != previous_started_at
    assert run.ended_at is None
    assert run.progress == 0.0
    assert run.error is None
    assert run.error_summary is None


def test_retry_task_step_is_the_only_failed_step_recovery_path() -> None:
    session = _make_session()
    previous_started_at = datetime(2026, 7, 13, 1, 0, tzinfo=timezone.utc)
    previous_finished_at = datetime(2026, 7, 13, 1, 5, tzinfo=timezone.utc)
    run = TaskRun(name="premarket", status=TaskStatus.running)
    session.add(run)
    session.flush()
    step = TaskStep(
        task_run_id=run.id,
        name="collect_macro",
        status=StepStatus.failed,
        started_at=previous_started_at,
        finished_at=previous_finished_at,
        error="network timeout",
        error_type="network_timeout",
        retryable=True,
        retry_count=2,
        step_order=0,
    )
    session.add(step)
    session.flush()

    status = state_machine.retry_task_step(session, step, source="worker", reason="scheduled_retry")

    assert status == StepStatus.running
    assert step.status == StepStatus.running
    assert step.started_at is not None
    assert step.started_at != previous_started_at
    assert step.finished_at is None
    assert step.error is None
    assert step.error_type is None
    assert step.retry_count == 3


def test_retry_helpers_reject_non_failed_or_non_retryable_records() -> None:
    session = _make_session()
    run = TaskRun(name="premarket", status=TaskStatus.success)
    session.add(run)
    session.flush()
    step = TaskStep(
        task_run_id=run.id,
        name="collect_macro",
        status=StepStatus.failed,
        retryable=False,
        step_order=0,
    )
    session.add(step)
    session.flush()

    with pytest.raises(ValueError, match="Only failed task runs can be retried"):
        state_machine.retry_task_run(session, run, source="api")
    with pytest.raises(ValueError, match="not retryable"):
        state_machine.retry_task_step(session, step, source="worker")
