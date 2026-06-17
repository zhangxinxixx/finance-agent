from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import PurePosixPath

from sqlalchemy.orm import Session

from apps.api.schemas.common import ArtifactType, DataStatus
from apps.api.schemas.data_source import DataSourceActionRequest, DataSourceActionResponse, ManualUploadRequest
from apps.api.schemas.source_trace import ArtifactRef, SourceRef
from database.models.task import StepStatus, TaskRun, TaskStatus, TaskStep


def create_ingestion_retry(db: Session, source_key: str, body: DataSourceActionRequest | None) -> DataSourceActionResponse:
    request = body or DataSourceActionRequest()
    source_ref = _source_ref(source_key, status="retry_requested")
    run = _create_run(
        db,
        name=f"ingestion_retry:{source_key}",
        task_type="ingestion_retry",
        status=TaskStatus.pending,
        stage="collector",
        step_name=f"retry:{source_key}",
        task_kind="retry",
        step_status=StepStatus.pending,
        source_refs=[source_ref],
        input_refs=[],
        output_refs=[],
        error=None,
    )
    db.commit()
    db.refresh(run)
    return DataSourceActionResponse(
        status="accepted",
        action="retry",
        source_key=source_key,
        run_id=str(run.id),
        audit_id=_audit_id(source_key, "retry", request),
        data_status=DataStatus.partial,
        source_refs=[source_ref],
    )


def register_manual_upload(db: Session, body: ManualUploadRequest) -> DataSourceActionResponse:
    artifact = ArtifactRef(
        artifact_id=f"manual:{body.source_key}:{body.file_name}",
        artifact_type=ArtifactType.raw_file,
        file_path=body.artifact_path or str(PurePosixPath("storage/raw/manual") / body.source_key / body.file_name),
        sha256=body.sha256,
    )
    source_ref = _source_ref(body.source_key, status="manual_required", file_path=artifact.file_path, sha256=body.sha256)
    run = _create_run(
        db,
        name=f"manual_upload:{body.source_key}",
        task_type="manual_upload",
        status=TaskStatus.blocked,
        stage="collector",
        step_name=f"manual_upload:{body.source_key}",
        task_kind="manual_upload",
        step_status=StepStatus.blocked,
        source_refs=[source_ref],
        input_refs=[],
        output_refs=[artifact],
        error="manual upload staged; parser follow-up required",
    )
    db.commit()
    db.refresh(run)
    return DataSourceActionResponse(
        status="manual_required",
        action="manual_upload",
        source_key=body.source_key,
        run_id=str(run.id),
        audit_id=_audit_id(body.source_key, "manual_upload", body),
        data_status=DataStatus.manual_required,
        source_refs=[source_ref],
        artifact_refs=[artifact],
    )


def _create_run(
    db: Session,
    *,
    name: str,
    task_type: str,
    status: TaskStatus,
    stage: str,
    step_name: str,
    task_kind: str,
    step_status: StepStatus,
    source_refs: list[SourceRef],
    input_refs: list[ArtifactRef],
    output_refs: list[ArtifactRef],
    error: str | None,
) -> TaskRun:
    now = datetime.now(UTC)
    run = TaskRun(
        name=name,
        task_type=task_type,
        status=status,
        current_stage=stage,
        progress=0.0,
        started_at=now,
        error_summary=error,
    )
    db.add(run)
    db.flush()
    db.add(
        TaskStep(
            task_run_id=run.id,
            name=step_name,
            stage=stage,
            task_kind=task_kind,
            status=step_status,
            started_at=now,
            source_refs=_dump_refs(source_refs),
            input_refs=_dump_refs(input_refs),
            output_refs=_dump_refs(output_refs),
            error=error,
            error_type="manual_required" if error else None,
            retry_count=0,
        )
    )
    db.flush()
    return run


def _source_ref(
    source_key: str,
    *,
    status: str,
    file_path: str | None = None,
    sha256: str | None = None,
) -> SourceRef:
    return SourceRef(
        source_id=source_key,
        source_name=source_key,
        source_type="manual" if status == "manual_required" else "api",
        file_path=file_path,
        sha256=sha256,
        status=status,
    )


def _audit_id(source_key: str, action: str, request: DataSourceActionRequest) -> str:
    return f"ingestion-action:{source_key}:{request.request_id or action}"


def _dump_refs(refs: list[SourceRef] | list[ArtifactRef]) -> str:
    return json.dumps([ref.model_dump(mode="json", exclude_none=True) for ref in refs], ensure_ascii=True)
