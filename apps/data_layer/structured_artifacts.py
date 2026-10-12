"""Read-only archive validation; whole-JSON writes are disabled.

Legacy payload columns remain solely to preserve already written history.
Warehouse ETL may validate original files transiently and map typed fields.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from apps.runtime.artifact_storage import LOCAL_FS_STORAGE_BACKEND, LocalFileSystemArtifactStorage
from database.models.execution import RunArtifact

DEFAULT_MAX_BYTES = 16 * 1024 * 1024
ALLOWED_LAYERS = frozenset({"raw", "parsed", "features", "analysis", "outputs"})
# Operational/evaluation evidence keeps its original namespace and authority.
ALLOWED_NAMESPACES = ALLOWED_LAYERS | frozenset({"monitoring", "data_control", "orchestration", "probes"})
STRUCTURED_STATUSES = frozenset({"persisted", "rejected", "unavailable", "not_applicable"})

ERROR_STORAGE_BACKEND = "STRUCTURED_STORAGE_BACKEND_UNSUPPORTED"
ERROR_PATH_INVALID = "STRUCTURED_PATH_INVALID"
ERROR_PATH_ESCAPE = "STRUCTURED_PATH_ESCAPE"
ERROR_LAYER_INVALID = "STRUCTURED_LAYER_INVALID"
ERROR_FILE_MISSING = "STRUCTURED_FILE_MISSING"
ERROR_FILE_TOO_LARGE = "STRUCTURED_FILE_TOO_LARGE"
ERROR_FILE_SHA_MISSING = "STRUCTURED_FILE_SHA_MISSING"
ERROR_FILE_SHA_MISMATCH = "STRUCTURED_FILE_SHA_MISMATCH"
ERROR_UTF8_INVALID = "STRUCTURED_UTF8_INVALID"
ERROR_JSON_INVALID = "STRUCTURED_JSON_INVALID"
ERROR_JSON_NONFINITE = "STRUCTURED_JSON_NONFINITE"
ERROR_JSON_ROOT_UNSUPPORTED = "STRUCTURED_JSON_ROOT_UNSUPPORTED"
ERROR_SENSITIVE_CONTENT = "STRUCTURED_SENSITIVE_CONTENT"
ERROR_PAYLOAD_CONFLICT = "STRUCTURED_PAYLOAD_CONFLICT"
ERROR_SCHEMA_INVALID = "STRUCTURED_SCHEMA_INVALID"
ERROR_JSON_NUL = "STRUCTURED_JSON_NUL"

_SENSITIVE_KEYS = frozenset(
    {
        "access_key",
        "access_token",
        "api_key",
        "apikey",
        "authorization",
        "client_secret",
        "cookie",
        "password",
        "passwd",
        "private_key",
        "secret",
        "token",
    }
)
_URL_SECRET_KEYS = frozenset({"access_token", "api_key", "apikey", "key", "token"})
_KEY_NORMALIZER = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class StructuredArtifactResult:
    status: str
    error: str | None
    layer: str | None
    payload_sha256: str | None
    changed: bool


def persist_structured_artifact(
    row: RunArtifact,
    storage: LocalFileSystemArtifactStorage,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> StructuredArtifactResult:
    """Deprecated write boundary: whole JSON storage was superseded by the DWH."""
    raise ValueError("whole_json_storage_disabled_use_warehouse")


def preview_structured_artifact(
    row: RunArtifact,
    storage: LocalFileSystemArtifactStorage,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> StructuredArtifactResult:
    """Run the same bounded validation without mutating the row."""

    result, payload, _ = _inspect_artifact(row, storage, max_bytes=max_bytes)
    if result.status != "persisted":
        return replace(result, changed=_failure_changed(row, result))
    if result.status == "persisted" and row.structured_payload is not None:
        if row.structured_payload_sha256 != result.payload_sha256 or row.structured_payload != payload:
            return StructuredArtifactResult("rejected", ERROR_PAYLOAD_CONFLICT, result.layer, None, False)
        return StructuredArtifactResult(
            "persisted",
            None,
            result.layer,
            result.payload_sha256,
            row.structured_status != "persisted" or row.structured_error is not None,
        )
    return result


def canonical_payload_sha256(payload: dict[str, Any] | list[Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _inspect_artifact(
    row: RunArtifact,
    storage: LocalFileSystemArtifactStorage,
    *,
    max_bytes: int,
) -> tuple[StructuredArtifactResult, dict[str, Any] | list[Any] | None, str | None]:
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    layer, path_error, path = _resolve_registered_path(row, storage)
    if path_error:
        status = "unavailable" if path_error == ERROR_FILE_MISSING else "rejected"
        return StructuredArtifactResult(status, path_error, layer, None, True), None, None
    assert path is not None

    if not _is_json_artifact(row, path):
        return StructuredArtifactResult("not_applicable", None, layer, None, True), None, None

    try:
        if path.stat().st_size > max_bytes:
            return StructuredArtifactResult("rejected", ERROR_FILE_TOO_LARGE, layer, None, True), None, None
        with path.open("rb") as stream:
            raw = stream.read(max_bytes + 1)
    except OSError:
        return StructuredArtifactResult("unavailable", ERROR_FILE_MISSING, layer, None, True), None, None
    if len(raw) > max_bytes:
        return StructuredArtifactResult("rejected", ERROR_FILE_TOO_LARGE, layer, None, True), None, None
    if not row.sha256:
        return StructuredArtifactResult("rejected", ERROR_FILE_SHA_MISSING, layer, None, True), None, None
    if hashlib.sha256(raw).hexdigest().lower() != row.sha256.lower():
        return StructuredArtifactResult("rejected", ERROR_FILE_SHA_MISMATCH, layer, None, True), None, None

    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return StructuredArtifactResult("rejected", ERROR_UTF8_INVALID, layer, None, True), None, None
    try:
        payload = json.loads(text, parse_constant=_reject_nonfinite, object_pairs_hook=_unique_object)
    except _NonFiniteValue:
        return StructuredArtifactResult("rejected", ERROR_JSON_NONFINITE, layer, None, True), None, None
    except (ValueError, RecursionError):
        return StructuredArtifactResult("rejected", ERROR_JSON_INVALID, layer, None, True), None, None
    if not isinstance(payload, (dict, list)):
        return StructuredArtifactResult("rejected", ERROR_JSON_ROOT_UNSUPPORTED, layer, None, True), None, None
    try:
        _validate_json_values(payload)
        sensitive = _contains_sensitive_content(payload)
    except _NonFiniteValue:
        return StructuredArtifactResult("rejected", ERROR_JSON_NONFINITE, layer, None, True), None, None
    except (ValueError, RecursionError) as exc:
        code = ERROR_JSON_NUL if isinstance(exc, _NulValue) else ERROR_JSON_INVALID
        return StructuredArtifactResult("rejected", code, layer, None, True), None, None
    if sensitive:
        return StructuredArtifactResult("rejected", ERROR_SENSITIVE_CONTENT, layer, None, True), None, None

    try:
        digest = canonical_payload_sha256(payload)
    except (ValueError, RecursionError):
        return StructuredArtifactResult("rejected", ERROR_JSON_INVALID, layer, None, True), None, None
    schema_version = _schema_version(payload)
    if schema_version is not None and len(schema_version) > 128:
        return StructuredArtifactResult("rejected", ERROR_SCHEMA_INVALID, layer, None, True), None, None
    return StructuredArtifactResult("persisted", None, layer, digest, True), payload, schema_version


def _resolve_registered_path(
    row: RunArtifact,
    storage: LocalFileSystemArtifactStorage,
) -> tuple[str | None, str | None, Path | None]:
    if (row.storage_backend or LOCAL_FS_STORAGE_BACKEND) != storage.backend_name:
        return None, ERROR_STORAGE_BACKEND, None
    root_raw = Path(storage.root).expanduser()
    if root_raw.is_symlink() or not root_raw.is_dir():
        return None, ERROR_PATH_INVALID, None
    root = root_raw.resolve(strict=True)
    base = root if root.name == "storage" or not (root / "storage").is_dir() else root / "storage"
    if base.is_symlink():
        from apps.runtime.storage_paths import configured_storage_root
        configured = configured_storage_root()
        if configured is None or base.resolve() != configured:
            return None, ERROR_PATH_ESCAPE, None
        root = base = configured
    from apps.runtime.storage_paths import remap_storage_path
    try:
        registered = remap_storage_path(row.file_path, storage_root=base)
    except ValueError:
        return None, ERROR_PATH_ESCAPE, None
    if registered.is_absolute():
        try:
            registered = registered.relative_to(base)
        except ValueError:
            return None, ERROR_PATH_ESCAPE, None
    if not registered.parts or any(part in {"", ".", ".."} for part in registered.parts):
        return None, ERROR_PATH_INVALID, None

    parts = registered.parts
    if parts[0] == "storage":
        parts = parts[1:]
    if not parts:
        return None, ERROR_PATH_INVALID, None
    layer = parts[0]
    if layer not in ALLOWED_NAMESPACES:
        return layer, ERROR_LAYER_INVALID, None
    if parts != registered.parts and base == root and root.name != "storage":
        base = root / "storage"
    candidate = base.joinpath(*parts)
    try:
        resolved = candidate.resolve(strict=True)
    except (FileNotFoundError, NotADirectoryError, OSError):
        return layer, ERROR_FILE_MISSING, None
    try:
        resolved.relative_to(base)
    except ValueError:
        return layer, ERROR_PATH_ESCAPE, None
    if not resolved.is_file() or candidate.is_symlink():
        return layer, ERROR_PATH_ESCAPE, None
    current = candidate.parent
    while current != root and current != current.parent:
        if current.is_symlink():
            return layer, ERROR_PATH_ESCAPE, None
        current = current.parent
    return layer, None, resolved


def _is_json_artifact(row: RunArtifact, path: Path) -> bool:
    content_type = (row.content_type or "").split(";", 1)[0].strip().lower()
    return path.suffix.lower() == ".json" or content_type == "application/json" or content_type.endswith("+json")


def _apply_failure(row: RunArtifact, result: StructuredArtifactResult) -> None:
    row.structured_payload = None
    row.structured_payload_sha256 = None
    row.structured_schema_version = None
    row.structured_layer = result.layer
    row.structured_status = result.status
    row.structured_error = result.error


def _failure_changed(row: RunArtifact, result: StructuredArtifactResult) -> bool:
    if row.structured_payload is not None:
        return (row.structured_status, row.structured_error) != (result.status, result.error)
    return (
        row.structured_payload_sha256,
        row.structured_schema_version,
        row.structured_layer,
        row.structured_status,
        row.structured_error,
    ) != (None, None, result.layer, result.status, result.error)


class _NonFiniteValue(ValueError):
    pass


class _NulValue(ValueError):
    pass


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _validate_json_values(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise _NonFiniteValue("nonfinite")
    if isinstance(value, str) and ("\x00" in value or any(0xD800 <= ord(c) <= 0xDFFF for c in value)):
        raise _NulValue("invalid_unicode")
    if isinstance(value, dict):
        for key, nested in value.items():
            _validate_json_values(key)
            _validate_json_values(nested)
    elif isinstance(value, list):
        for nested in value:
            _validate_json_values(nested)


def _reject_nonfinite(value: str) -> None:
    raise _NonFiniteValue(value)


def _normalize_key(value: Any) -> str:
    camel = re.sub(r"([a-z])([A-Z])", r"\1_\2", str(value).strip())
    return _KEY_NORMALIZER.sub("_", camel.lower()).strip("_")


def _contains_sensitive_content(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            if _normalize_key(key) in _SENSITIVE_KEYS or _contains_sensitive_content(nested):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_sensitive_content(item) for item in value)
    if isinstance(value, str):
        parsed = urlsplit(value)
        if parsed.scheme in {"http", "https"}:
            return bool(parsed.username or parsed.password) or any(
                _normalize_key(key) in _URL_SECRET_KEYS for key, _ in parse_qsl(parsed.query, keep_blank_values=True)
            )
    return False


def _schema_version(payload: dict[str, Any] | list[Any]) -> str | None:
    if not isinstance(payload, dict) or "schema_version" not in payload:
        return None
    value = payload["schema_version"]
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    text = str(value)
    return text if text else None
