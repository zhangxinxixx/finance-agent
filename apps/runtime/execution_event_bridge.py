"""Runtime bridge for Execution Observability (P0).

This module is intentionally lightweight and imported by worker/runtime code.
It isolates DB event emission from business logic and never lets observability
failures break the business pipeline.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from apps.api.services.execution_event_service import emit_execution_event

logger = logging.getLogger(__name__)


def _execution_events_available(db: Session) -> bool:
    cached = db.info.get("_execution_events_available")
    if cached is not None:
        return bool(cached)
    try:
        bind = db.connection()
    except Exception:
        return False
    try:
        available = inspect(bind).has_table("execution_events")
    except Exception:
        return False
    db.info["_execution_events_available"] = available
    return available


def emit_run_event(
    db: Session,
    run_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """Emit a run-scoped event (best-effort)."""
    if not _execution_events_available(db):
        return
    try:
        emit_execution_event(
            db,
            run_id=run_id,
            task_id=None,
            event_type=event_type,
            payload=payload or {},
        )
    except Exception as exc:
        logger.debug("Failed to emit run event %s for run=%s: %s", event_type, run_id, exc)


def emit_task_event(
    db: Session,
    run_id: str,
    task_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """Emit a task/step-scoped event (best-effort)."""
    if not _execution_events_available(db):
        return
    try:
        emit_execution_event(
            db,
            run_id=run_id,
            task_id=task_id,
            event_type=event_type,
            payload=payload or {},
        )
    except Exception as exc:
        logger.debug(
            "Failed to emit task event %s for run=%s task=%s: %s",
            event_type,
            run_id,
            task_id,
            exc,
        )
