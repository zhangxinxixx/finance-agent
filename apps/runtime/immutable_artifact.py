from __future__ import annotations

import fcntl
import hashlib
import json
import os
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

        for item, path in zip(items, paths, strict=True):
            if path.exists():
                written[path] = False
                continue
            _write_bytes_atomically(path, item.content)
            written[path] = True

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
    finally:
        temporary_path.unlink(missing_ok=True)


def _storage_relative_path(path: Path, storage_root: str | Path | None) -> str | None:
    if storage_root is None:
        return None
    root = Path(storage_root).resolve()
    try:
        return path.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f"artifact path must be inside storage_root: {path}") from exc
