"""Premarket pipeline skeleton tests。需要 PostgreSQL 连接。"""

from __future__ import annotations

import os
import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.premarket import PREMARKET_STEP_ORDER

# 如果没有 DATABASE_URL 则跳过（CI / 无 DB 环境）
requires_db = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL not set; requires PostgreSQL",
)

client = TestClient(app)


@requires_db
def test_premarket_returns_task_id():
    resp = client.post("/tasks/premarket")
    assert resp.status_code == 200
    body = resp.json()
    assert "task_id" in body
    assert body["name"] == "premarket"
    assert body["status"] == "pending"


@requires_db
def test_get_task_after_create():
    resp = client.post("/tasks/premarket")
    task_id = resp.json()["task_id"]

    resp2 = client.get(f"/tasks/{task_id}")
    assert resp2.status_code == 200
    body = resp2.json()
    assert body["id"] == task_id
    assert body["status"] == "pending"
    assert len(body["steps"]) == len(PREMARKET_STEP_ORDER)
    assert [step["name"] for step in body["steps"]] == list(PREMARKET_STEP_ORDER)


@requires_db
def test_get_task_logs():
    resp = client.post("/tasks/premarket")
    task_id = resp.json()["task_id"]

    resp2 = client.get(f"/tasks/{task_id}/logs")
    assert resp2.status_code == 200
    steps = resp2.json()
    assert len(steps) == len(PREMARKET_STEP_ORDER)
    assert [s["name"] for s in steps] == list(PREMARKET_STEP_ORDER)
