"""Artifact storage abstraction for registry-backed outputs."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

LOCAL_FS_STORAGE_BACKEND = "local_fs"
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class LocalFileSystemArtifactStorage:
    """Minimal local filesystem backend used by the current registry."""

    root: Path = _PROJECT_ROOT
    backend_name: str = LOCAL_FS_STORAGE_BACKEND

    def resolve(self, file_path: str) -> Path:
        path = Path(file_path)
        if path.is_absolute():
            return path
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
