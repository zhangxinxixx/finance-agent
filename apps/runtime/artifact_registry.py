"""RunArtifact registry helpers."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from apps.api.schemas.common import ArtifactType
from apps.api.schemas.source_trace import ArtifactRef
from apps.runtime.artifact_storage import LOCAL_FS_STORAGE_BACKEND, get_artifact_storage
from apps.runtime.execution_event_bridge import emit_task_event
from database.models.execution import RunArtifact
from database.models.task import TaskRun, TaskStep

_RUN_SNAPSHOT_LINEAGE_KEYS = frozenset({"analysis_snapshot", "coordinator"})
_SNAPSHOT_BOUND_ARTIFACT_TYPES = frozenset({ArtifactType.analysis_md, ArtifactType.structured_json})
_SOURCE_REF_IDENTITY_KEYS = frozenset({"source_id", "source_name", "source", "source_key", "source_ref"})
_SOURCE_REF_TRACE_KEYS = frozenset(
    {
        "article_id",
        "captured_at",
        "data_date",
        "endpoint",
        "file_path",
        "raw_path",
        "ref",
        "report_date",
        "sha256",
        "snapshot_id",
        "source_ref",
        "source_type",
        "source_url",
        "status",
        "symbol",
        "url",
    }
)


def _artifact_run(db: Session, *, step: TaskStep) -> TaskRun | None:
    return db.query(TaskRun).filter(TaskRun.id == step.task_run_id).first()


def _run_artifacts_available(db: Session) -> bool:
    cached = db.info.get("_run_artifacts_available")
    if cached is not None:
        return bool(cached)
    try:
        bind = db.connection()
    except Exception:
        return False
    try:
        available = inspect(bind).has_table("run_artifacts")
    except Exception:
        return False
    db.info["_run_artifacts_available"] = available
    return available


def _validate_run_artifact_lineage(*, run_id: str, step: TaskStep) -> uuid.UUID:
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError as exc:
        raise ValueError(f"run artifact lineage conflict: invalid run_id={run_id}") from exc

    if step.task_run_id != run_uuid:
        raise ValueError(
            "run artifact lineage conflict: "
            f"run_id={run_id} does not match step.task_run_id={step.task_run_id}"
        )
    return run_uuid


def _build_artifact_metadata(
    *,
    run: TaskRun | None,
    artifact: ArtifactRef,
    input_snapshot_ids: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lineage_kind = _artifact_lineage_kind(artifact.artifact_type)
    metadata: dict[str, Any] = {
        "artifact_id": artifact.artifact_id,
        "generated_at": artifact.generated_at.isoformat() if artifact.generated_at else None,
        "lineage_kind": lineage_kind,
        "lineage_status": _artifact_lineage_status(run=run, lineage_kind=lineage_kind),
    }
    if run is not None and run.snapshot_id:
        metadata["snapshot_id"] = run.snapshot_id
    if input_snapshot_ids:
        metadata["input_snapshot_ids"] = input_snapshot_ids
    return metadata


def _artifact_lineage_kind(artifact_type: ArtifactType) -> str:
    if artifact_type in _SNAPSHOT_BOUND_ARTIFACT_TYPES:
        return "snapshot_bound"
    if artifact_type in {ArtifactType.raw_file, ArtifactType.parsed_file}:
        return "source_input"
    return "derived_artifact"


def _artifact_lineage_status(*, run: TaskRun | None, lineage_kind: str) -> str:
    if lineage_kind == "snapshot_bound":
        return "bound" if run is not None and run.snapshot_id else "missing_snapshot"
    if run is not None and run.snapshot_id:
        return "run_bound"
    return "partial"


def _validate_artifact_snapshot_lineage(
    *,
    run: TaskRun | None,
    artifact: ArtifactRef,
    input_snapshot_ids: dict[str, Any] | None,
    source_refs: list[dict[str, Any]] | None,
) -> None:
    if run is None or not run.snapshot_id:
        return

    if artifact.artifact_type in _SNAPSHOT_BOUND_ARTIFACT_TYPES:
        artifact_snapshot = input_snapshot_ids.get("analysis_snapshot") if isinstance(input_snapshot_ids, dict) else None
        if isinstance(artifact_snapshot, str) and artifact_snapshot and artifact_snapshot != run.snapshot_id:
            raise ValueError(
                "run artifact lineage conflict: "
                f"{artifact.artifact_type.value} artifact analysis_snapshot={artifact_snapshot} "
                f"does not match run.snapshot_id={run.snapshot_id}"
            )

    for key in _RUN_SNAPSHOT_LINEAGE_KEYS:
        value = input_snapshot_ids.get(key) if isinstance(input_snapshot_ids, dict) else None
        if isinstance(value, str) and value and value != run.snapshot_id:
            raise ValueError(
                "run artifact lineage conflict: "
                f"input_snapshot_ids[{key}]={value} does not match run.snapshot_id={run.snapshot_id}"
            )

    for ref in source_refs or []:
        if not isinstance(ref, dict):
            continue
        snapshot_id = ref.get("snapshot_id")
        if not isinstance(snapshot_id, str) or not snapshot_id:
            continue
        source_name = str(ref.get("source") or ref.get("source_name") or ref.get("source_id") or "").lower()
        if source_name in _RUN_SNAPSHOT_LINEAGE_KEYS and snapshot_id != run.snapshot_id:
            raise ValueError(
                "run artifact lineage conflict: "
                f"source_ref[{source_name}].snapshot_id={snapshot_id} does not match run.snapshot_id={run.snapshot_id}"
            )


def _validate_artifact_source_refs(source_refs: list[dict[str, Any]] | None) -> None:
    if source_refs is None:
        return

    for index, ref in enumerate(source_refs):
        if not isinstance(ref, dict):
            raise ValueError(f"run artifact source_refs[{index}] must be an object")

        identity = _first_present_source_ref_key(ref, _SOURCE_REF_IDENTITY_KEYS)
        if identity is None:
            raise ValueError(
                "run artifact source_refs minimum field violation: "
                f"source_refs[{index}] must include one of {sorted(_SOURCE_REF_IDENTITY_KEYS)}"
            )

        trace_key = _first_present_source_ref_key(ref, _SOURCE_REF_TRACE_KEYS)
        if trace_key is None:
            raise ValueError(
                "run artifact source_refs minimum field violation: "
                f"source_refs[{index}] must include one trace/detail field"
            )


def _first_present_source_ref_key(ref: dict[str, Any], keys: frozenset[str]) -> str | None:
    for key in keys:
        value = ref.get(key)
        if value is not None and str(value).strip():
            return key
    return None


def register_step_artifacts(
    db: Session,
    *,
    run_id: str,
    step: TaskStep,
    output_refs: list[dict[str, Any]] | None = None,
    artifact_refs: list[dict[str, Any]] | None = None,
    output_ref: str | None = None,
    source_refs: list[dict[str, Any]] | None = None,
    input_snapshot_ids: dict[str, Any] | None = None,
) -> list[RunArtifact]:
    """Persist additive registry rows for a step's artifacts."""
    if not _run_artifacts_available(db):
        return []
    run_uuid = _validate_run_artifact_lineage(run_id=run_id, step=step)
    _validate_artifact_source_refs(source_refs)
    run = _artifact_run(db, step=step)
    storage = get_artifact_storage()
    persisted: list[RunArtifact] = []
    seen: set[tuple[str, str]] = set()

    for artifact, raw_artifact in _collect_artifacts(
        output_refs=output_refs,
        artifact_refs=artifact_refs,
        output_ref=output_ref,
    ):
        _validate_artifact_snapshot_lineage(
            run=run,
            artifact=artifact,
            input_snapshot_ids=input_snapshot_ids,
            source_refs=source_refs,
        )
        dedupe_key = (artifact.file_path, artifact.artifact_type)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        existing = (
            db.query(RunArtifact)
            .filter(
                RunArtifact.run_id == run_uuid,
                RunArtifact.task_id == step.id,
                RunArtifact.file_path == artifact.file_path,
                RunArtifact.artifact_type == artifact.artifact_type,
            )
            .first()
        )
        if existing is not None:
            persisted.append(existing)
            continue

        row = RunArtifact(
            run_id=run_uuid,
            task_id=step.id,
            artifact_type=artifact.artifact_type,
            file_path=artifact.file_path,
            storage_backend=artifact.storage_backend or storage.backend_name,
            sha256=artifact.sha256 or storage.compute_sha256(artifact.file_path),
            content_type=_optional_str(raw_artifact.get("content_type")),
            byte_size=_optional_int(raw_artifact.get("byte_size")),
            generated_at=_parse_datetime(raw_artifact.get("generated_at")) or artifact.generated_at,
            source_refs_data=list(source_refs or []),
            source_refs=json.dumps(source_refs, ensure_ascii=False) if source_refs else None,
        )
        row.artifact_metadata = _build_artifact_metadata(
            run=run,
            artifact=artifact,
            input_snapshot_ids=input_snapshot_ids,
        )
        row.metadata_json = json.dumps(row.artifact_metadata, ensure_ascii=False)
        db.add(row)
        db.flush()
        persisted.append(row)
        _emit_artifact_registered_event(db, run_id=str(run_uuid), step=step, artifact=row)

    if persisted:
        db.flush()
    return persisted


def _emit_artifact_registered_event(
    db: Session,
    *,
    run_id: str,
    step: TaskStep,
    artifact: RunArtifact,
) -> None:
    metadata = artifact.artifact_metadata or {}
    emit_task_event(
        db,
        run_id,
        str(step.id),
        "ARTIFACT_REGISTERED",
        {
            "artifact_id": str(artifact.artifact_id),
            "artifact_type": artifact.artifact_type,
            "file_path": artifact.file_path,
            "storage_backend": artifact.storage_backend,
            "sha256": artifact.sha256,
            "lineage_kind": metadata.get("lineage_kind"),
            "lineage_status": metadata.get("lineage_status"),
            "input_snapshot_ids": metadata.get("input_snapshot_ids") or {},
            "source_ref_count": len(artifact.source_refs_data or []),
        },
    )


def list_run_artifacts(db: Session, run_id: str) -> list[ArtifactRef]:
    if not _run_artifacts_available(db):
        return []
    rows = (
        db.query(RunArtifact)
        .filter(RunArtifact.run_id == uuid.UUID(run_id))
        .order_by(RunArtifact.created_at.asc(), RunArtifact.file_path.asc())
        .all()
    )
    return [
        ArtifactRef(
            artifact_id=str(row.artifact_id),
            artifact_type=_coerce_artifact_type(row.artifact_type, row.file_path),
            file_path=row.file_path,
            generated_at=row.created_at,
            storage_backend=row.storage_backend or LOCAL_FS_STORAGE_BACKEND,
            sha256=row.sha256,
        )
        for row in rows
    ]


def _collect_artifacts(
    *,
    output_refs: list[dict[str, Any]] | None,
    artifact_refs: list[dict[str, Any]] | None,
    output_ref: str | None,
) -> list[tuple[ArtifactRef, dict[str, Any]]]:
    artifacts: list[tuple[ArtifactRef, dict[str, Any]]] = []
    for refs in (output_refs, artifact_refs):
        for item in refs or []:
            if not isinstance(item, dict):
                continue
            file_path = str(item.get("file_path") or "").strip()
            if not file_path:
                continue
            artifacts.append(
                (
                    ArtifactRef(
                        artifact_id=str(item.get("artifact_id") or f"{file_path}:{len(artifacts)}"),
                        artifact_type=_coerce_artifact_type(item.get("artifact_type"), file_path),
                        file_path=file_path,
                        version=item.get("version"),
                        generated_at=item.get("generated_at"),
                        storage_backend=item.get("storage_backend"),
                        sha256=item.get("sha256"),
                    ),
                    item,
                )
            )

    if output_ref:
        artifacts.append(
            (
                ArtifactRef(
                    artifact_id=f"{step_key(output_ref)}:output_ref",
                    artifact_type=_coerce_artifact_type("output_ref", output_ref),
                    file_path=output_ref,
                    storage_backend=get_artifact_storage().backend_name,
                    sha256=get_artifact_storage().compute_sha256(output_ref),
                ),
                {},
            )
        )
    return artifacts


def _coerce_artifact_type(raw_type: str | ArtifactType | None, file_path: str) -> ArtifactType:
    if raw_type:
        try:
            if str(raw_type) == "output_ref":
                raise ValueError
            return ArtifactType(str(raw_type))
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


def step_key(file_path: str) -> str:
    return hashlib.sha1(file_path.encode("utf-8")).hexdigest()[:12]


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
