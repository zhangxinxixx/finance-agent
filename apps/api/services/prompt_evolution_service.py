from __future__ import annotations

from typing import Any

from sqlalchemy import desc
from sqlalchemy.orm import Session

from apps.analysis.agents.prompt_evolution import build_prompt_evolution_proposal
from database.models.analysis import AgentOutput, PromptFeedback, PromptVersion, ReviewItem


def build_prompt_evolution_preview(
    db: Session,
    *,
    agent_id: str,
    recent_limit: int = 10,
) -> dict[str, Any]:
    current_prompt, prompt_source = _current_prompt(db=db, agent_id=agent_id)
    recent_outputs = _recent_agent_outputs(db=db, agent_id=agent_id, limit=recent_limit)
    agent_output_ids = [str(row.id) for row in recent_outputs]
    feedback_rows = _prompt_feedback(db=db, agent_id=agent_id, limit=recent_limit)
    review_rows = _review_gate_findings(db=db, agent_output_ids=agent_output_ids, limit=recent_limit)
    proposal = build_prompt_evolution_proposal(
        agent_name=agent_id,
        current_prompt=current_prompt,
        recent_runs=[_agent_output_to_recent_run(row) for row in recent_outputs],
        review_gate_findings=[_review_item_to_finding(row) for row in review_rows],
        manual_feedback=[_feedback_to_finding(row) for row in feedback_rows],
        failed_test_cases=[],
        schema_version=_schema_version(current_prompt),
        data_source_health={},
    ).to_dict()
    return {
        "source": "prompt_evolution_preview",
        "agent_id": agent_id,
        "proposal_only": True,
        "current_prompt_source": prompt_source,
        "recent_run_count": len(recent_outputs),
        "feedback_count": len(feedback_rows),
        "review_gate_finding_count": len(review_rows),
        "input_refs": {
            "agent_output_ids": agent_output_ids,
            "feedback_ids": [row.feedback_id for row in feedback_rows],
            "review_ids": [row.review_id for row in review_rows],
        },
        "proposal": proposal,
        "writes": [],
    }


def _current_prompt(*, db: Session, agent_id: str) -> tuple[dict[str, Any], str]:
    row = (
        db.query(PromptVersion)
        .filter(PromptVersion.agent_id == agent_id, PromptVersion.status == "active", PromptVersion.enabled.is_(True))
        .order_by(desc(PromptVersion.created_at))
        .first()
    )
    if row is not None:
        return dict(row.prompt_template or {}), f"prompt_versions:{row.id}:{row.version}"

    from apps.analysis.agents.registry import get_agent_registry

    agent = get_agent_registry(agent_id)
    prompt = (agent or {}).get("prompt") if isinstance(agent, dict) else {}
    template = prompt.get("template") if isinstance(prompt, dict) else {}
    return dict(template or {"agent_id": agent_id}), "agent_registry"


def _recent_agent_outputs(*, db: Session, agent_id: str, limit: int) -> list[AgentOutput]:
    return list(
        db.query(AgentOutput)
        .filter(AgentOutput.agent_name == agent_id)
        .order_by(desc(AgentOutput.created_at))
        .limit(max(1, min(limit, 50)))
        .all()
    )


def _prompt_feedback(*, db: Session, agent_id: str, limit: int) -> list[PromptFeedback]:
    return list(
        db.query(PromptFeedback)
        .filter(PromptFeedback.agent_id == agent_id)
        .order_by(desc(PromptFeedback.created_at))
        .limit(max(1, min(limit, 50)))
        .all()
    )


def _review_gate_findings(*, db: Session, agent_output_ids: list[str], limit: int) -> list[ReviewItem]:
    if not agent_output_ids:
        return []
    return list(
        db.query(ReviewItem)
        .filter(ReviewItem.agent_output_id.in_(agent_output_ids))
        .order_by(desc(ReviewItem.created_at))
        .limit(max(1, min(limit, 50)))
        .all()
    )


def _agent_output_to_recent_run(row: AgentOutput) -> dict[str, Any]:
    payload = dict(row.payload or {})
    return {
        "agent_output_id": str(row.id),
        "run_id": row.run_id,
        "status": row.status,
        "summary": row.summary,
        "quality_issues": _quality_issues(payload),
        "review_gate": payload.get("review_gate") if isinstance(payload.get("review_gate"), dict) else {},
        "prompt_version_id": row.prompt_version_id,
    }


def _quality_issues(payload: dict[str, Any]) -> list[Any]:
    issues: list[Any] = []
    for key in ("quality_issues", "failure_patterns", "warnings", "blocking_issues"):
        value = payload.get(key)
        if isinstance(value, list):
            issues.extend(value)
    return issues


def _feedback_to_finding(row: PromptFeedback) -> dict[str, Any]:
    suggested = row.suggested_changes if isinstance(row.suggested_changes, dict) else {}
    issue_code = suggested.get("issue_code") or suggested.get("pattern_id") or row.category
    description = row.comment or suggested.get("description") or row.category
    return {
        "id": row.feedback_id,
        "issue_code": issue_code,
        "description": description,
        "likely_root_cause": suggested.get("likely_root_cause") or _root_cause_from_feedback(row),
        "rating": row.rating,
        "status": row.status,
    }


def _review_item_to_finding(row: ReviewItem) -> dict[str, Any]:
    return {
        "id": row.review_id,
        "issue_code": row.source_step_id or row.claim_id or row.source_module,
        "description": row.reason,
        "likely_root_cause": _root_cause_from_review(row),
        "severity": row.severity,
        "status": row.status,
    }


def _root_cause_from_feedback(row: PromptFeedback) -> str:
    if row.category in {"analysis_error", "prompt_quality"}:
        return "prompt"
    if row.category == "missing_context":
        return "data_missing"
    return "unknown"


def _root_cause_from_review(row: ReviewItem) -> str:
    text = f"{row.source_module} {row.reason} {row.suggested_action or ''}".lower()
    if "schema" in text:
        return "schema"
    if "source" in text or "p0" in text or "data" in text:
        return "data_missing"
    if "dag" in text or "trace" in text:
        return "dag"
    return "prompt"


def _schema_version(current_prompt: dict[str, Any]) -> str | None:
    value = current_prompt.get("schema_version")
    if value is None:
        value = current_prompt.get("output_schema_version")
    return str(value) if value not in {None, ""} else None
