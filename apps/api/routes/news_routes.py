"""News read-model routes extracted from the main FastAPI entrypoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from apps.api.services.daily_analysis_followup_service import (
    get_daily_analysis_followups,
    get_daily_analysis_followups_latest,
)
from apps.api.services.daily_analysis_followup_task_service import (
    DailyAnalysisFollowupDispatchError,
    create_daily_analysis_followup_tasks,
    dispatch_daily_analysis_followup_tasks,
)
from apps.api.services.daily_analysis_trigger_service import (
    get_daily_analysis_triggers,
    get_daily_analysis_triggers_latest,
)
from apps.api.services.daily_brief_service import get_daily_brief, get_daily_brief_latest
from apps.api.services.page_news_read_model_service import (
    get_page_news_monitor,
    get_page_news_monitor_latest,
    list_page_news_dates,
)
from database.models.engine import get_db

router = APIRouter()

# Compatibility names retained for route-level tests and direct imports. They
# now resolve to the DWS/ADS feature-backed readers, never the parsed-message
# monitor that previously occupied these names.
get_feishu_jin10_message_monitor = get_page_news_monitor
get_feishu_jin10_message_monitor_latest = get_page_news_monitor_latest
list_feishu_jin10_message_monitor_dates = list_page_news_dates


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
    """创建并派发本次明确选中的 follow-up task_ids 到 Dagster。"""
    if (date is not None or run_id is not None) and (not (date or "").strip() or not (run_id or "").strip()):
        raise HTTPException(status_code=422, detail="date and run_id must both be supplied, or both omitted")
    data = create_daily_analysis_followup_tasks(db, date=date, run_id=run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Daily analysis followups not found")

    task_ids = list(
        dict.fromkeys(
            [
                *data.get("created_run_ids", []),
                *data.get("existing_run_ids", []),
            ]
        )
    )
    try:
        dispatch = dispatch_daily_analysis_followup_tasks(task_ids)
    except DailyAnalysisFollowupDispatchError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail(task_ids=task_ids)) from exc
    data.update(dispatch)
    return data


@router.get("/api/news/feishu-jin10/messages/latest")
def api_feishu_jin10_message_monitor_latest():
    """返回最近一个已生成 news feature 的金十消息 ADS 监控视图。"""
    data = get_feishu_jin10_message_monitor_latest()
    if data is None:
        raise HTTPException(status_code=404, detail="Feishu Jin10 latest messages not found")
    return data


@router.get("/api/news/feishu-jin10/dates")
def api_feishu_jin10_message_monitor_dates():
    """返回有金十 news feature 的日期列表。"""
    return {"dates": list_feishu_jin10_message_monitor_dates()}


@router.get("/api/news/feishu-jin10/messages")
def api_feishu_jin10_message_monitor(date: str):
    """返回指定日期由 news feature 形成的 ADS 状态清单。"""
    return get_feishu_jin10_message_monitor(date=date)
