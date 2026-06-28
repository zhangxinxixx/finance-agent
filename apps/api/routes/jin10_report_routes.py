"""Jin10 report routes extracted from the main FastAPI entrypoint."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()


@router.get("/api/jin10/daily-report/latest")
def api_jin10_daily_report_latest():
    """返回最新的 Jin10 黄金每日报告。"""
    from apps.api import main as api_main

    data = api_main.get_jin10_daily_report_latest()
    if data is None:
        raise HTTPException(status_code=404, detail="Jin10 daily report not found")
    return data


@router.get("/api/jin10/daily-report")
def api_jin10_daily_report(date: str, run_id: str):
    """按日期和 run_id 返回 Jin10 黄金每日报告。"""
    from apps.api import main as api_main

    data = api_main.get_jin10_daily_report(date=date, run_id=run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Jin10 daily report not found")
    return data


@router.get("/api/jin10/weekly-report/latest")
def api_jin10_weekly_report_latest():
    """返回最新的 Jin10 黄金周报。"""
    from apps.api import main as api_main

    data = api_main.get_jin10_weekly_report_latest()
    if data is None:
        raise HTTPException(status_code=404, detail="Jin10 weekly report not found")
    return data


@router.get("/api/jin10/weekly-report")
def api_jin10_weekly_report(date: str, run_id: str):
    """按日期和 run_id 返回 Jin10 黄金周报。"""
    from apps.api import main as api_main

    data = api_main.get_jin10_weekly_report(date=date, run_id=run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Jin10 weekly report not found")
    return data


@router.get("/api/jin10/report-bundle/latest")
def api_jin10_report_bundle_latest():
    """返回最新的 Jin10 报告 bundle，默认优先 Agent 分析。"""
    from apps.api import main as api_main

    data = api_main.get_jin10_report_bundle_latest()
    if data is None:
        raise HTTPException(status_code=404, detail="Jin10 report bundle not found")
    return data


@router.get("/api/jin10/report-bundle")
def api_jin10_report_bundle(date: str, run_id: str):
    """按日期和 run_id 返回 Jin10 报告 bundle。"""
    from apps.api import main as api_main

    data = api_main.get_jin10_report_bundle(date=date, run_id=run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Jin10 report bundle not found")
    return data


@router.get("/api/jin10/report-bundle/{date}/{run_id}/asset/{asset_path:path}")
def api_jin10_report_bundle_asset(date: str, run_id: str, asset_path: str):
    """返回 Jin10 bundle 下的相对资源文件（图表、图片等）。"""
    from apps.api import main as api_main

    path = api_main.get_jin10_report_bundle_asset_path(date=date, run_id=run_id, asset_path=asset_path)
    if path is None:
        raise HTTPException(status_code=404, detail="Jin10 report asset not found")
    return FileResponse(path)


@router.get("/api/jin10/article-briefs/latest")
def api_jin10_article_briefs_latest():
    """返回最新的 Jin10 文章小快讯 read model。"""
    from apps.api import main as api_main

    data = api_main.get_jin10_article_briefs_latest()
    if data is None:
        raise HTTPException(status_code=404, detail="Jin10 article briefs not found")
    return data


@router.get("/api/jin10/article-briefs")
def api_jin10_article_briefs(date: str, run_id: str):
    """按日期和 run_id 返回 Jin10 文章小快讯 read model。"""
    from apps.api import main as api_main

    data = api_main.get_jin10_article_briefs(date=date, run_id=run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Jin10 article briefs not found")
    return data
