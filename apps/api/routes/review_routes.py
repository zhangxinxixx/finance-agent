"""Review routes extracted from the main FastAPI entrypoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from apps.api.schemas.review import ReviewActionRequest, ReviewItem
from apps.api.services import review_service
from database.models.engine import get_db

router = APIRouter()


@router.get("/api/reviews")
def api_reviews(
    status: str | None = None,
    source_module: str | None = None,
    run_id: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """列出待人工复核项，供 Review Center / Agent Tasks 读取。"""
    reviews = review_service.list_review_item_responses(
        db,
        status=status,
        source_module=source_module,
        run_id=run_id,
        limit=min(limit, 200),
    )
    return {"reviews": [item.model_dump(mode="json") for item in reviews], "total": len(reviews)}


@router.get("/api/reviews/{review_id}", response_model=ReviewItem)
def api_review_detail(review_id: str, db: Session = Depends(get_db)) -> ReviewItem:
    item = review_service.get_review_item_response(db, review_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Review item not found")
    return item


@router.post("/api/reviews/{review_id}/approve", response_model=ReviewItem)
def api_review_approve(
    review_id: str,
    body: ReviewActionRequest | None = None,
    db: Session = Depends(get_db),
) -> ReviewItem:
    return _resolve_review(review_id, status="approved", action="approve", body=body, db=db)


@router.post("/api/reviews/{review_id}/reject", response_model=ReviewItem)
def api_review_reject(
    review_id: str,
    body: ReviewActionRequest | None = None,
    db: Session = Depends(get_db),
) -> ReviewItem:
    return _resolve_review(review_id, status="rejected", action="reject", body=body, db=db)


@router.post("/api/reviews/{review_id}/rerun", response_model=ReviewItem)
def api_review_rerun(
    review_id: str,
    body: ReviewActionRequest | None = None,
    db: Session = Depends(get_db),
) -> ReviewItem:
    return _resolve_review(review_id, status="rerun", action="rerun", body=body, db=db)


@router.post("/api/reviews/{review_id}/use-fallback", response_model=ReviewItem)
def api_review_use_fallback(
    review_id: str,
    body: ReviewActionRequest | None = None,
    db: Session = Depends(get_db),
) -> ReviewItem:
    return _resolve_review(review_id, status="approved", action="use_fallback", body=body, db=db)


def _resolve_review(
    review_id: str,
    *,
    status: str,
    action: str,
    body: ReviewActionRequest | None,
    db: Session,
) -> ReviewItem:
    try:
        item = review_service.resolve_review_item(
            db,
            review_id,
            status=status,
            resolution_action=action,
            resolution_note=(body.reason or body.note) if body else None,
            resolution_actor=body.actor if body else None,
            resolution_request_id=body.request_id if body else None,
            expected_status=body.expected_status if body else None,
        )
    except review_service.ReviewStatusConflictError as exc:
        raise HTTPException(status_code=409, detail="Review item status conflict") from exc
    if item is None:
        raise HTTPException(status_code=404, detail="Review item not found")
    return item
