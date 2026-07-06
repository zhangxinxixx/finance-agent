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


def test_market_candles_service_returns_native_daily_rows(monkeypatch):
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
    assert payload["provider"] == "yahoo_finance"
    assert payload["candles"][0]["close"] == 3335.0
    assert payload["coverage"]["returned"] == 1
    assert payload["source_trace"]["latest_raw_path"] == "raw/technical/yahoo/GC=F.json"


def test_market_candles_aggregates_15m_from_minute_rows(monkeypatch):
    factory = _session_factory()
    base_time = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)
    with factory() as session:
        for index in range(16):
            price = 3300.0 + index
            upsert_market_candle(
                session,
                asset="XAUUSD",
                timeframe="1m",
                open_time=base_time + timedelta(minutes=index),
                open=price,
                high=price + 2,
                low=price - 1,
                close=price + 0.5,
                source="jin10_mcp_kline_1m",
            )
        session.commit()

    monkeypatch.setattr("apps.api.services.market_candle_service._market_session_factory", lambda: factory)
    payload = get_market_candles(asset="XAUUSD", timeframe="15m", limit=10)

    assert payload["source_timeframe"] == "1m"
    assert payload["provider"] == "jin10_mcp"
    assert len(payload["candles"]) == 2
    assert payload["candles"][0]["open"] == 3300.0
    assert payload["candles"][0]["high"] == 3316.0
    assert payload["candles"][0]["low"] == 3299.0
    assert payload["candles"][0]["close"] == 3314.5
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
    assert payload["coverage"]["reason"] == "candle gaps detected"


def test_market_candles_does_not_fabricate_dxy_intraday():
    payload = get_market_candles(asset="DXY", timeframe="1m", limit=100)

    assert payload["asset"] == "DXY"
    assert payload["timeframe"] == "1m"
    assert payload["candles"] == []
    assert payload["coverage"]["degraded"] is True
    assert "do not fabricate" in payload["coverage"]["reason"]
