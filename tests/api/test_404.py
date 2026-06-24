"""404 tests for task endpoints。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import app

client = TestClient(app)


def test_get_task_not_found():
    resp = client.get("/tasks/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


def test_get_task_invalid_id():
    resp = client.get("/tasks/not-a-uuid")
    assert resp.status_code == 400


def test_api_get_task_invalid_id_alias():
    resp = client.get("/api/tasks/not-a-uuid")
    assert resp.status_code == 400


def test_data_sources_detail_route_serves_frontend_entry():
    resp = client.get("/data-sources/jin10_feishu", follow_redirects=False)
    assert resp.status_code in {200, 307}


def test_favicon_serves_frontend_asset():
    resp = client.get("/favicon.svg")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/svg+xml")
