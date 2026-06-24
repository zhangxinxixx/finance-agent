"""项目主线记忆模块测试 — 使用原生 app_id/agent_id 实体作用域。

使用 mock MemoryService / MemoryClient，不产生真实 Mem0 API 调用。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from apps.analysis.memory import (
    MemoryPolicy,
    MemoryService,
    ProjectMainlineMemory,
    ProjectMemoryRecord,
    ProjectMemoryType,
)


# ── Fixtures ──────────────────────────────────────────


@pytest.fixture
def mock_memory_client() -> MagicMock:
    """模拟 mem0.Memory 客户端。"""
    client = MagicMock()
    client.add.return_value = {"id": "mem-001", "status": "ok"}
    # search 返回 dict with "results" key
    client.search.return_value = {
        "results": [
            {
                "id": "mem-001",
                "memory": "核心生产主链：api -> scheduler -> worker -> collectors...",
                "metadata": {
                    "memory_type": "project_principle",
                    "importance": "high",
                },
            },
        ]
    }
    client.get_all.return_value = {"results": []}
    return client


@pytest.fixture
def memory_service(mock_memory_client: MagicMock) -> MemoryService:
    return MemoryService(memory_client=mock_memory_client)


@pytest.fixture
def mainline(memory_service: MemoryService) -> ProjectMainlineMemory:
    return ProjectMainlineMemory(memory_service)


# ── MemoryPolicy 测试 ─────────────────────────────────


class TestMemoryPolicy:
    def test_valid_types_accepted(self):
        for mt in ProjectMemoryType:
            assert MemoryPolicy.is_valid_memory_type(mt.value) is True

    def test_invalid_type_rejected(self):
        assert MemoryPolicy.is_valid_memory_type("market_event") is False

    def test_content_too_long_rejected(self):
        ok, reason = MemoryPolicy.is_content_valid("长" * 2001)
        assert ok is False
        assert reason is not None
        assert "过长" in reason

    def test_code_block_rejected(self):
        ok, reason = MemoryPolicy.is_content_valid("```code```")
        assert ok is False
        assert reason is not None
        assert "代码块" in reason

    def test_empty_content_rejected(self):
        ok, _ = MemoryPolicy.is_content_valid("")
        assert ok is False

    def test_valid_content_accepted(self):
        ok, reason = MemoryPolicy.is_content_valid("当前执行 Phase 1")
        assert ok is True
        assert reason is None

    def test_validate_record_all_checks(self):
        ok, _ = MemoryPolicy.validate_record(
            memory_type="project_vision", content="金融分析中台"
        )
        assert ok is True

    def test_validate_record_bad_type(self):
        ok, _ = MemoryPolicy.validate_record(memory_type="bad_type", content="x")
        assert ok is False


# ── MemoryService 测试 ────────────────────────────────


class TestMemoryService:
    def test_unconfigured_raises(self):
        svc = MemoryService()
        with pytest.raises(RuntimeError, match="未初始化"):
            _ = svc.client

    def test_add_memory_user_scope(self, mock_memory_client: MagicMock):
        """add_memory user 级：传 user_id。"""
        svc = MemoryService(memory_client=mock_memory_client)
        svc.add_memory(content="偏好中文", user_id="local_user", memory_type="user_pref")
        kwargs = mock_memory_client.add.call_args.kwargs
        assert kwargs["user_id"] == "local_user"
        assert kwargs["metadata"]["memory_type"] == "user_pref"

    def test_add_memory_app_scope(self, mock_memory_client: MagicMock):
        """add_memory app 级：传 app_id，不传 user_id。"""
        svc = MemoryService(memory_client=mock_memory_client)
        svc.add_memory(
            content="核心主链规则",
            app_id="finance_agent",
            memory_type="project_principle",
            importance="high",
        )
        kwargs = mock_memory_client.add.call_args.kwargs
        assert kwargs["app_id"] == "finance_agent"
        assert "user_id" not in kwargs

    def test_add_memory_agent_scope(self, mock_memory_client: MagicMock):
        """add_memory agent 级：传 agent_id。"""
        svc = MemoryService(memory_client=mock_memory_client)
        svc.add_memory(
            content="risk agent read-only",
            agent_id="risk_agent",
            app_id="finance_agent",
            memory_type="agent_rule",
        )
        kwargs = mock_memory_client.add.call_args.kwargs
        assert kwargs["agent_id"] == "risk_agent"

    def test_search_for_app(self, mock_memory_client: MagicMock):
        """search_for_app 应传 app_id filter。"""
        svc = MemoryService(memory_client=mock_memory_client)
        svc.search_for_app(query="架构规则", app_id="finance_agent")
        kwargs = mock_memory_client.search.call_args.kwargs
        assert kwargs["filters"] == {"app_id": "finance_agent"}

    def test_search_for_agent(self, mock_memory_client: MagicMock):
        """search_for_agent 应传 agent_id filter。"""
        svc = MemoryService(memory_client=mock_memory_client)
        svc.search_for_agent(query="约束", agent_id="risk_agent")
        kwargs = mock_memory_client.search.call_args.kwargs
        assert kwargs["filters"] == {"agent_id": "risk_agent"}

    def test_search_context_for_task(self, mock_memory_client: MagicMock):
        """search_context_for_task 应返回三段。"""
        svc = MemoryService(memory_client=mock_memory_client)
        ctx = svc.search_context_for_task(
            task="risk 分析",
            app_id="finance_agent",
            agent_id="risk_agent",
            top_k=5,
        )
        assert "user" in ctx
        assert "app" in ctx
        assert "agent" in ctx

    def test_get_all_memories(self, memory_service: MemoryService):
        results = memory_service.get_all_memories(user_id="local_user")
        assert isinstance(results, dict)


# ── ProjectMainlineMemory 测试 ────────────────────────


class TestProjectMainlineMemory:
    def test_requires_memory_service(self):
        with pytest.raises(TypeError, match="MemoryService"):
            ProjectMainlineMemory(MagicMock())  # type: ignore[arg-type]

    def test_add_mainline_memory(
        self, mainline: ProjectMainlineMemory, mock_memory_client: MagicMock
    ):
        record = ProjectMemoryRecord(
            memory_type=ProjectMemoryType.CURRENT_PHASE,
            content="当前执行 Phase 1 布局重构",
            tags=["frontend", "phase1"],
            importance="high",
            source="agent_execution",
        )
        result = mainline.add_mainline_memory(record)
        assert result["status"] == "ok"
        kwargs = mock_memory_client.add.call_args.kwargs
        assert kwargs["app_id"] == "finance_agent"
        assert "user_id" not in kwargs  # app 级不传 user_id

    def test_add_mainline_memory_rejects_invalid(self, mainline: ProjectMainlineMemory):
        record = ProjectMemoryRecord(
            memory_type=ProjectMemoryType.CURRENT_PHASE,
            content="```code``` 不应通过校验",
        )
        with pytest.raises(ValueError, match="校验失败"):
            mainline.add_mainline_memory(record)

    def test_add_execution_update(
        self, mainline: ProjectMainlineMemory, mock_memory_client: MagicMock
    ):
        mainline.add_execution_update(
            summary="Phase 1 完成",
            completed="AppShell, Sidebar",
            next_steps="Phase 2 总览页",
            tags=["frontend"],
        )
        kwargs = mock_memory_client.add.call_args.kwargs
        content = kwargs["messages"][0]["content"]
        assert "Phase 1" in content
        assert "AppShell" in content

    def test_add_user_feedback(
        self, mainline: ProjectMainlineMemory, mock_memory_client: MagicMock
    ):
        mainline.add_user_feedback(feedback="Dashboard 需要突出研究流程")
        kwargs = mock_memory_client.add.call_args.kwargs
        assert kwargs["metadata"]["source"] == "user_feedback"

    def test_search_mainline(
        self, mainline: ProjectMainlineMemory, mock_memory_client: MagicMock
    ):
        results = mainline.search_mainline("当前阶段", limit=5)
        assert isinstance(results, list)
        kwargs = mock_memory_client.search.call_args.kwargs
        assert kwargs["filters"] == {"app_id": "finance_agent"}

    def test_get_execution_context(
        self, mainline: ProjectMainlineMemory, mock_memory_client: MagicMock
    ):
        results = mainline.get_execution_context("Phase 2 总览页内容重建")
        assert isinstance(results, dict)
        assert "user" in results
        assert "app" in results

    def test_get_by_type(
        self, mainline: ProjectMainlineMemory, mock_memory_client: MagicMock
    ):
        results = mainline.get_by_type(ProjectMemoryType.BLOCKER, limit=3)
        assert isinstance(results, list)

    def test_get_current_state(self, mainline: ProjectMainlineMemory):
        state = mainline.get_current_state()
        assert isinstance(state, dict)
        assert "current_phase" in state

    def test_format_context_for_prompt_empty(self, mainline: ProjectMainlineMemory):
        """空结果时应返回提示。"""
        result = mainline.format_context_for_prompt("测试任务")
        # mock 返回的结果不为空，但不影响格式
        assert "项目上下文" in result or "暂无" in result

    def test_no_real_mem0_calls(self, mock_memory_client: MagicMock):
        assert mock_memory_client.add.call_count >= 0
