"""Immutable storage for AnalysisContextBundle artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from apps.analysis.context_bundle.schemas import AnalysisContextBundle
from apps.output.artifacts import _validate_path_component
from apps.runtime.immutable_artifact import (
    ImmutableArtifactConflictError,
    immutable_json_item,
    write_immutable_artifact_bundle,
)


class ContextBundleLoadError(ValueError):
    """Persisted bundle is missing, unsafe, or violates its content hash."""


class ContextBundleConflictError(ImmutableArtifactConflictError):
    """A stable bundle identity was reused with different content."""


@dataclass(frozen=True, slots=True)
class ContextBundleWriteResult:
    storage_relative_path: str
    content_hash: str
    file_sha256: str
    written: bool
    registry_artifact: dict[str, Any]


def write_context_bundle(
    *,
    storage_root: str | Path,
    bundle: AnalysisContextBundle | dict[str, Any],
) -> ContextBundleWriteResult:
    validated = _validate_bundle(bundle)
    storage_dir = Path(storage_root).resolve()
    relative = Path(
        "outputs",
        "context_bundles",
        _validate_path_component("asset", validated.asset),
        _validate_path_component("run_id", validated.run_id),
        f"{_validate_path_component('bundle_id', validated.bundle_id)}.json",
    )
    target = (storage_dir / relative).resolve()
    if not target.is_relative_to(storage_dir):
        raise ValueError("context bundle path escapes storage root")
    try:
        [result] = write_immutable_artifact_bundle(
            [immutable_json_item(target, validated.model_dump(mode="json"))],
            storage_root=storage_dir,
        )
    except ImmutableArtifactConflictError as exc:
        raise ContextBundleConflictError(str(exc)) from exc
    if not result.storage_relative_path:
        raise RuntimeError("context bundle writer did not produce a storage-relative path")
    descriptor = {
        "artifact_id": validated.bundle_id,
        "artifact_type": "structured_json",
        "file_path": result.storage_relative_path,
        "sha256": result.content_sha256,
        "content_type": "application/json",
        "source_refs": [dict(item) for item in validated.source_refs],
        "metadata": {
            "artifact_family": "analysis_context_bundle",
            "schema_version": validated.schema_version,
            "bundle_id": validated.bundle_id,
            "content_hash": validated.content_hash,
            "asset": validated.asset,
            "run_id": validated.run_id,
            "canonical_state_id": validated.canonical_state_id,
            "estimated_tokens": validated.budget_trace.estimated_tokens,
        },
    }
    return ContextBundleWriteResult(
        storage_relative_path=result.storage_relative_path,
        content_hash=validated.content_hash,
        file_sha256=result.content_sha256,
        written=result.written,
        registry_artifact=descriptor,
    )


def load_context_bundle(
    *, storage_root: str | Path, storage_relative_path: str
) -> AnalysisContextBundle:
    storage_dir = Path(storage_root).resolve()
    relative = _validate_relative_path(storage_relative_path)
    path = (storage_dir / relative).resolve()
    if not path.is_relative_to(storage_dir):
        raise ContextBundleLoadError("context bundle path escapes storage root")
    if not path.is_file():
        raise ContextBundleLoadError("context bundle artifact does not exist")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        bundle = AnalysisContextBundle.model_validate(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
        raise ContextBundleLoadError("context bundle failed JSON/schema/hash validation") from exc
    expected = (
        "outputs",
        "context_bundles",
        bundle.asset,
        bundle.run_id,
        f"{bundle.bundle_id}.json",
    )
    if relative.parts != expected:
        raise ContextBundleLoadError("context bundle payload identity does not match path")
    return bundle


def _validate_bundle(
    bundle: AnalysisContextBundle | dict[str, Any],
) -> AnalysisContextBundle:
    payload = bundle.model_dump(mode="json") if isinstance(bundle, AnalysisContextBundle) else bundle
    return AnalysisContextBundle.model_validate(payload)


def _validate_relative_path(value: str) -> Path:
    path = Path(str(value).strip())
    if path.is_absolute() or not path.parts:
        raise ContextBundleLoadError("context bundle path must be storage-relative")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ContextBundleLoadError("context bundle path contains unsafe segments")
    if len(path.parts) != 5 or path.parts[:2] != ("outputs", "context_bundles"):
        raise ContextBundleLoadError("context bundle path has an invalid shape")
    if path.suffix != ".json":
        raise ContextBundleLoadError("context bundle artifact must be JSON")
    return path
