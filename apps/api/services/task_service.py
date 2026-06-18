from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session, selectinload

from apps.api.schemas.source_trace import ArtifactRef
from apps.api.schemas.source_trace import SourceRef
from apps.api.schemas.common import TaskStatus as ApiTaskStatus
from apps.api.schemas.task_run import TaskRunResponse, TaskStepResponse
from apps.api.services._trace_refs import (
    artifact_ref_from_path,
    coerce_artifact_type,
    dedupe_artifact_refs,
    dedupe_source_refs,
    parse_artifact_refs,
    parse_source_refs,
)
from apps.runtime.artifact_registry import list_run_artifacts
from database.models.engine import SessionLocal
from database.models.execution import RunArtifact
from database.models.task import StepStatus, TaskRun, TaskStatus, TaskStep


_TASK_STATUS_MAP: dict[str, ApiTaskStatus] = {
    "pending": ApiTaskStatus.queued,
    "running": ApiTaskStatus.running,
    "success": ApiTaskStatus.success,
    "failed": ApiTaskStatus.failed,
    "partial_success": ApiTaskStatus.partial_success,
    "blocked": ApiTaskStatus.needs_review,
    "stale": ApiTaskStatus.degraded,
    "degraded": ApiTaskStatus.degraded,
    "cancelled": ApiTaskStatus.cancelled,
    "retrying": ApiTaskStatus.retrying,
    "skipped": ApiTaskStatus.skipped,
}


def map_task_status_to_api(status: TaskStatus | StepStatus | str | None) -> ApiTaskStatus:
    raw = getattr(status, "value", status)
    if raw is None:
        return ApiTaskStatus.queued
    return _TASK_STATUS_MAP.get(str(raw), ApiTaskStatus.needs_review)


def list_recent_tasks(limit: int = 20) -> list[dict[str, Any]]:
    try:
        with SessionLocal() as session:
            tasks = (
                session.query(TaskRun)
                .options(selectinload(TaskRun.steps))
                .order_by(TaskRun.created_at.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "id": str(task.id),
                    "name": task.name,
                    "status": task.status.value,
                    "error": task.error,
                    "created_at": task.created_at.isoformat() if task.created_at else None,
                    "updated_at": task.updated_at.isoformat() if task.updated_at else None,
                    "step_count": len(task.steps),
                }
                for task in tasks
            ]
    except Exception:
        return []


def list_task_runs(db: Session, limit: int = 20) -> list[TaskRunResponse]:
    runs = (
        db.query(TaskRun)
        .options(selectinload(TaskRun.steps))
        .order_by(TaskRun.created_at.desc())
        .limit(limit)
        .all()
    )
    return [build_task_run_response(db, run) for run in runs]


def get_task_run(db: Session, run_id: str) -> TaskRun | None:
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError:
        return None
    return (
        db.query(TaskRun)
        .options(selectinload(TaskRun.steps))
        .filter(TaskRun.id == run_uuid)
        .first()
    )


def get_task_run_response(db: Session, run_id: str) -> TaskRunResponse | None:
    run = get_task_run(db, run_id)
    if run is None:
        return None
    return build_task_run_response(db, run)


def get_task_run_steps(db: Session, run_id: str) -> list[TaskStepResponse] | None:
    run = get_task_run(db, run_id)
    if run is None:
        return None
    return [build_task_step_response(step, run=run) for step in _sorted_steps(run.steps)]


def get_task_run_logs(db: Session, run_id: str) -> dict[str, Any] | None:
    steps = get_task_run_steps(db, run_id)
    if steps is None:
        return None
    return {"run_id": run_id, "logs": [step.model_dump(mode="json") for step in steps]}


def get_task_run_artifacts(db: Session, run_id: str) -> dict[str, Any] | None:
    run = get_task_run(db, run_id)
    if run is None:
        return None

    artifacts = list_run_artifacts(db, run_id)
    if not artifacts:
        artifacts = dedupe_artifact_refs(
            artifact
            for step in run.steps
            for artifact in _step_artifact_refs(step)
        )
    return {
        "run_id": str(run.id),
        "artifacts": [artifact.model_dump(mode="json") for artifact in artifacts],
    }


def build_task_run_response(db: Session, run: TaskRun) -> TaskRunResponse:
    steps = [build_task_step_response(step, run=run) for step in _sorted_steps(run.steps)]
    run_artifacts = _list_run_artifact_rows(db, run.id)
    run_artifact_refs = _run_artifact_refs(run_artifacts)
    run_artifact_source_refs = _run_artifact_source_refs(run_artifacts)
    started_at = run.started_at or _first_non_null(step.started_at for step in run.steps)
    ended_at = run.ended_at or _last_non_null(step.finished_at for step in run.steps)
    return TaskRunResponse(
        run_id=str(run.id),
        snapshot_id=run.snapshot_id,
        task_id=str(run.id),
        task_type=run.task_type or run.name,
        workspace_id=run.workspace_id,
        trading_date=run.trade_date,
        status=map_task_status_to_api(run.status),
        current_stage=run.current_stage or _infer_current_stage(run),
        progress=run.progress if run.progress is not None else _infer_run_progress(run.steps),
        started_at=started_at,
        ended_at=ended_at,
        total_cost_usd=run.total_cost_usd,
        token_in=run.token_in,
        token_out=run.token_out,
        final_result_id=run.final_result_id,
        error_summary=run.error_summary or run.error,
        source_refs=dedupe_source_refs(
            [
                *run_artifact_source_refs,
                *(source for step in run.steps for source in parse_source_refs(step.source_refs)),
            ]
        ),
        artifact_refs=dedupe_artifact_refs(
            [
                *run_artifact_refs,
                *(artifact for step in run.steps for artifact in _step_artifact_refs(step)),
            ]
        ),
        steps=steps,
    )


def _try_parse_json(raw: str | None) -> dict | None:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def build_task_step_response(step: TaskStep, *, run: TaskRun | None = None) -> TaskStepResponse:
    input_refs = parse_artifact_refs(step.input_refs)
    output_refs = parse_artifact_refs(step.output_refs)
    extra_artifacts = parse_artifact_refs(step.artifact_refs)
    primary_output = artifact_ref_from_path(step.output_ref, artifact_id=f"{step.id}:output_ref") if step.output_ref else None
    artifact_refs = dedupe_artifact_refs(
        [*output_refs, *extra_artifacts, *([primary_output] if primary_output else [])]
    )
    return TaskStepResponse(
        run_id=str(run.id) if run else None,
        snapshot_id=run.snapshot_id if run else None,
        step_id=str(step.id),
        task_name=step.name,
        stage=step.stage,
        task_kind=step.task_kind,
        status=map_task_status_to_api(step.status),
        progress=_infer_step_progress(step.status),
        input_refs=input_refs,
        output_refs=output_refs,
        source_refs=parse_source_refs(step.source_refs),
        artifact_refs=artifact_refs,
        started_at=step.started_at,
        ended_at=step.finished_at,
        duration_ms=step.duration_ms or _derive_duration_ms(step.started_at, step.finished_at),
        retry_count=step.retry_count if step.retry_count is not None else 0,
        error_type=step.error_type,
        error_message=step.error,
        input_json=_try_parse_json(step.input_json),
        output_json=_try_parse_json(step.output_json),
        error_json=_try_parse_json(step.error_json),
    )


def _sorted_steps(steps: Iterable[TaskStep]) -> list[TaskStep]:
    return sorted(
        steps,
        key=lambda step: (
            step.step_order is None,
            step.step_order if step.step_order is not None else 0,
            step.created_at or datetime.min,
        ),
    )


def _first_non_null(values: Iterable[datetime | None]) -> datetime | None:
    return min((value for value in values if value is not None), default=None)


def _last_non_null(values: Iterable[datetime | None]) -> datetime | None:
    return max((value for value in values if value is not None), default=None)


def _infer_current_stage(run: TaskRun) -> str | None:
    running_step = next((step for step in _sorted_steps(run.steps) if step.status == StepStatus.running), None)
    if running_step is not None:
        return running_step.stage or running_step.name
    last_step = _sorted_steps(run.steps)[-1] if run.steps else None
    return (last_step.stage or last_step.name) if last_step is not None else None


def _infer_run_progress(steps: list[TaskStep]) -> float | None:
    if not steps:
        return None
    finished = sum(
        1
        for step in steps
        if step.status in {StepStatus.success, StepStatus.failed, StepStatus.skipped, StepStatus.blocked}
    )
    return round(finished / len(steps), 4)


def _infer_step_progress(status: StepStatus | str | None) -> float | None:
    raw = getattr(status, "value", status)
    if raw in {"success", "failed", "skipped", "blocked"}:
        return 1.0
    if raw == "running":
        return 0.5
    if raw == "pending":
        return 0.0
    return None


def _derive_duration_ms(started_at: datetime | None, ended_at: datetime | None) -> int | None:
    if started_at is None or ended_at is None:
        return None
    return int((ended_at - started_at).total_seconds() * 1000)


def _parse_json(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _step_artifact_refs(step: TaskStep) -> list[ArtifactRef]:
    refs = [*parse_artifact_refs(step.output_refs), *parse_artifact_refs(step.artifact_refs)]
    if step.output_ref:
        refs.append(artifact_ref_from_path(step.output_ref, artifact_id=f"{step.id}:output_ref"))
    return refs


def _list_run_artifact_rows(db: Session, run_id: uuid.UUID) -> list[RunArtifact]:
    try:
        return (
            db.query(RunArtifact)
            .filter(RunArtifact.run_id == run_id)
            .order_by(RunArtifact.created_at.asc(), RunArtifact.file_path.asc())
            .all()
        )
    except (OperationalError, ProgrammingError, TypeError, ValueError):
        return []


def _run_artifact_refs(rows: list[RunArtifact]) -> list[ArtifactRef]:
    return [
        ArtifactRef(
            artifact_id=str(row.artifact_id),
            artifact_type=coerce_artifact_type(row.artifact_type, row.file_path),
            file_path=row.file_path,
            generated_at=row.created_at,
            sha256=row.sha256,
        )
        for row in rows
    ]


def _run_artifact_source_refs(rows: list[RunArtifact]) -> list[SourceRef]:
    return dedupe_source_refs(source for row in rows for source in parse_source_refs(row.source_refs))
