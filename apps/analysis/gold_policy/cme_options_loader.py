"""Fail-closed loader for same-trading-day CME options artifacts.

This module deliberately returns the persisted payload without adapting it into a
Gold Policy observation.  The adapter owns the interpretation; the loader owns
bounded discovery, provenance checks, and deterministic selection.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal
from urllib.parse import urlparse


CMEOptionsArtifactLoadStatus = Literal["available", "unavailable", "blocked"]
CMEOptionsArtifactQuality = Literal["accepted", "observe"]


@dataclass(frozen=True)
class CMEOptionsArtifactLoadResult:
    """The explicit result of a bounded CME options artifact lookup."""

    status: CMEOptionsArtifactLoadStatus
    reason_code: str
    artifact_path: Path | None
    run_id: str | None
    payload: Mapping[str, Any] | None
    source_status: str | None
    quality: CMEOptionsArtifactQuality | None
    generated_at: datetime | None
    input_snapshot_ids: Mapping[str, Any] | None


def load_cme_options_artifact(
    *, storage_root: Path, trade_date: date, decision_as_of: datetime
) -> CMEOptionsArtifactLoadResult:
    """Load exactly one valid same-day CME options artifact, or fail closed.

    The three artifact layouts are searched in their documented priority order.
    A lower-priority layout is considered only if no valid artifact exists in a
    higher-priority layout.  Multiple valid artifacts in one layout are never
    ordered by run id or timestamp: they are an explicit blocked state.
    """

    if decision_as_of.tzinfo is None or decision_as_of.utcoffset() is None:
        raise ValueError("decision_as_of must be timezone-aware")
    if decision_as_of.astimezone(UTC).date() != trade_date:
        return _result(
            status="blocked",
            reason_code="cme_options_decision_session_mismatch",
        )

    root = storage_root.resolve()
    if storage_root.is_symlink() or not root.is_dir():
        return _result(status="unavailable", reason_code="cme_options_artifact_storage_root_invalid")

    saw_candidate = False
    for candidates in _candidate_layers(root=root, trade_date=trade_date):
        valid: list[_VerifiedArtifact] = []
        for path in candidates:
            if not path.exists() and not path.is_symlink():
                continue
            saw_candidate = True
            artifact = _verify_artifact(path, root=root, trade_date=trade_date, decision_as_of=decision_as_of)
            if artifact is not None:
                valid.append(artifact)
        if len(valid) > 1:
            return _result(status="blocked", reason_code="cme_options_artifact_ambiguous")
        if len(valid) == 1:
            artifact = valid[0]
            if artifact.source_status == "FINAL":
                return _result(
                    status="available",
                    reason_code="cme_options_artifact_final",
                    artifact=artifact,
                    quality="accepted",
                )
            return _result(
                status="available",
                reason_code="cme_options_artifact_prelim_observe",
                artifact=artifact,
                quality="observe",
            )

    return _result(
        status="unavailable",
        reason_code=("cme_options_artifact_invalid" if saw_candidate else "cme_options_artifact_missing"),
    )


@dataclass(frozen=True)
class _VerifiedArtifact:
    path: Path
    run_id: str
    payload: Mapping[str, Any]
    source_status: Literal["PRELIM", "FINAL"]
    generated_at: datetime
    input_snapshot_ids: Mapping[str, Any]


def _candidate_layers(*, root: Path, trade_date: date) -> tuple[tuple[Path, ...], ...]:
    day = trade_date.isoformat()
    return (
        _run_directory_candidates(root / "features" / "cme" / day),
        _run_directory_candidates(root / "outputs" / "cme" / day),
        (root / "outputs" / "cme_options" / day / "options_analysis.json",),
    )


def _run_directory_candidates(base: Path) -> tuple[Path, ...]:
    if not base.exists() or not base.is_dir() or base.is_symlink():
        return ()
    return tuple(sorted((item / "options_analysis.json" for item in base.iterdir()), key=lambda path: path.as_posix()))


def _verify_artifact(path: Path, *, root: Path, trade_date: date, decision_as_of: datetime) -> _VerifiedArtifact | None:
    try:
        if not _is_non_symlink_path_within_root(path, root=root):
            return None
        resolved = path.resolve(strict=True)
        if not resolved.is_file() or not resolved.is_relative_to(root):
            return None
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None

    if not isinstance(payload, dict) or str(payload.get("trade_date") or "") != trade_date.isoformat():
        return None
    data_source = payload.get("data_source")
    if not isinstance(data_source, Mapping):
        return None
    if str(data_source.get("report_date") or "") != trade_date.isoformat():
        return None
    status = data_source.get("status")
    if status not in {"PRELIM", "FINAL"}:
        return None
    if not _is_official_cme_url(data_source.get("source_url")):
        return None
    if not isinstance(data_source.get("product"), str) or not data_source["product"].strip():
        return None
    input_snapshot_ids = data_source.get("input_snapshot_ids")
    if not isinstance(input_snapshot_ids, Mapping):
        return None
    if not _has_verifiable_lineage(payload, input_snapshot_ids=input_snapshot_ids):
        return None
    path_run_id = _run_id_from_path(resolved, root=root, trade_date=trade_date)
    declared_run_id = payload.get("run_id")
    if declared_run_id is not None and (
        not isinstance(declared_run_id, str)
        or not declared_run_id.strip()
        or (path_run_id is not None and declared_run_id != path_run_id)
    ):
        return None
    run_id = declared_run_id or path_run_id or "legacy"
    generated_at = _parse_aware_datetime(payload.get("generated_at"))
    if generated_at is None or generated_at > decision_as_of:
        return None
    return _VerifiedArtifact(
        path=resolved,
        run_id=run_id,
        payload=_freeze_mapping(payload),
        source_status=status,
        generated_at=generated_at,
        input_snapshot_ids=_freeze_mapping(dict(input_snapshot_ids)),
    )


def _is_non_symlink_path_within_root(path: Path, *, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return False
    return True


def _run_id_from_path(path: Path, *, root: Path, trade_date: date) -> str | None:
    relative = path.relative_to(root).parts
    day = trade_date.isoformat()
    if len(relative) == 5 and relative[:3] in {
        ("features", "cme", day),
        ("outputs", "cme", day),
    }:
        return relative[3]
    if relative == ("outputs", "cme_options", day, "options_analysis.json"):
        return None
    return ""


def _has_verifiable_lineage(payload: Mapping[str, Any], *, input_snapshot_ids: Mapping[str, Any]) -> bool:
    if any(
        isinstance(key, str) and key and isinstance(value, str) and value.strip()
        for key, value in input_snapshot_ids.items()
    ):
        return True
    source_trace = payload.get("source_trace")
    return isinstance(source_trace, list) and any(
        isinstance(item, Mapping)
        and any(
            isinstance(item.get(key), str) and item[key].strip() for key in ("source_ref", "source_url", "reference")
        )
        for item in source_trace
    )


def _parse_aware_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _is_official_cme_url(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    parsed = urlparse(value.strip())
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (host == "cmegroup.com" or host.endswith(".cmegroup.com"))


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType({key: _freeze_value(item) for key, item in value.items()})


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, list):
        return tuple(_freeze_value(item) for item in value)
    return value


def _result(
    *,
    status: CMEOptionsArtifactLoadStatus,
    reason_code: str,
    artifact: _VerifiedArtifact | None = None,
    quality: CMEOptionsArtifactQuality | None = None,
) -> CMEOptionsArtifactLoadResult:
    return CMEOptionsArtifactLoadResult(
        status=status,
        reason_code=reason_code,
        artifact_path=artifact.path if artifact else None,
        run_id=artifact.run_id if artifact else None,
        payload=artifact.payload if artifact else None,
        source_status=artifact.source_status if artifact else None,
        quality=quality,
        generated_at=artifact.generated_at if artifact else None,
        input_snapshot_ids=artifact.input_snapshot_ids if artifact else None,
    )
