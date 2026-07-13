from __future__ import annotations

import hashlib
import json
import re
import uuid
from contextlib import contextmanager
from fcntl import LOCK_EX, LOCK_UN, flock
from pathlib import Path
from typing import Any, Iterator


def stable_event_hash(*parts: object) -> str:
    text = "|".join("" if part is None else str(part) for part in parts)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_event_id(*parts: object) -> str:
    raw = "_".join("" if part is None else str(part) for part in parts if part is not None)
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("_")
    return safe[:160]


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def load_event_execution_ledger(*, storage_root: Path, trade_date: str) -> dict[str, Any]:
    payload = read_json(event_execution_ledger_path(storage_root=storage_root, trade_date=trade_date))
    events = payload.get("events") if isinstance(payload.get("events"), dict) else {}
    return {"trade_date": trade_date, "events": events, **{key: value for key, value in payload.items() if key not in {"trade_date", "events"}}}


def write_event_execution_ledger(*, storage_root: Path, trade_date: str, payload: dict[str, Any]) -> Path:
    path = event_execution_ledger_path(storage_root=storage_root, trade_date=trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def event_execution_ledger_path(*, storage_root: Path, trade_date: str) -> Path:
    return storage_root / "event_sla" / trade_date / "event_execution_ledger.json"


@contextmanager
def event_execution_lock(*, storage_root: Path, trade_date: str) -> Iterator[None]:
    lock_path = storage_root / "event_sla" / trade_date / ".event_execution_ledger.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        flock(lock_file.fileno(), LOCK_EX)
        try:
            yield
        finally:
            flock(lock_file.fileno(), LOCK_UN)


def rel(path: Path | None, storage_root: Path) -> str:
    if path is None:
        return ""
    try:
        return path.relative_to(storage_root).as_posix()
    except ValueError:
        return path.as_posix()
