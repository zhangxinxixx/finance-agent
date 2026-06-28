from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import app

client = TestClient(app)


def test_api_knowledge_items_returns_unavailable_contract() -> None:
    response = client.get("/api/knowledge/items")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unavailable"
    assert payload["source"] == "unavailable"
    assert payload["items"] == []
    assert payload["stats"]["total"] == 0


def test_api_knowledge_item_missing_returns_404() -> None:
    response = client.get("/api/knowledge/items/missing-item")

    assert response.status_code == 404
    assert response.json()["detail"] == "Knowledge item not found"
