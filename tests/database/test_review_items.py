"""TDD: ReviewItem persistence model and repository helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from database.models.analysis import ReviewItem, ensure_analysis_tables
from database.queries.review import get_review_item, list_review_items, update_review_status, upsert_review_item


def _make_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_analysis_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_review_items_table_is_created_by_analysis_metadata() -> None:
    session = _make_session()

    tables = inspect(session.get_bind()).get_table_names()

    assert "review_items" in tables
    assert ReviewItem.__tablename__ == "review_items"


def test_upsert_review_item_persists_traceable_fields() -> None:
    session = _make_session()

    item = upsert_review_item(
        session,
        {
            "review_id": "review-001",
            "run_id": "run-001",
            "source_module": "jin10_vlm",
            "source_step_id": "step-001",
            "severity": "warning",
            "reason": "low confidence chart extraction",
            "agent_output_id": "ao-001",
            "claim_id": "claim-001",
            "impact_modules": ["reports", "strategy"],
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

    fetched = get_review_item(session, "review-001")

    assert fetched is not None
    assert fetched.id == item.id
    assert fetched.run_id == "run-001"
    assert fetched.source_module == "jin10_vlm"
    assert fetched.agent_output_id == "ao-001"
    assert fetched.claim_id == "claim-001"
    assert fetched.impact_modules == ["reports", "strategy"]
    assert fetched.impact_report_ids == ["report-001"]
    assert fetched.source_refs[0]["source_id"] == "src-001"
    assert fetched.evidence_refs[0]["artifact_id"] == "artifact-001"
    assert fetched.status == "pending"


def test_list_review_items_filters_by_status_and_module() -> None:
    session = _make_session()
    upsert_review_item(session, {"review_id": "r1", "source_module": "cme", "severity": "error", "reason": "total mismatch"})
    upsert_review_item(
        session,
        {"review_id": "r2", "source_module": "jin10", "severity": "warning", "reason": "low confidence"},
    )
    update_review_status(session, "r2", status="approved", resolution_action="approve")
    session.commit()

    pending = list_review_items(session, status="pending")
    approved_jin10 = list_review_items(session, status="approved", source_module="jin10")

    assert [item.review_id for item in pending] == ["r1"]
    assert [item.review_id for item in approved_jin10] == ["r2"]


def test_update_review_status_sets_resolution_metadata() -> None:
    session = _make_session()
    upsert_review_item(session, {"review_id": "review-001", "source_module": "cme", "severity": "error", "reason": "parse mismatch"})
    session.commit()

    updated = update_review_status(
        session,
        "review-001",
        status="rejected",
        resolution_action="reject",
        resolution_note="parser output is invalid",
    )
    session.commit()

    assert updated is not None
    assert updated.status == "rejected"
    assert updated.resolution_action == "reject"
    assert updated.resolution_note == "parser output is invalid"
    assert updated.resolved_at is not None


def test_upsert_review_item_preserves_resolution_metadata_when_not_provided() -> None:
    session = _make_session()
    upsert_review_item(session, {"review_id": "review-001", "source_module": "cme", "severity": "error", "reason": "parse mismatch"})
    resolved = update_review_status(
        session,
        "review-001",
        status="approved",
        resolution_action="approve",
        resolution_note="checked manually",
    )
    assert resolved is not None
    resolved_at = resolved.resolved_at
    session.commit()

    upsert_review_item(
        session,
        {
            "review_id": "review-001",
            "source_module": "cme",
            "severity": "warning",
            "reason": "updated evidence",
            "impact_modules": ["reports"],
        },
    )
    session.commit()

    fetched = get_review_item(session, "review-001")
    assert fetched is not None
    assert fetched.status == "approved"
    assert fetched.resolution_action == "approve"
    assert fetched.resolution_note == "checked manually"
    assert fetched.resolved_at == resolved_at
    assert fetched.reason == "updated evidence"
