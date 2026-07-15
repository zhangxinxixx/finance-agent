"""Immutable storage for versioned FigureFact artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from apps.analysis.figure_facts import (
    FigureFact,
    FigureFactQualityStatus,
    validate_figure_fact,
)
from apps.output.artifacts import _validate_path_component
from apps.runtime.immutable_artifact import (
    ImmutableArtifactConflictError,
    immutable_json_item,
    write_immutable_artifact_bundle,
)


class FigureFactLoadError(ValueError):
    """Raised when a persisted FigureFact is invalid or does not match its path."""


class FigureFactConflictError(ImmutableArtifactConflictError):
    """Raised when a FigureFact id is reused for different semantic content."""


@dataclass(frozen=True, slots=True)
class FigureFactWriteResult:
    storage_relative_path: str
    content_hash: str
    file_sha256: str
    written: bool
    registry_artifact: dict[str, Any]


def write_figure_fact(
    *,
    storage_root: str | Path,
    trade_date: str,
    fact: FigureFact | dict[str, Any],
) -> FigureFactWriteResult:
    """Write one immutable FigureFact and return a RunArtifact-ready descriptor."""

    validated = validate_figure_fact(fact)
    artifact_path = _figure_fact_path(
        storage_root=storage_root,
        trade_date=trade_date,
        fact=validated,
    )
    storage_dir = Path(storage_root).resolve()

    if artifact_path.exists():
        existing = load_figure_fact(
            storage_root=storage_dir,
            storage_relative_path=artifact_path.relative_to(storage_dir).as_posix(),
        )
        if existing.content_hash != validated.content_hash:
            raise FigureFactConflictError(
                "FigureFact id already exists with a different content_hash: "
                f"{validated.figure_fact_id}"
            )

    try:
        [write_result] = write_immutable_artifact_bundle(
            [immutable_json_item(artifact_path, validated.model_dump(mode="json"))],
            storage_root=storage_dir,
        )
    except ImmutableArtifactConflictError as exc:
        raise FigureFactConflictError(str(exc)) from exc

    relative_path = write_result.storage_relative_path
    if not relative_path:
        raise RuntimeError("FigureFact writer failed to produce a storage-relative path")
    registry_artifact = {
        "artifact_id": validated.figure_fact_id,
        "artifact_type": "figure_fact_json",
        "file_path": relative_path,
        "sha256": write_result.content_sha256,
        "content_type": "application/json",
        "source_refs": [dict(validated.source_ref)],
        "metadata": {
            "schema_version": validated.schema_version,
            "figure_fact_id": validated.figure_fact_id,
            "figure_id": validated.figure_id,
            "report_id": validated.report_id,
            "page_no": validated.page_no,
            "quality_status": validated.quality_status.value,
            "confirmed_evidence": (
                validated.quality_status is FigureFactQualityStatus.ACCEPTED
            ),
            "content_hash": validated.content_hash,
            "image_content_hash": validated.image_content_hash,
        },
    }
    return FigureFactWriteResult(
        storage_relative_path=relative_path,
        content_hash=validated.content_hash,
        file_sha256=write_result.content_sha256,
        written=write_result.written,
        registry_artifact=registry_artifact,
    )


def load_figure_fact(
    *, storage_root: str | Path, storage_relative_path: str
) -> FigureFact:
    """Load and validate a storage-relative FigureFact path and payload."""

    storage_dir = Path(storage_root).resolve()
    relative = _validate_storage_relative_path(storage_relative_path)
    path = (storage_dir / relative).resolve()
    if not path.is_relative_to(storage_dir):
        raise FigureFactLoadError("FigureFact path escapes storage root")
    if not path.is_file():
        raise FigureFactLoadError(f"FigureFact artifact does not exist: {relative.as_posix()}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FigureFactLoadError(f"FigureFact artifact is not readable JSON: {relative}") from exc
    if not isinstance(payload, dict):
        raise FigureFactLoadError("FigureFact artifact root must be an object")
    try:
        fact = FigureFact.model_validate(payload)
    except ValidationError as exc:
        raise FigureFactLoadError("FigureFact artifact failed schema/hash validation") from exc
    _validate_path_matches_fact(relative, fact)
    return fact


def _figure_fact_path(
    *, storage_root: str | Path, trade_date: str, fact: FigureFact
) -> Path:
    try:
        date.fromisoformat(trade_date)
    except ValueError as exc:
        raise ValueError("trade_date must be an ISO date") from exc
    safe_date = _validate_path_component("trade_date", trade_date)
    components = (
        _validate_path_component("asset", fact.asset),
        _validate_path_component("report_id", fact.report_id),
        safe_date,
        _validate_path_component("created_by_run_id", fact.created_by_run_id),
        _validate_path_component("figure_id", fact.figure_id),
    )
    storage_dir = Path(storage_root).resolve()
    artifact_dir = (storage_dir / "outputs" / "figure_facts").joinpath(*components).resolve()
    if not artifact_dir.is_relative_to(storage_dir):
        raise ValueError("FigureFact artifact path escapes storage root")
    filename = f"{_validate_path_component('figure_fact_id', fact.figure_fact_id)}.json"
    return artifact_dir / filename


def _validate_storage_relative_path(value: str) -> Path:
    path = Path(str(value).strip())
    if path.is_absolute() or not path.parts:
        raise FigureFactLoadError("FigureFact path must be storage-relative")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise FigureFactLoadError("FigureFact path contains unsafe segments")
    if path.parts[:2] != ("outputs", "figure_facts") or path.suffix != ".json":
        raise FigureFactLoadError("path is not a FigureFact JSON artifact")
    return path


def _validate_path_matches_fact(relative: Path, fact: FigureFact) -> None:
    parts = relative.parts
    if len(parts) != 8:
        raise FigureFactLoadError("FigureFact path has an invalid canonical shape")
    _, _, asset, report_id, trade_date, run_id, figure_id, filename = parts
    try:
        date.fromisoformat(trade_date)
    except ValueError as exc:
        raise FigureFactLoadError("FigureFact path has an invalid trade date") from exc
    expected = (
        fact.asset,
        fact.report_id,
        fact.created_by_run_id,
        fact.figure_id,
        f"{fact.figure_fact_id}.json",
    )
    actual = (asset, report_id, run_id, figure_id, filename)
    if actual != expected:
        raise FigureFactLoadError("FigureFact payload identity does not match artifact path")
