"""Agent governance write routes extracted from the main FastAPI entrypoint."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc
from sqlalchemy.orm import Session

from apps.api.schemas.agent import (
    PromptEvolutionReleaseActionRequest,
    PromptFeedbackCreate,
    PromptVersionActivate,
    PromptVersionCreate,
)
from apps.api.services.agent_governance_service import (
    prompt_feedback_item,
    prompt_version_item,
    validate_prompt_version_create_payload,
)
from apps.api.services.prompt_evolution_service import evaluate_prompt_activation_readiness
from database.models.engine import get_db

router = APIRouter()


@router.post("/api/governance/prompt-evolution/release/action")
def api_prompt_evolution_release_action(payload: PromptEvolutionReleaseActionRequest):
    """Record a review-approved PromptEvolution release or rollback audit.

    This endpoint intentionally does not activate or mutate production prompts.
    """
    from apps.api.services.prompt_evolution_service import record_prompt_release_action

    try:
        return record_prompt_release_action(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/agents/prompts/{agent_id}")
def api_prompt_versions_create(
    agent_id: str,
    payload: PromptVersionCreate,
    db: Session = Depends(get_db),
):
    """为某个 Agent 创建新 prompt 版本。"""
    import hashlib
    import json

    from apps.analysis.agents.registry import get_agent_registry
    from database.models.analysis import PromptVersion

    agent = get_agent_registry(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    validate_prompt_version_create_payload(payload)

    template_raw = json.dumps(payload.prompt_template, sort_keys=True, ensure_ascii=False)
    sha = hashlib.sha256(template_raw.encode()).hexdigest()

    latest = (
        db.query(PromptVersion)
        .filter(PromptVersion.agent_id == agent_id)
        .order_by(desc(PromptVersion.created_at))
        .first()
    )
    if latest and latest.version.startswith("v"):
        try:
            latest_num = int(latest.version[1:])
            next_version = f"v{latest_num + 1}"
        except ValueError:
            next_version = "v2"
    else:
        next_version = "v1"

    pv = PromptVersion(
        id=str(uuid.uuid4()),
        agent_id=agent_id,
        version=next_version,
        prompt_kind=payload.prompt_kind or "llm",
        prompt_source=payload.prompt_source,
        prompt_template=payload.prompt_template,
        prompt_sha256=sha,
        status=payload.status or "draft",
        enabled=payload.enabled if payload.enabled is not None else True,
        model_routing=payload.model_routing,
        change_note=payload.change_note,
        created_by=payload.created_by,
        request_id=payload.request_id,
    )
    db.add(pv)
    db.commit()
    db.refresh(pv)
    return prompt_version_item(pv)


@router.patch("/api/agents/prompts/{agent_id}/activate")
def api_prompt_versions_activate(
    agent_id: str,
    payload: PromptVersionActivate,
    db: Session = Depends(get_db),
):
    """激活某个 Agent 的指定版本，同时停用该 Agent 所有其他版本。"""
    from database.models.analysis import PromptVersion

    target = (
        db.query(PromptVersion)
        .filter(PromptVersion.agent_id == agent_id, PromptVersion.version == payload.version)
        .first()
    )
    if target is None:
        raise HTTPException(
            status_code=404,
            detail=f"Version not found: {agent_id} {payload.version}",
        )
    if target.status == "candidate":
        decision = evaluate_prompt_activation_readiness(
            agent_name=agent_id,
            candidate_prompt_version_id=target.id,
            release_approval_artifact=payload.release_approval_artifact,
        )
        if not decision.ready:
            reasons = ", ".join(decision.blocking_reasons)
            raise HTTPException(
                status_code=400,
                detail=(
                    "candidate prompt activation requires a valid release_approved "
                    f"PromptEvolution decision: {reasons}"
                ),
            )

    db.query(PromptVersion).filter(
        PromptVersion.agent_id == agent_id,
        PromptVersion.id != target.id,
    ).update(
        {"status": "deprecated", "enabled": False},
        synchronize_session=False,
    )
    target.status = "active"
    target.enabled = True
    if payload.reason:
        target.change_note = (target.change_note or "") + f"\n激活: {payload.reason}"
    db.commit()
    db.refresh(target)
    return prompt_version_item(target)


@router.post("/api/agents/feedback")
def api_prompt_feedback_create(payload: PromptFeedbackCreate, db: Session = Depends(get_db)):
    """提交人工反馈（P2-11）。"""
    from database.models.analysis import PromptFeedback

    feedback = PromptFeedback(
        id=str(uuid.uuid4()),
        feedback_id=f"fb-{uuid.uuid4().hex[:12]}",
        agent_output_id=payload.agent_output_id,
        agent_id=payload.agent_id,
        prompt_version_id=payload.prompt_version_id,
        run_id=payload.run_id,
        rating=payload.rating,
        category=payload.category or "prompt_quality",
        comment=payload.comment,
        suggested_changes=payload.suggested_changes,
        status="open",
        submitted_by=payload.submitted_by,
        request_id=payload.request_id,
    )
    db.add(feedback)

    review_item: dict[str, object] | None = None
    severe_categories = {"analysis_error", "missing_context"}
    if payload.category in severe_categories and payload.agent_output_id:
        from database.models.analysis import ReviewItem as _ReviewItem

        review = _ReviewItem(
            id=str(uuid.uuid4()),
            review_id=f"rv-{uuid.uuid4().hex[:12]}",
            run_id=payload.run_id,
            source_module="prompt_feedback",
            agent_output_id=payload.agent_output_id,
            severity="warning",
            reason=f"[{payload.category}] {payload.comment or '(无评注)'}",
            impact_modules=[],
            impact_report_ids=[],
            source_refs=[],
            evidence_refs=[],
            suggested_action="请人工审查反馈并决定是否需要调整 Prompt 或重新运行分析。",
            status="pending",
        )
        db.add(review)
        db.flush()
        feedback.review_item_id = review.review_id
        review_item = {
            "review_id": review.review_id,
            "status": review.status,
            "severity": review.severity,
        }

    db.commit()
    db.refresh(feedback)

    result = prompt_feedback_item(feedback)
    if review_item:
        result["review_item"] = review_item
    return result


@router.get("/api/agents/feedback/{agent_id}")
def api_prompt_feedback_by_agent(
    agent_id: str,
    status: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """按 Agent 查询反馈记录。"""
    from database.models.analysis import PromptFeedback

    query = db.query(PromptFeedback).filter(PromptFeedback.agent_id == agent_id)
    if status:
        query = query.filter(PromptFeedback.status == status)
    query = query.order_by(desc(PromptFeedback.created_at)).limit(limit)

    rows = query.all()
    return {
        "agent_id": agent_id,
        "source": "prompt_feedback",
        "count": len(rows),
        "feedback": [prompt_feedback_item(r) for r in rows],
    }


@router.get("/api/agents/feedback")
def api_prompt_feedback_list(
    agent_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """列出所有反馈记录，可选按 agent/status 过滤。"""
    from database.models.analysis import PromptFeedback

    query = db.query(PromptFeedback)
    if agent_id:
        query = query.filter(PromptFeedback.agent_id == agent_id)
    if status:
        query = query.filter(PromptFeedback.status == status)
    query = query.order_by(desc(PromptFeedback.created_at)).limit(limit)

    rows = query.all()
    return {
        "source": "prompt_feedback",
        "count": len(rows),
        "feedback": [prompt_feedback_item(r) for r in rows],
    }
