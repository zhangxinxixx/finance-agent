from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.models.analysis import MacroObservation, ensure_analysis_tables
from database.queries.macro_observations import list_macro_observations, upsert_macro_observation


def _make_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_analysis_tables(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return factory()


def test_upsert_macro_observation_creates_portable_fact_row() -> None:
    session = _make_session()

    row = upsert_macro_observation(
        session,
        {
            "source_key": "fred",
            "symbol": "DGS10",
            "observation_date": "2026-07-04",
            "value": 4.25,
            "source_url": "https://api.stlouisfed.org/fred/series/observations?series_id=DGS10",
            "raw_path": "storage/raw/macro/fred/2026-07-04/DGS10.json",
            "retrieved_at": "2026-07-04T12:00:00Z",
            "run_id": "run-macro-001",
            "source_refs": [{"symbol": "DGS10", "source": "fred"}],
            "metadata": {"collector_source": "fred"},
        },
    )
    session.commit()

    saved = session.query(MacroObservation).one()
    assert saved.id == row.id
    assert saved.source_key == "fred"
    assert saved.symbol == "DGS10"
    assert saved.observation_date.isoformat() == "2026-07-04"
    assert saved.value == 4.25
    assert saved.raw_path == "storage/raw/macro/fred/2026-07-04/DGS10.json"
    assert saved.retrieved_at is not None
    assert saved.run_id == "run-macro-001"
    assert saved.source_refs == [{"symbol": "DGS10", "source": "fred"}]
    assert saved.observation_metadata == {"collector_source": "fred"}


def test_upsert_macro_observation_updates_same_source_symbol_date() -> None:
    session = _make_session()
    payload = {
        "source_key": "fred",
        "symbol": "DGS10",
        "observation_date": "2026-07-04T12:00:00+00:00",
        "value": 4.25,
        "run_id": "run-a",
    }
    first = upsert_macro_observation(session, payload)
    second = upsert_macro_observation(session, {**payload, "value": 4.31, "run_id": "run-b"})
    session.commit()

    rows = session.query(MacroObservation).all()
    assert len(rows) == 1
    assert first.id == second.id == rows[0].id
    assert rows[0].value == 4.31
    assert rows[0].run_id == "run-b"


def test_list_macro_observations_filters_by_run_and_date() -> None:
    session = _make_session()
    upsert_macro_observation(
        session,
        {
            "source_key": "fred",
            "symbol": "DGS10",
            "observation_date": "2026-07-04",
            "value": 4.25,
            "run_id": "run-a",
        },
    )
    upsert_macro_observation(
        session,
        {
            "source_key": "openbb_fred",
            "symbol": "DGS2",
            "observation_date": "2026-07-03",
            "value": 3.95,
            "run_id": "run-b",
        },
    )
    session.commit()

    rows = list_macro_observations(session, run_id="run-a", start_date="2026-07-01", end_date="2026-07-04")

    assert [row.symbol for row in rows] == ["DGS10"]
