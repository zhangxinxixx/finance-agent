from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.orm import Session

from apps.api.schemas.artifact import ArtifactDetailResponse
from apps.api.schemas.common import ArtifactType
from apps.api.schemas.source_trace import ArtifactRef, SourceRef
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
        artifact_type=_coerce_artifact_type(row.artifact_type, row.file_path),
        file_path=row.file_path,
        generated_at=row.created_at,
        sha256=row.sha256,
    )
    source_refs = _parse_source_refs(row.source_refs)
    if not source_refs and step is not None:
        source_refs = _parse_source_refs(step.source_refs)
    input_refs = _parse_artifact_refs(step.input_refs) if step is not None else []
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


def _parse_source_refs(raw: str | None) -> list[SourceRef]:
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []

    refs: list[SourceRef] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            continue
        source_name = str(item.get("source_name") or item.get("source") or item.get("source_id") or f"source-{index}")
        source_id = str(item.get("source_id") or f"{source_name}:{index}")
        source_type = str(item.get("source_type") or item.get("type") or "unknown")
        refs.append(
            SourceRef(
                source_id=source_id,
                source_name=source_name,
                source_type=source_type,
                data_date=item.get("data_date"),
                endpoint=item.get("endpoint"),
                captured_at=item.get("captured_at"),
                file_path=item.get("file_path"),
                sha256=item.get("sha256"),
                url=item.get("url"),
                status=item.get("status"),
            )
        )
    return refs


def _parse_artifact_refs(raw: str | None) -> list[ArtifactRef]:
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []

    artifacts: list[ArtifactRef] = []
    for index, item in enumerate(payload):
        if isinstance(item, dict):
            file_path = item.get("file_path")
            if not file_path:
                continue
            artifacts.append(
                ArtifactRef(
                    artifact_id=str(item.get("artifact_id") or f"{file_path}:{index}"),
                    artifact_type=_coerce_artifact_type(item.get("artifact_type"), file_path),
                    file_path=file_path,
                    version=item.get("version"),
                    generated_at=item.get("generated_at"),
                    sha256=item.get("sha256"),
                )
            )
        elif isinstance(item, str):
            artifacts.append(_artifact_from_path(item, artifact_id=f"{item}:{index}"))
    return artifacts


def _artifact_from_path(path: str, *, artifact_id: str) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=artifact_id,
        artifact_type=_coerce_artifact_type(None, path),
        file_path=path,
    )


def _build_related_artifacts(current: ArtifactRef, *, step: TaskStep | None) -> list[ArtifactRef]:
    if step is None:
        return [current]
    artifacts = [
        current,
        *_parse_artifact_refs(step.output_refs),
        *_parse_artifact_refs(step.artifact_refs),
    ]
    if step.output_ref:
        artifacts.append(_artifact_from_path(step.output_ref, artifact_id=f"{step.id}:output_ref"))
    return _dedupe_artifacts(artifacts)


def _dedupe_artifacts(artifacts: list[ArtifactRef]) -> list[ArtifactRef]:
    seen: set[tuple[str, str]] = set()
    deduped: list[ArtifactRef] = []
    for artifact in artifacts:
        key = (artifact.file_path, artifact.artifact_type.value)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(artifact)
    return deduped


def _coerce_artifact_type(raw_type: str | None, file_path: str) -> ArtifactType:
    if raw_type:
        try:
            return ArtifactType(raw_type)
        except ValueError:
            pass

    normalized = file_path.lower()
    if normalized.endswith("source.md"):
        return ArtifactType.source_md
    if normalized.endswith("analysis.md"):
        return ArtifactType.analysis_md
    if normalized.endswith("visual.html"):
        return ArtifactType.visual_html
    if normalized.endswith("report_structured.json"):
        return ArtifactType.structured_json
    if "/raw/" in normalized:
        return ArtifactType.raw_file
    if "/parsed/" in normalized:
        return ArtifactType.parsed_file
    if "/features/" in normalized:
        return ArtifactType.feature_json
    if normalized.endswith(".png") or normalized.endswith(".jpg") or normalized.endswith(".jpeg"):
        return ArtifactType.chart_snapshot
    return ArtifactType.structured_json
