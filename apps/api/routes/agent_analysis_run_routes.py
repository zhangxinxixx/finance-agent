"""Agent analysis run route extracted from the main FastAPI entrypoint."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.post("/api/agent-analysis/run")
def api_run_agent_analysis(
    agent: str = "all",
    date: str | None = None,
    force: bool = False,
):
    """Compatibility response for the retired untracked manual runner."""
    raise HTTPException(status_code=410, detail={
        "code": "manual_analysis_retired",
        "message": "旧手动分析入口已停用，请通过正式盘前流程创建可追溯的分析任务。",
        "preflight_url": "/api/tasks/premarket/preflight",
        "run_url": "/api/tasks/premarket",
    })
