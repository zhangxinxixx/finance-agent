"""Execution Event Service (P0 Observability Layer)

Provides minimal APIs for:
- emitting execution events
- querying run event timelines

This layer is intentionally lightweight and does NOT replace TaskRun/TaskStep.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from database.models.execution import ExecutionEvent


# -----------------------------
# Event emission
# -----------------------------

def emit_execution_event(
    db: Session,
    *,
    run_id: str,
    task_id: str | None = None,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> ExecutionEvent:
    event = ExecutionEvent(
        id=uuid.uuid4(),
        run_id=uuid.UUID(run_id),
        task_id=uuid.UUID(task_id) if task_id else None,
        event_type=event_type,
        payload=json.dumps(payload or {}, ensure_ascii=False),
        created_at=datetime.now(timezone.utc),
    )
    db.add(event)
    db.flush()
    return event


# -----------------------------
# Query
# -----------------------------

def list_run_events(db: Session, run_id: str) -> list[dict[str, Any]]:
    events = (
        db.query(ExecutionEvent)
        .filter(ExecutionEvent.run_id == uuid.UUID(run_id))
        .order_by(ExecutionEvent.created_at.asc())
        .all()
    )

    return [
        {
            "id": str(e.id),
            "run_id": str(e.run_id),
            "task_id": str(e.task_id) if e.task_id else None,
            "event_type": e.event_type,
            "payload": json.loads(e.payload) if e.payload else {},
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in events
    ]
