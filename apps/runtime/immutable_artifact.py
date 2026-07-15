from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import tempfile
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

ArtifactEncoding = Literal["json", "text"]


class ImmutableArtifactConflictError(FileExistsError):
    """Raised when an immutable artifact path already has different content."""


@dataclass(frozen=True, slots=True)
class ImmutableArtifactItem:
    path: Path
    content: bytes
    encoding: ArtifactEncoding


@dataclass(frozen=True, slots=True)
class ImmutableArtifactWriteResult:
    target_path: str
    storage_relative_path: str | None
    content_sha256: str
    written: bool


def immutable_json_item(path: str | Path, payload: dict[str, Any]) -> ImmutableArtifactItem:
    content = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")
    return ImmutableArtifactItem(path=Path(path), content=content, encoding="json")


def immutable_text_item(path: str | Path, text: str) -> ImmutableArtifactItem:
    return ImmutableArtifactItem(path=Path(path), content=text.encode("utf-8"), encoding="text")


def write_immutable_artifact_bundle(
    items: list[ImmutableArtifactItem],
    *,
    storage_root: str | Path | None = None,
) -> list[ImmutableArtifactWriteResult]:
    """Preflight an immutable bundle, then atomically fill only missing files."""

    if not items:
        return []
    paths = [item.path.resolve() for item in items]
    if len(set(paths)) != len(paths):
        raise ValueError("immutable artifact bundle contains duplicate target paths")
    relative_paths = [_storage_relative_path(path, storage_root) for path in paths]
    atomic_directory_result = _write_new_directory_bundle(items, paths, relative_paths)
    if atomic_directory_result is not None:
        return atomic_directory_result
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)

    written: dict[Path, bool] = {}
    with ExitStack() as stack:
        lock_handles = []
        for path in sorted(paths, key=str):
            lock_path = path.with_name(f".{path.name}.lock")
            handle = stack.enter_context(lock_path.open("a+", encoding="utf-8"))
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            lock_handles.append(handle)

        for item, path in zip(items, paths, strict=True):
            if not path.exists():
                continue
            if _existing_content(path, item.encoding) != item.content:
                raise ImmutableArtifactConflictError(
                    f"Immutable artifact already exists with different content: {path}"
                )

        created_paths: list[Path] = []
        try:
            for item, path in zip(items, paths, strict=True):
                if path.exists():
                    written[path] = False
                    continue
                _write_bytes_atomically(path, item.content)
                created_paths.append(path)
                written[path] = True
        except Exception:
            for created_path in created_paths:
                created_path.unlink(missing_ok=True)
                _fsync_directory(created_path.parent)
            raise

        for handle in reversed(lock_handles):
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    return [
        ImmutableArtifactWriteResult(
            target_path=str(path),
            storage_relative_path=relative_path,
            content_sha256=hashlib.sha256(item.content).hexdigest(),
            written=written[path],
        )
        for item, path, relative_path in zip(items, paths, relative_paths, strict=True)
    ]


def _existing_content(path: Path, encoding: ArtifactEncoding) -> bytes | None:
    if encoding == "text":
        try:
            return path.read_bytes()
        except OSError:
            return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        return (
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            + "\n"
        ).encode("utf-8")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None


def _write_bytes_atomically(path: Path, content: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        _fsync_directory(path.parent)
    finally:
        temporary_path.unlink(missing_ok=True)


def _write_new_directory_bundle(
    items: list[ImmutableArtifactItem],
    paths: list[Path],
    relative_paths: list[str | None],
) -> list[ImmutableArtifactWriteResult] | None:
    if len(items) < 2 or len({path.parent for path in paths}) != 1:
        return None
    target_dir = paths[0].parent
    if target_dir.exists():
        return None
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target_dir.parent / f".{target_dir.name}.bundle.lock"
    with lock_path.open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        if target_dir.exists():
            return None
        staging = Path(tempfile.mkdtemp(prefix=f".{target_dir.name}.bundle.", dir=target_dir.parent))
        try:
            manifest_items: list[dict[str, Any]] = []
            for item, path in zip(items, paths, strict=True):
                staged_path = staging / path.name
                _write_bytes_file(staged_path, item.content)
                manifest_items.append(
                    {
                        "path": path.name,
                        "sha256": hashlib.sha256(item.content).hexdigest(),
                        "encoding": item.encoding,
                    }
                )
            manifest = json.dumps(
                {"version": 1, "status": "committed", "items": manifest_items},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ).encode("utf-8") + b"\n"
            _write_bytes_file(staging / ".bundle-manifest.json", manifest)
            _fsync_directory(staging)
            os.replace(staging, target_dir)
            _fsync_directory(target_dir.parent)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
    return [
        ImmutableArtifactWriteResult(
            target_path=str(path),
            storage_relative_path=relative_path,
            content_sha256=hashlib.sha256(item.content).hexdigest(),
            written=True,
        )
        for item, path, relative_path in zip(items, paths, relative_paths, strict=True)
    ]


def _write_bytes_file(path: Path, content: bytes) -> None:
    with path.open("wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _storage_relative_path(path: Path, storage_root: str | Path | None) -> str | None:
    if storage_root is None:
        return None
    root = Path(storage_root).resolve()
    try:
        return path.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f"artifact path must be inside storage_root: {path}") from exc
