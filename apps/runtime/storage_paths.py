"""Explicit local storage aliases preserve immutable historical references."""

import os
from pathlib import Path


def configured_storage_root() -> Path | None:
    value = os.getenv("FINANCE_AGENT_STORAGE_ROOT")
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("FINANCE_AGENT_STORAGE_ROOT must be an absolute directory")
    return path.resolve()


def remap_storage_path(path: str | Path, *, storage_root: Path) -> Path:
    """Translate only configured absolute roots, never search arbitrary files."""
    candidate = Path(path)
    if ".." in candidate.parts:
        raise ValueError("artifact path traversal")
    if not candidate.is_absolute():
        return candidate
    aliases = os.getenv("FINANCE_AGENT_LEGACY_STORAGE_ROOTS", "").split(os.pathsep)
    for value in aliases:
        if not value:
            continue
        alias = Path(value).expanduser()
        if not alias.is_absolute() or ".." in alias.parts:
            raise ValueError("legacy storage root must be absolute")
        try:
            suffix = candidate.relative_to(alias)
        except ValueError:
            continue
        return Path(storage_root) / suffix
    return candidate


def project_artifact_path(path: str | Path, *, project_root: Path) -> Path:
    storage_root = project_root / "storage"
    resolved_root = storage_root.resolve()
    if resolved_root != project_root.resolve() / "storage":
        if configured_storage_root() != resolved_root:
            raise ValueError("external storage root must be explicitly configured")
    candidate = remap_storage_path(path, storage_root=storage_root)
    return candidate if candidate.is_absolute() else project_root / candidate
