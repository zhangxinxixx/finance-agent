from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ["FINANCE_AGENT_DISABLE_BACKGROUND_JOBS"] = "1"

from apps.api import main as api_main
from apps.api.services.live_strategy_service import get_live_strategy_latest
from database.models.engine import get_db


def test_live_strategy_route_returns_frozen_schema(monkeypatch) -> None:
    payload = {
        "schema_version": "live_strategy.v1",
        "status": "partial",
        "strategy_id": "live-strategy-test",
        "baseline_strategy_id": "baseline-1",
        "strategy_version": "live_strategy.rules.v2",
        "asset": "XAUUSD",
        "strategy_status": "SUSPENDED_DATA",
        "updated_at": "2026-07-17T12:00:00+00:00",
        "update_reason": {"reason_code": "canonical_candle_stale", "message": "stale", "related_level": None},
        "baseline": {},
        "live_market": {"price": 100.0},
        "market_state": {},
        "feasibility": {"execution_ready": False},
        "active_scenario": None,
        "setups": [],
        "no_trade": {"range": None, "reasons": ["blocked_data"], "waiting_conditions": ["fresh_canonical_5m_required"]},
        "source_refs": [],
        "artifact_refs": [],
        "data_quality": {},
    }
    monkeypatch.setattr("apps.api.routes.live_strategy_routes.get_live_strategy_latest", lambda **_: payload)
    api_main.app.dependency_overrides[get_db] = lambda: None
    try:
        response = TestClient(api_main.app).get("/api/live-strategy/latest", params={"asset": "XAUUSD"})
    finally:
        api_main.app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert response.json() == payload
    assert "/api/live-strategy/latest" in {route.path for route in api_main.app.routes}


def test_main_keeps_live_strategy_compatibility_alias() -> None:
    assert api_main.api_live_strategy_latest.__module__ == "apps.api.routes.live_strategy_routes"


def test_live_strategy_route_rejects_non_xauusd_assets() -> None:
    api_main.app.dependency_overrides[get_db] = lambda: None
    try:
        response = TestClient(api_main.app).get(
            "/api/live-strategy/latest",
            params={"asset": "GC"},
        )
    finally:
        api_main.app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 422


def test_live_strategy_service_rejects_non_xauusd_direct_calls() -> None:
    with pytest.raises(ValueError, match="supports only XAUUSD"):
        get_live_strategy_latest(asset="GC")


def test_live_strategy_service_reads_local_5m_and_15m_windows(monkeypatch) -> None:
    calls: list[tuple[str, int]] = []

    def fake_candles(*, timeframe: str, limit: int, **_: object) -> dict:
        calls.append((timeframe, limit))
        return {"timeframe": timeframe, "candles": []}

    monkeypatch.setattr("apps.api.services.live_strategy_service.get_strategy_card_read_model_latest", lambda **_: {})
    monkeypatch.setattr("apps.api.services.live_strategy_service.get_market_candles", fake_candles)
    monkeypatch.setattr("apps.api.services.live_strategy_service.get_options_decision", lambda **_: {})
    monkeypatch.setattr("apps.api.services.live_strategy_service._load_quote_cache", lambda *_: None)
    monkeypatch.setattr("apps.api.services.live_strategy_service.build_live_strategy", lambda **kwargs: kwargs)

    payload = get_live_strategy_latest(asset="XAUUSD", db=object())

    assert calls == [("5m", 30), ("15m", 5)]
    assert payload["canonical_market"]["timeframe"] == "5m"
    assert payload["canonical_market_15m"]["timeframe"] == "15m"
    assert payload["event_observation"] is None


def test_live_strategy_service_forwards_optional_event_observation(monkeypatch) -> None:
    observation = {
        "schema_version": "live_strategy.event_observation.v1",
        "status": "available",
        "event_id": "fed:release:1",
    }
    monkeypatch.setattr("apps.api.services.live_strategy_service.get_strategy_card_read_model_latest", lambda **_: {})
    monkeypatch.setattr(
        "apps.api.services.live_strategy_service.get_market_candles",
        lambda **_: {"candles": []},
    )
    monkeypatch.setattr("apps.api.services.live_strategy_service.get_options_decision", lambda **_: {})
    monkeypatch.setattr("apps.api.services.live_strategy_service._load_quote_cache", lambda *_: None)
    monkeypatch.setattr("apps.api.services.live_strategy_service.build_live_strategy", lambda **kwargs: kwargs)

    payload = get_live_strategy_latest(event_observation=observation)

    assert payload["event_observation"] is observation
