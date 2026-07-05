"""Gold mainline read-model routes."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi import HTTPException

router = APIRouter()


@router.get("/api/gold/mainlines/latest")
def api_gold_mainlines_latest():
    """Return the latest gold macro mainline read model."""
    from apps.api import main as api_main

    return api_main.get_gold_mainlines_latest()


@router.get("/api/gold/mainlines")
def api_gold_mainlines(date: str, run_id: str):
    """Return a gold macro mainline read model by date and run_id."""
    from apps.api import main as api_main

    return api_main.get_gold_mainlines(date=date, run_id=run_id)


@router.get("/api/gold/runtime-orchestration/contract")
def api_gold_runtime_orchestration_contract():
    """Return the read-only Gold v3 runtime orchestration contract."""
    from apps.gold_runtime_orchestration import build_gold_runtime_orchestration_contract

    return build_gold_runtime_orchestration_contract()


@router.get("/api/gold/runtime-orchestration/summary-preview")
def api_gold_runtime_summary_preview(run_mode: str, trigger_reason: str | None = None):
    """Return a read-only run summary preview for one Gold v3 run mode."""
    from apps.gold_runtime_orchestration import build_gold_runtime_summary_preview

    try:
        return build_gold_runtime_summary_preview(run_mode=run_mode, trigger_reason=trigger_reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
