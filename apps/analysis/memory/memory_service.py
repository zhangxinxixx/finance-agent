"""Mem0 MemoryService 封装层 — 使用原生 app_id/agent_id 实体作用域。

实体作用域（Mem0 原生）：
  user_id  — 用户偏好和长期规则
  app_id   — 项目/应用级规则（顶层参数，非 metadata）
  agent_id — Agent 岗位说明书（顶层参数，非 metadata）
  run_id   — 单次任务上下文

使用方式：
  svc.add_memory(content, app_id="finance_analysis_system", ...)   → app 级
  svc.add_memory(content, agent_id="risk_agent", ...)              → agent 级
  svc.add_memory(content, user_id="xinxi", ...)                    → user 级
  svc.search_for_app(query, app_id="finance_analysis_system")       → 检索 app 级
  svc.search_for_agent(query, agent_id="risk_agent")                → 检索 agent 级
"""

from __future__ import annotations
from typing import Any


class MemoryService:
    """Mem0 记忆服务封装 — 原生实体作用域。"""

    def __init__(self, memory_client: Any = None):
        self._client = memory_client

    def configure(self, config: dict[str, Any]) -> None:
        from mem0 import Memory
        self._client = Memory.from_config(config)

    @property
    def client(self) -> Any:
        if self._client is None:
            raise RuntimeError("MemoryService 未初始化")
        return self._client

    # ── 写入 ──────────────────────────────────────────

    def add_memory(
        self,
        content: str,
        *,
        user_id: str | None = None,
        app_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
        memory_type: str | None = None,
        importance: str = "medium",
        tags: list[str] | None = None,
        source: str = "manual",
        infer: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """添加一条记忆，使用 Mem0 原生实体作用域。

        app_id / agent_id / run_id 作为顶层参数传给 Mem0 SDK，
        自动获得对应实体作用域，不依赖 metadata 模拟。

        infer=False 防止 Mem0 对规则/约束类记忆做自动改写。
        """
        base_metadata: dict[str, Any] = {
            "memory_type": memory_type,
            "importance": importance,
            "tags": tags or [],
            "source": source,
        }
        if metadata:
            base_metadata.update(metadata)

        kwargs: dict[str, Any] = {
            "messages": [{"role": "user", "content": content}],
            "metadata": base_metadata,
            "infer": infer,
        }
        if user_id:
            kwargs["user_id"] = user_id
        if app_id:
            kwargs["app_id"] = app_id
        if agent_id:
            kwargs["agent_id"] = agent_id
        if run_id:
            kwargs["run_id"] = run_id

        return self.client.add(**kwargs)

    # ── 检索 ──────────────────────────────────────────

    def search_memory(
        self, query: str, *, top_k: int = 10, filters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """通用检索，filters 直接传给 Mem0。"""
        return self.client.search(query=query, filters=filters, top_k=top_k)

    def search_for_app(
        self, query: str, app_id: str, *, top_k: int = 10
    ) -> list[dict[str, Any]]:
        """检索 app 级记忆（原生 app_id 过滤）。"""
        result = self.client.search(
            query=query, filters={"app_id": app_id}, top_k=top_k
        )
        return result.get("results", [])

    def search_for_agent(
        self, query: str, agent_id: str, *, top_k: int = 10
    ) -> list[dict[str, Any]]:
        """检索 agent 级记忆（原生 agent_id 过滤）。"""
        result = self.client.search(
            query=query, filters={"agent_id": agent_id}, top_k=top_k
        )
        return result.get("results", [])

    def search_for_user(
        self, query: str, user_id: str = "xinxi", *, top_k: int = 10
    ) -> list[dict[str, Any]]:
        """检索 user 级记忆。"""
        result = self.client.search(
            query=query, filters={"user_id": user_id}, top_k=top_k
        )
        return result.get("results", [])

    def search_context_for_task(
        self,
        task: str,
        *,
        user_id: str = "xinxi",
        app_id: str = "finance_analysis_system",
        agent_id: str | None = None,
        top_k: int = 5,
    ) -> dict[str, list[dict[str, Any]]]:
        """三段检索：user → app → agent。"""
        result: dict[str, list[dict[str, Any]]] = {
            "user": self.search_for_user(query=task, user_id=user_id, top_k=top_k),
            "app": self.search_for_app(query=task, app_id=app_id, top_k=top_k),
        }
        if agent_id:
            result["agent"] = self.search_for_agent(
                query=task, agent_id=agent_id, top_k=top_k
            )
        else:
            result["agent"] = []
        return result

    def get_all_memories(self, *, user_id: str = "xinxi", top_k: int = 50):
        return self.client.get_all(filters={"user_id": user_id}, top_k=top_k)
