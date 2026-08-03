from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.features.market_data.formal_snapshot_loader import (
    load_formal_market_snapshots,
    resolve_formal_snapshot_as_of,
)
from database.models.analysis import ensure_analysis_tables
from database.queries.market import upsert_market_candle


def _session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    ensure_analysis_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _source_ref(*, provider_symbol: str, instrument_type: str, source_role: str, retrieved_at: datetime) -> dict:
    return {
        "provider_symbol": provider_symbol,
        "instrument_type": instrument_type,
        "source_role": source_role,
        "retrieved_at": retrieved_at.isoformat(),
        "source_url": f"fixture://{provider_symbol}",
    }


def _upsert_bar(session, *, asset: str, timeframe: str, open_time: datetime, source: str, source_ref: dict) -> None:
    upsert_market_candle(
        session,
        asset=asset,
        timeframe=timeframe,
        open_time=open_time,
        open=100.0,
        high=102.0,
        low=99.0,
        close=101.0,
        source=source,
        source_ref=source_ref,
        raw_path=f"raw/{asset}/{source}.json",
    )


def test_resolve_formal_snapshot_as_of_uses_shanghai_daily_close_and_run_time() -> None:
    run_time = datetime(2026, 7, 21, 3, 0, tzinfo=UTC)

    assert resolve_formal_snapshot_as_of(trade_date="2026-07-20", run_time=run_time) == datetime(
        2026, 7, 20, 13, 0, tzinfo=UTC
    )
    assert resolve_formal_snapshot_as_of(
        trade_date="2026-07-21", run_time=datetime(2026, 7, 21, 11, 30, tzinfo=UTC)
    ) == datetime(2026, 7, 21, 11, 30, tzinfo=UTC)
    assert resolve_formal_snapshot_as_of(
        trade_date="2026-07-21", run_time=datetime(2026, 7, 21, 14, 0, tzinfo=UTC)
    ) == datetime(2026, 7, 21, 13, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="future"):
        resolve_formal_snapshot_as_of(trade_date="2026-07-22", run_time=run_time)
    with pytest.raises(ValueError, match="timezone-aware"):
        resolve_formal_snapshot_as_of(trade_date="2026-07-21", run_time=datetime(2026, 7, 21, 12, 0))


def test_loader_queries_completed_bars_for_each_formal_asset(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    def fake_query(_session, **kwargs):
        calls.append(kwargs)
        return []

    monkeypatch.setattr(
        "apps.features.market_data.formal_snapshot_loader.list_completed_market_candles",
        fake_query,
    )
    as_of = datetime(2026, 7, 20, 13, 0, tzinfo=UTC)
    bundle = load_formal_market_snapshots(object(), as_of=as_of)

    assert [(item["asset"], item["timeframe"], item["bar_duration"]) for item in calls] == [
        ("XAUUSD", "5m", timedelta(minutes=5)),
        ("GC", "1d", timedelta(days=1)),
        ("WTI", "1d", timedelta(days=1)),
        ("BRENT", "1d", timedelta(days=1)),
        ("XAGUSD", "1d", timedelta(days=1)),
        ("DXY", "1d", timedelta(days=1)),
        ("VIX", "1d", timedelta(days=1)),
    ]
    assert all(item["as_of"] == as_of for item in calls)
    assert bundle.as_of == as_of
    assert bundle.market_prices.readiness == "blocked"
    assert bundle.oil.readiness == "blocked"
    assert bundle.market_context is not None
    assert bundle.market_context.readiness == "blocked"


def test_loader_normalizes_sqlite_orm_rows_and_selects_xau_primary() -> None:
    session = _session()
    as_of = datetime(2026, 7, 20, 13, 0, tzinfo=UTC)
    spot_open = as_of - timedelta(minutes=10)
    _upsert_bar(
        session,
        asset="XAUUSD",
        timeframe="5m",
        open_time=spot_open,
        source="jin10_mcp_derived_5m",
        source_ref=_source_ref(
            provider_symbol="XAUUSD",
            instrument_type="otc_spot_quote_proxy",
            source_role="market_primary",
            retrieved_at=spot_open + timedelta(minutes=5),
        ),
    )
    _upsert_bar(
        session,
        asset="XAUUSD",
        timeframe="5m",
        open_time=spot_open,
        source="twelvedata_xauusd_5m",
        source_ref=_source_ref(
            provider_symbol="XAU/USD",
            instrument_type="otc_spot_quote_proxy",
            source_role="fallback",
            retrieved_at=spot_open + timedelta(minutes=5),
        ),
    )
    gc_open = as_of - timedelta(days=2)
    _upsert_bar(
        session,
        asset="GC",
        timeframe="1d",
        open_time=gc_open,
        source="yahoo_finance_gc_f",
        source_ref=_source_ref(
            provider_symbol="GC=F",
            instrument_type="futures_continuous_proxy",
            source_role="futures_continuous_proxy",
            retrieved_at=gc_open + timedelta(days=1),
        ),
    )
    session.commit()

    bundle = load_formal_market_snapshots(session, as_of=as_of)

    assert bundle.market_prices.readiness == "ready"
    assert bundle.market_prices.xauusd_spot.source_refs[0].source == "jin10_mcp_derived_5m"
    assert bundle.market_prices.xauusd_spot.source_refs[0].raw_path.endswith("jin10_mcp_derived_5m.json")
    assert bundle.market_prices.xauusd_spot.bar_open_time.tzinfo is not None
    assert bundle.market_prices.gc_futures.quality_status == "accepted"
    assert bundle.oil.readiness == "blocked"
    assert bundle.oil.wti.freshness_status == "missing"
    assert bundle.oil.brent.freshness_status == "missing"
    assert bundle.market_context is not None
    assert bundle.market_context.readiness == "blocked"


def test_loader_propagates_repository_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_query(*_args, **_kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        "apps.features.market_data.formal_snapshot_loader.list_completed_market_candles",
        fail_query,
    )
    with pytest.raises(RuntimeError, match="database unavailable"):
        load_formal_market_snapshots(object(), as_of=datetime(2026, 7, 20, 13, 0, tzinfo=UTC))


def test_loader_is_stable_for_repeated_completed_queries() -> None:
    session = _session()
    as_of = datetime(2026, 7, 20, 13, 0, tzinfo=UTC)
    spot_open = as_of - timedelta(minutes=10)
    _upsert_bar(
        session,
        asset="XAUUSD",
        timeframe="5m",
        open_time=spot_open,
        source="jin10_mcp_derived_5m",
        source_ref=_source_ref(
            provider_symbol="XAUUSD",
            instrument_type="otc_spot_quote_proxy",
            source_role="market_primary",
            retrieved_at=spot_open + timedelta(minutes=5),
        ),
    )
    gc_open = as_of - timedelta(days=2)
    _upsert_bar(
        session,
        asset="GC",
        timeframe="1d",
        open_time=gc_open,
        source="yahoo_finance_gc_f",
        source_ref=_source_ref(
            provider_symbol="GC=F",
            instrument_type="futures_continuous_proxy",
            source_role="futures_continuous_proxy",
            retrieved_at=gc_open + timedelta(days=1),
        ),
    )
    session.commit()

    results = [load_formal_market_snapshots(session, as_of=as_of) for _ in range(100)]

    assert len({item.market_prices.model_dump_json() for item in results}) == 1
    assert len({item.oil.model_dump_json() for item in results}) == 1
    assert len({item.market_context.model_dump_json() for item in results if item.market_context is not None}) == 1
