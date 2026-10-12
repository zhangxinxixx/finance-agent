from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from apps.api.main import api_market_monitor
from apps.api.main import app
from apps.api.services.market_service import get_market_monitor_history, get_market_monitor_overview
from database.models.analysis import ensure_analysis_tables
from database.queries.market import upsert_market_candle
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from tests.helpers.warehouse import create_collection_schema, materialize_candles

os.environ["FINANCE_AGENT_DISABLE_BACKGROUND_JOBS"] = "1"


def _market_metric(data, key):
    return next(item for item in data["metrics"] if item["key"] == key)


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


@pytest.mark.parametrize("indicator_key", ["REAL_10Y", "REAL10Y"])
def test_market_monitor_overview_maps_real_rate_alias_and_preserves_metadata(monkeypatch, indicator_key):
    monkeypatch.setattr(
        "apps.api.services.market_service.get_market_tickers",
        lambda: {"generated_at": "2026-10-03T00:00:00+00:00", "tickers": {}},
    )
    monkeypatch.setattr(
        "apps.api.services.market_service.get_macro_latest",
        lambda: {
            "as_of": "2026-10-03",
            "indicators": {
                indicator_key: {
                    "value": 2.92,
                    "date": "2026-10-02",
                    "unit": "percentage_points",
                    "weekly_change": -0.12,
                    "monthly_change": 0.31,
                    "direction_note": "observed_real_rate",
                }
            },
        },
    )
    monkeypatch.setattr("apps.api.services.market_service._latest_market_candle", lambda **_kwargs: None)
    monkeypatch.setattr("apps.api.services.market_service.build_market_regime_agent_summary", lambda: None)

    metric = _market_metric(get_market_monitor_overview(), "REAL_10Y")

    assert metric["latest_value"] == 2.92
    assert metric["latest_date"] == "2026-10-02"
    assert metric["unit"] == "percentage_points"
    assert metric["one_week_change"] == -0.12
    assert metric["one_month_change"] == 0.31
    assert metric["interpretation"] == "observed_real_rate"
    assert metric["status"] == "ok"


def test_market_monitor_overview_prefers_existing_real_10y_key(monkeypatch):
    monkeypatch.setattr(
        "apps.api.services.market_service.get_market_tickers",
        lambda: {"generated_at": "2026-10-03T00:00:00+00:00", "tickers": {}},
    )
    monkeypatch.setattr(
        "apps.api.services.market_service.get_macro_latest",
        lambda: {
            "as_of": "2026-10-03",
            "indicators": {
                "REAL_10Y": {"value": 1.23, "date": "2026-10-01", "unit": "legacy_unit"},
                "REAL10Y": {"value": 2.92, "date": "2026-10-02", "unit": "official_unit"},
            },
        },
    )
    monkeypatch.setattr("apps.api.services.market_service._latest_market_candle", lambda **_kwargs: None)
    monkeypatch.setattr("apps.api.services.market_service.build_market_regime_agent_summary", lambda: None)

    metric = _market_metric(get_market_monitor_overview(), "REAL_10Y")

    assert metric["latest_value"] == 1.23
    assert metric["latest_date"] == "2026-10-01"
    assert metric["unit"] == "legacy_unit"


@pytest.mark.parametrize(
    "indicators, expected_date",
    [
        ({}, None),
        ({"REAL10Y": {"value": None, "date": "2026-10-02", "unit": "%"}}, "2026-10-02"),
        ({"REAL10Y": {"value": float("inf"), "date": "2026-10-02", "unit": "%"}}, "2026-10-02"),
    ],
)
def test_market_monitor_overview_does_not_promote_missing_or_non_finite_real_rate(
    monkeypatch, indicators, expected_date
):
    monkeypatch.setattr(
        "apps.api.services.market_service.get_market_tickers",
        lambda: {"generated_at": "2026-10-03T00:00:00+00:00", "tickers": {}},
    )
    monkeypatch.setattr(
        "apps.api.services.market_service.get_macro_latest",
        lambda: {"as_of": "2026-10-03", "indicators": indicators},
    )
    monkeypatch.setattr("apps.api.services.market_service._latest_market_candle", lambda **_kwargs: None)
    monkeypatch.setattr("apps.api.services.market_service.build_market_regime_agent_summary", lambda: None)

    metric = _market_metric(get_market_monitor_overview(), "REAL_10Y")

    assert metric["latest_value"] is None
    assert metric["latest_date"] == expected_date
    assert metric["status"] == "unavailable"


def test_market_monitor_history_route_is_registered(monkeypatch):
    monkeypatch.setattr(
        "apps.api.routes.market_monitor_routes.get_market_monitor_history",
        lambda *, limit, timeframe: {"timeframe": timeframe, "series": [], "limit": limit},
    )
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
        create_collection_schema(session.get_bind())
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
        materialize_candles(session)

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
        create_collection_schema(session.get_bind())
        upsert_market_candle(
            session,
            asset="XAUUSD",
            timeframe="1h",
            open_time=datetime(2026, 6, 4, 1, 0, tzinfo=UTC),
            open=3360.0,
            high=3365.0,
            low=3358.0,
            close=3362.0,
            source="twelvedata_xauusd",
        )
        session.commit()
        materialize_candles(session)

    monkeypatch.setattr("apps.api.services.market_service._market_session_factory", lambda: session_factory)
    data = get_market_monitor_history(limit=30, timeframe="1D")
    assert data["timeframe"] == "1D"
    assert data["source_timeframe"] == "1d"
    assert data["available_fields"][:2] == ["XAUUSD", "DXY"]
    assert data["degraded"] is True
    assert data["series"] == []


def test_market_monitor_history_daily_omits_non_finite_values(monkeypatch, tmp_path):
    macro_root = tmp_path / "storage" / "features" / "macro" / "2026-09-06"
    macro_root.mkdir(parents=True)
    (macro_root / "macro_snapshot.json").write_text(
        json.dumps(
            {
                "as_of": "2026-09-06",
                "indicators": {
                    "DXY": {"value": None},
                    "REAL_10Y": {"value": float("inf")},
                },
            }
        ),
        encoding="utf-8",
    )

    engine = create_engine("sqlite:///:memory:", echo=False)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        ensure_analysis_tables(session)
        create_collection_schema(session.get_bind())

    monkeypatch.setattr("apps.api.services.market_service._PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("apps.api.services.market_service._market_session_factory", lambda: session_factory)
    monkeypatch.setattr(
        "apps.api.services.market_service.list_market_candles_by_assets",
        lambda *_args, **_kwargs: [
            SimpleNamespace(
                asset="DXY",
                open_time=datetime(2026, 9, 6, 0, 0, tzinfo=UTC),
                open=float("nan"),
                high=float("nan"),
                low=float("nan"),
                close=float("nan"),
                source="test_non_finite_daily",
            )
        ],
    )

    data = get_market_monitor_history(limit=30, timeframe="1D")

    assert data["series"] == [
        {
            "date": "2026-09-06",
            "DXY": None,
            "US10Y": None,
            "REAL_10Y": None,
            "T10YIE": None,
            "YIELD_SPREAD_2Y_3M": None,
            "XAUUSD": None,
            "xauusd_ohlc": None,
        }
    ]
    assert data["degraded"] is True
    assert data["invalid_numeric_fields"] == [
        {"date": "2026-09-06", "field": "DXY", "reason": "non_finite"},
        {"date": "2026-09-06", "field": "REAL_10Y", "reason": "non_finite"},
    ]
    json.dumps(data, allow_nan=False)


@pytest.mark.parametrize("indicator_key", ["REAL_10Y", "REAL10Y"])
def test_market_monitor_history_maps_real_rate_alias(monkeypatch, tmp_path, indicator_key):
    macro_root = tmp_path / "storage" / "features" / "macro" / "2026-10-02"
    macro_root.mkdir(parents=True)
    (macro_root / "macro_snapshot.json").write_text(
        json.dumps(
            {
                "as_of": "2026-10-02",
                "indicators": {indicator_key: {"value": 2.92, "date": "2026-10-02", "unit": "%"}},
            }
        ),
        encoding="utf-8",
    )

    engine = create_engine("sqlite:///:memory:", echo=False)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        ensure_analysis_tables(session)
        create_collection_schema(session.get_bind())

    monkeypatch.setattr("apps.api.services.market_service._PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("apps.api.services.market_service._market_session_factory", lambda: session_factory)

    data = get_market_monitor_history(limit=30, timeframe="1D")

    assert data["series"][0]["date"] == "2026-10-02"
    assert data["series"][0]["REAL_10Y"] == 2.92
    assert data["invalid_numeric_fields"] == []


def test_market_monitor_history_prefers_existing_real_10y_key(monkeypatch, tmp_path):
    macro_root = tmp_path / "storage" / "features" / "macro" / "2026-10-02"
    macro_root.mkdir(parents=True)
    (macro_root / "macro_snapshot.json").write_text(
        json.dumps(
            {
                "as_of": "2026-10-02",
                "indicators": {
                    "REAL_10Y": {"value": 1.23},
                    "REAL10Y": {"value": 2.92},
                },
            }
        ),
        encoding="utf-8",
    )

    engine = create_engine("sqlite:///:memory:", echo=False)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        ensure_analysis_tables(session)
        create_collection_schema(session.get_bind())

    monkeypatch.setattr("apps.api.services.market_service._PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("apps.api.services.market_service._market_session_factory", lambda: session_factory)

    data = get_market_monitor_history(limit=30, timeframe="1D")

    assert data["series"][0]["REAL_10Y"] == 1.23


def test_market_monitor_history_does_not_fill_missing_real_rate_with_zero(monkeypatch, tmp_path):
    macro_root = tmp_path / "storage" / "features" / "macro" / "2026-10-02"
    macro_root.mkdir(parents=True)
    (macro_root / "macro_snapshot.json").write_text(
        json.dumps({"as_of": "2026-10-02", "indicators": {"DXY": {"value": 99.1}}}),
        encoding="utf-8",
    )

    engine = create_engine("sqlite:///:memory:", echo=False)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        ensure_analysis_tables(session)
        create_collection_schema(session.get_bind())

    monkeypatch.setattr("apps.api.services.market_service._PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("apps.api.services.market_service._market_session_factory", lambda: session_factory)

    data = get_market_monitor_history(limit=30, timeframe="1D")

    assert data["series"][0]["REAL_10Y"] is None


def test_market_monitor_history_keeps_non_finite_real_rate_degraded_for_alias(monkeypatch, tmp_path):
    macro_root = tmp_path / "storage" / "features" / "macro" / "2026-10-02"
    macro_root.mkdir(parents=True)
    (macro_root / "macro_snapshot.json").write_text(
        json.dumps({"as_of": "2026-10-02", "indicators": {"REAL10Y": {"value": float("inf")}}}),
        encoding="utf-8",
    )

    engine = create_engine("sqlite:///:memory:", echo=False)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        ensure_analysis_tables(session)
        create_collection_schema(session.get_bind())

    monkeypatch.setattr("apps.api.services.market_service._PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("apps.api.services.market_service._market_session_factory", lambda: session_factory)

    data = get_market_monitor_history(limit=30, timeframe="1D")

    assert data["series"][0]["REAL_10Y"] is None
    assert data["degraded"] is True
    assert data["invalid_numeric_fields"] == [
        {"date": "2026-10-02", "field": "REAL_10Y", "reason": "non_finite"}
    ]
    json.dumps(data, allow_nan=False)


def test_market_monitor_history_15m_aggregates_canonical_five_minute_candles(monkeypatch):
    engine = create_engine("sqlite:///:memory:", echo=False)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    base_time = datetime(2026, 6, 4, 1, 0, tzinfo=UTC)
    with session_factory() as session:
        ensure_analysis_tables(session)
        create_collection_schema(session.get_bind())
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
                source="twelvedata_xauusd_5m",
            )
        session.commit()
        materialize_candles(session)

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
        create_collection_schema(session.get_bind())
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
                source="twelvedata_xauusd_5m",
            )
        session.commit()
        materialize_candles(session)

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
        create_collection_schema(session.get_bind())
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
                source="twelvedata_xauusd_5m",
            )
        session.commit()
        materialize_candles(session)

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
        create_collection_schema(session.get_bind())
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
        materialize_candles(session)

    monkeypatch.setattr("apps.api.services.market_service._PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("apps.api.services.market_service._market_session_factory", lambda: session_factory)
    data = get_market_monitor_history(limit=30, timeframe="1M")
    assert data["timeframe"] == "1M"
    assert data["source_timeframe"] == "1d"
    assert data["series"][0]["XAUUSD"] is None
    assert data["series"][0]["DXY"] == 99.1
    assert data["series"][0]["xauusd_ohlc"] is None


def test_cross_asset_metrics_project_collected_macro_facts(monkeypatch):
    from apps.api.services import market_service as service
    indicators = {
        "ON_RRP_USAGE": {"value": 1.501, "unit": "B", "date": "2026-10-02", "weekly_change": .93},
        "WALCL": {"value": 6743.031, "unit": "B", "date": "2026-09-30", "monthly_change": -2},
        "BROAD_DOLLAR": {"value": 120.33, "unit": "index", "date": "2026-09-25"},
        "VIX": {"value": 16.39, "unit": "index", "date": "2026-10-01"},
    }
    monkeypatch.setattr(service, "get_macro_latest", lambda: {"as_of": "2026-10-05", "snapshot_id": "snapshot-latest", "indicators": indicators})
    monkeypatch.setattr(service, "get_market_tickers", lambda: {"tickers": {"xauusd": {"price": 4100, "time": "2026-10-05T14:00:00+08:00"}}})
    monkeypatch.setattr(service, "build_market_regime_agent_summary", lambda: None)
    def metrics():
        return {m["key"]: m for m in service.get_market_monitor_overview()["metrics"]}
    result = metrics()
    for key, symbol in [("REPO", "ON_RRP_USAGE"), ("FED_BS", "WALCL"), ("USDX_N", "BROAD_DOLLAR"), ("VIX", "VIX")]:
        item = result[key]
        source = indicators[symbol]
        assert item["latest_value"] == source["value"]
        assert item["latest_date"] == source["date"]
        assert item["unit"] == source["unit"]
        assert item["status"] == "ok"
        assert item["snapshot_id"] == "snapshot-latest"
        assert item["source_symbol"] == symbol
    assert result["RRP"]["latest_value"] == result["REPO"]["latest_value"]
    assert result["REPO"]["one_week_change"] == .93
    assert result["FED_BS"]["one_month_change"] == -2
    assert result["DXY"]["latest_value"] is None
    indicators.pop("WALCL")
    indicators["VIX"]["value"] = float("inf")
    result=metrics()
    assert result["FED_BS"]["latest_value"] is None
    assert result["FED_BS"]["latest_date"] is None
    assert result["FED_BS"]["status"] == "unavailable"
    assert result["VIX"]["latest_value"] is None
    assert result["VIX"]["status"] == "unavailable"
    indicators["RRP"] = indicators.pop("ON_RRP_USAGE")
    result = metrics()
    assert result["REPO"]["latest_value"] == 1.501
    assert result["REPO"]["source_symbol"] == "RRP"
    assert result["REPO"]["source_refs"] == ["GET /api/macro/latest#RRP"]
