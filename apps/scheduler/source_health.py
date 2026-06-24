"""Scheduler entrypoint for daily source-health snapshots."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from apps.api.services.source_service import get_data_source_health_latest
from database.models.analysis import ensure_analysis_tables
from database.models.engine import SessionLocal


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def record_daily_source_health_snapshot(
    *,
    session_factory: Callable[[], Any] = SessionLocal,
    snapshot_date: str | None = None,
) -> dict[str, Any]:
    """Persist today's source-health snapshot from the current data-source read model."""
    from database.queries.data_source_health import get_data_source_health_snapshot, upsert_data_source_health_snapshot

    day = snapshot_date or _utc_now().date().isoformat()
    payload = get_data_source_health_latest(date=day)
    with session_factory() as session:
        try:
            ensure_analysis_tables(session)
            snapshot = upsert_data_source_health_snapshot(session, payload)
            session.commit()
            persisted = get_data_source_health_snapshot(session, snapshot.snapshot_date)
            return persisted or payload
        except Exception:
            session.rollback()
            raise
