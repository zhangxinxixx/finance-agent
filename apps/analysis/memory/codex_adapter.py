"""Codex 的 Mem0 接入程序。

这是给 Codex 会话和开发任务用的只读上下文预取层，
参考 Hermes 的 prefetch 思路，但不替代 Hermes 插件本体。
"""

from __future__ import annotations

from apps.analysis.memory.memory_router import MemoryRouter
from apps.analysis.memory.memory_policy import should_retrieve


def build_codex_memory_context(task: str) -> str:
    """为 Codex 构建当前任务的 Mem0 上下文块。

    行为约束：
    - 仅用于 Codex 接入程序
    - 默认只读，不执行写回
    - 若任务明显不需要长期记忆，则返回跳过提示
    """
    normalized = task.strip()
    if not normalized:
        return "（Codex Mem0 接入程序：未提供任务描述，跳过长期记忆检索）"

    if not should_retrieve(normalized):
        return "（Codex Mem0 接入程序：当前任务未命中长期记忆检索条件）"

    router = MemoryRouter()
    context = router.format_for_prompt(normalized, task=normalized)
    return "\n".join(
        [
            "<!-- Codex Mem0 接入程序：会话/开发任务上下文预取 -->",
            context,
        ]
    )
