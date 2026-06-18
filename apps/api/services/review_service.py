from __future__ import annotations

from sqlalchemy.orm import Session

from apps.api.schemas.review import ReviewItem as ReviewItemSchema
from apps.api.schemas.source_trace import ArtifactRef
from apps.api.services._trace_refs import coerce_artifact_type, parse_source_refs
from database.models.analysis import ReviewItem
from database.queries.review import (
    get_review_item,
    list_review_items,
    update_review_status,
)


class ReviewStatusConflictError(ValueError):
    """Raised when a review action is based on stale or already-resolved state."""


def list_review_item_responses(
    db: Session,
    *,
    status: str | None = None,
    source_module: str | None = None,
    run_id: str | None = None,
    limit: int = 100,
) -> list[ReviewItemSchema]:
    return [
        build_review_item_response(item)
        for item in list_review_items(
            db,
            status=status,
            source_module=source_module,
            run_id=run_id,
            limit=limit,
        )
    ]


def get_review_item_response(db: Session, review_id: str) -> ReviewItemSchema | None:
    item = get_review_item(db, review_id)
    if item is None:
        return None
    return build_review_item_response(item)


def resolve_review_item(
    db: Session,
    review_id: str,
    *,
    status: str,
    resolution_action: str,
    resolution_note: str | None,
    resolution_actor: str | None = None,
    resolution_request_id: str | None = None,
    expected_status: str | None = None,
) -> ReviewItemSchema | None:
    current = get_review_item(db, review_id)
    if current is None:
        return None
    if expected_status is not None and current.status != expected_status:
        raise ReviewStatusConflictError
    if current.status != "pending":
        raise ReviewStatusConflictError

    action_status = "queued_not_implemented" if resolution_action == "rerun" else "success"
    audit_id = f"review-action:{review_id}:{resolution_request_id or resolution_action}"

    item = update_review_status(
        db,
        review_id,
        status=status,
        resolution_action=resolution_action,
        resolution_note=resolution_note,
        resolution_actor=resolution_actor,
        resolution_request_id=resolution_request_id,
        audit_id=audit_id,
        action_status=action_status,
        next_run_id=None,
    )
    if item is None:
        return None
    db.commit()
    db.refresh(item)
    return build_review_item_response(item)


def build_review_item_response(item: ReviewItem) -> ReviewItemSchema:
    return ReviewItemSchema(
        review_id=item.review_id,
        run_id=item.run_id,
        source_module=item.source_module,
        source_step_id=item.source_step_id,
        agent_output_id=item.agent_output_id,
        claim_id=item.claim_id,
        severity=item.severity,
        reason=item.reason,
        impact_modules=list(item.impact_modules or []),
        impact_report_ids=[str(value) for value in (item.impact_report_ids or [])],
        source_refs=parse_source_refs(item.source_refs),
        evidence_refs=_parse_artifact_refs(item.evidence_refs),
        suggested_action=item.suggested_action,
        status=item.status,
        resolution_action=item.resolution_action,
        resolution_note=item.resolution_note,
        resolution_actor=item.resolution_actor,
        resolution_request_id=item.resolution_request_id,
        audit_id=item.audit_id,
        action_status=item.action_status,
        next_run_id=item.next_run_id,
        created_at=item.created_at,
        updated_at=item.updated_at,
        resolved_at=item.resolved_at,
    )
def _parse_artifact_refs(raw: list[dict] | None) -> list[ArtifactRef]:
    refs: list[ArtifactRef] = []
    for index, item in enumerate(raw or []):
        if isinstance(item, str):
            refs.append(
                ArtifactRef(
                    artifact_id=f"evidence-{index + 1}",
                    artifact_type="analysis_md",
                    file_path=item,
                )
            )
            continue
        if not isinstance(item, dict):
            continue
        file_path = item.get("file_path") or item.get("artifact_path") or item.get("path")
        if not file_path:
            continue
        refs.append(
            ArtifactRef(
                artifact_id=str(item.get("artifact_id") or f"evidence-{index + 1}"),
                artifact_type=str(item.get("artifact_type") or coerce_artifact_type(None, str(file_path))),
                file_path=str(file_path),
                version=item.get("version"),
                generated_at=item.get("generated_at"),
                sha256=item.get("sha256"),
            )
        )
    return refs
