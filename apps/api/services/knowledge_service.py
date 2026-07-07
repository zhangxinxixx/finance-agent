"""Knowledge Base read-only index API."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULT_KNOWLEDGE_ITEMS_PATH = Path("storage/outputs/knowledge/items.json")


def build_knowledge_items() -> dict[str, Any]:
    """返回知识库只读列表。"""
    payload = _load_knowledge_payload()
    if payload is not None:
        items = _valid_items(payload.get("items"))
        return {
            "status": payload.get("status") or "available",
            "source": payload.get("source") or "storage_read_model",
            "updated_at": payload.get("updated_at"),
            "items": items,
            "stats": _build_stats(items, payload.get("stats")),
            "source_refs": payload.get("source_refs") if isinstance(payload.get("source_refs"), list) else [],
        }

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
    payload = _load_knowledge_payload()
    if payload is None:
        return None

    for item in _valid_items(payload.get("items")):
        if item.get("id") == item_id:
            return item
    return None


def _knowledge_items_path() -> Path:
    configured = os.environ.get("FINANCE_AGENT_KNOWLEDGE_ITEMS_PATH")
    return Path(configured) if configured else DEFAULT_KNOWLEDGE_ITEMS_PATH


def _load_knowledge_payload() -> dict[str, Any] | None:
    path = _knowledge_items_path()
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(raw, list):
        return {"items": raw}
    if isinstance(raw, dict):
        return raw
    return None


def _valid_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict) and isinstance(item.get("id"), str) and item.get("id")]


def _build_stats(items: list[dict[str, Any]], raw_stats: Any) -> dict[str, int]:
    stats = {
        "total": len(items),
        "agent_ready": sum(1 for item in items if bool(item.get("agentReady"))),
        "playbook_count": sum(1 for item in items if item.get("type") == "playbook"),
        "playbook_candidate_count": sum(1 for item in items if item.get("type") != "playbook" and _as_int(item.get("confidence")) >= 80),
        "playbook_published_count": sum(1 for item in items if item.get("type") == "playbook" and bool(item.get("agentReady"))),
        "pinned_count": sum(1 for item in items if bool(item.get("pinned"))),
        "review_queue_count": sum(1 for item in items if bool(item.get("reviewQueued"))),
        "total_citations": sum(_as_int(item.get("citations")) for item in items),
    }
    if not isinstance(raw_stats, dict):
        return stats
    for key, value in raw_stats.items():
        if key in stats and isinstance(value, int):
            stats[key] = value
    return stats


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
