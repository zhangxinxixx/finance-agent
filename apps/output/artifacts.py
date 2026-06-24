from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID


def _validate_path_component(name: str, value: str) -> str:
    value = str(value).strip()
    if not value:
        raise ValueError(f"{name} cannot be empty")
    if value in {".", ".."}:
        raise ValueError(f"{name} must not be a relative path component")
    if "/" in value or "\\" in value:
        raise ValueError(f"{name} must not contain path separators")
    if Path(value).is_absolute():
        raise ValueError(f"{name} must not be an absolute path")
    return value


def normalize_run_id(run_id: str | UUID | None = None) -> str:
    """Return a filesystem-safe run identifier."""
    if run_id is None:
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")

    return _validate_path_component("run_id", str(run_id))


def artifact_run_dir(
    storage_root: Path,
    *,
    layer: str,
    domain: str,
    date: str,
    run_id: str | UUID | None = None,
) -> Path:
    """Build a versioned artifact directory under ``storage_root/<layer>``."""
    safe_layer = _validate_path_component("layer", layer)
    safe_domain = _validate_path_component("domain", domain)
    safe_date = _validate_path_component("date", date)
    safe_run_id = normalize_run_id(run_id)

    storage_dir = storage_root.resolve()
    artifact_dir = (storage_dir / safe_layer / safe_domain / safe_date / safe_run_id).resolve()
    if not artifact_dir.is_relative_to(storage_dir):
        raise ValueError("artifact path escapes storage root")
    return artifact_dir
