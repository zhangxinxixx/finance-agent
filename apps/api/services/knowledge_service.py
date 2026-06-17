"""
P1-09: Knowledge Base 只读索引 API。

当前阶段返回 unavailable，为前端提供标准契约结构。
未来接入 Obsidian/Mem0/数据库后在此填充真实数据。
"""

from __future__ import annotations

from typing import Any


def build_knowledge_items() -> dict[str, Any]:
    """返回知识库只读列表。"""
    return {
        "status": "unavailable",
        "source": "unavailable",
        "items": [],
        "stats": {
            "total": 0,
            "agent_ready": 0,
            "playbook_count": 0,
            "pinned_count": 0,
            "review_queue_count": 0,
        },
        "source_refs": [],
    }


def build_knowledge_item(item_id: str) -> dict[str, Any] | None:
    """返回单条知识详情。"""
    return None
