from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ["FINANCE_AGENT_DISABLE_BACKGROUND_JOBS"] = "1"

from apps.api.main import app
from apps.api.services.market_candle_service import get_market_candles
from database.models.analysis import ensure_analysis_tables
from database.queries.market import upsert_market_candle


def _session_factory():
    engine = create_engine("sqlite:///:memory:", echo=False)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        ensure_analysis_tables(session)
    return factory


def test_market_candles_route_returns_unified_contract(monkeypatch):
    monkeypatch.setattr(
        "apps.api.services.market_candle_service.get_market_candles",
        lambda **_: {
            "asset": "XAUUSD",
            "timeframe": "1D",
            "requested_limit": 1,
            "source_timeframe": "1D",
            "provider": "yahoo_finance",
            "candles": [{"time": "2026-07-01T00:00:00+00:00", "open": 3320.0, "high": 3340.0, "low": 3310.0, "close": 3335.0}],
            "coverage": {"returned": 1, "degraded": False},
            "source_trace": {"latest_raw_path": "raw/technical/yahoo/GC=F.json"},
        },
    )
    response = TestClient(app).get("/api/market/candles", params={"asset": "XAUUSD", "timeframe": "1D", "limit": 1})

    assert response.status_code == 200
    payload = response.json()
    assert payload["asset"] == "XAUUSD"
    assert payload["timeframe"] == "1D"
    assert payload["provider"] == "yahoo_finance"


def test_market_candles_service_excludes_gc_f_rows_from_xauusd(monkeypatch):
    factory = _session_factory()
    with factory() as session:
        upsert_market_candle(
            session,
            asset="XAUUSD",
            timeframe="1d",
            open_time=datetime(2026, 7, 1, 0, 0, tzinfo=UTC),
            open=3320.0,
            high=3340.0,
            low=3310.0,
            close=3335.0,
            source="yahoo_finance_gc_f",
            raw_path="raw/technical/yahoo/GC=F.json",
        )
        session.commit()

    monkeypatch.setattr("apps.api.services.market_candle_service._market_session_factory", lambda: factory)
    payload = get_market_candles(asset="XAUUSD", timeframe="1D", limit=1)

    assert payload["asset"] == "XAUUSD"
    assert payload["timeframe"] == "1D"
    assert payload["source_timeframe"] == "1D"
    assert payload["provider"] == "unavailable"
    assert payload["candles"] == []
    assert payload["coverage"]["degraded"] is True
    assert payload["source_trace"]["latest_raw_path"] is None


def test_market_candles_service_accepts_injected_session(monkeypatch):
    factory = _session_factory()
    with factory() as session:
        upsert_market_candle(
            session,
            asset="XAUUSD",
            timeframe="5m",
            open_time=datetime(2026, 7, 2, 10, 0, tzinfo=UTC),
            open=3330.0,
            high=3350.0,
            low=3320.0,
            close=3345.0,
            source="jin10_mcp_derived_5m",
            raw_path="raw/macro/jin10_mcp/XAUUSD-20260702.json",
        )
        session.commit()

        def fail_factory():
            raise AssertionError("session factory should not be used when a session is injected")

        monkeypatch.setattr("apps.api.services.market_candle_service._market_session_factory", fail_factory)

        payload = get_market_candles(asset="XAUUSD", timeframe="5m", limit=1, session=session)

    assert payload["source_timeframe"] == "5m"
    assert payload["provider"] == "jin10_mcp"
    assert payload["candles"][0]["close"] == 3345.0
    assert payload["source_trace"]["latest_raw_path"] == "raw/macro/jin10_mcp/XAUUSD-20260702.json"


def test_market_candles_aggregates_15m_from_canonical_five_minute_rows(monkeypatch):
    factory = _session_factory()
    base_time = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)
    with factory() as session:
        for index in range(3):
            price = 3300.0 + index * 5
            upsert_market_candle(
                session,
                asset="XAUUSD",
                timeframe="5m",
                open_time=base_time + timedelta(minutes=index * 5),
                open=price,
                high=price + 2,
                low=price - 1,
                close=price + 0.5,
                source="jin10_mcp_derived_5m",
            )
        session.commit()

    monkeypatch.setattr("apps.api.services.market_candle_service._market_session_factory", lambda: factory)
    payload = get_market_candles(asset="XAUUSD", timeframe="15m", limit=10)

    assert payload["source_timeframe"] == "5m"
    assert payload["provider"] == "jin10_mcp"
    assert len(payload["candles"]) == 1
    assert payload["candles"][0]["open"] == 3300.0
    assert payload["candles"][0]["high"] == 3312.0
    assert payload["candles"][0]["low"] == 3299.0
    assert payload["candles"][0]["close"] == 3310.5
    assert payload["coverage"]["expected_interval_seconds"] == 900


def test_market_candles_detects_gaps_and_degraded_coverage(monkeypatch):
    factory = _session_factory()
    base_time = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)
    with factory() as session:
        for minute in (0, 1, 10):
            price = 3300.0 + minute
            upsert_market_candle(
                session,
                asset="XAUUSD",
                timeframe="1m",
                open_time=base_time + timedelta(minutes=minute),
                open=price,
                high=price + 1,
                low=price - 1,
                close=price,
                source="jin10_mcp_kline_1m",
            )
        session.commit()

    monkeypatch.setattr("apps.api.services.market_candle_service._market_session_factory", lambda: factory)
    payload = get_market_candles(asset="XAUUSD", timeframe="1m", limit=3)

    assert payload["coverage"]["gap_count"] == 1
    assert payload["coverage"]["max_gap_seconds"] == 540
    assert payload["coverage"]["degraded"] is True
    assert payload["coverage"]["reason"] == "1m is internal staging; the formal minimum XAUUSD timeframe is 5m."


def test_market_candles_uses_whole_twelve_bar_when_local_15m_is_incomplete(monkeypatch):
    factory = _session_factory()
    base_time = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)
    with factory() as session:
        for index in range(2):
            upsert_market_candle(
                session,
                asset="XAUUSD",
                timeframe="5m",
                open_time=base_time + timedelta(minutes=index * 5),
                open=3300.0 + index,
                high=3302.0 + index,
                low=3299.0 + index,
                close=3301.0 + index,
                source="jin10_mcp_derived_5m",
            )
        upsert_market_candle(
            session,
            asset="XAUUSD",
            timeframe="15m",
            open_time=base_time,
            open=3298.0,
            high=3305.0,
            low=3297.0,
            close=3304.0,
            source="twelvedata_xauusd_15m",
            source_ref={"provider_symbol": "XAU/USD", "quality_status": "accepted_fallback"},
        )
        session.commit()

    monkeypatch.setattr("apps.api.services.market_candle_service._market_session_factory", lambda: factory)
    payload = get_market_candles(asset="XAUUSD", timeframe="15m", limit=1)

    assert payload["provider"] == "twelve_data"
    assert payload["candles"] == [
        {
            "time": base_time.isoformat(),
            "open": 3298.0,
            "high": 3305.0,
            "low": 3297.0,
            "close": 3304.0,
            "volume": None,
            "source": "twelvedata_xauusd_15m",
            "partial": False,
        }
    ]


def test_market_candles_does_not_fabricate_dxy_intraday():
    payload = get_market_candles(asset="DXY", timeframe="1m", limit=100)

    assert payload["asset"] == "DXY"
    assert payload["timeframe"] == "1m"
    assert payload["candles"] == []
    assert payload["coverage"]["degraded"] is True
    assert "do not fabricate" in payload["coverage"]["reason"]


def test_market_candles_returns_gc_under_its_own_asset_identity():
    factory = _session_factory()
    with factory() as session:
        upsert_market_candle(
            session,
            asset="GC",
            timeframe="1d",
            open_time=datetime(2026, 7, 1, tzinfo=UTC),
            open=3320.0,
            high=3340.0,
            low=3310.0,
            close=3335.0,
            source="yahoo_finance_gc_f",
            source_ref={
                "provider_symbol": "GC=F",
                "instrument_type": "futures_continuous_proxy",
            },
        )
        session.commit()
        payload = get_market_candles(asset="GC", timeframe="1D", limit=1, session=session)

    assert payload["asset"] == "GC"
    assert payload["provider"] == "yahoo_finance"
    assert payload["candles"][0]["close"] == 3335.0
