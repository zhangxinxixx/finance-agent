"""RunArtifact registry helpers."""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from apps.api.schemas.common import ArtifactType
from apps.api.schemas.source_trace import ArtifactRef
from database.models.execution import RunArtifact
from database.models.task import TaskStep

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


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


def register_step_artifacts(
    db: Session,
    *,
    run_id: str,
    step: TaskStep,
    output_refs: list[dict[str, Any]] | None = None,
    artifact_refs: list[dict[str, Any]] | None = None,
    output_ref: str | None = None,
    source_refs: list[dict[str, Any]] | None = None,
) -> list[RunArtifact]:
    """Persist additive registry rows for a step's artifacts."""
    if not _run_artifacts_available(db):
        return []
    persisted: list[RunArtifact] = []
    seen: set[tuple[str, str]] = set()

    for artifact in _collect_artifacts(
        output_refs=output_refs,
        artifact_refs=artifact_refs,
        output_ref=output_ref,
    ):
        dedupe_key = (artifact.file_path, artifact.artifact_type)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        existing = (
            db.query(RunArtifact)
            .filter(
                RunArtifact.run_id == uuid.UUID(run_id),
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
            run_id=uuid.UUID(run_id),
            task_id=step.id,
            artifact_type=artifact.artifact_type,
            file_path=artifact.file_path,
            sha256=artifact.sha256 or _maybe_sha256(artifact.file_path),
            source_refs=json.dumps(source_refs, ensure_ascii=False) if source_refs else None,
            metadata_json=json.dumps(
                {
                    "artifact_id": artifact.artifact_id,
                    "generated_at": artifact.generated_at.isoformat() if artifact.generated_at else None,
                },
                ensure_ascii=False,
            ),
        )
        db.add(row)
        persisted.append(row)

    if persisted:
        db.flush()
    return persisted


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
            sha256=row.sha256,
        )
        for row in rows
    ]


def _collect_artifacts(
    *,
    output_refs: list[dict[str, Any]] | None,
    artifact_refs: list[dict[str, Any]] | None,
    output_ref: str | None,
) -> list[ArtifactRef]:
    artifacts: list[ArtifactRef] = []
    for refs in (output_refs, artifact_refs):
        for item in refs or []:
            if not isinstance(item, dict):
                continue
            file_path = str(item.get("file_path") or "").strip()
            if not file_path:
                continue
            artifacts.append(
                ArtifactRef(
                    artifact_id=str(item.get("artifact_id") or f"{file_path}:{len(artifacts)}"),
                    artifact_type=_coerce_artifact_type(item.get("artifact_type"), file_path),
                    file_path=file_path,
                    version=item.get("version"),
                    generated_at=item.get("generated_at"),
                    sha256=item.get("sha256"),
                )
            )

    if output_ref:
        artifacts.append(
            ArtifactRef(
                artifact_id=f"{step_key(output_ref)}:output_ref",
                artifact_type=_coerce_artifact_type("output_ref", output_ref),
                file_path=output_ref,
                sha256=_maybe_sha256(output_ref),
            )
        )
    return artifacts


def _maybe_sha256(file_path: str) -> str | None:
    path = _PROJECT_ROOT / file_path
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
