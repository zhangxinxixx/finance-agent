"""Shared Dagster RunArtifact registration helpers."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session


def register_dagster_output_artifacts(
    context: Any,
    *,
    db: Session,
    paths: list[str],
    step_name: str,
    stage: str,
    task_kind: str,
    source_refs: list[dict[str, Any]] | None = None,
    input_snapshot_ids: dict[str, Any] | None = None,
    snapshot_id: str | None = None,
    trade_date: str | None = None,
    json_artifact_type: str = "structured_json",
) -> str | None:
    """Register artifacts written by a Dagster op into the canonical registry."""
    output_refs = [
        {
            "artifact_id": f"{context.run_id}:{step_name}:{index}",
            "artifact_type": _artifact_type_for_path(path, json_artifact_type=json_artifact_type),
            "file_path": str(path),
        }
        for index, path in enumerate(paths)
        if isinstance(path, str) and path
    ]
    if not output_refs:
        return None

    try:
        run_uuid = uuid.UUID(str(context.run_id))
    except ValueError:
        context.log.warning("Skipping RunArtifact registration for %s: invalid run_id=%s", step_name, context.run_id)
        return None

    from apps.runtime.artifact_registry import register_step_artifacts
    from database.models.execution import ensure_execution_tables
    from database.models.task import StepStatus, TaskRun, TaskStatus, TaskStep, ensure_task_tables

    ensure_task_tables(db)
    ensure_execution_tables(db)

    run = db.get(TaskRun, run_uuid)
    if run is None:
        run = TaskRun(
            id=run_uuid,
            name="premarket_job",
            task_type="premarket",
            status=TaskStatus.running,
            trade_date=_optional_str(trade_date),
            snapshot_id=_optional_str(snapshot_id),
        )
        db.add(run)
        db.flush()
    else:
        if snapshot_id and not run.snapshot_id:
            run.snapshot_id = _optional_str(snapshot_id)
        if trade_date and not run.trade_date:
            run.trade_date = _optional_str(trade_date)

    step = (
        db.query(TaskStep)
        .filter(TaskStep.task_run_id == run_uuid, TaskStep.name == step_name)
        .first()
    )
    if step is None:
        step = TaskStep(
            task_run_id=run_uuid,
            name=step_name,
            stage=stage,
            task_kind=task_kind,
            status=StepStatus.success,
        )
        db.add(step)
        db.flush()
    else:
        step.status = StepStatus.success

    register_step_artifacts(
        db,
        run_id=str(run_uuid),
        step=step,
        output_refs=output_refs,
        source_refs=source_refs,
        input_snapshot_ids=input_snapshot_ids,
    )
    db.commit()
    return str(step.id)


def _artifact_type_for_path(path: str, *, json_artifact_type: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix == ".md":
        return "analysis_md"
    if suffix == ".html":
        return "visual_html"
    return json_artifact_type


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
