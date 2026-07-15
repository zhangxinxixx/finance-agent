from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from apps.api.main import api_market_monitor
from apps.api.main import app
from apps.api.services.market_service import get_market_monitor_history, get_market_monitor_overview
from database.models.analysis import ensure_analysis_tables
from database.queries.market import upsert_market_candle
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ["FINANCE_AGENT_DISABLE_BACKGROUND_JOBS"] = "1"


def test_market_monitor_route_returns_read_model():
    data = api_market_monitor()
    assert "generated_at" in data
    assert "metrics" in data
    assert "environment_filters" in data
    assert "source_trace" in data
    assert "market_regime" in data
    assert "primary_driver" in data
    assert "agent_market_regime" in data


def test_market_monitor_route_includes_agent_market_regime(monkeypatch):
    monkeypatch.setattr(
        "apps.api.services.market_service.build_market_regime_agent_summary",
        lambda: {
            "agent_name": "market_regime",
            "regime": "trend_tailwind",
            "regime_label": "趋势顺风",
            "summary": "宏观流动性支持风险资产。",
            "key_drivers": ["REAL_10Y"],
        },
    )

    data = api_market_monitor()

    assert data["agent_market_regime"]["regime"] == "trend_tailwind"
    assert data["agent_market_regime"]["key_drivers"] == ["REAL_10Y"]


def test_market_monitor_history_route_is_registered():
    client = TestClient(app)
    response = client.get("/api/market/monitor/history", params={"timeframe": "1D", "limit": 30})
    assert response.status_code == 200
    payload = response.json()
    assert payload["timeframe"] == "1D"
    assert "series" in payload


def test_market_monitor_overview_does_not_use_gc_f_as_xauusd_fallback(monkeypatch):
    engine = create_engine("sqlite:///:memory:", echo=False)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        ensure_analysis_tables(session)
        upsert_market_candle(
            session,
            asset="XAUUSD",
            timeframe="1d",
            open_time=datetime(2026, 6, 4, 0, 0, tzinfo=UTC),
            open=3350.0,
            high=3360.0,
            low=3348.0,
            close=3358.5,
            source="yahoo_finance_gc_f",
        )
        session.commit()

    monkeypatch.setattr(
        "apps.api.services.market_service.get_market_tickers",
        lambda: {
            "generated_at": "2026-06-05T00:00:00+00:00",
            "sources": ["jin10_mcp_error"],
            "tickers": {},
            "market_regime": {"regime": "neutral", "confidence": 0.0, "available": False},
            "primary_driver": {"driver": "data_insufficient", "secondary": None, "confidence": 0.0},
        },
    )
    monkeypatch.setattr("apps.api.services.market_service.get_macro_latest", lambda: None)
    monkeypatch.setattr("apps.api.services.market_service._market_session_factory", lambda: session_factory)

    data = get_market_monitor_overview()

    xauusd = next(item for item in data["metrics"] if item["key"] == "XAUUSD")
    assert xauusd["latest_value"] is None
    assert xauusd["status"] == "unavailable"


def test_market_monitor_history_1d_does_not_sample_hourly_rows(monkeypatch):
    engine = create_engine("sqlite:///:memory:", echo=False)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        ensure_analysis_tables(session)
        upsert_market_candle(
            session,
            asset="XAUUSD",
            timeframe="1h",
            open_time=datetime(2026, 6, 4, 1, 0, tzinfo=UTC),
            open=3360.0,
            high=3365.0,
            low=3358.0,
            close=3362.0,
            source="jin10_mcp",
        )
        session.commit()

    monkeypatch.setattr("apps.api.services.market_service._market_session_factory", lambda: session_factory)
    data = get_market_monitor_history(limit=30, timeframe="1D")
    assert data["timeframe"] == "1D"
    assert data["source_timeframe"] == "1d"
    assert data["available_fields"][:2] == ["XAUUSD", "DXY"]
    assert data["degraded"] is True
    assert data["series"] == []


def test_market_monitor_history_15m_aggregates_canonical_five_minute_candles(monkeypatch):
    engine = create_engine("sqlite:///:memory:", echo=False)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    base_time = datetime(2026, 6, 4, 1, 0, tzinfo=UTC)
    with session_factory() as session:
        ensure_analysis_tables(session)
        for index in range(3):
            price = 3360.0 + index * 5
            upsert_market_candle(
                session,
                asset="XAUUSD",
                timeframe="5m",
                open_time=base_time + timedelta(minutes=index * 5),
                open=price,
                high=price + 2.0,
                low=price - 1.0,
                close=price + 0.5,
                source="jin10_mcp_derived_5m",
            )
        session.commit()

    monkeypatch.setattr("apps.api.services.market_service._market_session_factory", lambda: session_factory)
    data = get_market_monitor_history(limit=30, timeframe="15M")
    assert data["timeframe"] == "15M"
    assert data["source_timeframe"] == "5m"
    assert data["available_points"] == 1
    assert data["series"][0]["date"] == base_time.isoformat()
    assert data["series"][0]["xauusd_ohlc"] == {
        "open": 3360.0,
        "high": 3372.0,
        "low": 3359.0,
        "close": 3370.5,
    }


def test_market_monitor_history_30m_rejects_incomplete_bucket(monkeypatch):
    engine = create_engine("sqlite:///:memory:", echo=False)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    base_time = datetime(2026, 6, 5, 7, 30, tzinfo=UTC)
    with session_factory() as session:
        ensure_analysis_tables(session)
        for index in range(5):
            price = 4460.0 + index * 0.1
            upsert_market_candle(
                session,
                asset="XAUUSD",
                timeframe="5m",
                open_time=base_time + timedelta(minutes=index * 5),
                open=price,
                high=price + 0.5,
                low=price - 0.5,
                close=price + 0.2,
                source="jin10_mcp_derived_5m",
            )
        session.commit()

    monkeypatch.setattr("apps.api.services.market_service._market_session_factory", lambda: session_factory)
    data = get_market_monitor_history(limit=8, timeframe="30M")
    assert data["timeframe"] == "30M"
    assert data["source_timeframe"] == "30m"
    assert data["available_points"] == 0
    assert data["series"] == []
    assert data["degraded"] is True


def test_market_monitor_history_5m_returns_canonical_bars(monkeypatch):
    engine = create_engine("sqlite:///:memory:", echo=False)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    base_time = datetime(2026, 6, 5, 9, 0, tzinfo=UTC)
    with session_factory() as session:
        ensure_analysis_tables(session)
        for index in range(2):
            price = 4400.0 + index * 0.1
            upsert_market_candle(
                session,
                asset="XAUUSD",
                timeframe="5m",
                open_time=base_time + timedelta(minutes=index * 5),
                open=price,
                high=price + 1.0,
                low=price - 1.0,
                close=price + 0.2,
                source="jin10_mcp_derived_5m",
            )
        session.commit()

    monkeypatch.setattr("apps.api.services.market_service._market_session_factory", lambda: session_factory)
    data = get_market_monitor_history(limit=8, timeframe="5M")
    assert data["timeframe"] == "5M"
    assert data["source_timeframe"] == "5m"
    assert data["available_points"] == 2
    assert data["series"][0]["date"] == base_time.isoformat()
    assert data["series"][1]["date"] == (base_time + timedelta(minutes=5)).isoformat()


def test_market_monitor_history_daily_excludes_gc_f_misclassified_as_xauusd(monkeypatch, tmp_path):
    macro_root = tmp_path / "storage" / "features" / "macro" / "2026-06-04"
    macro_root.mkdir(parents=True, exist_ok=True)
    (macro_root / "macro_snapshot.json").write_text(
        """
        {
          "as_of": "2026-06-04",
          "indicators": {
            "DXY": {"value": 99.1},
            "REAL_10Y": {"value": 2.02},
            "T10YIE": {"value": 2.31}
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    engine = create_engine("sqlite:///:memory:", echo=False)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        ensure_analysis_tables(session)
        upsert_market_candle(
            session,
            asset="XAUUSD",
            timeframe="1d",
            open_time=datetime(2026, 6, 4, 0, 0, tzinfo=UTC),
            open=3350.0,
            high=3360.0,
            low=3348.0,
            close=3358.5,
            source="yahoo_finance_gc_f",
        )
        session.commit()

    monkeypatch.setattr("apps.api.services.market_service._PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("apps.api.services.market_service._market_session_factory", lambda: session_factory)
    data = get_market_monitor_history(limit=30, timeframe="1M")
    assert data["timeframe"] == "1M"
    assert data["source_timeframe"] == "1d"
    assert data["series"][0]["XAUUSD"] is None
    assert data["series"][0]["DXY"] == 99.1
    assert data["series"][0]["xauusd_ohlc"] is None
