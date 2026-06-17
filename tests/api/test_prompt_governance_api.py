from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.main import (
    api_prompt_feedback_create,
    api_prompt_feedback_list,
    api_prompt_versions_activate,
    api_prompt_versions_by_agent,
    api_prompt_versions_create,
)
from apps.api.schemas.agent import PromptFeedbackCreate, PromptVersionActivate, PromptVersionCreate
from database.models.analysis import AgentOutput, AnalysisBase, PromptFeedback, ReviewItem, ensure_analysis_tables


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    AnalysisBase.metadata.create_all(engine)
    ensure_analysis_tables(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return factory()


def _agent_output(*, prompt_version_id: str | None = None) -> AgentOutput:
    return AgentOutput(
        snapshot_id="jin10:2026-06-07:221333:agent_analysis",
        asset="XAUUSD",
        trade_date=date(2026, 6, 7),
        run_id="221333",
        agent_name="jin10_report_analysis_agent",
        module="jin10_reports",
        version="1.0",
        status="success",
        bias="neutral",
        confidence=0.62,
        input_snapshot_ids={"raw": "raw-001"},
        source_refs=[{"source": "jin10_external", "article_id": "221333"}],
        key_findings=["下探风险升温"],
        risk_points=[],
        watchlist=[],
        invalid_conditions=[],
        summary="黄金惯性下探风险升温。",
        payload={"prompt_version": "v1"},
        payload_sha256="agent-output",
        prompt_version_id=prompt_version_id,
    )


def test_prompt_version_create_and_activate_are_versioned_and_append_only() -> None:
    db = _session()
    agent_id = "jin10_report_analysis_agent"

    first = api_prompt_versions_create(
        agent_id,
        PromptVersionCreate(
            prompt_template={"messages": [{"role": "user", "content": "v1 prompt"}]},
            status="active",
            change_note="initial",
            created_by="tester",
        ),
        db=db,
    )
    output = _agent_output(prompt_version_id=first["id"])
    db.add(output)
    db.commit()

    second = api_prompt_versions_create(
        agent_id,
        PromptVersionCreate(
            prompt_template={"messages": [{"role": "user", "content": "v2 prompt"}]},
            status="draft",
            change_note="candidate",
            created_by="tester",
        ),
        db=db,
    )

    activated = api_prompt_versions_activate(
        agent_id,
        PromptVersionActivate(version=second["version"], reason="accept v2"),
        db=db,
    )
    versions = api_prompt_versions_by_agent(agent_id, db=db)["versions"]
    db.refresh(output)

    assert first["version"] == "v1"
    assert second["version"] == "v2"
    assert activated["id"] == second["id"]
    assert activated["status"] == "active"
    assert {item["version"]: item["status"] for item in versions} == {"v1": "deprecated", "v2": "active"}
    assert output.prompt_version_id == first["id"]


def test_prompt_version_create_rejects_empty_or_invalid_contract() -> None:
    db = _session()

    with pytest.raises(Exception) as empty_exc:
        api_prompt_versions_create(
            "jin10_report_analysis_agent",
            PromptVersionCreate(prompt_template={}),
            db=db,
        )
    assert getattr(empty_exc.value, "status_code", None) == 400

    with pytest.raises(Exception) as status_exc:
        api_prompt_versions_create(
            "jin10_report_analysis_agent",
            PromptVersionCreate(
                prompt_template={"messages": [{"role": "user", "content": "prompt"}]},
                status="published",
            ),
            db=db,
        )
    assert getattr(status_exc.value, "status_code", None) == 400


def test_prompt_version_activate_enables_target_version() -> None:
    db = _session()
    agent_id = "jin10_report_analysis_agent"
    created = api_prompt_versions_create(
        agent_id,
        PromptVersionCreate(
            prompt_template={"messages": [{"role": "user", "content": "draft prompt"}]},
            status="draft",
            enabled=False,
        ),
        db=db,
    )

    activated = api_prompt_versions_activate(
        agent_id,
        PromptVersionActivate(version=created["version"], reason="enable and activate"),
        db=db,
    )

    assert activated["status"] == "active"
    assert activated["enabled"] is True


def test_prompt_feedback_is_append_only_and_can_create_review_item() -> None:
    db = _session()
    output = _agent_output()
    db.add(output)
    db.commit()

    response = api_prompt_feedback_create(
        PromptFeedbackCreate(
            agent_id="jin10_report_analysis_agent",
            agent_output_id=str(output.id),
            run_id=output.run_id,
            rating=2,
            category="analysis_error",
            comment="结论超出证据，需要复核。",
            suggested_changes={"prompt": "要求显式列出证据不足"},
            submitted_by="tester",
            request_id="req-feedback-001",
        ),
        db=db,
    )

    feedback_rows = db.query(PromptFeedback).all()
    review_rows = db.query(ReviewItem).all()
    db.refresh(output)

    assert response["status"] == "open"
    assert response["review_item"]["status"] == "pending"
    assert len(feedback_rows) == 1
    assert feedback_rows[0].agent_output_id == str(output.id)
    assert feedback_rows[0].suggested_changes == {"prompt": "要求显式列出证据不足"}
    assert len(review_rows) == 1
    assert review_rows[0].source_module == "prompt_feedback"
    assert review_rows[0].agent_output_id == str(output.id)
    assert output.summary == "黄金惯性下探风险升温。"


def test_prompt_feedback_list_filters_before_limit() -> None:
    db = _session()

    for agent_id in ("jin10_report_analysis_agent", "cme_options_agent"):
        api_prompt_feedback_create(
            PromptFeedbackCreate(
                agent_id=agent_id,
                category="prompt_quality",
                comment=f"{agent_id} feedback",
                submitted_by="tester",
            ),
            db=db,
        )

    response = api_prompt_feedback_list(agent_id="jin10_report_analysis_agent", status="open", limit=10, db=db)

    assert response["count"] == 1
    assert response["feedback"][0]["agent_id"] == "jin10_report_analysis_agent"
