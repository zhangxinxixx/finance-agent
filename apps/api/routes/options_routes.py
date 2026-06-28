"""Options routes extracted from the main FastAPI entrypoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.models.engine import get_db

router = APIRouter()


@router.get("/api/options/snapshot")
def api_options_snapshot(date: str | None = None, db: Session = Depends(get_db)):
    """返回 CME 期权分析 JSON snapshot。不传 date 则返回最新。"""
    from apps.api import main as api_main

    data = api_main.get_options_snapshot(date, db=db)
    if data is None:
        raise HTTPException(status_code=404, detail="Options snapshot not found")
    return data


@router.get("/api/options/report")
def api_options_report(date: str | None = None):
    """返回 CME 期权分析 Markdown 报告原文。"""
    from apps.api import main as api_main

    md = api_main.get_options_report_md(date)
    if md is None:
        raise HTTPException(status_code=404, detail="Options report not found")
    return {"content": md, "format": "markdown"}


@router.get("/api/options/dates")
def api_options_dates():
    """列出所有已生成报告的日期。"""
    from apps.api import main as api_main

    return {"dates": api_main.list_options_report_dates()}


@router.get("/api/options/visual-report/latest")
def api_options_visual_report_latest():
    """返回最新 CME visual report HTML。"""
    from apps.api import main as api_main

    data = api_main.get_options_visual_report_html()
    if data is None:
        raise HTTPException(status_code=404, detail="Options visual report not found")
    return data


@router.get("/api/options/visual-report")
def api_options_visual_report(date: str | None = None, run_id: str | None = None):
    """按日期/run_id 返回 CME visual report HTML。"""
    from apps.api import main as api_main

    data = api_main.get_options_visual_report_html(date, run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Options visual report not found")
    return data
