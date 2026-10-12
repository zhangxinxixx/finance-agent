from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from apps.data_layer.warehouse_etl import load_warehouse
from database.models.analysis import MacroObservation, MarketCandle
from database.models.task import TaskRun, TaskStep
from database.models.warehouse import (
    AssetDimension,
    CandleFact,
    DateDimension,
    LoadBatch,
    MacroFact,
    MetricDimension,
    SourceDimension,
    WarehouseBase,
)
from database.queries.warehouse_read import (
    list_completed_warehouse_candles,
    list_warehouse_candles,
    list_warehouse_candles_by_assets,
    list_warehouse_macro_observations,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    WarehouseBase.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    engine.dispose()


def _batch(db, dataset: str, cursor: str) -> LoadBatch:
    row = LoadBatch(
        dataset=dataset,
        source_cursor=cursor,
        load_time=datetime(2026, 10, 10, tzinfo=UTC),
        transform_version="test",
        processed=1,
        inserted=1,
        skipped=0,
        rejected=0,
        status="loaded",
        audit_task_run_id=str(uuid4()),
        audit_task_step_id=str(uuid4()),
    )
    db.add(row)
    db.flush()
    return row


def _day(db, value: date) -> DateDimension:
    key = int(value.strftime("%Y%m%d"))
    row = db.get(DateDimension, key)
    if row is None:
        row = DateDimension(
            date_key=key,
            date=value,
            year=value.year,
            month=value.month,
            day=value.day,
            weekday=value.weekday(),
        )
        db.add(row)
        db.flush()
    return row


def _source(db, key: str) -> SourceDimension:
    row = db.scalar(select(SourceDimension).where(SourceDimension.source_key == key))
    if row is None:
        row = SourceDimension(source_key=key)
        db.add(row)
        db.flush()
    return row


def _asset(db, code: str) -> AssetDimension:
    row = db.scalar(select(AssetDimension).where(AssetDimension.code == code))
    if row is None:
        row = AssetDimension(code=code)
        db.add(row)
        db.flush()
    return row


def _macro_fact(
    db,
    *,
    fact_id: int,
    value: float | None,
    retrieved_at: datetime | None,
    version: str,
    source_url: str = "https://fred.example/DGS10",
    unit: str = "percent",
    frequency: str = "daily",
) -> MacroFact:
    source = _source(db, "fred")
    metric = db.scalar(
        select(MetricDimension).where(
            MetricDimension.source_id == source.id,
            MetricDimension.symbol == "DGS10",
            MetricDimension.unit == unit,
            MetricDimension.frequency == frequency,
        )
    )
    if metric is None:
        metric = MetricDimension(source_id=source.id, symbol="DGS10", unit=unit, frequency=frequency)
        db.add(metric)
        db.flush()
    day = _day(db, date(2026, 10, 9))
    batch = _batch(db, "macro", f"macro-{fact_id}")
    row = MacroFact(
        id=fact_id,
        batch_id=batch.id,
        version_sha256=version * 64,
        source_record_id="macro-record",
        metric_id=metric.id,
        date_key=day.date_key,
        value=value,
        unit=unit,
        retrieved_at=retrieved_at,
        source_url=source_url,
        raw_path=f"raw/{version}.json",
        quality_status="blocked" if value is None else "accepted",
    )
    db.add(row)
    db.flush()
    return row


def _candle_fact(
    db,
    *,
    fact_id: int,
    asset: str = "XAUUSD",
    source: str = "primary",
    opened: datetime = datetime(2026, 10, 10, 1, tzinfo=UTC),
    close: float = 4000,
    available_at: datetime | None = datetime(2026, 10, 10, 1, 6, tzinfo=UTC),
    version: str = "a",
) -> CandleFact:
    batch = _batch(db, "candles", f"candle-{fact_id}")
    row = CandleFact(
        id=fact_id,
        batch_id=batch.id,
        version_sha256=version * 64,
        source_record_id=f"candle-record-{asset}-{source}-{opened.isoformat()}",
        asset_id=_asset(db, asset).id,
        source_id=_source(db, source).id,
        date_key=_day(db, opened.date()).date_key,
        timeframe="5m",
        open_time=opened,
        open=close - 2,
        high=close + 3,
        low=close - 4,
        close=close,
        volume=10,
        retrieved_at=available_at,
        created_at=available_at,
        updated_at=available_at,
        provider="twelve_data",
        provider_symbol="XAU/USD" if asset == "XAUUSD" else asset,
        provider_timeframe="5min",
        instrument_type="composite_otc_spot_proxy" if asset == "XAUUSD" else "index",
        source_role="market_primary",
        source_url="https://provider.example/chart",
        source_reference="provider://chart",
        reference_status="ok",
        evidence_scope="provider_chart_observation",
        source_tier="primary",
        quality_status="accepted",
        raw_path=f"raw/{version}.json",
    )
    db.add(row)
    db.flush()
    return row


def test_macro_latest_revision_and_point_in_time_do_not_filter_for_good_value(db):
    first = datetime(2026, 10, 10, 2, tzinfo=UTC)
    second = datetime(2026, 10, 10, 3, tzinfo=UTC)
    _macro_fact(db, fact_id=1, value=4.2, retrieved_at=first, version="a")
    _macro_fact(
        db,
        fact_id=2,
        value=None,
        retrieved_at=second,
        version="b",
        source_url="https://revised.example",
        unit="basis_points",
    )
    db.commit()

    latest = list_warehouse_macro_observations(db)
    assert len(latest) == 1
    assert latest[0].value is None
    assert latest[0].warehouse_fact_id == 2
    assert latest[0].source_url == "https://revised.example"
    assert latest[0].unit == "basis_points"
    assert latest[0].source_refs[0]["quality_status"] == "blocked"
    assert latest[0].id == "macro-record" and latest[0].batch_id > 0

    historical = list_warehouse_macro_observations(
        db,
        as_of=datetime(2026, 10, 10, 10, 30, tzinfo=timezone(timedelta(hours=8))),
    )
    assert [row.warehouse_fact_id for row in historical] == [1]
    assert historical[0].retrieved_at == first


def test_macro_empty_ids_bounds_and_later_unknown_revision_block_pit(db):
    _macro_fact(db, fact_id=1, value=4.2, retrieved_at=datetime(2026, 10, 10, 2, tzinfo=UTC), version="a")
    _macro_fact(db, fact_id=2, value=4.3, retrieved_at=None, version="b")
    db.commit()

    assert list_warehouse_macro_observations(db, record_ids=[]) == []
    assert list_warehouse_macro_observations(db, as_of=datetime(2026, 10, 11, tzinfo=UTC)) == []
    assert list_warehouse_macro_observations(db)[0].warehouse_fact_id == 2
    with pytest.raises(ValueError, match="limit"):
        list_warehouse_macro_observations(db, limit=0)
    with pytest.raises(ValueError, match="fit within limit"):
        list_warehouse_macro_observations(db, record_ids=["a", "b"], limit=1)


def test_candle_latest_revision_pit_completion_boundary_and_order(db):
    opened = datetime(2026, 10, 10, 1, tzinfo=UTC)
    _candle_fact(db, fact_id=1, opened=opened, close=4000, available_at=opened + timedelta(minutes=6), version="a")
    _candle_fact(db, fact_id=2, opened=opened, close=4010, available_at=opened + timedelta(minutes=8), version="b")
    _candle_fact(
        db,
        fact_id=3,
        opened=opened + timedelta(minutes=5),
        close=4020,
        available_at=opened + timedelta(minutes=11),
        version="c",
    )
    db.commit()

    latest = list_warehouse_candles(db, asset="XAUUSD", timeframe="5m", limit=10)
    assert [row.close for row in latest] == [4010.0, 4020.0]
    assert latest[0].source_ref["provider_symbol"] == "XAU/USD"
    assert latest[0].source_ref["retrieved_at"] == opened + timedelta(minutes=8)
    assert latest[0].id.startswith("candle-record-XAUUSD")

    pit = list_warehouse_candles(
        db,
        asset="XAUUSD",
        timeframe="5m",
        as_of=opened + timedelta(minutes=7),
        limit=10,
    )
    assert [row.close for row in pit] == [4000.0]

    completed = list_completed_warehouse_candles(
        db,
        asset="XAUUSD",
        timeframe="5m",
        as_of=opened + timedelta(minutes=11),
        bar_duration=timedelta(minutes=5),
        limit=10,
    )
    assert [row.open_time for row in completed] == [opened, opened + timedelta(minutes=5)]


def test_candle_unknown_later_revision_blocks_pit_and_assets_stay_isolated(db):
    opened = datetime(2026, 10, 10, 1, tzinfo=UTC)
    _candle_fact(db, fact_id=1, opened=opened, available_at=opened + timedelta(minutes=6), version="a")
    _candle_fact(db, fact_id=2, opened=opened, available_at=None, close=5000, version="b")
    _candle_fact(db, fact_id=3, asset="GC", source="yahoo_finance_gc_f", opened=opened, version="c")
    _candle_fact(
        db,
        fact_id=4,
        asset="GC",
        source="yahoo_finance_gc_f",
        opened=opened + timedelta(minutes=5),
        version="d",
    )
    db.commit()

    assert list_warehouse_candles(
        db, asset="XAUUSD", timeframe="5m", as_of=opened + timedelta(days=1)
    ) == []
    latest = list_warehouse_candles(db, asset="XAUUSD", timeframe="5m")
    assert [row.close for row in latest] == [5000.0]
    grouped = list_warehouse_candles_by_assets(
        db, assets=["XAUUSD", "GC", "GC"], timeframe="5m", limit=1
    )
    assert [(row.asset, row.close) for row in grouped] == [("XAUUSD", 5000.0), ("GC", 4000.0)]
    assert all(row.asset != "XAUUSD" or row.source != "yahoo_finance_gc_f" for row in grouped)


def test_reader_executes_only_dwd_selects_and_missing_schema_is_not_hidden(db):
    _macro_fact(db, fact_id=1, value=4.2, retrieved_at=datetime(2026, 10, 10, 2, tzinfo=UTC), version="a")
    _candle_fact(db, fact_id=2)
    db.commit()
    statements: list[str] = []
    event.listen(db.get_bind(), "before_cursor_execute", lambda c, cu, sql, p, ctx, many: statements.append(sql))

    assert list_warehouse_macro_observations(db)
    assert list_warehouse_candles(db, asset="XAUUSD", timeframe="5m")
    assert statements and all(sql.lstrip().upper().startswith("SELECT") for sql in statements)
    assert all(" macro_observations " not in sql and " market_candles " not in sql for sql in statements)

    empty_engine = create_engine("sqlite:///:memory:")
    with sessionmaker(empty_engine)() as empty:
        with pytest.raises(OperationalError):
            list_warehouse_macro_observations(empty)
        with pytest.raises(OperationalError):
            list_warehouse_candles(empty, asset="XAUUSD", timeframe="5m")
    empty_engine.dispose()


def test_etl_maps_typed_lineage_and_evidence_changes_create_versions(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'etl.sqlite'}")
    for model in (MacroObservation, MarketCandle, TaskRun, TaskStep):
        model.__table__.create(engine, checkfirst=True)
    WarehouseBase.metadata.create_all(engine, checkfirst=True)
    with sessionmaker(engine, expire_on_commit=False)() as db:
        macro = MacroObservation(
            id="macro-a",
            source_key="fred",
            symbol="DGS10",
            observation_date=date(2026, 10, 9),
            value=4.2,
            unit="percent",
            frequency="daily",
            source_url="https://fred.example/v1",
            raw_path="raw/macro.json",
            retrieved_at=datetime(2026, 10, 10, 2, tzinfo=UTC),
            source_refs=[{"source": "fred", "symbol": "DGS10", "quality_status": "accepted"}],
        )
        candle = MarketCandle(
            id="candle-a",
            asset="XAUUSD",
            timeframe="5m",
            open_time=datetime(2026, 10, 10, 1, tzinfo=UTC),
            open=3998,
            high=4003,
            low=3997,
            close=4001,
            volume=None,
            source="twelvedata_xauusd_5m",
            raw_path="raw/candle.json",
            source_ref={
                "provider": "twelve_data",
                "provider_symbol": "XAU/USD",
                "provider_timeframe": "5min",
                "instrument_type": "composite_otc_spot_proxy",
                "source_role": "validation",
                "retrieved_at": "2026-10-10T01:06:00Z",
                "quality_status": "accepted_validation",
            },
            created_at=datetime(2026, 10, 10, 1, 6, tzinfo=UTC),
            updated_at=datetime(2026, 10, 10, 1, 6, tzinfo=UTC),
        )
        db.add_all([macro, candle])
        db.commit()

        assert load_warehouse(db, "macro", dry_run=False)["inserted"] == 1
        assert load_warehouse(db, "candles", dry_run=False)["inserted"] == 1
        db.commit()
        macro_row = list_warehouse_macro_observations(db)[0]
        candle_row = list_warehouse_candles(db, asset="XAUUSD", timeframe="5m")[0]
        assert macro_row.source_url == "https://fred.example/v1"
        assert candle_row.created_at == datetime(2026, 10, 10, 1, 6, tzinfo=UTC)
        assert candle_row.source_ref["instrument_type"] == "composite_otc_spot_proxy"
        assert candle_row.source_ref["source_role"] == "validation"

        assert load_warehouse(db, "macro", dry_run=False)["inserted"] == 0
        assert load_warehouse(db, "candles", dry_run=False)["inserted"] == 0
        macro.source_url = "https://fred.example/v2"
        db.commit()
        assert load_warehouse(db, "macro", dry_run=False)["inserted"] == 1
        db.commit()
        assert db.scalar(select(func.count()).select_from(MacroFact)) == 2
        assert list_warehouse_macro_observations(db)[0].source_url == "https://fred.example/v2"
    engine.dispose()
