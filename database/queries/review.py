"""ReviewItem repository helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models.analysis import ReviewItem


def _parse_datetime(value: datetime | str | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def upsert_review_item(session: Session, payload: dict[str, Any]) -> ReviewItem:
    """Create or update a review item by stable review_id."""
    review_id = str(payload["review_id"])
    item = get_review_item(session, review_id)
    if item is None:
        item = ReviewItem(
            review_id=review_id,
            source_module=str(payload["source_module"]),
            severity=str(payload.get("severity") or "warning"),
            reason=str(payload["reason"]),
        )
        session.add(item)

    item.run_id = payload.get("run_id")
    item.source_module = str(payload.get("source_module") or item.source_module)
    item.source_step_id = payload.get("source_step_id")
    item.agent_output_id = payload.get("agent_output_id")
    item.claim_id = payload.get("claim_id")
    item.severity = str(payload.get("severity") or item.severity)
    item.reason = str(payload.get("reason") or item.reason)
    item.impact_modules = list(payload.get("impact_modules") or [])
    item.impact_report_ids = list(payload.get("impact_report_ids") or [])
    item.source_refs = list(payload.get("source_refs") or [])
    item.evidence_refs = list(payload.get("evidence_refs") or [])
    item.suggested_action = payload.get("suggested_action")
    item.status = str(payload.get("status") or item.status or "pending")
    if "resolution_action" in payload:
        item.resolution_action = payload.get("resolution_action")
    if "resolution_note" in payload:
        item.resolution_note = payload.get("resolution_note")
    if "resolution_actor" in payload:
        item.resolution_actor = payload.get("resolution_actor")
    if "resolution_request_id" in payload:
        item.resolution_request_id = payload.get("resolution_request_id")
    if "audit_id" in payload:
        item.audit_id = payload.get("audit_id")
    if "action_status" in payload:
        item.action_status = payload.get("action_status")
    if "next_run_id" in payload:
        item.next_run_id = payload.get("next_run_id")
    if "resolved_at" in payload:
        item.resolved_at = _parse_datetime(payload.get("resolved_at"))
    if payload.get("created_at") is not None:
        item.created_at = _parse_datetime(payload.get("created_at"))
    session.flush()
    return item


def get_review_item(session: Session, review_id: str) -> ReviewItem | None:
    return session.scalar(select(ReviewItem).where(ReviewItem.review_id == review_id))


def list_review_items(
    session: Session,
    *,
    status: str | None = None,
    source_module: str | None = None,
    run_id: str | None = None,
    limit: int = 100,
) -> list[ReviewItem]:
    stmt = select(ReviewItem)
    if status is not None:
        stmt = stmt.where(ReviewItem.status == status)
    if source_module is not None:
        stmt = stmt.where(ReviewItem.source_module == source_module)
    if run_id is not None:
        stmt = stmt.where(ReviewItem.run_id == run_id)
    stmt = stmt.order_by(ReviewItem.created_at.desc(), ReviewItem.review_id.asc()).limit(limit)
    return list(session.scalars(stmt))


def update_review_status(
    session: Session,
    review_id: str,
    *,
    status: str,
    resolution_action: str,
    resolution_note: str | None = None,
    resolution_actor: str | None = None,
    resolution_request_id: str | None = None,
    audit_id: str | None = None,
    action_status: str | None = None,
    next_run_id: str | None = None,
) -> ReviewItem | None:
    item = get_review_item(session, review_id)
    if item is None:
        return None
    item.status = status
    item.resolution_action = resolution_action
    item.resolution_note = resolution_note
    item.resolution_actor = resolution_actor
    item.resolution_request_id = resolution_request_id
    item.audit_id = audit_id
    item.action_status = action_status
    item.next_run_id = next_run_id
    item.resolved_at = datetime.now(UTC)
    session.flush()
    return item
