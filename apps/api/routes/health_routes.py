"""Health routes extracted from the main FastAPI entrypoint."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
@router.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
