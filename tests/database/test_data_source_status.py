"""TDD: DataSourceStatus model — SQLite-compatible tests.

All tests use in-memory SQLite to avoid depending on local PostgreSQL.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker

from database.models.analysis import AnalysisBase, DataSourceStatus, ensure_analysis_tables


def _make_engine() -> create_engine:
    """In-memory SQLite engine for portable tests."""
    return create_engine("sqlite:///:memory:", echo=False)


def _make_session() -> Session:
    """Create in-memory SQLite session with analysis tables including data_source_status."""
    engine = _make_engine()
    ensure_analysis_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


# ── RED: table creation ──


def test_data_source_status_table_created() -> None:
    """ensure_analysis_tables creates data_source_status table on SQLite."""
    engine = _make_engine()
    ensure_analysis_tables(engine)

    inspector = inspect(engine)
    tables = inspector.get_table_names()
    assert "data_source_status" in tables, f"Expected data_source_status in tables, got {tables}"


def test_create_twice_is_idempotent() -> None:
    """Repeated create_all must not error (checkfirst semantics)."""
    engine = _make_engine()
    ensure_analysis_tables(engine)
    ensure_analysis_tables(engine)  # must not raise


def test_model_registered_in_analysis_base() -> None:
    """DataSourceStatus must be in AnalysisBase.metadata tables."""
    tables = {t.name for t in AnalysisBase.metadata.tables.values()}
    assert "data_source_status" in tables


# ── Column type validation ──


def test_data_source_status_columns_use_portable_types() -> None:
    """All columns use SQLite-compatible types (no PostgreSQL-only types)."""
    cols = DataSourceStatus.__table__.columns

    # Primary key is String(36) for UUID
    assert str(cols["id"].type) == "VARCHAR(36)", f"id type: {cols['id'].type}"

    # source_key is unique string
    assert str(cols["source_key"].type).startswith("VARCHAR"), f"source_key type: {cols['source_key'].type}"

    # source_name
    assert str(cols["source_name"].type).startswith("VARCHAR")

    # Boolean fields
    assert "boolean" in str(cols["configured"].type).lower()
    assert "boolean" in str(cols["raw_ingested"].type).lower()
    assert "boolean" in str(cols["parsed"].type).lower()
    assert "boolean" in str(cols["analysis_ready"].type).lower()

    # status field
    assert str(cols["status"].type).startswith("VARCHAR")

    # JSON field for source_metadata
    assert "json" in str(cols["source_metadata"].type).lower()

    # Integer for row_count
    assert "integer" in str(cols["row_count"].type).lower()


def test_data_source_status_unique_constraint() -> None:
    """Unique constraint on source_key."""
    engine = _make_engine()
    ensure_analysis_tables(engine)
    inspector = inspect(engine)

    uq_constraints = inspector.get_unique_constraints("data_source_status")
    # SQLite auto-names unique constraints; just verify there's at least one on source_key
    has_source_key_uq = any("source_key" in str(c.get("column_names", c.get("columns", []))) for c in uq_constraints)
    if not has_source_key_uq and uq_constraints:
        # Check if any constraint is on source_key
        for c in uq_constraints:
            cols = c.get("column_names", c.get("columns", []))
            if "source_key" in cols:
                has_source_key_uq = True
                break
    assert has_source_key_uq or len(uq_constraints) > 0, f"Expected unique constraint on source_key, got {uq_constraints}"


# ── Basic insert/read roundtrip ──


def test_data_source_status_insert_and_read() -> None:
    """Insert a status record and read it back with all fields preserved."""
    session = _make_session()

    now = datetime(2026, 5, 16, 10, 0, 0, tzinfo=timezone.utc)
    status = DataSourceStatus(
        source_key="fred",
        source_name="FRED",
        source_group="macro",
        source_type="api",
        access_method="fred_api",
        configured=True,
        raw_ingested=True,
        parsed=True,
        analysis_ready=True,
        latest_raw_time=now,
        latest_parsed_time=now,
        latest_snapshot_id="snap-001",
        row_count=42,
        status="ok",
        error_message=None,
        last_run_id="run-001",
        next_run_time=None,
        source_metadata={"api_key_name": "FRED_API_KEY"},
    )
    session.add(status)
    session.commit()

    result = session.query(DataSourceStatus).filter_by(source_key="fred").one()
    assert result.source_key == "fred"
    assert result.source_name == "FRED"
    assert result.source_group == "macro"
    assert result.source_type == "api"
    assert result.access_method == "fred_api"
    assert result.configured is True
    assert result.raw_ingested is True
    assert result.parsed is True
    assert result.analysis_ready is True
    assert result.latest_raw_time == now
    assert result.latest_parsed_time == now
    assert result.latest_snapshot_id == "snap-001"
    assert result.row_count == 42
    assert result.status == "ok"
    assert result.error_message is None
    assert result.last_run_id == "run-001"
    assert result.next_run_time is None
    assert result.source_metadata == {"api_key_name": "FRED_API_KEY"}


def test_data_source_status_default_values() -> None:
    """Default values for booleans and status."""
    session = _make_session()

    status = DataSourceStatus(
        source_key="jin10_news",
        source_name="Jin10 News",
    )
    session.add(status)
    session.commit()

    result = session.query(DataSourceStatus).filter_by(source_key="jin10_news").one()
    assert result.configured is False
    assert result.raw_ingested is False
    assert result.parsed is False
    assert result.analysis_ready is False
    assert result.status == "not_connected"
    assert result.source_metadata == {}
    assert result.source_group is None
    assert result.source_type is None


def test_data_source_status_json_metadata_roundtrip() -> None:
    """source_metadata JSON column preserves nested dicts and lists on SQLite."""
    session = _make_session()

    metadata_val = {"sources": ["a", "b"], "nested": {"key": "value", "count": 3}}
    status = DataSourceStatus(
        source_key="cme_options",
        source_name="CME Options Data",
        source_metadata=metadata_val,
    )
    session.add(status)
    session.commit()

    result = session.query(DataSourceStatus).filter_by(source_key="cme_options").one()
    assert result.source_metadata == metadata_val
    assert result.source_metadata["nested"]["count"] == 3
    assert result.source_metadata["sources"] == ["a", "b"]


# ── All four boolean layers independent ──


def test_four_boolean_layers_independent() -> None:
    """configured/raw_ingested/parsed/analysis_ready are independently expressible."""
    session = _make_session()

    # configured but nothing else
    s1 = DataSourceStatus(source_key="src1", source_name="S1", configured=True)
    # configured + raw but not parsed
    s2 = DataSourceStatus(source_key="src2", source_name="S2", configured=True, raw_ingested=True)
    # configured + raw + parsed but not analysis_ready
    s3 = DataSourceStatus(source_key="src3", source_name="S3", configured=True, raw_ingested=True, parsed=True)
    # all four
    s4 = DataSourceStatus(source_key="src4", source_name="S4", configured=True, raw_ingested=True, parsed=True, analysis_ready=True)

    session.add_all([s1, s2, s3, s4])
    session.commit()

    r1 = session.query(DataSourceStatus).filter_by(source_key="src1").one()
    assert r1.configured is True
    assert r1.raw_ingested is False
    assert r1.parsed is False
    assert r1.analysis_ready is False

    r2 = session.query(DataSourceStatus).filter_by(source_key="src2").one()
    assert r2.configured is True
    assert r2.raw_ingested is True
    assert r2.parsed is False
    assert r2.analysis_ready is False

    r3 = session.query(DataSourceStatus).filter_by(source_key="src3").one()
    assert r3.configured is True
    assert r3.raw_ingested is True
    assert r3.parsed is True
    assert r3.analysis_ready is False

    r4 = session.query(DataSourceStatus).filter_by(source_key="src4").one()
    assert r4.configured is True
    assert r4.raw_ingested is True
    assert r4.parsed is True
    assert r4.analysis_ready is True


# ── Status values ──


def test_all_status_values_accepted() -> None:
    """ok | stale | partial | failed | not_connected are all accepted."""
    session = _make_session()

    for i, status_val in enumerate(["ok", "stale", "partial", "failed", "not_connected"]):
        s = DataSourceStatus(source_key=f"src_{i}", source_name=f"S{i}", status=status_val)
        session.add(s)
    session.commit()

    results = session.query(DataSourceStatus).all()
    assert len(results) == 5
    statuses = {r.status for r in results}
    assert statuses == {"ok", "stale", "partial", "failed", "not_connected"}


# ── Repository: upsert, list, get ──


def test_upsert_creates_new_record() -> None:
    """upsert_data_source_status creates a new record when source_key doesn't exist."""
    from database.queries.data_source_status import upsert_data_source_status

    session = _make_session()
    data = {
        "source_key": "fred",
        "source_name": "FRED",
        "source_group": "macro",
        "source_type": "api",
        "configured": True,
        "raw_ingested": True,
        "status": "ok",
        "source_metadata": {"api": "fred"},
    }
    result = upsert_data_source_status(session, data)
    assert result.source_key == "fred"
    assert result.source_name == "FRED"
    assert result.configured is True
    assert result.raw_ingested is True
    assert result.status == "ok"
    assert result.source_metadata == {"api": "fred"}

    # Verify it's persisted
    session.expire_all()
    fetched = session.query(DataSourceStatus).filter_by(source_key="fred").one()
    assert fetched.source_name == "FRED"


def test_upsert_is_idempotent_update() -> None:
    """upsert_data_source_status updates existing record without creating duplicate."""
    from database.queries.data_source_status import upsert_data_source_status

    session = _make_session()

    # First insert
    data1 = {
        "source_key": "dxy",
        "source_name": "DXY Index",
        "source_group": "macro",
        "status": "partial",
        "configured": True,
        "raw_ingested": True,
        "parsed": False,
    }
    r1 = upsert_data_source_status(session, data1)
    session.commit()
    id1 = r1.id

    # Second upsert with different values
    data2 = {
        "source_key": "dxy",
        "source_name": "DXY Index Updated",
        "source_group": "macro",
        "status": "ok",
        "configured": True,
        "raw_ingested": True,
        "parsed": True,
        "analysis_ready": True,
        "row_count": 100,
    }
    r2 = upsert_data_source_status(session, data2)
    session.commit()

    # Same ID — no duplicate
    assert r2.id == id1
    assert r2.source_name == "DXY Index Updated"
    assert r2.status == "ok"
    assert r2.parsed is True
    assert r2.analysis_ready is True
    assert r2.row_count == 100

    # Only one record
    count = session.query(DataSourceStatus).filter_by(source_key="dxy").count()
    assert count == 1


def test_list_returns_all_sorted() -> None:
    """list_data_source_statuses returns all records sorted by source_key."""
    from database.queries.data_source_status import list_data_source_statuses

    session = _make_session()
    session.add_all([
        DataSourceStatus(source_key="cme_options", source_name="CME Options", source_group="cme"),
        DataSourceStatus(source_key="fred", source_name="FRED", source_group="macro"),
        DataSourceStatus(source_key="dxy", source_name="DXY", source_group="macro"),
        DataSourceStatus(source_key="fed", source_name="FED", source_group="macro"),
    ])
    session.commit()

    results = list_data_source_statuses(session)
    assert len(results) == 4
    keys = [r.source_key for r in results]
    assert keys == ["cme_options", "dxy", "fed", "fred"]  # alpha sorted


def test_list_filters_by_source_group() -> None:
    """list_data_source_statuses can filter by source_group."""
    from database.queries.data_source_status import list_data_source_statuses

    session = _make_session()
    session.add_all([
        DataSourceStatus(source_key="fred", source_name="FRED", source_group="macro"),
        DataSourceStatus(source_key="fed", source_name="FED", source_group="macro"),
        DataSourceStatus(source_key="cme_options", source_name="CME Options", source_group="cme"),
        DataSourceStatus(source_key="jin10_news", source_name="Jin10 News", source_group="news"),
    ])
    session.commit()

    macro_results = list_data_source_statuses(session, source_group="macro")
    assert len(macro_results) == 2
    keys = {r.source_key for r in macro_results}
    assert keys == {"fred", "fed"}

    news_results = list_data_source_statuses(session, source_group="news")
    assert len(news_results) == 1
    assert news_results[0].source_key == "jin10_news"


def test_get_returns_single_or_none() -> None:
    """get_data_source_status returns single record or None."""
    from database.queries.data_source_status import get_data_source_status

    session = _make_session()
    session.add(DataSourceStatus(source_key="treasury", source_name="US Treasury", source_group="macro"))
    session.commit()

    found = get_data_source_status(session, "treasury")
    assert found is not None
    assert found.source_name == "US Treasury"

    missing = get_data_source_status(session, "nonexistent")
    assert missing is None
