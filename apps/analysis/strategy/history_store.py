"""Append-only local history for immutable live-strategy versions.

The store persists already-built strategy mappings.  It deliberately does not
recompute, enrich, or interpret a strategy; its only responsibilities are
partitioning, immutable writes, and deterministic reads for later diff and
evaluation work.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

HISTORY_SCHEMA_VERSION = "live_strategy.history.v1"
MAX_LIST_LIMIT = 100
_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class StrategyHistoryConflictError(ValueError):
    """Raised when an immutable strategy version already has other content."""


@dataclass(frozen=True, slots=True)
class HistoryWriteResult:
    """Stable references returned by an append-only write."""

    path: Path
    created: bool
    artifact_ref: str
    schema_version: str
    strategy_version: str


class StrategyHistoryStore:
    """Store strategy versions below an explicitly supplied local directory."""

    def __init__(self, storage_root: str | os.PathLike[str]) -> None:
        root = Path(storage_root).expanduser()
        if not root.is_absolute():
            root = root.resolve()
        if root.exists() and (not root.is_dir() or root.is_symlink()):
            raise ValueError(f"storage_root must be a real directory: {root}")
        self.storage_root = root

    def write(self, strategy: Mapping[str, Any]) -> HistoryWriteResult:
        """Persist one strategy version without replacing an existing file."""

        payload, asset, strategy_id, strategy_version, trade_date = _validated_payload(strategy)
        path = self._path(asset, trade_date, strategy_id, strategy_version)
        return self._write_json(path, payload, strategy_version)

    def read(self, ref_or_path: str | os.PathLike[str] | Path) -> dict[str, Any]:
        """Read a stored strategy by ``artifact_ref`` or an absolute path."""

        path = self._safe_existing_path(ref_or_path)
        payload = _read_json(path)
        _validated_payload(payload)
        return payload

    def list_latest(
        self,
        *,
        asset: str,
        strategy_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """List immutable versions, newest first, with stable history refs."""

        safe_asset = _safe_component(asset, "asset")
        safe_strategy_id = _safe_component(strategy_id, "strategy_id") if strategy_id is not None else None
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIST_LIMIT:
            raise ValueError(f"limit must be an integer between 1 and {MAX_LIST_LIMIT}")

        base = self.storage_root / "strategy_history" / safe_asset
        if not base.exists():
            return []
        if base.is_symlink() or not base.is_dir():
            raise ValueError(f"invalid strategy history directory: {base}")

        records: list[dict[str, Any]] = []
        for path in base.rglob("*.json"):
            if path.is_symlink() or not path.is_file():
                continue
            if not _is_within(path, self.storage_root):
                raise ValueError(f"strategy history path escapes storage root: {path}")
            try:
                payload = _read_json(path)
                _, found_asset, found_id, found_version, _ = _validated_payload(payload)
            except ValueError:
                raise
            if found_asset != safe_asset or (safe_strategy_id is not None and found_id != safe_strategy_id):
                continue
            updated_at = _normalize_updated_at(payload["updated_at"])
            records.append(
                _record_metadata(path, payload, updated_at=updated_at, root=self.storage_root)
            )
        records.sort(key=lambda item: (item["updated_at"], item["artifact_ref"]), reverse=True)
        return records[:limit]

    def _path(self, asset: str, trade_date: str, strategy_id: str, strategy_version: str) -> Path:
        path = self.storage_root / "strategy_history" / asset / trade_date / strategy_id / f"{strategy_version}.json"
        parent = path.parent
        if parent.exists() and not _is_within(parent, self.storage_root):
            raise ValueError("strategy history path escapes storage root")
        return path

    def _write_json(self, path: Path, payload: Mapping[str, Any], strategy_version: str) -> HistoryWriteResult:
        canonical = _canonical_bytes(payload)
        parent = path.parent
        parent.mkdir(parents=True, exist_ok=True)
        if not _is_within(parent, self.storage_root):
            raise ValueError("strategy history path escapes storage root")
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
                    raise ValueError(f"invalid strategy history path: {path}")
                try:
                    existing = _canonical_bytes(_read_json(path))
                except ValueError:
                    existing = None
                if existing == canonical:
                    created = False
                else:
                    raise StrategyHistoryConflictError(f"immutable strategy version already differs: {path}")
            else:
                _fsync_directory(parent)
                created = True
            return HistoryWriteResult(
                path=path,
                created=created,
                artifact_ref=_artifact_ref(path, self.storage_root),
                schema_version=HISTORY_SCHEMA_VERSION,
                strategy_version=strategy_version,
            )
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _safe_existing_path(self, ref_or_path: str | os.PathLike[str] | Path) -> Path:
        raw = Path(ref_or_path)
        path = raw if raw.is_absolute() else self.storage_root / raw
        if path.suffix != ".json" or not _is_within(path, self.storage_root):
            raise ValueError("strategy history reference escapes storage root")
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"invalid strategy history reference: {path}")
        return path


def _validated_payload(strategy: Mapping[str, Any]) -> tuple[dict[str, Any], str, str, str, str]:
    if not isinstance(strategy, Mapping):
        raise TypeError("strategy must be a mapping")
    required = ("asset", "strategy_id", "strategy_version", "updated_at")
    missing = [key for key in required if key not in strategy]
    if missing:
        raise ValueError(f"strategy is missing required fields: {', '.join(missing)}")
    asset = _safe_component(strategy["asset"], "asset")
    strategy_id = _safe_component(strategy["strategy_id"], "strategy_id")
    strategy_version = _safe_component(strategy["strategy_version"], "strategy_version")
    updated_at = _normalize_updated_at(strategy["updated_at"])
    payload = {str(key): value for key, value in strategy.items()}
    payload["asset"] = asset
    payload["strategy_id"] = strategy_id
    payload["strategy_version"] = strategy_version
    payload["updated_at"] = updated_at
    _canonical_bytes(payload)
    return payload, asset, strategy_id, strategy_version, updated_at[:10]


def _normalize_updated_at(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("updated_at must be an ISO-8601 string with timezone")
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("updated_at must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("updated_at must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_component(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or not _COMPONENT_RE.fullmatch(value):
        raise ValueError(f"invalid {name}; expected one safe path component")
    return value


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    try:
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("strategy payload must be JSON serializable") from exc
    return (text + "\n").encode("utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid strategy history artifact: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"strategy history artifact must contain a JSON object: {path}")
    return value


def _record_metadata(path: Path, payload: Mapping[str, Any], *, updated_at: str, root: Path) -> dict[str, Any]:
    return {
        "schema_version": HISTORY_SCHEMA_VERSION,
        "artifact_ref": _artifact_ref(path, root),
        "strategy_version": payload["strategy_version"],
        "asset": payload["asset"],
        "strategy_id": payload["strategy_id"],
        "updated_at": updated_at,
        "payload": dict(payload),
    }


def _artifact_ref(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


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
    "HISTORY_SCHEMA_VERSION",
    "MAX_LIST_LIMIT",
    "HistoryWriteResult",
    "StrategyHistoryConflictError",
    "StrategyHistoryStore",
]
