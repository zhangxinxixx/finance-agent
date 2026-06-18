from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.orm import Session

from apps.api.schemas.artifact import ArtifactDetailResponse
from apps.api.schemas.source_trace import ArtifactRef
from apps.api.services._trace_refs import (
    artifact_ref_from_path,
    coerce_artifact_type,
    dedupe_artifact_refs,
    dedupe_source_refs,
    parse_artifact_refs,
    parse_source_refs,
)
from database.models.execution import RunArtifact
from database.models.task import TaskRun, TaskStep


def get_artifact_detail_response(db: Session, artifact_id: str) -> ArtifactDetailResponse | None:
    row = db.query(RunArtifact).filter(RunArtifact.artifact_id == uuid.UUID(artifact_id)).first()
    if row is None:
        return None

    run = db.query(TaskRun).filter(TaskRun.id == row.run_id).first() if row.run_id else None
    step = db.query(TaskStep).filter(TaskStep.id == row.task_id).first() if row.task_id else None

    artifact = ArtifactRef(
        artifact_id=str(row.artifact_id),
        artifact_type=coerce_artifact_type(row.artifact_type, row.file_path),
        file_path=row.file_path,
        generated_at=row.created_at,
        sha256=row.sha256,
    )
    source_refs = parse_source_refs(row.source_refs)
    if step is not None:
        source_refs = dedupe_source_refs([*source_refs, *parse_source_refs(step.source_refs)])
    input_refs = parse_artifact_refs(step.input_refs) if step is not None else []
    related_artifacts = _build_related_artifacts(artifact, step=step)

    return ArtifactDetailResponse(
        run_id=str(row.run_id) if row.run_id else None,
        snapshot_id=run.snapshot_id if run is not None else None,
        artifact=artifact,
        task_id=str(step.id) if step is not None else str(row.task_id) if row.task_id else None,
        task_name=step.name if step is not None else None,
        stage=step.stage if step is not None else None,
        input_refs=input_refs,
        source_refs=source_refs,
        artifact_refs=related_artifacts,
        metadata=_parse_metadata(row.metadata_json),
    )


def _parse_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _build_related_artifacts(current: ArtifactRef, *, step: TaskStep | None) -> list[ArtifactRef]:
    if step is None:
        return [current]
    artifacts = [
        current,
        *parse_artifact_refs(step.output_refs),
        *parse_artifact_refs(step.artifact_refs),
    ]
    if step.output_ref:
        artifacts.append(artifact_ref_from_path(step.output_ref, artifact_id=f"{step.id}:output_ref"))
    return dedupe_artifact_refs(artifacts)
