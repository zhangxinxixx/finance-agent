"""TDD: persisted daily source-health snapshots."""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker

from database.models.analysis import (
    AnalysisBase,
    DailySourceHealthItem,
    DailySourceHealthSnapshot,
    ensure_analysis_tables,
)
from database.queries.data_source_health import (
    get_data_source_health_snapshot,
    list_data_source_health_history,
    upsert_data_source_health_snapshot,
)


def _make_session() -> Session:
    engine = create_engine("sqlite:///:memory:", echo=False)
    ensure_analysis_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_daily_source_health_tables_are_created() -> None:
    engine = create_engine("sqlite:///:memory:", echo=False)
    ensure_analysis_tables(engine)

    tables = set(inspect(engine).get_table_names())
    assert "daily_source_health_snapshots" in tables
    assert "daily_source_health_items" in tables
    assert "daily_source_health_snapshots" in {table.name for table in AnalysisBase.metadata.tables.values()}
    assert "daily_source_health_items" in {table.name for table in AnalysisBase.metadata.tables.values()}


def test_upsert_data_source_health_snapshot_round_trips_items() -> None:
    session = _make_session()
    payload = {
        "snapshot_date": "2026-06-24",
        "as_of": "2026-06-24T10:00:00+00:00",
        "overall_status": "PARTIAL",
        "counts": {"total": 2, "live": 1, "partial": 1, "unavailable": 0, "stale": 1},
        "stale_sources": ["Jin10 MCP 快讯"],
        "items": [
            {
                "source_key": "fred",
                "source_name": "FRED",
                "source_group": "macro",
                "freshness_status": "fresh",
                "freshness_reason": "within_sla",
                "raw_status": "success",
                "parsed_status": "success",
                "feature_status": "success",
                "analysis_status": "success",
                "data_status": "live",
                "latest_health_at": "2026-06-24T09:30:00+00:00",
                "latest_snapshot_id": "snap-001",
            },
            {
                "source_key": "jin10_mcp_flash",
                "source_name": "Jin10 MCP Flash",
                "source_group": "news",
                "freshness_status": "stale",
                "freshness_reason": "ttl_exceeded",
                "raw_status": "success",
                "parsed_status": "success",
                "feature_status": "success",
                "analysis_status": "success",
                "data_status": "partial",
                "latest_health_at": "2026-06-24T07:00:00+00:00",
                "latest_snapshot_id": "snap-news",
            },
        ],
    }

    snapshot = upsert_data_source_health_snapshot(session, payload)
    session.commit()

    assert isinstance(snapshot, DailySourceHealthSnapshot)
    assert snapshot.snapshot_date == date(2026, 6, 24)
    assert snapshot.overall_status == "PARTIAL"
    assert len(snapshot.items) == 2
    assert all(isinstance(item, DailySourceHealthItem) for item in snapshot.items)

    loaded = get_data_source_health_snapshot(session, date(2026, 6, 24))
    assert loaded is not None
    assert loaded["snapshot_date"] == "2026-06-24"
    assert loaded["counts"]["stale"] == 1
    assert [item["source_key"] for item in loaded["items"]] == ["fred", "jin10_mcp_flash"]


def test_upsert_data_source_health_snapshot_replaces_same_day_items() -> None:
    session = _make_session()
    first = {
        "snapshot_date": "2026-06-24",
        "as_of": datetime(2026, 6, 24, 10, 0, tzinfo=timezone.utc).isoformat(),
        "overall_status": "PARTIAL",
        "counts": {"total": 1, "live": 0, "partial": 1, "unavailable": 0, "stale": 1},
        "stale_sources": ["FRED"],
        "items": [{"source_key": "fred", "source_name": "FRED", "data_status": "partial"}],
    }
    second = {
        "snapshot_date": "2026-06-24",
        "as_of": datetime(2026, 6, 24, 11, 0, tzinfo=timezone.utc).isoformat(),
        "overall_status": "LIVE",
        "counts": {"total": 1, "live": 1, "partial": 0, "unavailable": 0, "stale": 0},
        "stale_sources": [],
        "items": [{"source_key": "fred", "source_name": "FRED", "data_status": "live"}],
    }

    upsert_data_source_health_snapshot(session, first)
    upsert_data_source_health_snapshot(session, second)
    session.commit()

    loaded = get_data_source_health_snapshot(session, "2026-06-24")
    assert loaded is not None
    assert loaded["overall_status"] == "LIVE"
    assert loaded["counts"]["live"] == 1
    assert loaded["items"] == [{"source_key": "fred", "source_name": "FRED", "data_status": "live"}]


def test_list_data_source_health_history_filters_source_and_orders_latest_first() -> None:
    session = _make_session()
    upsert_data_source_health_snapshot(
        session,
        {
            "snapshot_date": "2026-06-23",
            "as_of": "2026-06-23T10:00:00+00:00",
            "overall_status": "PARTIAL",
            "counts": {"total": 2, "live": 1, "partial": 1, "unavailable": 0, "stale": 1},
            "stale_sources": ["FRED"],
            "items": [
                {"source_key": "fred", "source_name": "FRED", "data_status": "partial", "freshness_status": "stale"},
                {"source_key": "cme_daily_bulletin", "source_name": "CME", "data_status": "live"},
            ],
        },
    )
    upsert_data_source_health_snapshot(
        session,
        {
            "snapshot_date": "2026-06-24",
            "as_of": "2026-06-24T10:00:00+00:00",
            "overall_status": "LIVE",
            "counts": {"total": 1, "live": 1, "partial": 0, "unavailable": 0, "stale": 0},
            "stale_sources": [],
            "items": [{"source_key": "fred", "source_name": "FRED", "data_status": "live", "freshness_status": "fresh"}],
        },
    )
    session.commit()

    history = list_data_source_health_history(session, "fred", limit=10)

    assert history["source_key"] == "fred"
    assert history["total"] == 2
    assert [item["snapshot_date"] for item in history["items"]] == ["2026-06-24", "2026-06-23"]
    assert [item["data_status"] for item in history["items"]] == ["live", "partial"]
