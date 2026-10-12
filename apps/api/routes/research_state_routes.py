"""Read-only S1–SX research ledger; approval remains an explicit local action."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database.models.engine import get_db
from database.queries.market_state import load_accepted_state, state_history

from apps.api.services.research_source_health_service import build_research_source_health_view

router = APIRouter()


@router.get("/api/gold/research-state")
def research_state(limit: int = Query(30, ge=1, le=100), db: Session = Depends(get_db)):
    try:
        return {"schema_version": "market_state_view.v1", "product": "Gold Research Agent v0.9 — Production Shadow", "accepted": load_accepted_state(db), "history": state_history(db, limit=limit), "formal_gold_authority": False, "automatic_trading_allowed": False}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/gold/source-health")
def research_source_health(db: Session = Depends(get_db)):
    from database.queries.data_source_status import list_data_source_statuses

    records = list_data_source_statuses(db, source_group="gold_core")
    return build_research_source_health_view(records)


@router.get("/api/gold/shadow-readiness")
def research_shadow_readiness(db: Session = Depends(get_db)):
    import os
    from database.queries.research_shadow import shadow_readiness

    return shadow_readiness(db,storage_root=os.environ.get("STORAGE_ROOT","./storage"))
