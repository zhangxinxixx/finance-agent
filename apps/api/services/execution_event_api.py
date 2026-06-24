"""Execution Event API helpers (P0)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from .execution_event_service import list_run_events


def get_run_events(db: Session, run_id: str) -> dict:
    return {
        "run_id": run_id,
        "events": list_run_events(db, run_id),
    }
