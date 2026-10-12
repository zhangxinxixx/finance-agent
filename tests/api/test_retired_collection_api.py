"""Retired manual collection cannot acknowledge or dispatch work."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.routes import operations_routes


def test_manual_collection_returns_retirement_and_formal_workflow():
    app = FastAPI()
    app.include_router(operations_routes.router)
    with TestClient(app) as client:
        response = client.post("/api/scheduler/run-all-collectors")

    assert response.status_code == 410
    detail = response.json()["detail"]
    assert detail["code"] == "manual_collection_retired"
    assert detail["preflight_url"] == "/api/tasks/premarket/preflight"
    assert detail["run_url"] == "/api/tasks/premarket"
