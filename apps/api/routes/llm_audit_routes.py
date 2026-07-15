"""Read-only LLM call audit routes."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from apps.api.schemas.llm_audit import LLMAuditDetail, LLMAuditListResponse
from apps.api.services.llm_audit_service import get_llm_audit_view, list_llm_audit_view
from database.models.engine import get_db

router = APIRouter()


@router.get("/api/llm/audits", response_model=LLMAuditListResponse)
def api_llm_audits(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    caller: str | None = None,
    run_id: str | None = None,
    report_id: str | None = None,
    trade_date: date | None = None,
    db: Session = Depends(get_db),
) -> LLMAuditListResponse:
    return list_llm_audit_view(
        db,
        limit=limit,
        offset=offset,
        status=status,
        provider=provider,
        model=model,
        caller=caller,
        run_id=run_id,
        report_id=report_id,
        trade_date=trade_date,
    )


@router.get("/api/llm/audits/{audit_id}", response_model=LLMAuditDetail)
def api_llm_audit_detail(audit_id: str, db: Session = Depends(get_db)) -> LLMAuditDetail:
    payload = get_llm_audit_view(db, audit_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="LLM audit record not found")
    return payload
