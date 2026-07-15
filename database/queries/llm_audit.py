"""Append-only LLM call audit persistence and read queries."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database.models.analysis import LLMCallAudit


def create_llm_call_audit(session: Session, payload: dict[str, Any]) -> LLMCallAudit:
    """Insert one immutable audit row."""

    row = LLMCallAudit(**payload)
    session.add(row)
    session.flush()
    return row


def get_llm_call_audit(session: Session, audit_id: str) -> LLMCallAudit | None:
    return session.scalar(
        select(LLMCallAudit).where(
            (LLMCallAudit.id == audit_id) | (LLMCallAudit.call_id == audit_id)
        )
    )


def list_llm_call_audits(
    session: Session,
    *,
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    caller: str | None = None,
    run_id: str | None = None,
    report_id: str | None = None,
    trade_date: date | None = None,
) -> tuple[list[LLMCallAudit], int]:
    filters = []
    if status:
        filters.append(LLMCallAudit.status == status)
    if provider:
        filters.append(LLMCallAudit.provider_resolved == provider)
    if model:
        filters.append(LLMCallAudit.model_resolved == model)
    if caller:
        filters.append(LLMCallAudit.caller.ilike(f"%{caller}%"))
    if run_id:
        filters.append(LLMCallAudit.run_id == run_id)
    if report_id:
        filters.append(LLMCallAudit.report_id == report_id)
    if trade_date:
        filters.append(LLMCallAudit.trade_date == trade_date)

    total = int(session.scalar(select(func.count()).select_from(LLMCallAudit).where(*filters)) or 0)
    rows = list(
        session.scalars(
            select(LLMCallAudit)
            .where(*filters)
            .order_by(LLMCallAudit.created_at.desc(), LLMCallAudit.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return rows, total
