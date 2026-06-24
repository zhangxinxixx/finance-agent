from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models.analysis import ensure_analysis_tables


def test_record_daily_source_health_snapshot_persists_current_read_model(monkeypatch) -> None:
    from apps.scheduler import source_health
    from apps.api.services import source_service
    from database.queries.data_source_health import get_data_source_health_snapshot

    engine = create_engine("sqlite:///:memory:", echo=False)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    payload = {
        "sources": [
            {
                "source_key": "fred",
                "source_name": "FRED",
                "source_group": "macro",
                "status": "ok",
                "configured": True,
                "raw_ingested": True,
                "parsed": True,
                "analysis_ready": True,
                "latest_update_time": "2026-06-24T09:30:00+00:00",
                "freshness_status": "fresh",
                "freshness_reason": "within_sla",
                "gate_state": "open",
                "metadata": {"frontend_label": "FRED 官方宏观主源"},
            }
        ]
    }
    monkeypatch.setattr(source_health, "_utc_now", lambda: datetime(2026, 6, 24, 10, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(source_service, "_utc_now", lambda: datetime(2026, 6, 24, 10, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(source_service, "get_data_source_statuses", lambda: payload)

    result = source_health.record_daily_source_health_snapshot(session_factory=SessionLocal)

    assert result["snapshot_date"] == "2026-06-24"
    assert result["overall_status"] == "LIVE"
    assert result["counts"]["live"] == 1

    with SessionLocal() as session:
        ensure_analysis_tables(session)
        loaded = get_data_source_health_snapshot(session, "2026-06-24")
    assert loaded is not None
    assert loaded["items"][0]["source_key"] == "fred"
