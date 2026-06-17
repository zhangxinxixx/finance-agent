"""项目主线记忆模块 —— 基于 Mem0 的轻量项目上下文管理。

只负责项目开发主线摘要和约束，不存完整文档/代码/报告。
完整文档 -> Obsidian / docs
代码变更 -> Git
业务数据 -> Postgres / ClickHouse
"""

from apps.analysis.memory.memory_types import ProjectMemoryRecord, ProjectMemoryType
from apps.analysis.memory.memory_service import MemoryService
from apps.analysis.memory.memory_policy import (
    MemoryPolicy,
    classify_entity,
    should_retrieve,
    should_write,
)
from apps.analysis.memory.memory_router import MemoryRouter
from apps.analysis.memory.project_mainline import ProjectMainlineMemory
from apps.analysis.memory.codex_adapter import build_codex_memory_context

__all__ = [
    "ProjectMemoryRecord",
    "ProjectMemoryType",
    "MemoryService",
    "MemoryPolicy",
    "MemoryRouter",
    "ProjectMainlineMemory",
    "build_codex_memory_context",
    "classify_entity",
    "should_retrieve",
    "should_write",
]
