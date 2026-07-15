from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from fcntl import LOCK_EX, LOCK_UN, flock
from pathlib import Path
from typing import Any, Iterator


@contextmanager
def orchestration_run_lock(*, storage_root: Path) -> Iterator[None]:
    lock_path = storage_root / "orchestration" / ".automation_orchestration.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        flock(lock_file.fileno(), LOCK_EX)
        try:
            yield
        finally:
            flock(lock_file.fileno(), LOCK_UN)


def append_notification_delivery_log(
    *,
    storage_root: Path,
    trade_date: str,
    observed_at: str,
    results: list[dict[str, Any]],
) -> None:
    deliveries = [_delivery_record(result, observed_at=observed_at) for result in results if result.get("status") != "skipped"]
    if not deliveries:
        return
    base = storage_root / "orchestration" / trade_date
    path = base / "notification_delivery_log.json"
    lock_path = base / ".notification_delivery_log.lock"
    base.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        flock(lock_file.fileno(), LOCK_EX)
        try:
            payload = _read_json(path)
            existing = payload.get("deliveries") if isinstance(payload.get("deliveries"), list) else []
            _write_json_atomic(path, {"trade_date": trade_date, "deliveries": [*existing, *deliveries]})
        finally:
            flock(lock_file.fileno(), LOCK_UN)


def _delivery_record(result: dict[str, Any], *, observed_at: str) -> dict[str, Any]:
    return {
        "notification_id": result.get("notification_id"),
        "dedupe_key": result.get("dedupe_key"),
        "kind": result.get("kind"),
        "status": result.get("status"),
        "ok": result.get("ok"),
        "attempts": result.get("attempts") or result.get("attempt_count"),
        "sent_at": observed_at,
        "retried_at": result.get("retried_at"),
        "cooldown_minutes": result.get("cooldown_minutes"),
        "error": result.get("error"),
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
