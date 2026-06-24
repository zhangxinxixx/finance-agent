"""Unified execution state helpers for TaskRun / TaskStep."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from apps.runtime.execution_event_bridge import emit_run_event, emit_task_event
from database.models.task import StepStatus, TaskRun, TaskStatus, TaskStep
from sqlalchemy.orm import Session

ACTIVE_DAGSTER_RUN_STATUSES = frozenset({"QUEUED", "STARTING", "STARTED", "CANCELING"})
_TERMINAL_RUN_STATUSES = {
    TaskStatus.success,
    TaskStatus.partial_success,
    TaskStatus.failed,
    TaskStatus.degraded,
    TaskStatus.blocked,
    TaskStatus.cancelled,
    TaskStatus.stale,
}
_TERMINAL_STEP_STATUSES = {StepStatus.success, StepStatus.failed, StepStatus.skipped, StepStatus.blocked}

_ALLOWED_RUN_TRANSITIONS = {
    TaskStatus.pending: {
        TaskStatus.running,
        TaskStatus.success,
        TaskStatus.failed,
        TaskStatus.partial_success,
        TaskStatus.degraded,
        TaskStatus.blocked,
        TaskStatus.cancelled,
        TaskStatus.stale,
    },
    TaskStatus.running: {
        TaskStatus.pending,
        TaskStatus.success,
        TaskStatus.failed,
        TaskStatus.partial_success,
        TaskStatus.degraded,
        TaskStatus.blocked,
        TaskStatus.cancelled,
        TaskStatus.stale,
    },
    TaskStatus.blocked: {TaskStatus.running, TaskStatus.failed, TaskStatus.success},
    TaskStatus.stale: {TaskStatus.running, TaskStatus.failed, TaskStatus.success},
}
_ALLOWED_STEP_TRANSITIONS = {
    StepStatus.pending: {StepStatus.running, StepStatus.success, StepStatus.failed, StepStatus.skipped, StepStatus.blocked},
    StepStatus.running: {StepStatus.success, StepStatus.failed, StepStatus.skipped, StepStatus.blocked},
    StepStatus.blocked: {StepStatus.pending, StepStatus.running, StepStatus.success, StepStatus.failed, StepStatus.skipped},
    StepStatus.failed: {StepStatus.running},
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def coerce_task_status(value: TaskStatus | str | None) -> TaskStatus:
    if isinstance(value, TaskStatus):
        return value
    normalized = str(value or "").strip().lower()
    try:
        return TaskStatus(normalized)
    except ValueError as exc:
        raise ValueError(f"Unsupported task status: {value}") from exc


def coerce_step_status(value: StepStatus | str | None) -> StepStatus:
    if isinstance(value, StepStatus):
        return value
    normalized = str(value or "").strip().lower()
    try:
        return StepStatus(normalized)
    except ValueError as exc:
        raise ValueError(f"Unsupported step status: {value}") from exc


def map_dagster_status_to_task_status(status: str | None) -> str:
    value = str(status or "").upper()
    if value in ACTIVE_DAGSTER_RUN_STATUSES:
        return TaskStatus.running.value
    if value == "SUCCESS":
        return TaskStatus.success.value
    if value in {"FAILURE", "CANCELED", "CANCELLED"}:
        return TaskStatus.failed.value
    return TaskStatus.pending.value


def derive_task_run_status(
    step_statuses: Iterable[StepStatus | str],
    *,
    has_partial_signal: bool = False,
    has_degraded_signal: bool = False,
) -> TaskStatus:
    statuses = [coerce_step_status(status) for status in step_statuses]
    if not statuses:
        return TaskStatus.pending
    if any(status == StepStatus.running for status in statuses):
        return TaskStatus.running
    if any(status == StepStatus.pending for status in statuses):
        return TaskStatus.pending

    success_like = sum(1 for status in statuses if status in {StepStatus.success, StepStatus.skipped})
    failed = sum(1 for status in statuses if status == StepStatus.failed)
    blocked = sum(1 for status in statuses if status == StepStatus.blocked)

    if failed:
        return TaskStatus.partial_success if success_like or blocked else TaskStatus.failed
    if has_degraded_signal:
        return TaskStatus.degraded
    if has_partial_signal or (success_like and blocked):
        return TaskStatus.partial_success
    if blocked == len(statuses):
        return TaskStatus.blocked
    if success_like:
        return TaskStatus.success
    return TaskStatus.pending


def transition_task_run(
    db: Session,
    run: TaskRun,
    to_status: TaskStatus | str,
    *,
    source: str,
    reason: str | None = None,
    error_message: str | None = None,
    progress: float | None = None,
) -> TaskStatus:
    from_status = coerce_task_status(run.status)
    target = coerce_task_status(to_status)

    if from_status != target:
        allowed = _ALLOWED_RUN_TRANSITIONS.get(from_status)
        if allowed is not None and target not in allowed:
            raise ValueError(f"Invalid task run transition: {from_status.value} -> {target.value}")
        run.status = target

    if target == TaskStatus.running and run.started_at is None:
        run.started_at = _utc_now()
    if target in _TERMINAL_RUN_STATUSES:
        run.ended_at = run.ended_at or _utc_now()
    elif target == TaskStatus.running:
        run.ended_at = None

    if progress is not None:
        run.progress = progress
    if error_message is not None:
        run.error = error_message
        run.error_summary = error_message[:500]

    payload = {
        "from_status": from_status.value,
        "to_status": target.value,
        "source": source,
    }
    if reason:
        payload["reason"] = reason
    if error_message:
        payload["error_message"] = error_message
    if progress is not None:
        payload["progress"] = progress

    if from_status != target or reason or error_message or progress is not None:
        emit_run_event(db, str(run.id), "RUN_STATUS_CHANGED", payload)
        _emit_run_lifecycle_event(db, run, from_status=from_status, to_status=target, payload=payload)
        if target == TaskStatus.stale:
            emit_run_event(db, str(run.id), "RUN_MARKED_STALE", payload)

    return target


def transition_task_step(
    db: Session,
    step: TaskStep,
    to_status: StepStatus | str,
    *,
    source: str,
    reason: str | None = None,
    error_message: str | None = None,
    error_type: str | None = None,
    retryable: bool | None = None,
    blocked_reason: str | None = None,
) -> StepStatus:
    from_status = coerce_step_status(step.status)
    target = coerce_step_status(to_status)

    if from_status != target:
        allowed = _ALLOWED_STEP_TRANSITIONS.get(from_status)
        if allowed is not None and target not in allowed:
            raise ValueError(f"Invalid task step transition: {from_status.value} -> {target.value}")
        step.status = target

    if target == StepStatus.pending and from_status == StepStatus.blocked:
        step.started_at = None
        step.finished_at = None
    if target == StepStatus.running and step.started_at is None:
        step.started_at = _utc_now()
    if target in _TERMINAL_STEP_STATUSES:
        step.finished_at = step.finished_at or _utc_now()
    elif target == StepStatus.running:
        step.finished_at = None

    if error_message is not None:
        step.error = error_message
    if error_type is not None:
        step.error_type = error_type
    if retryable is not None:
        step.retryable = retryable
    if blocked_reason is not None:
        step.blocked_reason = blocked_reason

    payload = {
        "from_status": from_status.value,
        "to_status": target.value,
        "source": source,
        "step_name": step.name,
        "stage": step.stage,
        "task_kind": step.task_kind,
        "step_order": step.step_order,
    }
    if reason:
        payload["reason"] = reason
    if error_message:
        payload["error_message"] = error_message
    if error_type:
        payload["error_type"] = error_type
    if retryable is not None:
        payload["retryable"] = retryable
    if blocked_reason:
        payload["blocked_reason"] = blocked_reason

    if from_status != target or reason or error_message or blocked_reason or error_type:
        emit_task_event(db, str(step.task_run_id), str(step.id), "TASK_STATUS_CHANGED", payload)
        _emit_task_lifecycle_event(db, step, from_status=from_status, to_status=target, payload=payload)
        if target == StepStatus.blocked:
            emit_task_event(db, str(step.task_run_id), str(step.id), "TASK_BLOCKED", payload)

    return target


def _emit_run_lifecycle_event(
    db: Session,
    run: TaskRun,
    *,
    from_status: TaskStatus,
    to_status: TaskStatus,
    payload: dict[str, object],
) -> None:
    lifecycle_payload = {
        "task_name": run.name,
        "task_type": run.task_type,
        "trade_date": run.trade_date,
        "workspace_id": run.workspace_id,
        **payload,
    }
    if to_status == TaskStatus.running and from_status != TaskStatus.running:
        emit_run_event(db, str(run.id), "RUN_STARTED", lifecycle_payload)
        return
    if to_status == TaskStatus.success and from_status != TaskStatus.success:
        emit_run_event(
            db,
            str(run.id),
            "RUN_FINISHED",
            {"status": TaskStatus.success.value, "progress": 1.0, **lifecycle_payload},
        )
        return
    if (
        to_status in {TaskStatus.partial_success, TaskStatus.degraded, TaskStatus.blocked, TaskStatus.cancelled, TaskStatus.stale}
        and from_status != to_status
    ):
        emit_run_event(
            db,
            str(run.id),
            "RUN_FINISHED",
            {"status": to_status.value, "progress": payload.get("progress"), **lifecycle_payload},
        )
        return
    if to_status == TaskStatus.failed and from_status != TaskStatus.failed:
        emit_run_event(
            db,
            str(run.id),
            "RUN_FAILED",
            {"status": TaskStatus.failed.value, "error_message": payload.get("error_message"), **lifecycle_payload},
        )


def _emit_task_lifecycle_event(
    db: Session,
    step: TaskStep,
    *,
    from_status: StepStatus,
    to_status: StepStatus,
    payload: dict[str, object],
) -> None:
    lifecycle_payload = {
        "step_name": step.name,
        "stage": step.stage,
        "task_kind": step.task_kind,
        "step_order": step.step_order,
        **payload,
    }
    if to_status == StepStatus.running and from_status != StepStatus.running:
        emit_task_event(db, str(step.task_run_id), str(step.id), "TASK_STARTED", lifecycle_payload)
        return
    if to_status == StepStatus.success and from_status != StepStatus.success:
        emit_task_event(
            db,
            str(step.task_run_id),
            str(step.id),
            "TASK_FINISHED",
            {"status": StepStatus.success.value, **lifecycle_payload},
        )
        return
    if to_status == StepStatus.failed and from_status != StepStatus.failed:
        emit_task_event(
            db,
            str(step.task_run_id),
            str(step.id),
            "TASK_FAILED",
            {"error_message": payload.get("error_message"), **lifecycle_payload},
        )
        return
    if to_status == StepStatus.skipped and from_status != StepStatus.skipped:
        emit_task_event(
            db,
            str(step.task_run_id),
            str(step.id),
            "TASK_FINISHED",
            {"status": StepStatus.skipped.value, **lifecycle_payload},
        )
