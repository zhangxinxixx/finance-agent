"""项目主线记忆管理器。

封装项目主线记忆的读写操作，对上层提供统一接口。
所有 Mem0 调用通过 MemoryService，不直接接触 mem0 SDK。
使用实体作用域：entity="app" + app_id="finance_analysis_system"。

典型用法：
    from apps.analysis.memory import ProjectMainlineMemory, ProjectMemoryRecord, ProjectMemoryType

    mainline = ProjectMainlineMemory(memory_service)

    # 写入项目主线记忆
    record = ProjectMemoryRecord(
        memory_type=ProjectMemoryType.CURRENT_PHASE,
        content="当前执行 Phase 1 布局重构",
        tags=["frontend", "phase1"],
        importance="high",
        source="hermes_execution",
    )
    mainline.add_mainline_memory(record)

    # 检索执行上下文 (user + app + agent 三段)
    context = mainline.get_execution_context("Phase 2 总览页内容重建", agent_id="codex_dev_agent")
"""

from __future__ import annotations

from typing import Any

from apps.analysis.memory.memory_service import MemoryService
from apps.analysis.memory.memory_policy import MemoryPolicy
from apps.analysis.memory.memory_types import ProjectMemoryRecord, ProjectMemoryType

# ── 项目常量 ──────────────────────────────────────────
DEFAULT_USER_ID = "xinxi"
DEFAULT_APP_ID = "finance_analysis_system"


class ProjectMainlineMemory:
    """项目主线记忆管理器。

    只管理项目开发主线记忆（阶段/目标/约束/决策/反馈），
    不管理金融分析业务记忆。
    """

    def __init__(self, memory_service: MemoryService):
        if not isinstance(memory_service, MemoryService):
            raise TypeError(
                f"memory_service 必须是 MemoryService 实例，"
                f"收到 {type(memory_service).__name__}"
            )
        self._memory = memory_service
        self._policy = MemoryPolicy()

    # ── 写入 ──────────────────────────────────────────

    def add_mainline_memory(
        self,
        record: ProjectMemoryRecord,
        *,
        app_id: str = DEFAULT_APP_ID,
    ) -> dict[str, Any]:
        """添加一条项目主线记忆（写入 app 级作用域）。

        写入前会做策略校验（类型白名单、内容长度、禁止模式）。
        """
        ok, reason = self._policy.validate_record(
            memory_type=record.memory_type.value,
            content=record.content,
        )
        if not ok:
            raise ValueError(f"记忆校验失败: {reason}")

        return self._memory.add_memory(
            content=record.content,
            app_id=app_id,
            memory_type=record.memory_type.value,
            importance=record.importance,
            tags=record.tags,
            source=record.source,
            metadata=record.metadata or None,
        )

    def add_execution_update(
        self,
        summary: str,
        *,
        tags: list[str] | None = None,
        completed: str | None = None,
        not_completed: str | None = None,
        risks: str | None = None,
        next_steps: str | None = None,
    ) -> dict[str, Any]:
        """添加执行后的主线更新记忆。"""
        content_parts = [f"执行更新: {summary}"]
        if completed:
            content_parts.append(f"已完成: {completed}")
        if not_completed:
            content_parts.append(f"未完成: {not_completed}")
        if risks:
            content_parts.append(f"风险点: {risks}")
        if next_steps:
            content_parts.append(f"下一步: {next_steps}")

        record = ProjectMemoryRecord(
            memory_type=ProjectMemoryType.CURRENT_PHASE,
            content="\n".join(content_parts),
            tags=tags or [],
            importance="high",
            source="hermes_execution_summary",
        )
        return self.add_mainline_memory(record)

    def add_user_feedback(
        self, feedback: str, *, tags: list[str] | None = None
    ) -> dict[str, Any]:
        """添加用户反馈记忆。"""
        record = ProjectMemoryRecord(
            memory_type=ProjectMemoryType.USER_FEEDBACK,
            content=feedback,
            tags=tags or [],
            importance="high",
            source="user_feedback",
        )
        return self.add_mainline_memory(record)

    # ── 检索 ──────────────────────────────────────────

    def search_mainline(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        """按查询检索项目主线记忆（app 级作用域）。"""
        return self._memory.search_for_app(
            query=query, app_id=DEFAULT_APP_ID, top_k=limit
        )

    def get_execution_context(
        self,
        task: str,
        *,
        limit: int = 12,
        agent_id: str | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """获取执行前完整上下文（user + app + agent 三段）。

        Args:
            task: 当前任务描述。
            limit: 每段返回记忆数量上限。
            agent_id: 当前执行的 Agent ID（可选，如 "codex_dev_agent"）。

        Returns:
            {"user": [...], "app": [...], "agent": [...]}
        """
        return self._memory.search_context_for_task(
            task=task,
            user_id=DEFAULT_USER_ID,
            app_id=DEFAULT_APP_ID,
            agent_id=agent_id,
            top_k=limit // 3 or 4,
        )

    def get_by_type(
        self, memory_type: ProjectMemoryType, *, limit: int = 5
    ) -> list[dict[str, Any]]:
        """按类型获取记忆（app 级作用域）。"""
        return self._memory.search_for_app(
            query=f"项目记忆类型 {memory_type.value}",
            app_id=DEFAULT_APP_ID,
            top_k=limit,
        )

    def get_current_state(self) -> dict[str, list[dict[str, Any]]]:
        """获取当前项目主线状态快照。"""
        types = [
            ProjectMemoryType.CURRENT_PHASE,
            ProjectMemoryType.CURRENT_PRIORITY,
            ProjectMemoryType.BLOCKER,
            ProjectMemoryType.NEXT_ACTION,
            ProjectMemoryType.USER_FEEDBACK,
        ]
        result: dict[str, list[dict[str, Any]]] = {}
        for mt in types:
            result[mt.value] = self.get_by_type(mt, limit=3)
        return result

    def format_context_for_prompt(
        self, task: str, *, agent_id: str | None = None
    ) -> str:
        """格式化为可直接注入 Agent Prompt 的上下文块。

        按 user → app → agent 三段输出。
        """
        ctx = self.get_execution_context(task, agent_id=agent_id)

        sections = {
            "user": "用户偏好与长期规则",
            "app": "项目规则与架构约束",
            "agent": "Agent 岗位说明书",
        }

        lines = [
            "## 项目上下文（来自 Mem0 记忆系统）",
            "",
            "以下是从项目记忆系统检索到的相关上下文，请严格遵守：",
            "",
        ]

        for entity_key, section_title in sections.items():
            memories = ctx.get(entity_key, [])
            if not memories:
                continue
            lines.append(f"### {section_title}")
            for i, m in enumerate(memories, 1):
                content = m.get("memory", m.get("content", ""))
                meta = m.get("metadata", {})
                mtype = meta.get("memory_type", "unknown")
                importance = meta.get("importance", "medium")
                lines.append(f"**{i}. [{mtype}]** (重要性: {importance})")
                lines.append(content)
                lines.append("")
            lines.append("")

        if not any(ctx.values()):
            return "（暂无项目主线记忆）"

        return "\n".join(lines)
