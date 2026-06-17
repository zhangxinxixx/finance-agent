"""Runtime bridge for Execution Observability (P0).

This module is intentionally lightweight and imported by worker.
It isolates DB event emission from business logic.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from apps.api.services.execution_event_service import emit_execution_event


def emit_run_event(
    db: Session,
    run_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> None:
    emit_execution_event(
        db,
        run_id=run_id,
        task_id=None,
        event_type=event_type,
        payload=payload or {},
    )


def emit_task_event(
    db: Session,
    run_id: str,
    task_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> None:
    emit_execution_event(
        db,
        run_id=run_id,
        task_id=task_id,
        event_type=event_type,
        payload=payload or {},
    )
