"""Immutable filesystem artifacts for accepted analysis-state reviews."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from apps.analysis.state.hashing import content_hash
from apps.output.artifacts import _validate_path_component
from apps.runtime.immutable_artifact import immutable_json_item, write_immutable_artifact_bundle


@dataclass(frozen=True, slots=True)
class AnalysisStateReviewWriteResult:
    artifact_id: str
    storage_relative_path: str
    content_hash: str
    file_sha256: str
    written: bool


def review_artifact_id(*, candidate_state_id: str, request_id: str) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"finance-agent:analysis-state-review:{candidate_state_id}:{request_id}",
        )
    )


def write_analysis_state_review(
    *,
    storage_root: str | Path,
    payload: dict[str, Any],
) -> AnalysisStateReviewWriteResult:
    storage_dir = Path(storage_root).resolve()
    artifact_id = review_artifact_id(
        candidate_state_id=str(payload["candidate_state_id"]),
        request_id=str(payload["request_id"]),
    )
    expected_id = str(payload.get("artifact_id") or "")
    if expected_id != artifact_id:
        raise ValueError("review artifact identity does not match candidate/request")
    relative = Path(
        "outputs",
        "analysis_state_reviews",
        _validate_path_component("asset", str(payload["asset"])),
        _validate_path_component("run_id", str(payload["run_id"])),
        f"{_validate_path_component('artifact_id', artifact_id)}.json",
    )
    target = (storage_dir / relative).resolve()
    if not target.is_relative_to(storage_dir):
        raise ValueError("analysis state review path escapes storage root")
    [result] = write_immutable_artifact_bundle(
        [immutable_json_item(target, payload)],
        storage_root=storage_dir,
    )
    if not result.storage_relative_path:
        raise RuntimeError("analysis state review writer did not return a storage-relative path")
    return AnalysisStateReviewWriteResult(
        artifact_id=artifact_id,
        storage_relative_path=result.storage_relative_path,
        content_hash=content_hash(payload, exclude_keys=frozenset()),
        file_sha256=result.content_sha256,
        written=result.written,
    )
