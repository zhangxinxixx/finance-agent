"""Operations overview routes extracted from the main FastAPI entrypoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends
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


@router.post("/api/scheduler/run-all-collectors")
def api_run_all_collectors():
    """手动触发全部数据采集器（异步）。采集结果写入 task_runs。"""
    from apps.api.services.collector_trigger import run_all_collectors_async

    return run_all_collectors_async()


@router.get("/api/dashboard/summary")
def api_dashboard_summary():
    """返回 Dashboard 聚合摘要。"""
    return get_dashboard_summary()
