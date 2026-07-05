from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.models.analysis import FeatureSnapshot, ensure_analysis_tables
from database.queries.feature_snapshots import list_feature_snapshots, upsert_feature_snapshot


def _make_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_analysis_tables(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return factory()


def test_upsert_feature_snapshot_creates_portable_row() -> None:
    session = _make_session()

    row = upsert_feature_snapshot(
        session,
        {
            "snapshot_id": "feature:macro:macro_snapshot:2026-07-04:run-a",
            "domain": "macro",
            "snapshot_kind": "macro_snapshot",
            "asset": "XAUUSD",
            "trade_date": "2026-07-04",
            "run_id": "run-a",
            "status": "partial",
            "payload": {"as_of": "2026-07-04", "unavailable_symbols": ["TGA"]},
            "artifact_path": "storage/features/macro/2026-07-04/run-a/macro_snapshot.json",
            "source_refs": [{"symbol": "DGS10", "source": "fred"}],
            "metadata": {"pipeline_step": "report_render"},
        },
    )
    session.commit()

    saved = session.query(FeatureSnapshot).one()
    assert saved.id == row.id
    assert saved.snapshot_id == "feature:macro:macro_snapshot:2026-07-04:run-a"
    assert saved.domain == "macro"
    assert saved.snapshot_kind == "macro_snapshot"
    assert saved.asset == "XAUUSD"
    assert saved.trade_date.isoformat() == "2026-07-04"
    assert saved.run_id == "run-a"
    assert saved.status == "partial"
    assert saved.payload == {"as_of": "2026-07-04", "unavailable_symbols": ["TGA"]}
    assert len(saved.payload_sha256) == 64
    assert saved.artifact_path == "storage/features/macro/2026-07-04/run-a/macro_snapshot.json"
    assert saved.source_refs == [{"symbol": "DGS10", "source": "fred"}]
    assert saved.feature_metadata == {"pipeline_step": "report_render"}


def test_upsert_feature_snapshot_updates_same_snapshot_id() -> None:
    session = _make_session()
    payload = {
        "snapshot_id": "feature:macro:macro_snapshot:2026-07-04:run-a",
        "domain": "macro",
        "snapshot_kind": "macro_snapshot",
        "asset": "XAUUSD",
        "trade_date": "2026-07-04",
        "run_id": "run-a",
        "status": "partial",
        "payload": {"value": 1},
    }

    first = upsert_feature_snapshot(session, payload)
    second = upsert_feature_snapshot(session, {**payload, "status": "success", "payload": {"value": 2}})
    session.commit()

    rows = session.query(FeatureSnapshot).all()
    assert len(rows) == 1
    assert first.id == second.id == rows[0].id
    assert rows[0].status == "success"
    assert rows[0].payload == {"value": 2}


def test_list_feature_snapshots_filters_by_domain_kind_run_and_date() -> None:
    session = _make_session()
    upsert_feature_snapshot(
        session,
        {
            "snapshot_id": "feature:macro:macro_snapshot:2026-07-04:run-a",
            "domain": "macro",
            "snapshot_kind": "macro_snapshot",
            "asset": "XAUUSD",
            "trade_date": "2026-07-04",
            "run_id": "run-a",
            "payload": {"as_of": "2026-07-04"},
        },
    )
    upsert_feature_snapshot(
        session,
        {
            "snapshot_id": "feature:macro:macro_conclusion:2026-07-04:run-a",
            "domain": "macro",
            "snapshot_kind": "macro_conclusion",
            "asset": "XAUUSD",
            "trade_date": "2026-07-04",
            "run_id": "run-a",
            "payload": {"bias": "neutral"},
        },
    )
    session.commit()

    rows = list_feature_snapshots(
        session,
        domain="macro",
        snapshot_kind="macro_conclusion",
        run_id="run-a",
        trade_date="2026-07-04",
    )

    assert [row.snapshot_kind for row in rows] == ["macro_conclusion"]
