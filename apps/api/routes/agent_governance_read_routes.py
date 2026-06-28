"""Agent governance read routes extracted from the main FastAPI entrypoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc
from sqlalchemy.orm import Session

from database.models.engine import get_db

router = APIRouter()


@router.get("/api/agents/registry")
def api_agents_registry():
    """返回 Agent 注册表与可审查 Prompt 模板。"""
    from apps.analysis.agents.registry import build_agent_registry_response

    return build_agent_registry_response()


@router.get("/api/agents/registry/{agent_id}")
def api_agent_registry_detail(agent_id: str):
    """返回单个 Agent 的注册信息与 Prompt 模板。"""
    from apps.analysis.agents.registry import get_agent_registry

    agent = get_agent_registry(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent registry entry not found: {agent_id}")
    return agent


@router.get("/api/agents/prompts")
def api_prompt_versions_list(agent_id: str | None = None, status: str | None = None, db: Session = Depends(get_db)):
    """列出 prompt 版本记录。"""
    from apps.api import main as api_main
    from database.models.analysis import PromptVersion

    query = db.query(PromptVersion).order_by(desc(PromptVersion.created_at))
    if agent_id:
        query = query.filter(PromptVersion.agent_id == agent_id)
    if status:
        query = query.filter(PromptVersion.status == status)

    rows = query.all()
    return {
        "source": "prompt_versions",
        "count": len(rows),
        "versions": [api_main._prompt_version_item(r) for r in rows],
    }


@router.get("/api/agents/prompts/{agent_id}")
def api_prompt_versions_by_agent(agent_id: str, db: Session = Depends(get_db)):
    """返回某个 Agent 的所有 prompt 版本记录。"""
    from apps.api import main as api_main
    from database.models.analysis import PromptVersion

    rows = (
        db.query(PromptVersion)
        .filter(PromptVersion.agent_id == agent_id)
        .order_by(desc(PromptVersion.created_at))
        .all()
    )
    if not rows:
        from apps.analysis.agents.registry import get_agent_registry

        agent = get_agent_registry(agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
        return {
            "agent_id": agent_id,
            "name": agent["name"],
            "source": "prompt_versions",
            "count": 0,
            "versions": [],
            "note": "尚无持久化 prompt 版本，将在首次运行后自动落库。",
        }

    return {
        "agent_id": agent_id,
        "name": rows[0].agent_id,
        "source": "prompt_versions",
        "count": len(rows),
        "versions": [api_main._prompt_version_item(r) for r in rows],
    }


@router.get("/api/agents/prompts/{agent_id}/active")
def api_prompt_versions_active(agent_id: str, db: Session = Depends(get_db)):
    """返回某个 Agent 当前激活的 prompt 版本。"""
    from apps.api import main as api_main
    from database.models.analysis import PromptVersion

    row = (
        db.query(PromptVersion)
        .filter(PromptVersion.agent_id == agent_id, PromptVersion.status == "active", PromptVersion.enabled.is_(True))
        .order_by(desc(PromptVersion.created_at))
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"No active prompt version for agent: {agent_id}")
    return api_main._prompt_version_item(row)
