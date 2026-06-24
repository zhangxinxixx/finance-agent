"""记忆路由器 — 根据任务自动选择检索范围，合并去重。

相比于 MemoryService.search_context_for_task() 的增强：
  1. agent_id 自动推断 — 从任务关键词推断该查哪个 Agent
  2. 结果去重 — 跨 user/app/agent 三段去重
  3. 检索策略控制 — 轻量任务只查 user，重量任务全查

使用方式：
    from apps.analysis.memory.memory_router import MemoryRouter

    router = MemoryRouter()
    context = router.retrieve("CME 期权分析状态", task="cme_options_agent")
    # → {"user": [...], "app": [...], "agent": [...]}

    prompt_block = router.format_for_prompt("CME 期权分析状态", ...)
"""

from __future__ import annotations

from typing import Any

from apps.analysis.memory.mem0_client import get_mem0_client
from apps.analysis.memory.memory_service import MemoryService

# ── 项目常量 ──────────────────────────────────────────
DEFAULT_USER_ID = "local_user"
DEFAULT_APP_ID = "finance_agent"

# ── Agent 关键词推断映射 ───────────────────────────────
# 从任务描述中的关键词推断应查询的 agent_id。
# 顺序敏感：越靠前优先级越高，匹配第一个命中即停止。
AGENT_KEYWORD_MAP: list[tuple[list[str], str]] = [
    (["cme", "期权", "option", "put", "call", "持仓报告", "cot", "期权墙", "greeks"], "cme_options_agent"),
    (["宏观", "利率", "流动性", "macro", "liquidity", "fed", "央行", "缩表", "加息", "fomc"], "macro_liquidity_agent"),
    (["风险", "risk", "var", "压力测试", "止损", "回撤", "敞口"], "risk_agent"),
    (["持仓", "position", "仓位", "头寸", "多空比", "敞口分布"], "positioning_agent"),
    (["新闻", "快讯", "头条", "news", "舆情", "情绪"], "news_agent"),
    (["技术", "technical", "k线", "均线", "macd", "rsi", "布林", "形态"], "technical_agent"),
    (["市场", "概率", "odds", "定价", "加息概率", "降息概率"], "market_odds_agent"),
    (["调度", "协调", "工作流", "任务", "pipeline", "主链"], "coordinator_agent"),
]


class MemoryRouter:
    """记忆路由器 — 根据任务上下文自动选择检索策略。

    在 MemoryService 基础上增加了 agent_id 自动推断和去重机制。
    """

    def __init__(self, memory_service: MemoryService | None = None):
        if memory_service is None:
            client = get_mem0_client()
            memory_service = MemoryService(memory_client=client)
        self._svc = memory_service

    # ── Agent 推断 ──────────────────────────────────

    @staticmethod
    def infer_agent_id(task: str) -> str | None:
        """从任务描述推断应查询的 Agent。

        按 AGENT_KEYWORD_MAP 顺序匹配，第一个命中即返回。
        未命中返回 None，即不查 agent 级记忆。
        """
        task_lower = task.lower()
        for keywords, agent_id in AGENT_KEYWORD_MAP:
            if any(kw.lower() in task_lower for kw in keywords):
                return agent_id
        return None

    @staticmethod
    def infer_all_agent_ids(task: str) -> list[str]:
        """从任务描述推断所有可能相关的 Agent（多匹配）。

        用于跨 Agent 协调场景。
        """
        task_lower = task.lower()
        matched = []
        for keywords, agent_id in AGENT_KEYWORD_MAP:
            if any(kw.lower() in task_lower for kw in keywords):
                matched.append(agent_id)
        return matched or []

    # ── 检索 ────────────────────────────────────────

    def retrieve(
        self,
        query: str,
        *,
        task: str = "",
        agent_id: str | None = None,
        app_id: str = DEFAULT_APP_ID,
        user_id: str = DEFAULT_USER_ID,
        top_k: int = 5,
    ) -> dict[str, list[dict[str, Any]]]:
        """三段检索：user → app → agent。

        agent_id 优先级：显式传入 > 自动推断。
        自动推断时 task 参数用于关键词匹配。
        """
        # 确定 agent_id
        if agent_id is None and task:
            agent_id = self.infer_agent_id(task)

        raw = self._svc.search_context_for_task(
            query,
            user_id=user_id,
            app_id=app_id,
            agent_id=agent_id,
            top_k=top_k,
        )

        # 三段去重
        return {
            "user": self._dedupe(raw["user"]),
            "app": self._dedupe(raw["app"]),
            "agent": self._dedupe(raw["agent"]),
        }

    def retrieve_light(
        self,
        query: str,
        *,
        user_id: str = DEFAULT_USER_ID,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """轻量检索 — 只查 user 级记忆，用于非项目相关任务。"""
        return self._dedupe(
            self._svc.search_for_user(query, user_id=user_id, top_k=top_k)
        )

    # ── 格式化 ──────────────────────────────────────

    def format_for_prompt(
        self,
        query: str,
        *,
        task: str = "",
        agent_id: str | None = None,
        max_items: int = 12,
    ) -> str:
        """检索并格式化为可直接注入 Agent Prompt 的上下文块。

        按 user → app → agent 三段输出，限制总条数。
        """
        ctx = self.retrieve(query, task=task, agent_id=agent_id)

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

        total = 0
        for entity_key, section_title in sections.items():
            memories = ctx.get(entity_key, [])
            if not memories:
                continue
            lines.append(f"### {section_title}")
            for i, m in enumerate(memories, 1):
                if total >= max_items:
                    break
                content = m.get("memory", m.get("content", ""))
                if not content:
                    continue
                meta = m.get("metadata", {})
                mtype = meta.get("memory_type", "unknown")
                importance = meta.get("importance", "medium")
                lines.append(f"**{total + 1}. [{mtype}]** (重要性: {importance})")
                lines.append(content)
                lines.append("")
                total += 1

        if total == 0:
            return "（暂无相关项目记忆）"

        return "\n".join(lines)

    # ── 工具 ────────────────────────────────────────

    @staticmethod
    def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """按 memory 内容去重（保留首次出现）。"""
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for item in items:
            key = item.get("id") or item.get("memory", "")[:120]
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out
