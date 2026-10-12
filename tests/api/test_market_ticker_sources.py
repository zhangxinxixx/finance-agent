from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.api.services import market_service as service
from database.models.analysis import ensure_analysis_tables
from database.queries.market import upsert_market_candle
from tests.helpers.warehouse import materialize_candles


def test_disabled_jin10_uses_newest_spot_bar_and_never_gc(monkeypatch):
    factory = sessionmaker(bind=create_engine("sqlite:///:memory:"), expire_on_commit=False)
    with factory() as session:
        ensure_analysis_tables(session)
        for hour, timeframe, source, price in [
            (0, "1d", "twelvedata", 3700),
            (9, "5m", "twelvedata", 3710),
            (10, "5m", "yahoo_finance_gc_f", 3900),
        ]:
            upsert_market_candle(session, asset="XAUUSD", timeframe=timeframe,
                                 open_time=datetime(2026, 9, 25, hour, tzinfo=UTC),
                                 open=price, high=price, low=price, close=price, source=source)
        materialize_candles(session)
    monkeypatch.setenv("FINANCE_AGENT_DISABLE_JIN10", "true")
    monkeypatch.setattr(service, "_market_session_factory", lambda: factory)
    monkeypatch.setattr(service, "get_macro_latest", lambda: None)

    payload = service.get_market_tickers()

    assert payload["tickers"]["xauusd"]["price"] == 3710
    assert payload["tickers"]["xauusd"]["time"] == "2026-09-25T09:00:00+00:00"
    assert "jin10_news_only" in payload["sources"]


def test_monitor_uses_observation_dates_instead_of_refresh_date(monkeypatch):
    monkeypatch.setattr(service, "get_market_tickers", lambda: {
        "generated_at": "2026-09-28T15:00:00+00:00", "tickers": {
            "xauusd": {"price": 3710, "time": "2026-09-25T09:00:00+00:00", "source": "twelvedata"}
        }
    })
    monkeypatch.setattr(service, "get_macro_latest", lambda: {
        "as_of": "2026-09-28", "indicators": {"US10Y": {"value": 4.1, "date": "2026-09-24"}}
    })
    monkeypatch.setattr(service, "build_market_regime_agent_summary", lambda: None)

    overview = service.get_market_monitor_overview()
    metrics = {row["key"]: row for row in overview["metrics"]}

    assert metrics["XAUUSD"]["latest_date"] == "2026-09-25"
    assert metrics["US10Y"]["latest_date"] == "2026-09-24"
    assert metrics["SOFR"]["latest_date"] is None
    assert metrics["SOFR"]["status"] == "unavailable"
    assert overview["latest_date"] == "2026-09-25"
    monkeypatch.setattr(service, "get_market_tickers", lambda: {
        "generated_at": "2026-09-28T15:00:00+00:00", "tickers": {}})
    monkeypatch.setattr(service, "get_macro_latest", lambda: {"as_of": "2026-09-28", "indicators": {}})
    assert service.get_market_monitor_overview()["latest_date"] is None


def test_monitor_projects_cot_and_gld_with_their_own_report_dates(monkeypatch):
    monkeypatch.setattr(service, "get_market_tickers", lambda: {"tickers": {}})
    monkeypatch.setattr(service, "_latest_market_candle", lambda **kwargs: None)
    monkeypatch.setattr(service, "build_market_regime_agent_summary", lambda: None)
    monkeypatch.setattr(service, "get_macro_latest", lambda: {
        "as_of": "2026-09-28", "snapshot_id": "registered-funds", "indicators": {},
        "cot_reports": {"futures_only": {
            "report_date": "2026-09-22", "freshness_status": "fresh",
            "managed_money": {"latest": {"net": 127389}, "delta": {"net": -5727}},
            "source_refs": [{"reference": "https://www.cftc.gov/"}],
        }},
        "official_etf": {"gold_holdings_tonnes": 1054.55, "as_of": "2026-09-25",
                         "gold_holdings_tonnes_weekly_delta": -2.57,
                         "source_refs": [{"source_url": "https://www.spdrgoldshares.com/"}]},
    })

    metrics = {row["key"]: row for row in service.get_market_monitor_overview()["metrics"]}

    assert metrics["COT_GOLD_NET"]["latest_value"] == 127389
    assert metrics["COT_GOLD_NET"]["latest_date"] == "2026-09-22"
    assert metrics["GLD_HOLDINGS"]["latest_value"] == 1054.55
    assert metrics["GLD_HOLDINGS"]["latest_date"] == "2026-09-25"
    assert metrics["GLD_HOLDINGS"]["status"] == "info"
    assert metrics["GLD_HOLDINGS"]["snapshot_id"] == "registered-funds"
