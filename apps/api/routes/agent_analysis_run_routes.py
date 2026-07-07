"""Agent analysis run route extracted from the main FastAPI entrypoint."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from apps.api.services.agent_analysis_run_service import run_event_impact_async, run_market_regime_async

router = APIRouter()


@router.post("/api/agent-analysis/run")
def api_run_agent_analysis(
    agent: str = "all",
    date: str | None = None,
    force: bool = False,
):
    """手动触发 agent 分析。"""
    target_date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if agent in ("market_regime", "all"):
        run_market_regime_async(target_date)
    if agent in ("event_impact", "all"):
        run_event_impact_async(target_date)

    return {"status": "dispatched", "agent": agent, "date": target_date}
