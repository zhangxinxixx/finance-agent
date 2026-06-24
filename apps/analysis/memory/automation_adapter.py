"""Automation Mem0 context adapter.

这是给自动化会话和开发任务用的只读上下文预取层，
参考 prefetch 思路，但不替代运行时记忆插件本体。
"""

from __future__ import annotations

from apps.analysis.memory.memory_router import MemoryRouter
from apps.analysis.memory.memory_policy import should_retrieve


def build_automation_memory_context(task: str) -> str:
    """为自动化任务构建当前任务的 Mem0 上下文块。

    行为约束：
    - 仅用于自动化上下文预取
    - 默认只读，不执行写回
    - 若任务明显不需要长期记忆，则返回跳过提示
    """
    normalized = task.strip()
    if not normalized:
        return "（Mem0 上下文预取：未提供任务描述，跳过长期记忆检索）"

    if not should_retrieve(normalized):
        return "（Mem0 上下文预取：当前任务未命中长期记忆检索条件）"

    router = MemoryRouter()
    context = router.format_for_prompt(normalized, task=normalized)
    return "\n".join(
        [
            "<!-- Mem0 上下文预取：自动化任务上下文 -->",
            context,
        ]
    )
