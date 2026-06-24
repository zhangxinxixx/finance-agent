"""TDD: ReviewItem API backend closure."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.main import (
    api_review_approve,
    api_review_detail,
    api_review_reject,
    api_review_rerun,
    api_review_use_fallback,
    api_reviews,
)
from apps.api.schemas.review import ReviewActionRequest
from database.models.analysis import ensure_analysis_tables
from database.queries.review import upsert_review_item


def _make_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_analysis_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _seed_review(session: Session, review_id: str = "review-001") -> None:
    upsert_review_item(
        session,
        {
            "review_id": review_id,
            "run_id": "run-001",
            "source_module": "jin10_vlm",
            "source_step_id": "step-001",
            "severity": "warning",
            "reason": "low confidence extraction",
            "agent_output_id": "ao-001",
            "claim_id": "claim-001",
            "impact_modules": ["reports"],
            "impact_report_ids": ["report-001"],
            "source_refs": [
                {
                    "source_id": "src-001",
                    "source_name": "Jin10",
                    "source_type": "article",
                    "status": "available",
                }
            ],
            "evidence_refs": [
                {
                    "artifact_id": "artifact-001",
                    "artifact_type": "chart_snapshot",
                    "file_path": "storage/parsed/reports/2026-05-26/chart.png",
                }
            ],
            "suggested_action": "manual review",
            "status": "pending",
            "created_at": datetime(2026, 5, 26, 9, 0, tzinfo=UTC),
        },
    )
    session.commit()


def test_list_reviews_returns_pending_items_with_trace_fields() -> None:
    session = _make_session()
    _seed_review(session)

    payload = api_reviews(status="pending", db=session)

    assert payload["total"] == 1
    item = payload["reviews"][0]
    assert item["review_id"] == "review-001"
    assert item["status"] == "pending"
    assert item["source_module"] == "jin10_vlm"
    assert item["agent_output_id"] == "ao-001"
    assert item["claim_id"] == "claim-001"
    assert item["impact_modules"] == ["reports"]
    assert item["impact_report_ids"] == ["report-001"]
    assert item["source_refs"][0]["source_id"] == "src-001"
    assert item["evidence_refs"][0]["artifact_id"] == "artifact-001"


def test_get_review_detail_returns_single_item() -> None:
    session = _make_session()
    _seed_review(session)

    item = api_review_detail("review-001", db=session).model_dump(mode="json")

    assert item["review_id"] == "review-001"
    assert item["reason"] == "low confidence extraction"


def test_review_actions_update_status_and_resolution_fields() -> None:
    session = _make_session()
    _seed_review(session, "approve-me")
    _seed_review(session, "reject-me")
    _seed_review(session, "rerun-me")
    _seed_review(session, "fallback-me")

    approved = api_review_approve("approve-me", body=ReviewActionRequest(note="looks good"), db=session)
    rejected = api_review_reject("reject-me", body=ReviewActionRequest(note="bad parse"), db=session)
    rerun = api_review_rerun("rerun-me", body=ReviewActionRequest(note="rerun parser"), db=session)
    fallback = api_review_use_fallback("fallback-me", body=ReviewActionRequest(note="use file fallback"), db=session)

    assert approved.status == "approved"
    assert approved.resolution_action == "approve"
    assert rejected.status == "rejected"
    assert rejected.resolution_action == "reject"
    assert rerun.status == "rerun"
    assert rerun.resolution_action == "rerun"
    assert fallback.status == "approved"
    assert fallback.resolution_action == "use_fallback"


def test_review_action_records_actor_request_and_audit_trace() -> None:
    session = _make_session()
    _seed_review(session, "approve-with-audit")

    approved = api_review_approve(
        "approve-with-audit",
        body=ReviewActionRequest(
            actor="automation",
            reason="validated source refs",
            request_id="req-001",
            expected_status="pending",
        ),
        db=session,
    )

    assert approved.status == "approved"
    assert approved.resolution_note == "validated source refs"
    assert approved.resolution_actor == "automation"
    assert approved.resolution_request_id == "req-001"
    assert approved.audit_id == "review-action:approve-with-audit:req-001"
    assert approved.action_status == "success"


def test_review_action_rejects_stale_expected_status() -> None:
    session = _make_session()
    _seed_review(session, "stale-review")

    with pytest.raises(HTTPException) as exc:
        api_review_approve(
            "stale-review",
            body=ReviewActionRequest(actor="automation", reason="stale", expected_status="approved"),
            db=session,
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "Review item status conflict"


def test_review_action_rejects_repeated_resolution() -> None:
    session = _make_session()
    _seed_review(session, "already-approved")

    api_review_approve(
        "already-approved",
        body=ReviewActionRequest(actor="automation", reason="first", request_id="req-first"),
        db=session,
    )

    with pytest.raises(HTTPException) as exc:
        api_review_reject(
            "already-approved",
            body=ReviewActionRequest(actor="automation", reason="second", request_id="req-second"),
            db=session,
        )

    assert exc.value.status_code == 409


def test_review_rerun_does_not_fake_scheduler_run_when_unwired() -> None:
    session = _make_session()
    _seed_review(session, "rerun-unwired")

    rerun = api_review_rerun(
        "rerun-unwired",
        body=ReviewActionRequest(actor="automation", reason="rerun parser", request_id="req-rerun"),
        db=session,
    )

    assert rerun.status == "rerun"
    assert rerun.resolution_action == "rerun"
    assert rerun.action_status == "queued_not_implemented"
    assert rerun.next_run_id is None


def test_review_detail_and_actions_return_404_for_missing_review() -> None:
    session = _make_session()

    with pytest.raises(HTTPException) as detail_exc:
        api_review_detail("missing-review", db=session)
    with pytest.raises(HTTPException) as action_exc:
        api_review_approve("missing-review", body=ReviewActionRequest(note="noop"), db=session)

    assert detail_exc.value.status_code == 404
    assert action_exc.value.status_code == 404
