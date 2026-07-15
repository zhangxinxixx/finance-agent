"""Read-only routes for Issue 63-A live strategy state."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from apps.analysis.strategy.live_schemas import LiveStrategyOutput
from apps.api.schemas.strategy import LiveStrategyRecomputePreviewResponse
from apps.api.services.live_strategy_recompute_service import (
    LiveStrategyRecomputePreviewQueryError,
    preview_live_strategy_recompute,
)
from apps.api.services.live_strategy_service import (
    LiveStrategyHistoryQueryError,
    LiveStrategyHistoryStorageError,
    get_live_strategy_history,
    get_live_strategy_latest,
)
from database.models.engine import get_db


router = APIRouter()


@router.get("/api/live-strategy/latest", response_model=LiveStrategyOutput)
def api_live_strategy_latest(
    asset: Literal["XAUUSD"] = Query(default="XAUUSD"),
    db: Session = Depends(get_db),
):
    """Return the deterministic, read-only XAUUSD live strategy ViewModel."""
    return get_live_strategy_latest(asset=asset, db=db)


@router.get("/api/live-strategy/history")
def api_live_strategy_history(
    asset: str = Query(default="XAUUSD"),
    limit: int = Query(default=20),
):
    """Return immutable, read-only XAUUSD strategy versions, newest first."""
    try:
        return get_live_strategy_history(asset=asset, limit=limit)
    except LiveStrategyHistoryQueryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LiveStrategyHistoryStorageError as exc:
        raise HTTPException(status_code=500, detail="Live strategy history artifacts are invalid") from exc


@router.get(
    "/api/live-strategy/recompute-preview",
    response_model=LiveStrategyRecomputePreviewResponse,
)
def api_live_strategy_recompute_preview(
    event_id: str = Query(...),
    db: Session = Depends(get_db),
):
    """Preview an event-gated strategy recompute without persisting it."""
    try:
        return preview_live_strategy_recompute(event_id=event_id, db=db)
    except LiveStrategyRecomputePreviewQueryError as exc:
        raise HTTPException(status_code=422, detail="invalid event_id") from exc
