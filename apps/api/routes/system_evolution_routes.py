"""SystemEvolution governance read routes."""

from __future__ import annotations

from apps.api.services.system_evolution_service import (
    create_system_evolution_proposal_action,
    get_system_evolution_latest,
)
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()


class SystemEvolutionProposalActionRequest(BaseModel):
    date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    proposal_id: str = Field(..., min_length=1)
    action: str = Field(..., pattern="^(approve|reject|link_issue|link_pr|mark_implemented|mark_rolled_back)$")
    actor: str = Field(default="operator", min_length=1)
    note: str | None = None
    issue_url: str | None = None
    pr_url: str | None = None
    test_result: str | None = None
    manual_confirmation: str | None = None
    rollback_reason: str | None = None


@router.get("/api/governance/system-evolution/latest")
def api_system_evolution_latest(date: str | None = None):
    return get_system_evolution_latest(date=date)


@router.post("/api/governance/system-evolution/proposal/action")
def api_system_evolution_proposal_action(body: SystemEvolutionProposalActionRequest):
    try:
        return create_system_evolution_proposal_action(
            date=body.date,
            proposal_id=body.proposal_id,
            action=body.action,
            actor=body.actor,
            note=body.note,
            issue_url=body.issue_url,
            pr_url=body.pr_url,
            test_result=body.test_result,
            manual_confirmation=body.manual_confirmation,
            rollback_reason=body.rollback_reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
