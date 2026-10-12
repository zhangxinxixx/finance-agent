"""Operations overview routes extracted from the main FastAPI entrypoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from apps.api.data_service import get_dashboard_summary, list_recent_tasks
from apps.api.services.scheduler_service import get_scheduler_overview
from database.models.engine import get_db

router = APIRouter()


@router.get("/api/tasks")
def api_tasks(limit: int = 20):
    """列出最近的任务。"""
    return {"tasks": list_recent_tasks(min(limit, 100))}


@router.get("/api/scheduler/overview")
def api_scheduler_overview(days: int = 7, limit: int = 50, db: Session = Depends(get_db)):
    """调度中心全景视图：任务运行、数据源状态、产出物。"""
    return get_scheduler_overview(db, days=min(days, 90), limit=min(limit, 200))


@router.post("/api/scheduler/run-all-collectors", deprecated=True, responses={410: {"description": "旧采集入口已停用"}})
def api_run_all_collectors():
    """旧线程采集入口的兼容响应；采集统一由正式任务流程执行。"""
    raise HTTPException(status_code=410, detail={
        "code": "manual_collection_retired",
        "message": "旧批量采集入口已停用，请通过正式盘前流程创建可追溯的采集任务。",
        "preflight_url": "/api/tasks/premarket/preflight",
        "run_url": "/api/tasks/premarket",
    })


@router.get("/api/dashboard/summary")
def api_dashboard_summary():
    """返回 Dashboard 聚合摘要。"""
    return get_dashboard_summary()
