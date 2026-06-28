from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from apps.api.schemas.artifact import ArtifactDetailResponse
from apps.api.schemas.common import WarningItem
from apps.api.schemas.source_trace import ArtifactRef
from apps.api.services._lineage_warnings import build_artifact_lineage_warnings
from apps.api.services._report_lineage import resolve_report_lineage_context
from apps.api.services._storage import _PROJECT_ROOT
from apps.api.services._trace_refs import (
    artifact_ref_from_path,
    coerce_artifact_type,
    dedupe_artifact_refs,
    dedupe_source_refs,
    parse_artifact_refs,
    parse_source_refs,
)
from apps.runtime.artifact_storage import LOCAL_FS_STORAGE_BACKEND
from database.models.execution import RunArtifact
from database.models.report import ReportArtifact, ReportItem
from database.models.task import TaskRun, TaskStep


def get_artifact_detail_response(db: Session, artifact_id: str) -> ArtifactDetailResponse | None:
    try:
        parsed_uuid = uuid.UUID(artifact_id)
    except ValueError:
        parsed_uuid = None

    if parsed_uuid is not None:
        row = db.query(RunArtifact).filter(RunArtifact.artifact_id == parsed_uuid).first()
        if row is not None:
            return _build_registry_artifact_detail(db, row)

    report_artifact = db.get(ReportArtifact, artifact_id)
    if report_artifact is not None:
        return _build_report_artifact_detail(db, report_artifact)

    return None


def _build_registry_artifact_detail(db: Session, row: RunArtifact) -> ArtifactDetailResponse:
    run = db.query(TaskRun).filter(TaskRun.id == row.run_id).first() if row.run_id else None
    step = db.query(TaskStep).filter(TaskStep.id == row.task_id).first() if row.task_id else None
    metadata = _parse_metadata(row.metadata_json)
    artifact_input_snapshot_ids = metadata.get("input_snapshot_ids")
    warnings = [
        *build_artifact_lineage_warnings(
        artifact_id=str(row.artifact_id),
        run_id=str(row.run_id) if row.run_id else None,
        run_snapshot_id=run.snapshot_id if run is not None else None,
        artifact_snapshot_id=metadata.get("snapshot_id") if isinstance(metadata.get("snapshot_id"), str) else None,
        artifact_input_snapshot_ids=artifact_input_snapshot_ids if isinstance(artifact_input_snapshot_ids, dict) else None,
        ),
        *_missing_file_warnings(row.file_path),
    ]

    artifact = ArtifactRef(
        artifact_id=str(row.artifact_id),
        artifact_type=coerce_artifact_type(row.artifact_type, row.file_path),
        file_path=row.file_path,
        storage_backend=row.storage_backend or LOCAL_FS_STORAGE_BACKEND,
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
        snapshot_id=run.snapshot_id if run is not None and run.snapshot_id else metadata.get("snapshot_id"),
        artifact=artifact,
        task_id=str(step.id) if step is not None else str(row.task_id) if row.task_id else None,
        task_name=step.name if step is not None else None,
        stage=step.stage if step is not None else None,
        input_refs=input_refs,
        source_refs=source_refs,
        artifact_refs=related_artifacts,
        warnings=warnings,
        metadata=metadata,
    )


def _build_report_artifact_detail(db: Session, report_artifact: ReportArtifact) -> ArtifactDetailResponse:
    report_item = db.get(ReportItem, report_artifact.report_id)
    artifact = ArtifactRef(
        artifact_id=report_artifact.artifact_id,
        artifact_type=coerce_artifact_type(report_artifact.artifact_type, report_artifact.file_path),
        file_path=report_artifact.file_path,
        storage_backend=LOCAL_FS_STORAGE_BACKEND,
        version=report_artifact.version,
        generated_at=report_artifact.generated_at or report_artifact.updated_at or report_artifact.created_at,
        sha256=report_artifact.sha256,
    )
    sibling_artifacts = []
    if report_item is not None:
        sibling_artifacts = [
            ArtifactRef(
                artifact_id=item.artifact_id,
                artifact_type=coerce_artifact_type(item.artifact_type, item.file_path),
                file_path=item.file_path,
                storage_backend=LOCAL_FS_STORAGE_BACKEND,
                version=item.version,
                generated_at=item.generated_at or item.updated_at or item.created_at,
                sha256=item.sha256,
            )
            for item in db.query(ReportArtifact)
            .filter(ReportArtifact.report_id == report_item.report_id)
            .order_by(ReportArtifact.is_primary.desc(), ReportArtifact.generated_at.desc(), ReportArtifact.artifact_id.asc())
            .all()
        ]
    lineage = (
        resolve_report_lineage_context(
            db,
            report_id=report_item.report_id,
            report_run_id=report_item.run_id,
            report_snapshot_id=report_item.snapshot_id,
        )
        if report_item is not None
        else None
    )

    metadata = _parse_metadata(report_artifact.metadata_text)
    if report_item is not None:
        metadata = {
            **metadata,
            "report_id": report_item.report_id,
            "family": report_item.family,
            "title": report_item.title,
            "lifecycle_status": report_item.lifecycle_status,
        }
    warnings = [
        *(lineage.warnings if lineage is not None else []),
        *_missing_file_warnings(report_artifact.file_path),
    ]

    return ArtifactDetailResponse(
        run_id=lineage.resolved_run_id if lineage is not None else report_item.run_id if report_item is not None else None,
        snapshot_id=lineage.resolved_snapshot_id if lineage is not None else report_item.snapshot_id if report_item is not None else None,
        artifact=artifact,
        task_name="report_artifact",
        stage="report",
        input_refs=[],
        source_refs=parse_source_refs(report_item.source_refs) if report_item is not None else [],
        artifact_refs=dedupe_artifact_refs(sibling_artifacts or [artifact]),
        warnings=warnings,
        metadata=metadata,
    )


def _parse_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _missing_file_warnings(file_path: str) -> list[WarningItem]:
    path = _resolve_registered_artifact_path(file_path)
    if path.is_file():
        return []
    return [
        WarningItem(
            code="artifact-missing-file",
            message=f"Registered artifact file is missing: {file_path}",
            field=file_path,
        )
    ]


def _resolve_registered_artifact_path(file_path: str) -> Path:
    path = Path(file_path)
    return path if path.is_absolute() else _PROJECT_ROOT / path


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
