"""News read-model routes extracted from the main FastAPI entrypoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from apps.api.services.daily_analysis_followup_service import get_daily_analysis_followups, get_daily_analysis_followups_latest
from apps.api.services.daily_analysis_followup_task_service import create_daily_analysis_followup_tasks
from apps.api.services.daily_analysis_trigger_service import get_daily_analysis_triggers, get_daily_analysis_triggers_latest
from apps.api.services.daily_brief_service import get_daily_brief, get_daily_brief_latest
from apps.api.services.feishu_jin10_message_monitor_service import get_feishu_jin10_message_monitor, get_feishu_jin10_message_monitor_latest, list_feishu_jin10_message_monitor_dates
from database.models.engine import get_db

router = APIRouter()


@router.get("/api/news/daily-analysis-triggers/latest")
def api_daily_analysis_triggers_latest():
    """返回最新的 daily analysis triggers read model。"""
    data = get_daily_analysis_triggers_latest()
    if data is None:
        raise HTTPException(status_code=404, detail="Daily analysis triggers not found")
    return data


@router.get("/api/news/daily-analysis-triggers")
def api_daily_analysis_triggers(date: str, run_id: str):
    """按日期和 run_id 返回 daily analysis triggers read model。"""
    data = get_daily_analysis_triggers(date=date, run_id=run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Daily analysis triggers not found")
    return data


@router.get("/api/news/daily-brief/latest")
def api_daily_brief_latest():
    """返回最新的稳定日报 read model。"""
    data = get_daily_brief_latest()
    if data is None:
        raise HTTPException(status_code=404, detail="Daily brief not found")
    return data


@router.get("/api/news/daily-brief")
def api_daily_brief(date: str, run_id: str):
    """按日期和 run_id 返回稳定日报 read model。"""
    data = get_daily_brief(date=date, run_id=run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Daily brief not found")
    return data


@router.get("/api/news/daily-analysis-followups/latest")
def api_daily_analysis_followups_latest():
    """返回最新的 daily analysis follow-up queue read model。"""
    data = get_daily_analysis_followups_latest()
    if data is None:
        raise HTTPException(status_code=404, detail="Daily analysis followups not found")
    return data


@router.get("/api/news/daily-analysis-followups")
def api_daily_analysis_followups(date: str, run_id: str):
    """按日期和 run_id 返回 daily analysis follow-up queue read model。"""
    data = get_daily_analysis_followups(date=date, run_id=run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Daily analysis followups not found")
    return data


@router.post("/api/news/daily-analysis-followups/tasks")
def api_create_daily_analysis_followup_tasks(
    date: str | None = None,
    run_id: str | None = None,
    db: Session = Depends(get_db),
):
    """把 daily analysis follow-up queue 映射为 pending task rows。"""
    data = create_daily_analysis_followup_tasks(db, date=date, run_id=run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Daily analysis followups not found")
    return data


@router.get("/api/news/feishu-jin10/messages/latest")
def api_feishu_jin10_message_monitor_latest(db: Session = Depends(get_db)):
    """返回最近一个有 Feishu 金十消息 parsed artifact 的日期监控视图。"""
    data = get_feishu_jin10_message_monitor_latest(db=db)
    if data is None:
        raise HTTPException(status_code=404, detail="Feishu Jin10 latest messages not found")
    return data


@router.get("/api/news/feishu-jin10/dates")
def api_feishu_jin10_message_monitor_dates():
    """返回有 Feishu 金十消息 parsed artifact 的日期列表。"""
    return {"dates": list_feishu_jin10_message_monitor_dates()}


@router.get("/api/news/feishu-jin10/messages")
def api_feishu_jin10_message_monitor(date: str, db: Session = Depends(get_db)):
    """返回指定日期的 Feishu 金十消息采集与后续纳入状态清单。"""
    return get_feishu_jin10_message_monitor(date=date, db=db)
