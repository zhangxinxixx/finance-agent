from copy import deepcopy
from datetime import datetime, timezone
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from apps.api.services import gold_workspace_service as service

NOW = datetime(2026, 10, 7, 13, 1, tzinfo=timezone.utc)


def quote(**extra):
    return {"tickers": {"xauusd": {"price": 4076.1, "change_pct": -2.09,
                                  "time": "2026-10-07T13:00:00Z", "source": "engineering_spot", **extra}}}


def report(**extra):
    return {"status": "available", "report_id": "engineering-report", "run_id": "engineering-run",
            "snapshot_id": "engineering-snapshot", "trade_date": "2026-10-07", "as_of": "2026-10-07T12:00:00Z",
            "summary": "## 一句话结论\n\n工程研究正文末段。", "bias": "bearish", "publish_allowed": False,
            "price_anchor": {"instrument_type": "spot", "price": 4143.1, "price_time": "2026-10-07T04:00:00Z"}, **extra}


def build(macro=None, quotes=None, research=None):
    return service.build_gold_workspace(macro=macro, quotes=quotes, research=research, now=NOW)


def factor(result, key):
    return next(row for row in result["factors"] if row["key"] == key)


def test_real_input_units_refs_windows_and_immutability():
    macro = {"source_refs": {"DFII10": {"source": "fred", "source_url": "https://fred.stlouisfed.org/series/DFII10"},
                              "DGS10": {"source": "fred"}, "DXY": {"source": "engineering-dxy"}},
             "indicators": {"REAL10Y": {"value": 2.91, "date": "2026-10-06", "daily_change": -.04, "unit": "%"},
                            "REAL_10Y": {"value": 8.0, "date": "2026-10-06", "daily_change": .1},
                            "US10Y": {"value": 5.27, "date": "2026-10-06", "weekly_change": .12},
                            "DXY": {"value": 102.4, "date": "2026-10-07", "daily_change": .45}}}
    inputs = (macro, quote(), report())
    baseline = deepcopy(inputs)
    result = build(*inputs)
    assert inputs == baseline
    real = factor(result, "REAL10Y")
    assert real["value"] == 2.91 and real["change"] == -4
    assert real["change_unit"] == "bp" and real["change_window"] == "1d"
    assert real["impact"] == "supportive" and real["source_refs"][0]["source"] == "fred"
    assert factor(result, "US10Y")["change"] == 12
    assert factor(result, "US10Y")["change_window"] == "1w"
    assert factor(result, "DXY")["change"] == .45
    assert factor(result, "DXY")["impact"] == "pressure"
    assert result["comparison"]["price_change"] == -67
    assert result["research"]["status"] == "current"
    assert result["research"]["publish_allowed"] is False
    assert "末段" in result["research"]["narrative"]


@pytest.mark.parametrize("extra", [
    {"price": float("nan")}, {"price": float("inf")}, {"price": True}, {"price": 0}, {"price": -3},
    {"time": "2026-10-07T14:00:00Z"}, {"time": "2026-10-07T13:00:00"}, {"time": "bad"},
    {"time": "2026-10-06T13:00:00Z"}, {"source": None}, {"source": "mock_realtime"},
    {"source": "research_snapshot_spot"}, {"instrument_kind": "futures"}, {"status": "stale"}, {"status": "blocked"},
])
def test_unverified_prices_cannot_drive_comparison(extra):
    result = build(quotes=quote(**extra), research=report())
    assert result["price"]["status"] != "fresh"
    assert result["comparison"]["status"] == "unavailable"
    json.dumps(result, allow_nan=False)


def test_gc_never_becomes_spot_and_missing_rows_survive():
    result = build(quotes={"tickers": {"GC": {"price": 9999, "time": "2026-10-07T13:00:00Z"}}})
    assert result["price"]["value"] is None
    assert len(result["factors"]) == 14
    assert all(row["status"] == "unavailable" for row in result["factors"])
    assert result["status"] == "unavailable"


@pytest.mark.parametrize("row", [
    {"value": 4.8, "date": "2020-01-01"}, {"value": 4.8, "date": "2026-10-08"},
    {"value": 4.8, "date": "2026-10-07", "status": "blocked"},
    {"value": 4.8, "date": "2026-10-07", "freshness_status": "stale"},
    {"value": 4.8, "date": "2026-10-07T13:30:00Z"},
    {"value": 4.8, "date": "2026-10-07", "quality_status": "unverified"},
    {"value": float("inf"), "date": "2026-10-07"}, {"value": True, "date": "2026-10-07"},
    {"value": 4.8},
])
def test_invalid_or_old_macro_never_has_directional_impact(row):
    result = build(macro={"indicators": {"US10Y": {**row, "daily_change": .02, "source": "fred"}}})
    assert factor(result, "US10Y")["status"] not in {"fresh", "recent"}
    assert factor(result, "US10Y")["impact"] == "unconfirmed"
    json.dumps(result, allow_nan=False)


def test_estimated_real_yield_remains_explicit():
    result = build(macro={"indicators": {"REAL_10Y": {"value": 2.9, "date": "2026-10-06", "daily_change": .01}},
                          "source_refs": {"DGS10": {"source": "fred"}, "T10YIE": {"source": "fred"}}})
    real = factor(result, "REAL10Y")
    assert "估算" in real["label"] and "非同期直接 TIPS" in real["interpretation"]
    assert len(real["source_refs"]) == 2


def test_mixed_energy_and_slow_flow_frequencies_are_preserved():
    macro = {"indicators": {"WTI_SPOT": {"value": 80, "date": "2026-10-06", "daily_change": 2, "source": "eia"}},
             "official_etf": {"gold_holdings_tonnes": 900, "gold_holdings_tonnes_reported_on": "2026-10-06",
                              "gold_holdings_tonnes_weekly_delta": 3, "source_refs": [{"source": "spdr"}]},
             "cot_reports": {"futures_only": {"report_date": "2026-09-29", "source_refs": [{"source": "cftc"}],
                             "managed_money": {"latest": {"net": -100}, "delta": {"net": 10}}}}}
    result = build(macro=macro)
    assert factor(result, "WTI_SPOT")["impact"] == "mixed"
    assert factor(result, "GLD_HOLDINGS")["change_window"] == "1w"
    assert factor(result, "COT_GOLD_NET")["frequency"] == "weekly"
    assert factor(result, "COT_GOLD_NET")["value"] == -100


@pytest.mark.parametrize("extra", [{"status": "unavailable"}, {"run_id": None}, {"report_id": None}, {"snapshot_id": None}, {"trade_date": None}, {"summary": "  "}])
def test_rejected_or_unbound_research_never_becomes_direction(extra):
    value = build(quotes=quote(), research=report(**extra))
    assert value["research"]["status"] == "unavailable"
    assert value["research"]["bias"] is None and value["research"]["narrative"] == ""
    assert value["research"]["trade_plan"] is None
    assert value["comparison"]["status"] == "unavailable"


@pytest.mark.parametrize("as_of", ["2026-10-07T04:00:00Z", "2026-10-07T12:00:00", "2026-10-07T14:00:00Z", None])
def test_same_date_does_not_make_research_current(as_of):
    assert build(research=report(as_of=as_of))["research"]["status"] == "historical"


def test_explicit_historical_reading_does_not_turn_blocked_latest_run_into_success():
    source = {"status": "unavailable", "reason": "input_validation_blocked", "run_id": "new-blocked-run",
              "historical_research": report(historical_only=True)}
    before = deepcopy(source)
    value = build(quotes=quote(), research=source)
    assert value["research"]["status"] == "historical"
    assert value["research"]["run_id"] == "engineering-run"
    assert value["research"]["latest_status"] == "unavailable"
    assert value["research"]["latest_run_id"] == "new-blocked-run"
    assert value["research"]["latest_reason"] == "input_validation_blocked"
    assert value["comparison"]["status"] == "unavailable"
    assert value["research"]["publish_allowed"] is False
    assert source == before


def test_only_explicit_spot_levels_are_projected():
    levels = [{"price": 4100, "coordinate": "spot", "instrument": "XAUUSD", "role": "resistance"},
              {"price": 4200, "coordinate": "gc_futures", "instrument": "GC"},
              {"price": 4185, "instrument": "XAUUSD"},
              {"price": 4110, "coordinate": "spot", "instrument": "GC"},
              {"price": float("nan"), "coordinate": "spot", "instrument": "XAUUSD"}]
    assert [row["price"] for row in build(research=report(key_levels=levels))["research"]["key_levels"]] == [4100]


def test_service_failures_remain_partial_without_writes(monkeypatch):
    def unavailable():
        raise RuntimeError("engineering failure")
    monkeypatch.setattr(service, "get_market_macro_latest", unavailable)
    monkeypatch.setattr(service, "get_market_tickers", lambda: quote())
    monkeypatch.setattr(service, "get_dashboard_research_context", lambda: None)
    value = service.get_gold_workspace()
    assert value["price"]["value"] == 4076.1
    assert value["research"]["status"] == "unavailable"


def test_existing_router_exposes_read_only_gold_endpoint(monkeypatch):
    from apps.api.routes.market_monitor_routes import router
    monkeypatch.setattr(service, "get_gold_workspace", lambda: build(quotes=quote(), research=report()))
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get("/api/gold/workspace")
        assert response.status_code == 200 and response.json()["schema_version"] == "gold_workspace.v1"
        assert client.post("/api/gold/workspace").status_code == 405


def test_now_requires_a_timezone():
    with pytest.raises(ValueError, match="timezone"):
        service.build_gold_workspace(macro=None, quotes=None, research=None, now=datetime(2026, 10, 7))
