from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ["FINANCE_AGENT_DISABLE_BACKGROUND_JOBS"] = "1"

from apps.api import main as api_main
from apps.api.services.evaluation_history_service import (
    EvaluationHistoryArtifactError,
    EvaluationHistoryQueryError,
)


def _payload(*, items: list[dict[str, object]] | None = None) -> dict[str, object]:
    history_items = items or []
    return {
        "schema_version": "shadow_evaluation_history.v1",
        "account_id": "codex-xauusd-shadow",
        "asset": "XAUUSD",
        "items": history_items,
        "total": len(history_items),
        "truncated": False,
    }


def test_shadow_evaluation_history_route_is_registered_and_maps_query(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    expected = _payload(items=[{"trade_date": "2026-07-17", "evaluation_id": "eval-api"}])

    def read_history(**kwargs):
        calls.append(kwargs)
        return expected

    monkeypatch.setattr("apps.api.routes.evaluation_routes.get_shadow_evaluation_history", read_history)

    response = TestClient(api_main.app).get(
        "/api/shadow-evaluation/history",
        params={"account_id": "codex-xauusd-shadow", "asset": "xauusd", "limit": 7},
    )

    assert response.status_code == 200
    assert response.json() == expected
    assert calls == [{"account_id": "codex-xauusd-shadow", "asset": "xauusd", "limit": 7}]


def test_shadow_evaluation_history_route_preserves_empty_payload(monkeypatch) -> None:
    expected = _payload()
    monkeypatch.setattr(
        "apps.api.routes.evaluation_routes.get_shadow_evaluation_history",
        lambda **_: expected,
    )

    response = TestClient(api_main.app).get("/api/shadow-evaluation/history")

    assert response.status_code == 200
    assert response.json() == expected


@pytest.mark.parametrize(
    "params",
    [
        {"account_id": "../escape"},
        {"asset": "DXY"},
        {"limit": 0},
        {"limit": 101},
        {"limit": "not-an-integer"},
    ],
)
def test_shadow_evaluation_history_route_rejects_invalid_query(monkeypatch, params) -> None:
    original = api_main.evaluation_routes.get_shadow_evaluation_history

    def reject_or_delegate(**kwargs):
        if params.get("limit") in {0, 101, "not-an-integer"}:
            return original(**kwargs)
        raise EvaluationHistoryQueryError("invalid shadow evaluation history query")

    monkeypatch.setattr(
        "apps.api.routes.evaluation_routes.get_shadow_evaluation_history",
        reject_or_delegate,
    )

    response = TestClient(api_main.app).get("/api/shadow-evaluation/history", params=params)

    assert response.status_code == 422


def test_shadow_evaluation_history_route_maps_artifact_error_without_path_leak(monkeypatch) -> None:
    def fail(**_):
        raise EvaluationHistoryArtifactError("invalid artifact /secret/path/strategy_snapshot.json")

    monkeypatch.setattr("apps.api.routes.evaluation_routes.get_shadow_evaluation_history", fail)

    response = TestClient(api_main.app).get("/api/shadow-evaluation/history")

    assert response.status_code == 500
    assert response.json() == {"detail": "Shadow evaluation history artifacts are invalid"}
    assert "/secret/path" not in response.text
