"""Read-only routes for Issue #59 shadow evaluation."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from apps.api.services.evaluation_service import (
    EvaluationArtifactError,
    EvaluationQueryError,
    get_latest_shadow_evaluation_metrics,
    get_shadow_evaluation_metrics,
)
from apps.api.services.evaluation_history_service import (
    EvaluationHistoryArtifactError,
    EvaluationHistoryQueryError,
    get_shadow_evaluation_history,
)

router = APIRouter()


@router.get("/api/shadow-evaluation/history")
def api_shadow_evaluation_history(
    account_id: str = Query(default="codex-xauusd-shadow"),
    asset: str = Query(default="XAUUSD"),
    limit: int = Query(default=20, ge=1, le=100),
):
    """Return immutable local shadow-evaluation history."""
    try:
        return get_shadow_evaluation_history(
            account_id=account_id,
            asset=asset,
            limit=limit,
        )
    except EvaluationHistoryQueryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except EvaluationHistoryArtifactError as exc:
        raise HTTPException(status_code=500, detail="Shadow evaluation history artifacts are invalid") from exc


@router.get("/api/shadow-evaluation/metrics/latest")
def api_latest_shadow_evaluation_metrics(
    account_id: str = Query(default="codex-xauusd-shadow"),
    asset: str = Query(default="XAUUSD"),
):
    """Return the latest immutable local shadow-evaluation partition."""
    try:
        payload = get_latest_shadow_evaluation_metrics(
            account_id=account_id,
            asset=asset,
        )
    except EvaluationQueryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except EvaluationArtifactError as exc:
        raise HTTPException(status_code=500, detail="Shadow evaluation artifacts are invalid") from exc
    if payload is None:
        raise HTTPException(status_code=404, detail="Shadow evaluation metrics not found")
    return payload


@router.get("/api/shadow-evaluation/metrics")
def api_shadow_evaluation_metrics(
    account_id: str = Query(default="codex-xauusd-shadow"),
    asset: str = Query(default="XAUUSD"),
    trade_date: str = Query(...),
):
    """Return one immutable local shadow-evaluation partition."""
    try:
        payload = get_shadow_evaluation_metrics(
            account_id=account_id,
            asset=asset,
            trade_date=trade_date,
        )
    except EvaluationQueryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except EvaluationArtifactError as exc:
        raise HTTPException(status_code=500, detail="Shadow evaluation artifacts are invalid") from exc
    if payload is None:
        raise HTTPException(status_code=404, detail="Shadow evaluation metrics not found")
    return payload


__all__ = [
    "api_latest_shadow_evaluation_metrics",
    "api_shadow_evaluation_history",
    "api_shadow_evaluation_metrics",
    "router",
]
