"""Macro routes extracted from the main FastAPI entrypoint."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/api/macro/latest")
def api_macro_latest():
    """返回最新宏观指标 JSON snapshot。"""
    from apps.api import main as api_main

    data = api_main.get_macro_latest()
    if data is None:
        raise HTTPException(status_code=404, detail="Macro snapshot not found")
    return data


@router.get("/api/macro/report")
def api_macro_report(date: str | None = None):
    """返回宏观指标 Markdown 报告。"""
    from apps.api import main as api_main

    md = api_main.get_macro_report_md(date)
    if md is None:
        raise HTTPException(status_code=404, detail="Macro report not found")
    return {"content": md, "format": "markdown"}
