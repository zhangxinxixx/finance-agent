"""Read-only LLM call audit routes."""

from __future__ import annotations

from datetime import date
import os
import secrets
from ipaddress import ip_address

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.orm import Session

from apps.api.schemas.llm_audit import LLMAuditDetail, LLMAuditListResponse
from apps.api.services.llm_audit_service import get_llm_audit_view, list_llm_audit_view
from database.models.engine import get_db

router = APIRouter()


def require_audit_reader(
    request: Request,
    x_finance_audit_token: str | None = Header(default=None, alias="X-Finance-Audit-Token"),
) -> None:
    expected = os.getenv("FINANCE_AGENT_AUDIT_READER_TOKEN", "").strip()
    if not expected:
        if _is_local_audit_request(request):
            return
        raise HTTPException(
            status_code=503,
            detail="LLM audit access requires FINANCE_AGENT_AUDIT_READER_TOKEN for non-local clients",
        )
    if not x_finance_audit_token or not secrets.compare_digest(x_finance_audit_token, expected):
        raise HTTPException(status_code=403, detail="LLM audit reader permission required")


def _is_local_audit_request(request: Request) -> bool:
    client_host = request.client.host if request.client is not None else ""
    forwarded_hosts = [item.strip() for item in request.headers.get("x-forwarded-for", "").split(",") if item.strip()]
    return _is_loopback_host(client_host) and all(_is_loopback_host(host) for host in forwarded_hosts)


def _is_loopback_host(host: str) -> bool:
    if host == "testclient":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


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
    _audit_reader: None = Depends(require_audit_reader),
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
def api_llm_audit_detail(
    audit_id: str,
    include_content: bool = Query(False),
    _audit_reader: None = Depends(require_audit_reader),
    db: Session = Depends(get_db),
) -> LLMAuditDetail:
    payload = get_llm_audit_view(db, audit_id, include_content=include_content)
    if payload is None:
        raise HTTPException(status_code=404, detail="LLM audit record not found")
    return payload
