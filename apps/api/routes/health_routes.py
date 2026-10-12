"""Health routes extracted from the main FastAPI entrypoint."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from apps.api.services.readiness_service import get_readiness

router = APIRouter()


@router.get("/health")
@router.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/ready")
@router.get("/api/ready")
def ready() -> JSONResponse:
    payload = get_readiness()
    return JSONResponse(payload, status_code=200 if payload["status"] == "ready" else 503)
