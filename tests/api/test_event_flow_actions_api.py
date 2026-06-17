"""Event Flow Slice 8 action contract tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.main import (
    api_event_flow_brief_ignore,
    api_event_flow_brief_link,
    api_event_flow_event_review,
    api_event_flow_report_input_exclude,
    api_event_flow_report_input_include,
    api_review_detail,
    api_run_detail,
)
from apps.api.schemas.event_flow import EventFlowActionRequest, EventFlowBriefLinkRequest
from database.models.analysis import ensure_analysis_tables
from database.models.task import ensure_task_tables


def _make_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_task_tables(engine)
    ensure_analysis_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_brief_link_creates_traceable_task_run_and_review() -> None:
    session = _make_session()

    response = api_event_flow_brief_link(
        "brief-001",
        body=EventFlowBriefLinkRequest(
            actor="codex",
            reason="merge brief into existing macro event",
            request_id="link-001",
            target_event_id="event-001",
        ),
        db=session,
    )

    assert response.status == "accepted"
    assert response.action == "link"
    assert response.entity_type == "brief"
    assert response.entity_id == "brief-001"
    assert response.run_id is not None
    assert response.review_id is not None
    assert response.audit_id == "event-flow-action:brief:brief-001:link-001"
    assert response.data_status == "partial"
    assert {ref.source_id for ref in response.source_refs} == {
        "event_flow_brief:brief-001",
        "event_flow_event:event-001",
    }

    run = api_run_detail(response.run_id, db=session).model_dump(mode="json")
    assert run["task_type"] == "event_flow_action"
    assert run["status"] == "needs_review"
    assert run["steps"][0]["task_kind"] == "event_flow_link"
    assert {ref["source_id"] for ref in run["steps"][0]["source_refs"]} == {
        "event_flow_brief:brief-001",
        "event_flow_event:event-001",
    }

    review = api_review_detail(response.review_id, db=session).model_dump(mode="json")
    assert review["source_module"] == "event_flow"
    assert review["status"] == "pending"
    assert review["suggested_action"] == "link"
    assert review["run_id"] == response.run_id
    assert review["source_step_id"] == run["steps"][0]["step_id"]


def test_other_event_flow_actions_register_reviewable_requests() -> None:
    session = _make_session()

    ignore = api_event_flow_brief_ignore(
        "brief-ignored",
        body=EventFlowActionRequest(actor="codex", reason="noise item", request_id="ignore-001"),
        db=session,
    )
    include = api_event_flow_report_input_include(
        "input-include",
        body=EventFlowActionRequest(actor="codex", reason="promote to daily synthesis", request_id="include-001"),
        db=session,
    )
    exclude = api_event_flow_report_input_exclude(
        "input-exclude",
        body=EventFlowActionRequest(actor="codex", reason="duplicate input", request_id="exclude-001"),
        db=session,
    )
    review = api_event_flow_event_review(
        "event-review",
        body=EventFlowActionRequest(actor="codex", reason="needs human check", request_id="review-001"),
        db=session,
    )

    assert ignore.audit_id == "event-flow-action:brief:brief-ignored:ignore-001"
    assert include.audit_id == "event-flow-action:report_input:input-include:include-001"
    assert exclude.audit_id == "event-flow-action:report_input:input-exclude:exclude-001"
    assert review.audit_id == "event-flow-action:event:event-review:review-001"

    for response, expected_action, expected_entity_type in [
        (ignore, "ignore", "brief"),
        (include, "include", "report_input"),
        (exclude, "exclude", "report_input"),
        (review, "review", "event"),
    ]:
        assert response.status == "accepted"
        assert response.action == expected_action
        assert response.entity_type == expected_entity_type
        assert response.run_id is not None
        assert response.review_id is not None
        assert response.data_status == "partial"

        run = api_run_detail(response.run_id, db=session).model_dump(mode="json")
        assert run["status"] == "needs_review"
        assert run["steps"][0]["task_kind"] == f"event_flow_{expected_action}"

        review_item = api_review_detail(response.review_id, db=session).model_dump(mode="json")
        assert review_item["status"] == "pending"
        assert review_item["suggested_action"] == expected_action
        assert review_item["run_id"] == response.run_id


def test_brief_link_requires_target_event_id() -> None:
    with pytest.raises(ValidationError):
        EventFlowBriefLinkRequest.model_validate(
            {
                "actor": "codex",
                "reason": "missing target",
                "request_id": "bad-001",
            }
        )
