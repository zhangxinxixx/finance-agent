from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

os.environ["FINANCE_AGENT_DISABLE_BACKGROUND_JOBS"] = "1"

from apps.api import main as api_main
from apps.api.schemas.strategy import LiveStrategyRecomputePreviewResponse
from apps.api.services.live_strategy_recompute_service import (
    LiveStrategyRecomputePreviewQueryError,
)
from database.models.engine import get_db


def _preview_payload(*, status: str = "unavailable") -> dict:
    return {
        "schema_version": "live_strategy.recompute_preview.v1",
        "status": status,
        "event_id": "fed:release:1",
        "reasons": ["event_not_found"],
        "event_observation": None,
        "previous_strategy": None,
        "candidate_strategy": None,
        "execution": None,
    }


def test_recompute_preview_response_schema_freezes_version_and_status() -> None:
    payload = _preview_payload()

    assert LiveStrategyRecomputePreviewResponse.model_validate(payload).model_dump() == payload
    for field in (
        "schema_version",
        "status",
        "event_id",
        "reasons",
        "event_observation",
        "previous_strategy",
        "candidate_strategy",
        "execution",
    ):
        assert field in LiveStrategyRecomputePreviewResponse.model_fields

    with pytest.raises(ValidationError):
        LiveStrategyRecomputePreviewResponse.model_validate(
            {**payload, "schema_version": "live_strategy.recompute_preview.v2"}
        )
    with pytest.raises(ValidationError):
        LiveStrategyRecomputePreviewResponse.model_validate({**payload, "status": "failed"})


def test_recompute_preview_route_returns_typed_read_only_payload(monkeypatch) -> None:
    db = object()
    calls: list[dict] = []

    def fake_preview(**kwargs):
        calls.append(kwargs)
        return _preview_payload()

    monkeypatch.setattr(
        "apps.api.routes.live_strategy_routes.preview_live_strategy_recompute",
        fake_preview,
    )
    api_main.app.dependency_overrides[get_db] = lambda: db
    try:
        response = TestClient(api_main.app).get(
            "/api/live-strategy/recompute-preview",
            params={"event_id": "fed:release:1"},
        )
    finally:
        api_main.app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert response.json() == _preview_payload()
    assert calls == [{"event_id": "fed:release:1", "db": db}]


@pytest.mark.parametrize("status", ["unavailable", "blocked"])
def test_recompute_preview_missing_or_blocked_is_a_typed_200(monkeypatch, status) -> None:
    payload = _preview_payload(status=status)
    monkeypatch.setattr(
        "apps.api.routes.live_strategy_routes.preview_live_strategy_recompute",
        lambda **_: payload,
    )

    response = TestClient(api_main.app).get(
        "/api/live-strategy/recompute-preview",
        params={"event_id": "fed:release:1"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == status
    assert set(response.json()) == {
        "schema_version",
        "status",
        "event_id",
        "reasons",
        "event_observation",
        "previous_strategy",
        "candidate_strategy",
        "execution",
    }


@pytest.mark.parametrize("event_id", ["", "../secret", "event/secret", "a" * 129, "事件:1"])
def test_recompute_preview_invalid_event_id_has_fixed_422_semantics(event_id) -> None:
    response = TestClient(api_main.app).get(
        "/api/live-strategy/recompute-preview",
        params={"event_id": event_id},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "invalid event_id"}
    assert "secret" not in response.text


def test_recompute_preview_query_error_does_not_leak_internal_detail(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.api.routes.live_strategy_routes.preview_live_strategy_recompute",
        lambda **_: (_ for _ in ()).throw(
            LiveStrategyRecomputePreviewQueryError("invalid /secret/event source")
        ),
    )

    response = TestClient(api_main.app).get(
        "/api/live-strategy/recompute-preview",
        params={"event_id": "fed:release:1"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "invalid event_id"}
    assert "/secret" not in response.text
