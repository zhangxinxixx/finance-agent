"""Automation orchestration read routes."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from apps.api.services.orchestration_service import (
    create_manual_review_action,
    get_orchestration_latest,
    get_orchestration_manual_review,
    get_orchestration_notification_plan,
)

router = APIRouter()


class ManualReviewActionRequest(BaseModel):
    date: str = Field(..., min_length=1)
    dedupe_key: str = Field(..., min_length=1)
    action: str = Field(..., pattern="^(acknowledged|resolved|dismissed)$")
    actor: str = Field(default="operator", min_length=1)
    note: str | None = None


@router.get("/api/orchestration/latest")
def api_orchestration_latest(date: str | None = None):
    """Return latest orchestration summary, workflow runs and delivery status."""
    return get_orchestration_latest(date=date)


@router.get("/api/orchestration/notification-plan")
def api_orchestration_notification_plan(date: str | None = None):
    """Return generated notification plan for a trade date."""
    return get_orchestration_notification_plan(date=date)


@router.get("/api/orchestration/manual-review")
def api_orchestration_manual_review(date: str | None = None):
    """Return manual-review items extracted from workflow_runs."""
    return get_orchestration_manual_review(date=date)


@router.post("/api/orchestration/manual-review/action")
def api_orchestration_manual_review_action(body: ManualReviewActionRequest):
    """Record an operator action for a manual-review item."""
    return create_manual_review_action(
        date=body.date,
        dedupe_key=body.dedupe_key,
        action=body.action,
        actor=body.actor,
        note=body.note,
    )
