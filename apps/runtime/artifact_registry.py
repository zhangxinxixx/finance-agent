"""RunArtifact registry helpers."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import uuid
from datetime import date
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from apps.api.schemas.common import ArtifactType
from apps.api.schemas.source_trace import ArtifactRef
from apps.runtime.artifact_storage import LOCAL_FS_STORAGE_BACKEND, LocalFileSystemArtifactStorage, get_artifact_storage
from database.models.execution import RunArtifact
from database.models.task import TaskRun, TaskStep

_STORAGE_LAYERS = frozenset({"raw", "parsed", "features", "outputs"})
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
_ARTIFACT_QUALITY_METADATA_KEYS = frozenset(
    {
        "quality_status",
        "usable_for",
        "blocked_for",
        "execution_mode",
        "publish_allowed",
        "output_mode",
    }
)
_CONTEXT_BUNDLE_ARTIFACT_FAMILY = "analysis_context_bundle"
_CONTEXT_BUNDLE_SCHEMA_VERSION = "analysis_context_bundle.v3"
_CONTEXT_BUNDLE_SELECTOR_LIMIT = 128


def _artifact_run(db: Session, *, step: TaskStep) -> TaskRun | None:
    return db.query(TaskRun).filter(TaskRun.id == step.task_run_id).first()


def _artifact_run_by_id(db: Session, *, run_id: uuid.UUID) -> TaskRun | None:
    return db.query(TaskRun).filter(TaskRun.id == run_id).first()


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
            f"run artifact lineage conflict: run_id={run_id} does not match step.task_run_id={step.task_run_id}"
        )
    return run_uuid


def _coerce_run_uuid(run_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(run_id)
    except ValueError as exc:
        raise ValueError(f"run artifact lineage conflict: invalid run_id={run_id}") from exc


def _build_artifact_metadata(
    *,
    run: TaskRun | None,
    artifact: ArtifactRef,
    input_snapshot_ids: dict[str, Any] | None = None,
    path_metadata: dict[str, Any] | None = None,
    extra_metadata: dict[str, Any] | None = None,
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
    if path_metadata:
        metadata.update(path_metadata)
    if extra_metadata:
        for key, value in extra_metadata.items():
            metadata.setdefault(key, value)
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
        artifact_snapshot = (
            input_snapshot_ids.get("analysis_snapshot") if isinstance(input_snapshot_ids, dict) else None
        )
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


def register_artifact(
    db: Session,
    *,
    run_id: str,
    file_path: str,
    artifact_type: str | ArtifactType | None = None,
    step: TaskStep | None = None,
    artifact_id: str | None = None,
    storage_backend: str | None = None,
    sha256: str | None = None,
    content_type: str | None = None,
    byte_size: int | None = None,
    generated_at: datetime | str | None = None,
    source_refs: list[dict[str, Any]] | None = None,
    input_snapshot_ids: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    registry_artifact_id: uuid.UUID | None = None,
    require_canonical_path: bool = True,
    storage: LocalFileSystemArtifactStorage | None = None,
) -> RunArtifact | None:
    """Register one run artifact using the canonical DB registry path.

    This is the generic helper for new writer paths. It requires a TaskRun
    parent, optionally binds a TaskStep, and rejects non run-partitioned paths
    by default. Legacy adapters can keep using ``register_step_artifacts``.
    """
    if not _run_artifacts_available(db):
        return None

    run_uuid = (
        _validate_run_artifact_lineage(run_id=run_id, step=step) if step is not None else _coerce_run_uuid(run_id)
    )
    _validate_artifact_source_refs(source_refs)
    run = _artifact_run(db, step=step) if step is not None else _artifact_run_by_id(db, run_id=run_uuid)
    if run is None:
        raise ValueError(f"run artifact lineage conflict: run_id={run_id} does not match an existing TaskRun")

    effective_storage = storage or get_artifact_storage(storage_backend)
    raw_artifact = _enrich_raw_artifact(
        {
            "artifact_id": artifact_id,
            "artifact_type": artifact_type,
            "file_path": file_path,
            "storage_backend": storage_backend,
            "sha256": sha256,
            "content_type": content_type,
            "byte_size": byte_size,
            "generated_at": generated_at,
        },
        storage=effective_storage,
    )
    artifact = ArtifactRef(
        artifact_id=str(artifact_id or f"{step_key(file_path)}:artifact"),
        artifact_type=_coerce_artifact_type(artifact_type, file_path),
        file_path=file_path,
        generated_at=_parse_datetime(raw_artifact.get("generated_at")),
        storage_backend=_optional_str(raw_artifact.get("storage_backend")),
        sha256=_optional_str(raw_artifact.get("sha256")),
    )
    return _persist_run_artifact(
        db,
        run_uuid=run_uuid,
        task_id=step.id if step is not None else None,
        run=run,
        artifact=artifact,
        raw_artifact=raw_artifact,
        source_refs=source_refs,
        input_snapshot_ids=input_snapshot_ids,
        metadata=metadata,
        registry_artifact_id=registry_artifact_id,
        storage=effective_storage,
        require_canonical_path=require_canonical_path,
        flush=True,
    )


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

        row = _persist_run_artifact(
            db,
            run_uuid=run_uuid,
            task_id=step.id,
            run=run,
            artifact=artifact,
            raw_artifact=raw_artifact,
            source_refs=source_refs,
            input_snapshot_ids=input_snapshot_ids,
            metadata=_artifact_quality_metadata(raw_artifact),
            registry_artifact_id=None,
            storage=storage,
            require_canonical_path=False,
            flush=False,
        )
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
            storage_backend=row.storage_backend or LOCAL_FS_STORAGE_BACKEND,
            sha256=row.sha256,
        )
        for row in rows
    ]


def select_context_bundle_artifact_for_run(
    db: Session,
    *,
    run_id: str,
    storage_root: str | Path,
) -> dict[str, Any] | None:
    """Return the one validated ContextBundle descriptor registered for ``run_id``.

    The registry row is only an index.  This read boundary revalidates its
    metadata, immutable file hash, and Bundle payload before returning an
    explicit recovery descriptor.  Multiple Bundle rows for one run are an
    authority conflict, never a "latest" choice.
    """

    if not _run_artifacts_available(db):
        return None
    run_uuid = _coerce_run_uuid(run_id)
    rows = (
        db.query(RunArtifact)
        .filter(RunArtifact.run_id == run_uuid)
        .order_by(RunArtifact.created_at.asc(), RunArtifact.artifact_id.asc())
        .all()
    )
    candidates = [row for row in rows if _is_context_bundle_row(row)]
    if not candidates:
        return None
    if len(candidates) == 1:
        return _validated_context_bundle_descriptor(
            candidates[0],
            storage_root=storage_root,
            expected_run_id=run_id,
        )
    if len(candidates) != 2:
        raise ValueError("TaskRun has ambiguous ContextBundle registry artifacts")
    recompute = [
        row
        for row in candidates
        if isinstance(row.artifact_metadata, dict)
        and row.artifact_metadata.get("artifact_role") == "canary_recompute"
    ]
    predecessor = [row for row in candidates if row not in recompute]
    if len(recompute) != 1 or len(predecessor) != 1:
        raise ValueError("TaskRun has ambiguous ContextBundle registry artifacts")
    predecessor_descriptor = _validated_context_bundle_descriptor(
        predecessor[0],
        storage_root=storage_root,
        expected_run_id=run_id,
    )
    recompute_descriptor = _validated_context_bundle_descriptor(
        recompute[0],
        storage_root=storage_root,
        expected_run_id=run_id,
    )
    _validate_canary_recompute_descriptor(
        predecessor=predecessor_descriptor,
        recompute=recompute_descriptor,
    )
    return recompute_descriptor


def select_canary_terminal_result_for_run(
    db: Session,
    *,
    run_id: str,
    storage_root: str | Path,
) -> Any | None:
    """Recover the one terminal canary outcome for a TaskRun, if committed."""

    run_uuid = _coerce_run_uuid(run_id)
    rows = (
        db.query(RunArtifact)
        .filter(RunArtifact.run_id == run_uuid)
        .order_by(RunArtifact.created_at.asc())
        .all()
    )
    candidates = [
        row
        for row in rows
        if isinstance(row.artifact_metadata, dict)
        and row.artifact_metadata.get("artifact_family")
        == "analysis_state_canary_terminal"
    ]
    if not candidates:
        return None
    if len(candidates) != 1:
        raise ValueError("TaskRun has ambiguous terminal canary outcomes")
    row = candidates[0]
    expected_id = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"finance-agent:analysis-state-canary-terminal:{run_id}",
    )
    if row.artifact_id != expected_id or not row.sha256:
        raise ValueError("terminal canary registry identity is invalid")
    root = Path(storage_root).resolve()
    path = Path(row.file_path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("terminal canary artifact path is unavailable")
    if hashlib.sha256(path.read_bytes()).hexdigest() != row.sha256:
        raise ValueError("terminal canary artifact hash is invalid")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("terminal canary artifact is invalid JSON") from exc
    from apps.worker.canary_materialization import CanaryMaterializationResult

    result = CanaryMaterializationResult.model_validate(payload)
    expected_path = (
        root
        / "outputs"
        / "analysis_memory_canary"
        / result.trade_date.isoformat()
        / run_id
        / "terminal-results"
        / f"{row.sha256}.json"
    ).resolve()
    if path != expected_path or result.run_id != run_id or result.status == "recompute_required":
        raise ValueError("terminal canary artifact lineage is invalid")
    return result


def select_previous_context_bundle_artifact(
    db: Session,
    *,
    current_run_id: str,
    asset: str,
    state_scope: str,
    canonical_state_id: str,
    cutoff_at: datetime | None,
    storage_root: str | Path,
) -> dict[str, Any] | None:
    """Return the latest validated prior Bundle for one canonical-state lineage.

    Portable SQL JSON predicates first restrict the scan to the requested
    registry lineage. The bounded matching-candidate scan is stable; exceeding
    it fails closed rather than silently selecting from an incomplete set.
    """

    if not _run_artifacts_available(db):
        return None
    current_run_uuid = _coerce_run_uuid(current_run_id)
    normalized_asset = str(asset).strip()
    normalized_scope = str(state_scope).strip()
    normalized_state_id = str(canonical_state_id).strip()
    if not all((normalized_asset, normalized_scope, normalized_state_id)):
        raise ValueError("ContextBundle selector lineage is incomplete")
    if cutoff_at is not None and (cutoff_at.tzinfo is None or cutoff_at.utcoffset() is None):
        raise ValueError("ContextBundle selector cutoff_at must be timezone-aware")

    rows = (
        db.query(RunArtifact)
        .filter(
            RunArtifact.artifact_type == ArtifactType.structured_json.value,
            RunArtifact.run_id != current_run_uuid,
            RunArtifact.artifact_metadata["artifact_family"].as_string() == _CONTEXT_BUNDLE_ARTIFACT_FAMILY,
            RunArtifact.artifact_metadata["asset"].as_string() == normalized_asset,
            RunArtifact.artifact_metadata["state_scope"].as_string() == normalized_scope,
            RunArtifact.artifact_metadata["canonical_state_id"].as_string() == normalized_state_id,
        )
        .order_by(RunArtifact.created_at.desc(), RunArtifact.artifact_id.desc())
        .limit(_CONTEXT_BUNDLE_SELECTOR_LIMIT + 1)
        .all()
    )
    if len(rows) > _CONTEXT_BUNDLE_SELECTOR_LIMIT:
        raise ValueError("ContextBundle selector candidate limit exceeded")

    candidates: list[tuple[datetime, datetime, dict[str, Any]]] = []
    for row in rows:
        if not _is_context_bundle_row(row):  # pragma: no cover - SQL predicate
            continue
        metadata = row.artifact_metadata
        if not isinstance(metadata, dict):  # guarded by _is_context_bundle_row
            continue
        descriptor = _validated_context_bundle_descriptor(
            row,
            storage_root=storage_root,
            expected_asset=normalized_asset,
            expected_state_scope=normalized_scope,
            expected_canonical_state_id=normalized_state_id,
        )
        bundle_cutoff_at = _context_bundle_cutoff_at(
            descriptor,
            storage_root=storage_root,
        )
        if cutoff_at is not None and bundle_cutoff_at > cutoff_at:
            continue
        created_at = row.created_at
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        candidates.append((bundle_cutoff_at, created_at.astimezone(timezone.utc), descriptor))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1], item[2]["file_path"]), reverse=True)
    latest = candidates[0]
    if len(candidates) > 1 and candidates[1][:2] == latest[:2]:
        raise ValueError("ContextBundle selector latest candidate is ambiguous")
    return latest[2]


def select_exact_context_bundle_artifact(
    db: Session,
    *,
    bundle_id: str,
    content_hash: str,
    run_id: str,
    asset: str,
    state_scope: str,
    base_canonical_state_id: str,
    current_run_id: str,
    storage_root: str | Path,
) -> dict[str, Any] | None:
    """Return one immutable Bundle by its complete persisted identity.

    This selector is intentionally different from the historical/latest
    selector above.  CAS recovery already knows which Bundle produced the
    current scoped head, so any missing or ambiguous identity must fail closed
    instead of choosing a nearby artifact.
    """

    if not _run_artifacts_available(db):
        return None
    source_run_uuid = _coerce_run_uuid(run_id)
    current_run_uuid = _coerce_run_uuid(current_run_id)
    if source_run_uuid == current_run_uuid:
        raise ValueError("ContextBundle continuity source must belong to a different run")
    expected = {
        "bundle_id": str(bundle_id).strip(),
        "content_hash": str(content_hash).strip(),
        "asset": str(asset).strip(),
        "state_scope": str(state_scope).strip(),
        "canonical_state_id": str(base_canonical_state_id).strip(),
    }
    if any(not value for value in expected.values()) or not _is_lowercase_sha256(
        expected["content_hash"]
    ):
        raise ValueError("ContextBundle exact selector identity is incomplete")

    rows = (
        db.query(RunArtifact)
        .filter(
            RunArtifact.run_id == source_run_uuid,
            RunArtifact.artifact_type == ArtifactType.structured_json.value,
            RunArtifact.artifact_metadata["artifact_family"].as_string()
            == _CONTEXT_BUNDLE_ARTIFACT_FAMILY,
            RunArtifact.artifact_metadata["bundle_id"].as_string() == expected["bundle_id"],
            RunArtifact.artifact_metadata["content_hash"].as_string() == expected["content_hash"],
            RunArtifact.artifact_metadata["asset"].as_string() == expected["asset"],
            RunArtifact.artifact_metadata["state_scope"].as_string() == expected["state_scope"],
            RunArtifact.artifact_metadata["canonical_state_id"].as_string()
            == expected["canonical_state_id"],
        )
        .order_by(RunArtifact.created_at.asc(), RunArtifact.artifact_id.asc())
        .limit(2)
        .all()
    )
    if not rows:
        return None
    if len(rows) != 1:
        raise ValueError("ContextBundle exact selector identity is ambiguous")
    return _validated_context_bundle_descriptor(
        rows[0],
        storage_root=storage_root,
        expected_run_id=run_id,
        expected_asset=expected["asset"],
        expected_state_scope=expected["state_scope"],
        expected_canonical_state_id=expected["canonical_state_id"],
        expected_bundle_id=expected["bundle_id"],
        expected_content_hash=expected["content_hash"],
    )


def _is_context_bundle_row(row: RunArtifact) -> bool:
    metadata = row.artifact_metadata
    return isinstance(metadata, dict) and metadata.get("artifact_family") == _CONTEXT_BUNDLE_ARTIFACT_FAMILY


def _validate_canary_recompute_descriptor(
    *,
    predecessor: dict[str, Any],
    recompute: dict[str, Any],
) -> None:
    predecessor_metadata = predecessor["metadata"]
    recompute_metadata = recompute["metadata"]
    if recompute_metadata.get("canary_recompute_attempt") != 1:
        raise ValueError("ContextBundle canary recompute attempt is invalid")
    expected = {
        "supersedes_bundle_id": predecessor_metadata.get("bundle_id"),
        "supersedes_bundle_hash": predecessor_metadata.get("content_hash"),
        "supersedes_canonical_state_id": predecessor_metadata.get("canonical_state_id"),
    }
    for key, value in expected.items():
        if not value or str(recompute_metadata.get(key) or "") != str(value):
            raise ValueError(f"ContextBundle canary recompute {key} is invalid")
    if recompute_metadata.get("canonical_state_id") == predecessor_metadata.get("canonical_state_id"):
        raise ValueError("ContextBundle canary recompute canonical state is stale")


def _validated_context_bundle_descriptor(
    row: RunArtifact,
    *,
    storage_root: str | Path,
    expected_run_id: str | None = None,
    expected_asset: str | None = None,
    expected_state_scope: str | None = None,
    expected_canonical_state_id: str | None = None,
    expected_bundle_id: str | None = None,
    expected_content_hash: str | None = None,
) -> dict[str, Any]:
    """Revalidate one registry row and reconstruct its recovery descriptor."""

    from apps.output.context_bundle import load_context_bundle

    metadata = row.artifact_metadata
    if not isinstance(metadata, dict) or metadata.get("artifact_family") != _CONTEXT_BUNDLE_ARTIFACT_FAMILY:
        raise ValueError("ContextBundle registry artifact family is invalid")
    required = {
        "bundle_id": str(metadata.get("bundle_id") or "").strip(),
        "content_hash": str(metadata.get("content_hash") or "").strip(),
        "run_id": str(metadata.get("run_id") or "").strip(),
        "canonical_state_id": str(metadata.get("canonical_state_id") or "").strip(),
        "schema_version": str(metadata.get("schema_version") or "").strip(),
        "asset": str(metadata.get("asset") or "").strip(),
        "state_scope": str(metadata.get("state_scope") or "").strip(),
    }
    if any(not value for value in required.values()) or not _is_lowercase_sha256(required["content_hash"]):
        raise ValueError("ContextBundle registry metadata identity is incomplete")
    if required["schema_version"] != _CONTEXT_BUNDLE_SCHEMA_VERSION:
        raise ValueError("ContextBundle registry schema version is unsupported")
    if required["run_id"] != str(row.run_id):
        raise ValueError("ContextBundle registry metadata run_id conflicts with row")
    if expected_run_id is not None and required["run_id"] != str(expected_run_id):
        raise ValueError("ContextBundle registry run_id does not match selector")
    for key, expected in (
        ("bundle_id", expected_bundle_id),
        ("content_hash", expected_content_hash),
        ("asset", expected_asset),
        ("state_scope", expected_state_scope),
        ("canonical_state_id", expected_canonical_state_id),
    ):
        if expected is not None and required[key] != expected:
            raise ValueError(f"ContextBundle registry {key} does not match selector")
    if _artifact_type_value(row.artifact_type) != ArtifactType.structured_json.value:
        raise ValueError("ContextBundle registry artifact_type is invalid")
    file_path = str(row.file_path or "").strip()
    file_sha256 = str(row.sha256 or "").strip()
    if not file_path or not _is_lowercase_sha256(file_sha256):
        raise ValueError("ContextBundle registry file identity is incomplete")
    storage = LocalFileSystemArtifactStorage(root=Path(storage_root).resolve())
    actual_file_sha256 = storage.compute_sha256(file_path)
    if actual_file_sha256 is None or actual_file_sha256 != file_sha256:
        raise ValueError("ContextBundle registry file hash mismatch")
    bundle = load_context_bundle(storage_root=storage_root, storage_relative_path=file_path)
    if (
        bundle.schema_version != _CONTEXT_BUNDLE_SCHEMA_VERSION
        or bundle.bundle_id != required["bundle_id"]
        or bundle.content_hash != required["content_hash"]
        or bundle.run_id != required["run_id"]
        or bundle.asset != required["asset"]
        or bundle.state_scope != required["state_scope"]
        or bundle.canonical_state_id != required["canonical_state_id"]
    ):
        raise ValueError("ContextBundle registry payload identity conflicts with metadata")
    return {
        "artifact_id": required["bundle_id"],
        "artifact_type": ArtifactType.structured_json.value,
        "file_path": file_path,
        "sha256": file_sha256,
        "content_type": row.content_type or "application/json",
        "source_refs": list(row.source_refs_data or []),
        "metadata": dict(metadata),
    }


def _context_bundle_cutoff_at(
    descriptor: dict[str, Any],
    *,
    storage_root: str | Path,
) -> datetime:
    from apps.output.context_bundle import load_context_bundle

    bundle = load_context_bundle(
        storage_root=storage_root,
        storage_relative_path=str(descriptor["file_path"]),
    )
    return bundle.cutoff_at.astimezone(timezone.utc)


def _is_lowercase_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _artifact_type_value(value: Any) -> str:
    return str(value.value) if isinstance(value, ArtifactType) else str(value)


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
            file_path = str(item.get("file_path") or item.get("path") or "").strip()
            if not file_path:
                continue
            normalized_item = {**item, "file_path": file_path}
            artifacts.append(
                (
                    ArtifactRef(
                        artifact_id=str(normalized_item.get("artifact_id") or f"{file_path}:{len(artifacts)}"),
                        artifact_type=_coerce_artifact_type(normalized_item.get("artifact_type"), file_path),
                        file_path=file_path,
                        version=normalized_item.get("version"),
                        generated_at=normalized_item.get("generated_at"),
                        storage_backend=normalized_item.get("storage_backend"),
                        sha256=normalized_item.get("sha256"),
                    ),
                    normalized_item,
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


def _artifact_quality_metadata(raw_artifact: dict[str, Any]) -> dict[str, Any] | None:
    metadata = {key: raw_artifact[key] for key in _ARTIFACT_QUALITY_METADATA_KEYS if key in raw_artifact}
    nested = raw_artifact.get("metadata")
    if isinstance(nested, dict):
        for key in _ARTIFACT_QUALITY_METADATA_KEYS:
            if key in nested:
                metadata.setdefault(key, nested[key])
    return metadata or None


def _persist_run_artifact(
    db: Session,
    *,
    run_uuid: uuid.UUID,
    task_id: uuid.UUID | None,
    run: TaskRun | None,
    artifact: ArtifactRef,
    raw_artifact: dict[str, Any],
    source_refs: list[dict[str, Any]] | None,
    input_snapshot_ids: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
    registry_artifact_id: uuid.UUID | None,
    storage: LocalFileSystemArtifactStorage,
    require_canonical_path: bool,
    flush: bool,
) -> RunArtifact:
    existing = (
        db.query(RunArtifact)
        .filter(
            RunArtifact.run_id == run_uuid,
            RunArtifact.task_id == task_id,
            RunArtifact.file_path == artifact.file_path,
            RunArtifact.artifact_type == artifact.artifact_type,
        )
        .first()
    )
    if existing is not None:
        return existing

    path_metadata = _extract_path_metadata(
        file_path=artifact.file_path,
        run_id=run_uuid,
        require_canonical_path=require_canonical_path,
    )
    row = RunArtifact(
        artifact_id=registry_artifact_id or uuid.uuid4(),
        run_id=run_uuid,
        task_id=task_id,
        artifact_type=artifact.artifact_type,
        file_path=artifact.file_path,
        storage_backend=artifact.storage_backend or storage.backend_name,
        sha256=artifact.sha256 or storage.compute_sha256(artifact.file_path),
        content_type=_optional_str(raw_artifact.get("content_type")) or _guess_content_type(artifact.file_path),
        byte_size=_optional_int(raw_artifact.get("byte_size")),
        generated_at=_parse_datetime(raw_artifact.get("generated_at")) or artifact.generated_at,
        source_refs_data=list(source_refs or []),
        source_refs=json.dumps(source_refs, ensure_ascii=False) if source_refs else None,
    )
    row.artifact_metadata = _build_artifact_metadata(
        run=run,
        artifact=artifact,
        input_snapshot_ids=input_snapshot_ids,
        path_metadata=path_metadata,
        extra_metadata=metadata,
    )
    row.metadata_json = json.dumps(row.artifact_metadata, ensure_ascii=False)
    db.add(row)
    if flush:
        db.flush()
    return row


def _enrich_raw_artifact(
    raw_artifact: dict[str, Any],
    *,
    storage: LocalFileSystemArtifactStorage,
) -> dict[str, Any]:
    enriched = dict(raw_artifact)
    file_path = _optional_str(enriched.get("file_path"))
    if not file_path:
        return enriched
    path = storage.resolve(file_path)
    if path.is_file():
        stat = path.stat()
        if not _optional_str(enriched.get("sha256")):
            enriched["sha256"] = storage.compute_sha256(file_path)
        if _optional_int(enriched.get("byte_size")) is None:
            enriched["byte_size"] = stat.st_size
        if _parse_datetime(enriched.get("generated_at")) is None:
            enriched["generated_at"] = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
    if not _optional_str(enriched.get("storage_backend")):
        enriched["storage_backend"] = storage.backend_name
    if not _optional_str(enriched.get("content_type")):
        enriched["content_type"] = _guess_content_type(file_path)
    return enriched


def _extract_path_metadata(
    *,
    file_path: str,
    run_id: uuid.UUID,
    require_canonical_path: bool,
) -> dict[str, Any]:
    parts = Path(file_path).parts
    reason: str | None = None
    layer_index = 1
    if Path(file_path).is_absolute():
        reason = "absolute_path"
    elif any(part in {"", ".", ".."} for part in parts):
        reason = "unsafe_path_segment"
    elif parts and parts[0] in _STORAGE_LAYERS:
        layer_index = 0
        if len(parts) < 5:
            reason = "missing_trade_date_run_id_or_artifact"
    elif len(parts) < 6 or parts[0] != "storage":
        reason = "unknown_storage_root"
    elif parts[1] not in _STORAGE_LAYERS:
        reason = "unknown_storage_layer"

    if reason is not None:
        if require_canonical_path:
            raise ValueError(f"canonical artifact path violation: {reason}: {file_path}")
        return {"canonical_path": False, "canonical_path_reason": reason}

    layer = parts[layer_index]
    domain = parts[layer_index + 1]
    context_start_index = layer_index + 2
    date_index = _find_trade_date_index(parts, start=context_start_index)
    if date_index is None or date_index + 2 >= len(parts):
        if require_canonical_path:
            raise ValueError(f"canonical artifact path violation: missing trade_date/run_id/artifact: {file_path}")
        return {
            "layer": layer,
            "domain": domain,
            "canonical_path": False,
            "canonical_path_reason": "missing_trade_date_run_id_or_artifact",
        }

    path_run_id = parts[date_index + 1]
    if path_run_id != str(run_id):
        if require_canonical_path:
            raise ValueError(
                f"canonical artifact path violation: path run_id={path_run_id} does not match registry run_id={run_id}"
            )
        return {
            "layer": layer,
            "domain": domain,
            "trade_date": parts[date_index],
            "path_run_id": path_run_id,
            "canonical_path": False,
            "canonical_path_reason": "run_id_mismatch",
        }

    context = list(parts[context_start_index:date_index])
    return {
        "layer": layer,
        "domain": domain,
        "trade_date": parts[date_index],
        "path_run_id": path_run_id,
        "path_context": context,
        "artifact_name": "/".join(parts[date_index + 2 :]),
        "canonical_path": True,
    }


def _find_trade_date_index(parts: tuple[str, ...], *, start: int = 3) -> int | None:
    for index, part in enumerate(parts[start:], start=start):
        try:
            date.fromisoformat(part)
        except ValueError:
            continue
        return index
    return None


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


def _guess_content_type(file_path: str) -> str | None:
    content_type, _ = mimetypes.guess_type(file_path)
    return content_type


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
