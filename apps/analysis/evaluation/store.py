"""Append-only local storage for Issue #59 evaluation artifacts.

The store intentionally persists the already-validated ``to_dict`` payloads
from :mod:`strategy_snapshot` and :mod:`outcomes`. It does not recalculate,
enrich, or otherwise mutate evaluation semantics.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .outcomes import OutcomeEvaluation
from .strategy_snapshot import StrategySnapshot

_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class EvaluationStoreConflictError(ValueError):
    """Raised when an existing evaluation id has different content."""


@dataclass(frozen=True, slots=True)
class StoreWriteResult:
    """Result of an append-only write."""

    path: Path
    created: bool


class EvaluationStore:
    """Store snapshots and outcomes below an explicitly supplied root."""

    def __init__(self, storage_root: str | os.PathLike[str]) -> None:
        root = Path(storage_root).expanduser()
        if not root.is_absolute():
            root = root.resolve()
        if root.exists() and not root.is_dir():
            raise ValueError(f"storage_root must be a directory: {root}")
        self.storage_root = root

    def write_snapshot(self, snapshot: StrategySnapshot) -> StoreWriteResult:
        """Persist one immutable strategy snapshot."""

        path = self._snapshot_path(snapshot)
        return self._write_json(path, snapshot.to_dict())

    def write_outcome(self, snapshot: StrategySnapshot, outcome: OutcomeEvaluation) -> StoreWriteResult:
        """Persist an outcome in the snapshot's account/date partition."""

        if outcome.evaluation_id != snapshot.evaluation_id:
            raise ValueError("outcome evaluation_id must match snapshot evaluation_id")
        path = self._outcome_path(snapshot, outcome.horizon)
        return self._write_json(path, outcome.to_dict())

    def read_snapshot(self, snapshot_or_context: StrategySnapshot | Mapping[str, Any]) -> dict[str, Any]:
        """Read and parse a snapshot by object or snapshot context mapping."""

        return self._read_json(self._snapshot_path(snapshot_or_context))

    def read_outcome(
        self,
        snapshot_or_context: StrategySnapshot | Mapping[str, Any],
        horizon: str,
    ) -> dict[str, Any]:
        """Read and parse one horizon outcome."""

        return self._read_json(self._outcome_path(snapshot_or_context, horizon))

    def snapshot_path(self, snapshot: StrategySnapshot | Mapping[str, Any]) -> Path:
        """Return the canonical snapshot path without touching the filesystem."""

        return self._snapshot_path(snapshot)

    def outcome_path(self, snapshot: StrategySnapshot | Mapping[str, Any], horizon: str) -> Path:
        """Return the canonical outcome path without touching the filesystem."""

        return self._outcome_path(snapshot, horizon)

    def _snapshot_path(self, snapshot: StrategySnapshot | Mapping[str, Any]) -> Path:
        account, asset, trade_date, evaluation_id = _context(snapshot)
        return self._partition(account, asset, trade_date, evaluation_id) / "strategy_snapshot.json"

    def _outcome_path(self, snapshot: StrategySnapshot | Mapping[str, Any], horizon: str) -> Path:
        account, asset, trade_date, evaluation_id = _context(snapshot)
        horizon_component = _safe_component(horizon, "horizon")
        return self._partition(account, asset, trade_date, evaluation_id) / "outcomes" / f"{horizon_component}.json"

    def _partition(self, account: str, asset: str, trade_date: str, evaluation_id: str) -> Path:
        return self.storage_root / "evaluation" / account / asset / trade_date / evaluation_id

    def _write_json(self, path: Path, payload: Mapping[str, Any]) -> StoreWriteResult:
        canonical = _canonical_bytes(payload)
        parent = path.parent
        parent.mkdir(parents=True, exist_ok=True)
        # Flush a temporary file, then atomically link it without replacing an
        # existing path. This keeps the store append-only under write races.
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
                try:
                    existing_payload = json.loads(path.read_text(encoding="utf-8"))
                    existing = _canonical_bytes(existing_payload)
                except (OSError, json.JSONDecodeError, TypeError):
                    existing = None
                if existing == canonical:
                    return StoreWriteResult(path=path, created=False)
                raise EvaluationStoreConflictError(f"immutable evaluation artifact already differs: {path}")
            _fsync_directory(parent)
            return StoreWriteResult(path=path, created=True)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid evaluation artifact: {path}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"evaluation artifact must contain a JSON object: {path}")
        return value


def _context(snapshot: StrategySnapshot | Mapping[str, Any]) -> tuple[str, str, str, str]:
    if isinstance(snapshot, StrategySnapshot):
        values = (snapshot.account_id, snapshot.asset, snapshot.trade_date, snapshot.evaluation_id)
    elif isinstance(snapshot, Mapping):
        values = tuple(snapshot.get(key) for key in ("account_id", "asset", "trade_date", "evaluation_id"))
    else:
        raise TypeError("snapshot context must be StrategySnapshot or mapping")
    names = ("account_id", "asset", "trade_date", "evaluation_id")
    return tuple(_safe_component(value, name) for value, name in zip(values, names, strict=True))  # type: ignore[return-value]


def _safe_component(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or not _COMPONENT_RE.fullmatch(value):
        raise ValueError(f"invalid {name}; expected one safe path component")
    return value


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(_json_ready(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _json_ready(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def _fsync_directory(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


__all__ = ["EvaluationStore", "EvaluationStoreConflictError", "StoreWriteResult"]
