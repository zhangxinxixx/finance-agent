"""Mem0 上下文只读 API 测试。"""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from apps.api.main import app

client = TestClient(app)


def test_memory_context_returns_formatted_prompt_block() -> None:
    with patch(
        "apps.api.main.build_automation_memory_context",
        return_value="## 项目上下文（来自 Mem0 记忆系统）\n\n测试上下文",
    ) as mocked:
        resp = client.get("/api/memory/context", params={"task": "接入 mem0"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["task"] == "接入 mem0"
    assert data["context"].startswith("## 项目上下文")
    assert data["source"] == "automation_mem0_adapter"
    mocked.assert_called_once_with("接入 mem0")


def test_memory_context_requires_task_param() -> None:
    resp = client.get("/api/memory/context")
    assert resp.status_code == 422


def test_memory_context_handles_missing_mem0_gracefully() -> None:
    with patch(
        "apps.api.main.build_automation_memory_context",
        side_effect=RuntimeError("MEM0_API_KEY 未设置。"),
    ):
        resp = client.get("/api/memory/context", params={"task": "接入 mem0"})

    assert resp.status_code == 503
    assert "MEM0_API_KEY" in resp.json()["detail"]
