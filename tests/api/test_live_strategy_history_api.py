from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ["FINANCE_AGENT_DISABLE_BACKGROUND_JOBS"] = "1"

from apps.api import main as api_main
from apps.api.services import live_strategy_service
from apps.api.services.live_strategy_service import (
    LiveStrategyHistoryQueryError,
    LiveStrategyHistoryStorageError,
    get_live_strategy_history,
)


def test_live_strategy_history_route_is_registered() -> None:
    assert "/api/live-strategy/history" in {route.path for route in api_main.app.routes}


def test_live_strategy_history_empty_storage_returns_read_only_payload(tmp_path) -> None:
    payload = get_live_strategy_history(storage_root=tmp_path, limit=10)

    assert payload == {
        "schema_version": "live_strategy.history_api.v1",
        "asset": "XAUUSD",
        "limit": 10,
        "items": [],
        "truncated": False,
    }
    assert not (tmp_path / "strategy_history").exists()


@pytest.mark.parametrize(
    ("records", "expected_truncated"),
    [
        (
            [
                {"strategy_version": "v2", "updated_at": "2026-07-18T00:00:00Z"},
                {"strategy_version": "v1", "updated_at": "2026-07-17T00:00:00Z"},
            ],
            False,
        ),
        (
            [
                {"strategy_version": "v3", "updated_at": "2026-07-19T00:00:00Z"},
                {"strategy_version": "v2", "updated_at": "2026-07-18T00:00:00Z"},
                {"strategy_version": "v1", "updated_at": "2026-07-17T00:00:00Z"},
            ],
            True,
        ),
    ],
)
def test_live_strategy_history_probes_limit_and_preserves_latest_order(
    monkeypatch, tmp_path, records, expected_truncated
) -> None:
    calls: list[tuple[str, int]] = []

    class FakeStore:
        def __init__(self, root):
            assert root == tmp_path

        def list_latest(self, *, asset: str, limit: int):
            calls.append((asset, limit))
            assert limit == 3
            return records

    monkeypatch.setattr(live_strategy_service, "StrategyHistoryStore", FakeStore)

    payload = get_live_strategy_history(asset="xauusd", limit=2, storage_root=tmp_path)

    assert calls == [("XAUUSD", 3)]
    assert payload["items"] == records[:2]
    assert payload["truncated"] is expected_truncated


@pytest.mark.parametrize("params", [{"asset": "GC"}, {"limit": 0}, {"limit": 101}])
def test_live_strategy_history_route_rejects_invalid_query(params) -> None:
    response = TestClient(api_main.app).get("/api/live-strategy/history", params=params)

    assert response.status_code == 422


@pytest.mark.parametrize(
    "error",
    [
        LiveStrategyHistoryStorageError("storage root /secret/path is invalid"),
        LiveStrategyHistoryStorageError("invalid artifact /secret/path/strategy.json"),
    ],
)
def test_live_strategy_history_route_maps_storage_errors_without_path_leak(monkeypatch, error) -> None:
    monkeypatch.setattr(
        "apps.api.routes.live_strategy_routes.get_live_strategy_history",
        lambda **_: (_ for _ in ()).throw(error),
    )

    response = TestClient(api_main.app).get("/api/live-strategy/history")

    assert response.status_code == 500
    assert response.json() == {"detail": "Live strategy history artifacts are invalid"}
    assert "/secret/path" not in response.text


def test_live_strategy_history_service_maps_store_errors(monkeypatch, tmp_path) -> None:
    class BrokenStore:
        def __init__(self, root):
            pass

        def list_latest(self, **kwargs):
            raise ValueError("path /secret/path is invalid")

    monkeypatch.setattr(live_strategy_service, "StrategyHistoryStore", BrokenStore)

    with pytest.raises(LiveStrategyHistoryStorageError, match="artifacts are invalid"):
        get_live_strategy_history(storage_root=tmp_path)


@pytest.mark.parametrize("asset, limit", [("GC", 20), ("XAUUSD", 0), ("XAUUSD", 101)])
def test_live_strategy_history_service_rejects_invalid_query(asset, limit, tmp_path) -> None:
    with pytest.raises(LiveStrategyHistoryQueryError):
        get_live_strategy_history(asset=asset, limit=limit, storage_root=tmp_path)


def test_live_strategy_history_hides_legacy_stale_artifacts(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        live_strategy_service,
        "StrategyHistoryStore",
        lambda _root: type(
            "Store",
            (),
            {
                "list_latest": lambda self, **_: [
                    {
                        "strategy_version": "stale",
                        "payload": {
                            "schema_version": "live_strategy.v1",
                            "strategy_status": "SUSPENDED_DATA",
                        },
                    },
                    {
                        "strategy_version": "fresh",
                        "payload": {
                            "schema_version": "live_strategy.v1",
                            "strategy_status": "WATCHING",
                            "live_market": {"status": "available"},
                            "data_quality": {"canonical_candle": {"status": "available"}},
                        },
                    },
                ],
            },
        )(),
    )

    payload = get_live_strategy_history(storage_root=tmp_path, limit=2)

    assert [item["strategy_version"] for item in payload["items"]] == ["fresh"]
    assert payload["truncated"] is False
