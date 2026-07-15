"""Append-only persistence for live-strategy recompute result attempts."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping


RESULT_SCHEMA_NAME = "live_strategy_recompute_result"
RESULT_SCHEMA_VERSION = "live_strategy_recompute_result.v1"
_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
_ATTEMPT_STATUSES = {"accepted", "blocked", "failed", "unchanged", "unavailable"}
_RESOLUTION_STATUSES = {"blocked", "eligible", "unresolved"}


class RecomputeResultStoreConflictError(ValueError):
    """Raised when a result id already exists with different content."""


@dataclass(frozen=True, slots=True)
class RecomputeResultWriteResult:
    path: Path
    created: bool
    artifact_ref: str


class RecomputeResultStore:
    """Persist already-produced recompute attempts without executing them."""

    def __init__(self, storage_root: str | os.PathLike[str]) -> None:
        root = Path(storage_root).expanduser()
        if not root.is_absolute():
            root = root.resolve()
        if root.exists() and (not root.is_dir() or root.is_symlink()):
            raise ValueError(f"storage_root must be a real directory: {root}")
        self.storage_root = root

    def write(self, result: Mapping[str, Any]) -> RecomputeResultWriteResult:
        payload = validate_recompute_result(result)
        path = self.result_path(payload)
        canonical = _canonical_bytes(payload)
        parent = path.parent
        parent.mkdir(parents=True, exist_ok=True)
        if not _is_within(parent, self.storage_root):
            raise ValueError("recompute result path escapes storage root")
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(canonical)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                if path.is_symlink() or not _is_within(path, self.storage_root):
                    raise ValueError(f"invalid recompute result path: {path}")
                try:
                    existing = _canonical_bytes(_read_json(path))
                except ValueError:
                    existing = None
                if existing != canonical:
                    raise RecomputeResultStoreConflictError(f"immutable recompute result already differs: {path}")
                created = False
            else:
                _fsync_directory(parent)
                created = True
            return RecomputeResultWriteResult(
                path=path,
                created=created,
                artifact_ref=path.relative_to(self.storage_root).as_posix(),
            )
        finally:
            temporary.unlink(missing_ok=True)

    def read(self, result_or_context: Mapping[str, Any]) -> dict[str, Any]:
        path = self.result_path(result_or_context)
        payload = _read_json(path)
        return validate_recompute_result(payload)

    def result_path(self, result_or_context: Mapping[str, Any]) -> Path:
        if not isinstance(result_or_context, Mapping):
            raise TypeError("recompute result context must be a mapping")
        trade_date = _trade_date(result_or_context.get("trade_date"))
        event_id = _safe_component(result_or_context.get("event_id"), "event_id")
        request_id = _safe_component(result_or_context.get("request_id"), "request_id")
        result_id = _safe_component(result_or_context.get("result_id"), "result_id")
        return (
            self.storage_root
            / "event_sla"
            / trade_date
            / event_id
            / "recompute_results"
            / request_id
            / result_id
            / "live_strategy_recompute_result.json"
        )


def validate_recompute_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a typed attempt while preserving its JSON-safe evidence payload."""

    if not isinstance(result, Mapping):
        raise ValueError("recompute result must be a JSON object")
    payload = _json_object(result)
    required = (
        "schema_name",
        "schema_version",
        "result_id",
        "request_id",
        "event_id",
        "trade_date",
        "attempted_at",
        "attempt_status",
        "resolution_status",
        "reason_codes",
        "input_snapshot_ids",
        "source_refs",
    )
    missing = [field for field in required if field not in payload]
    if missing:
        raise ValueError(f"recompute result missing required fields: {', '.join(missing)}")
    if payload["schema_name"] != RESULT_SCHEMA_NAME:
        raise ValueError(f"schema_name must be {RESULT_SCHEMA_NAME}")
    if payload["schema_version"] != RESULT_SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {RESULT_SCHEMA_VERSION}")
    for field in ("result_id", "request_id", "event_id"):
        payload[field] = _safe_component(payload[field], field)
    payload["trade_date"] = _trade_date(payload["trade_date"])
    payload["attempted_at"] = _timestamp(payload["attempted_at"], "attempted_at")
    if payload["attempt_status"] not in _ATTEMPT_STATUSES:
        raise ValueError("attempt_status is invalid")
    if payload["resolution_status"] not in _RESOLUTION_STATUSES:
        raise ValueError("resolution_status is invalid")
    if not isinstance(payload["reason_codes"], list) or any(
        not isinstance(item, str) or not item.strip() for item in payload["reason_codes"]
    ):
        raise ValueError("reason_codes must be a list of non-empty strings")
    payload["reason_codes"] = [item.strip() for item in payload["reason_codes"]]
    if not isinstance(payload["input_snapshot_ids"], dict):
        raise ValueError("input_snapshot_ids must be a JSON object")
    if not isinstance(payload["source_refs"], list) or any(
        not isinstance(item, dict) or not item for item in payload["source_refs"]
    ):
        raise ValueError("source_refs must be a list of non-empty JSON objects")
    return payload


def _safe_component(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or not _COMPONENT_RE.fullmatch(value):
        raise ValueError(f"invalid {name}; expected one safe path component")
    return value


def _trade_date(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("trade_date must be an ISO-8601 date")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError("trade_date must be an ISO-8601 date") from exc


def _timestamp(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be an ISO-8601 timestamp with timezone")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp with timezone") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_object(value: Mapping[str, Any]) -> dict[str, Any]:
    try:
        encoded = json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        payload = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ValueError("recompute result must be JSON serializable with finite values") from exc
    if not isinstance(payload, dict):
        raise ValueError("recompute result must be a JSON object")
    return payload


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    try:
        return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("recompute result must be JSON serializable with finite values") from exc


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid recompute result artifact: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"recompute result artifact must contain a JSON object: {path}")
    return payload


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return False
    return True


def _fsync_directory(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


__all__ = [
    "RESULT_SCHEMA_NAME",
    "RESULT_SCHEMA_VERSION",
    "RecomputeResultStore",
    "RecomputeResultStoreConflictError",
    "RecomputeResultWriteResult",
    "validate_recompute_result",
]
