from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.main import (
    api_prompt_evolution_proposal,
    api_prompt_feedback_create,
    api_prompt_feedback_list,
    api_prompt_versions_activate,
    api_prompt_versions_by_agent,
    api_prompt_versions_create,
)
from apps.api.routes import agent_governance_write_routes
from apps.api.schemas.agent import PromptFeedbackCreate, PromptVersionActivate, PromptVersionCreate
from database.models.analysis import AgentOutput, AnalysisBase, PromptFeedback, ReviewItem, ensure_analysis_tables


def test_agent_governance_routes_do_not_depend_on_fastapi_main() -> None:
    from pathlib import Path

    for route_file in (
        "agent_governance_read_routes.py",
        "agent_governance_write_routes.py",
    ):
        source = Path("apps/api/routes", route_file).read_text(encoding="utf-8")
        assert "from apps.api import main as api_main" not in source, route_file


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


def test_prompt_version_item_exposes_issue_52_contract_aliases() -> None:
    db = _session()
    agent_id = "jin10_report_analysis_agent"

    created = api_prompt_versions_create(
        agent_id,
        PromptVersionCreate(
            prompt_source="apps/analysis/agents/jin10_report_prompt.py",
            prompt_template={"messages": [{"role": "user", "content": "v1 prompt"}]},
            status="active",
            change_note="initial",
            created_by="tester",
        ),
        db=db,
    )

    assert created["prompt_id"] == "jin10_report_analysis_agent_prompt"
    assert created["agent_name"] == agent_id
    assert created["checksum"] == created["prompt_sha256"]
    assert created["source_file"] == "apps/analysis/agents/jin10_report_prompt.py"
    assert created["version"] == "v1"
    assert created["status"] == "active"


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


def test_prompt_version_create_accepts_candidate_and_rolled_back_statuses() -> None:
    db = _session()
    agent_id = "jin10_report_analysis_agent"

    candidate = api_prompt_versions_create(
        agent_id,
        PromptVersionCreate(
            prompt_template={"messages": [{"role": "user", "content": "candidate prompt"}]},
            status="candidate",
            change_note="candidate under A/B validation",
        ),
        db=db,
    )
    rolled_back = api_prompt_versions_create(
        agent_id,
        PromptVersionCreate(
            prompt_template={"messages": [{"role": "user", "content": "rolled back prompt"}]},
            status="rolled_back",
            change_note="rolled back after regression",
        ),
        db=db,
    )

    versions = api_prompt_versions_by_agent(agent_id, db=db)["versions"]

    assert candidate["status"] == "candidate"
    assert rolled_back["status"] == "rolled_back"
    assert {item["version"]: item["status"] for item in versions} == {
        "v1": "candidate",
        "v2": "rolled_back",
    }


def test_candidate_prompt_activation_requires_release_approval_audit() -> None:
    db = _session()
    agent_id = "jin10_report_analysis_agent"
    active = api_prompt_versions_create(
        agent_id,
        PromptVersionCreate(
            prompt_template={"messages": [{"role": "user", "content": "active prompt"}]},
            status="active",
        ),
        db=db,
    )
    candidate = api_prompt_versions_create(
        agent_id,
        PromptVersionCreate(
            prompt_template={"messages": [{"role": "user", "content": "candidate prompt"}]},
            status="candidate",
        ),
        db=db,
    )

    with pytest.raises(Exception) as exc:
        api_prompt_versions_activate(
            agent_id,
            PromptVersionActivate(version=candidate["version"], reason="release candidate"),
            db=db,
        )

    assert getattr(exc.value, "status_code", None) == 400
    assert "release_approved" in str(getattr(exc.value, "detail", ""))
    versions = api_prompt_versions_by_agent(agent_id, db=db)["versions"]
    assert {item["version"]: item["status"] for item in versions} == {
        active["version"]: "active",
        candidate["version"]: "candidate",
    }


def test_candidate_prompt_activation_accepts_release_approval_audit(monkeypatch) -> None:
    db = _session()
    agent_id = "jin10_report_analysis_agent"
    active = api_prompt_versions_create(
        agent_id,
        PromptVersionCreate(
            prompt_template={"messages": [{"role": "user", "content": "active prompt"}]},
            status="active",
        ),
        db=db,
    )
    candidate = api_prompt_versions_create(
        agent_id,
        PromptVersionCreate(
            prompt_template={"messages": [{"role": "user", "content": "candidate prompt"}]},
            status="candidate",
        ),
        db=db,
    )
    approval_check: dict[str, object] = {}

    def _evaluate(**kwargs):
        approval_check.update(kwargs)
        return SimpleNamespace(ready=True, blocking_reasons=())

    monkeypatch.setattr(agent_governance_write_routes, "evaluate_prompt_activation_readiness", _evaluate)

    activated = api_prompt_versions_activate(
        agent_id,
        PromptVersionActivate(
            version=candidate["version"],
            reason="approved release",
            release_approval_artifact="governance/prompt_evolution/2026-07-09/prompt_release_records.json",
        ),
        db=db,
    )

    versions = api_prompt_versions_by_agent(agent_id, db=db)["versions"]
    assert activated["id"] == candidate["id"]
    assert activated["status"] == "active"
    assert approval_check == {
        "agent_name": agent_id,
        "candidate_prompt_version_id": candidate["id"],
        "release_approval_artifact": "governance/prompt_evolution/2026-07-09/prompt_release_records.json",
    }
    assert {item["version"]: item["status"] for item in versions} == {
        active["version"]: "deprecated",
        candidate["version"]: "active",
    }
    assert {item["version"]: item["enabled"] for item in versions} == {
        active["version"]: False,
        candidate["version"]: True,
    }


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


def test_prompt_evolution_proposal_preview_uses_outputs_feedback_and_reviews_without_writes() -> None:
    db = _session()
    agent_id = "event_attribution_agent"

    first = AgentOutput(
        snapshot_id="gold-v3:run-1",
        asset="XAUUSD",
        trade_date=date(2026, 6, 30),
        run_id="run-1",
        agent_name=agent_id,
        module="gold_v3",
        version="1.0",
        status="success",
        bias="mixed",
        confidence=0.64,
        input_snapshot_ids={"event_flow": "event-flow-1"},
        source_refs=[{"source": "fixture", "source_ref": "event:1"}],
        key_findings=[],
        risk_points=[],
        watchlist=[],
        invalid_conditions=[],
        summary="Hormuz event missed oil_price.",
        payload={
            "quality_issues": [
                {
                    "issue_code": "missing_oil_price_mainline",
                    "description": "Hormuz event missed oil_price mainline",
                    "likely_root_cause": "prompt",
                }
            ]
        },
        payload_sha256="agent-output-1",
    )
    second = AgentOutput(
        snapshot_id="gold-v3:run-2",
        asset="XAUUSD",
        trade_date=date(2026, 7, 1),
        run_id="run-2",
        agent_name=agent_id,
        module="gold_v3",
        version="1.0",
        status="success",
        bias="mixed",
        confidence=0.66,
        input_snapshot_ids={"event_flow": "event-flow-2"},
        source_refs=[{"source": "fixture", "source_ref": "event:2"}],
        key_findings=[],
        risk_points=[],
        watchlist=[],
        invalid_conditions=[],
        summary="Red Sea event missed oil_price.",
        payload={
            "quality_issues": [
                {
                    "issue_code": "missing_oil_price_mainline",
                    "description": "Red Sea event missed oil_price mainline",
                    "likely_root_cause": "prompt",
                }
            ]
        },
        payload_sha256="agent-output-2",
    )
    db.add_all([first, second])
    db.commit()

    api_prompt_feedback_create(
        PromptFeedbackCreate(
            agent_id=agent_id,
            agent_output_id=str(second.id),
            run_id=second.run_id,
            rating=2,
            category="prompt_quality",
            comment="Repeated geopolitical events did not check oil_price",
            suggested_changes={
                "issue_code": "missing_oil_price_mainline",
                "likely_root_cause": "prompt",
            },
            submitted_by="tester",
        ),
        db=db,
    )
    db.add(
        ReviewItem(
            review_id="rv-review-gate-001",
            run_id=second.run_id,
            source_module="review_gate",
            source_step_id="missing_oil_price_mainline",
            agent_output_id=str(second.id),
            severity="warning",
            reason="ReviewGate: geopolitical event did not include oil_price mainline.",
            impact_modules=["gold_mainlines"],
            impact_report_ids=[],
            source_refs=[],
            evidence_refs=[],
            suggested_action="Review prompt rule for oil linkage.",
            status="pending",
        )
    )
    db.commit()
    before_feedback_count = db.query(PromptFeedback).count()
    before_review_items = db.query(ReviewItem).count()

    response = api_prompt_evolution_proposal(agent_id, recent_limit=10, db=db)

    assert response["source"] == "prompt_evolution_preview"
    assert response["proposal_only"] is True
    assert response["writes"] == []
    assert response["recent_run_count"] == 2
    assert response["feedback_count"] == 1
    assert response["review_gate_finding_count"] == 1
    proposal = response["proposal"]
    assert proposal["prompt_update_proposal"]["proposal_type"] == "prompt_update"
    assert proposal["prompt_update_proposal"]["test_cases"]
    assert proposal["manual_review_required"] is True
    assert db.query(PromptFeedback).count() == before_feedback_count
    assert db.query(ReviewItem).count() == before_review_items
