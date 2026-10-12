"""Artifact storage abstraction for registry-backed outputs."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from apps.runtime.storage_paths import configured_storage_root, remap_storage_path

LOCAL_FS_STORAGE_BACKEND = "local_fs"
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class LocalFileSystemArtifactStorage:
    """Minimal local filesystem backend used by the current registry."""

    root: Path = _PROJECT_ROOT
    backend_name: str = LOCAL_FS_STORAGE_BACKEND

    def resolve(self, file_path: str) -> Path:
        storage_root = configured_storage_root() if self.root == _PROJECT_ROOT else None
        path = remap_storage_path(file_path, storage_root=storage_root or self.root / "storage")
        if path.is_absolute():
            return path
        if storage_root and path.parts[:1] == ("storage",):
            return storage_root.joinpath(*path.parts[1:])
        return self.root / path

    def exists(self, file_path: str) -> bool:
        return self.resolve(file_path).is_file()

    def compute_sha256(self, file_path: str) -> str | None:
        path = self.resolve(file_path)
        if not path.is_file():
            return None
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def read_text(self, file_path: str) -> str:
        return self.resolve(file_path).read_text(encoding="utf-8")

    def open_bytes(self, file_path: str) -> bytes:
        return self.resolve(file_path).read_bytes()


def get_artifact_storage(backend_name: str | None = None) -> LocalFileSystemArtifactStorage:
    """Return the configured artifact storage backend.

    Only local filesystem storage is implemented today, but the call-site shape
    is explicit so S3/hybrid backends can slot in without changing registry
    consumers.
    """

    if backend_name in {None, "", LOCAL_FS_STORAGE_BACKEND}:
        return LocalFileSystemArtifactStorage()
    raise ValueError(f"Unsupported artifact storage backend: {backend_name}")
