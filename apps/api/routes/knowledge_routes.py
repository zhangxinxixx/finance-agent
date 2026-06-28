"""Knowledge routes extracted from the main FastAPI entrypoint."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/api/knowledge/items")
def api_knowledge_items():
    """返回知识库只读列表。"""
    from apps.api.services.knowledge_service import build_knowledge_items

    return build_knowledge_items()


@router.get("/api/knowledge/items/{item_id}")
def api_knowledge_item(item_id: str):
    """返回单条知识详情。"""
    from apps.api.services.knowledge_service import build_knowledge_item

    data = build_knowledge_item(item_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Knowledge item not found")
    return data
