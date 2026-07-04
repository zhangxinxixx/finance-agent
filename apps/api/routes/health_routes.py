"""Health and memory-context routes extracted from the main FastAPI entrypoint."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/health")
@router.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/api/memory/context")
def api_memory_context(task: str):
    """按任务描述预取长期记忆上下文。"""
    from apps.api import main as api_main

    try:
        context = api_main.build_codex_memory_context(task)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return api_main.MemoryContextResponse(
        task=task,
        context=context,
        source="memory_context_adapter",
    )
