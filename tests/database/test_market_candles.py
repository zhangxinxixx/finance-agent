"""TDD: MarketCandle model and repository."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker

from database.models.analysis import AnalysisBase, MarketCandle, ensure_analysis_tables
from database.queries.market import list_market_candles, upsert_market_candle


def _make_engine():
    return create_engine("sqlite:///:memory:", echo=False)


def _make_session() -> Session:
    engine = _make_engine()
    ensure_analysis_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_market_candles_table_created() -> None:
    engine = _make_engine()
    ensure_analysis_tables(engine)

    inspector = inspect(engine)
    assert "market_candles" in inspector.get_table_names()


def test_market_candle_registered_in_analysis_base() -> None:
    tables = {t.name for t in AnalysisBase.metadata.tables.values()}
    assert "market_candles" in tables


def test_market_candle_columns_use_portable_types() -> None:
    cols = MarketCandle.__table__.columns

    assert str(cols["id"].type) == "VARCHAR(36)"
    assert str(cols["asset"].type).startswith("VARCHAR")
    assert str(cols["timeframe"].type).startswith("VARCHAR")
    assert "datetime" in str(cols["open_time"].type).lower()
    assert str(cols["open"].type) == "FLOAT"
    assert str(cols["high"].type) == "FLOAT"
    assert str(cols["low"].type) == "FLOAT"
    assert str(cols["close"].type) == "FLOAT"
    assert str(cols["volume"].type) == "FLOAT"
    assert "json" in str(cols["source_ref"].type).lower()


def test_market_candle_indexes_and_unique_constraint() -> None:
    engine = _make_engine()
    ensure_analysis_tables(engine)
    inspector = inspect(engine)

    uq_names = [c["name"] for c in inspector.get_unique_constraints("market_candles")]
    assert any("uq_market_candle" in name for name in uq_names), uq_names

    index_names = {idx["name"] for idx in inspector.get_indexes("market_candles")}
    assert any("asset" in name and "timeframe" in name for name in index_names), index_names
    assert any("timeframe" in name for name in index_names), index_names
    assert any("source" in name for name in index_names), index_names


def test_upsert_market_candle_creates_and_updates_idempotently() -> None:
    session = _make_session()
    open_time = datetime(2026, 6, 4, 1, 0, tzinfo=UTC)

    first = upsert_market_candle(
        session,
        asset="XAUUSD",
        timeframe="1h",
        open_time=open_time,
        open=3360.0,
        high=3365.0,
        low=3358.0,
        close=3362.0,
        volume=12.5,
        source="jin10_mcp",
        source_ref={"symbol": "XAUUSD"},
        raw_path="storage/raw/jin10/xau.json",
    )
    second = upsert_market_candle(
        session,
        asset="XAUUSD",
        timeframe="1h",
        open_time=open_time,
        open=3361.0,
        high=3366.0,
        low=3359.0,
        close=3364.0,
        volume=13.0,
        source="jin10_mcp",
        source_ref={"symbol": "XAUUSD", "reloaded": True},
        raw_path="storage/raw/jin10/xau-2.json",
    )
    session.commit()

    assert first.id == second.id
    rows = session.query(MarketCandle).all()
    assert len(rows) == 1
    assert rows[0].close == 3364.0
    assert rows[0].raw_path == "storage/raw/jin10/xau-2.json"


def test_list_market_candles_returns_oldest_to_newest() -> None:
    session = _make_session()
    for hour, close in ((1, 3361.0), (2, 3362.5), (3, 3360.8)):
        upsert_market_candle(
            session,
            asset="XAUUSD",
            timeframe="1h",
            open_time=datetime(2026, 6, 4, hour, 0, tzinfo=UTC),
            open=close - 1,
            high=close + 1,
            low=close - 2,
            close=close,
            source="jin10_mcp",
        )
    session.commit()

    rows = list_market_candles(session, asset="XAUUSD", timeframe="1h", limit=2)
    assert [row.open_time.hour for row in rows] == [2, 3]
    assert [row.close for row in rows] == [3362.5, 3360.8]
