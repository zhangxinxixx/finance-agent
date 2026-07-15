"""Lifecycle-owned Jin10 cache refresh scheduler for the FastAPI process."""

from __future__ import annotations

import logging
import os
from functools import partial
from threading import Thread
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler

from apps.scheduler.jin10_refresh import (
    refresh_jin10_calendar_cache,
    refresh_jin10_flash_cache,
    refresh_jin10_kline_cache,
    refresh_jin10_quotes_cache,
    refresh_jin10_web_article_analysis,
    refresh_jin10_web_flash_briefs,
)
from apps.scheduler.task_wrapper import record_jin10_refresh
from apps.scheduler.twelvedata_refresh import refresh_due_twelvedata_xauusd

logger = logging.getLogger(__name__)

_REFRESH_JOBS_ENV = "FINANCE_AGENT_API_BACKGROUND_REFRESH_JOBS"
_TWELVEDATA_LEGACY_TASK_TYPES = {
    "twelvedata_xauusd_5m",
    "twelvedata_xauusd_15m",
    "twelvedata_xauusd_1h",
    "twelvedata_xauusd_4h",
}


def _configured_refresh_jobs() -> set[str] | None:
    raw = os.getenv(_REFRESH_JOBS_ENV, "").strip()
    if not raw or raw == "*":
        return None
    return {item.strip() for item in raw.split(",") if item.strip()}


def _job_is_enabled(task_type: str, configured_jobs: set[str] | None) -> bool:
    return configured_jobs is None or task_type in configured_jobs


def _twelvedata_dispatch_is_enabled(configured_jobs: set[str] | None) -> bool:
    return (
        configured_jobs is None
        or "twelvedata_xauusd_dispatch" in configured_jobs
        or bool(configured_jobs & _TWELVEDATA_LEGACY_TASK_TYPES)
    )

def _refresh_jobs() -> tuple[tuple[str, str, Any, int, str, str | None], ...]:
    return (
        ("jin10_quotes", "Jin10 行情刷新", refresh_jin10_quotes_cache, 15, "jin10_quotes_refresh", "startup-quotes"),
        ("jin10_kline", "Jin10 K线刷新", refresh_jin10_kline_cache, 1, "jin10_kline_refresh", "startup-kline"),
        ("jin10_calendar", "Jin10 财经日历刷新", refresh_jin10_calendar_cache, 60, "jin10_calendar_refresh", None),
        ("jin10_flash", "Jin10 快讯刷新", refresh_jin10_flash_cache, 15, "jin10_flash_refresh", "startup-flash"),
        ("jin10_web_flash", "Jin10 网页重点/VIP快讯刷新", refresh_jin10_web_flash_briefs, 5, "jin10_web_flash_refresh", "startup-web-flash"),
        (
            "jin10_web_article_analysis",
            "Jin10 网页图文详情分析",
            refresh_jin10_web_article_analysis,
            30,
            "jin10_web_article_analysis_refresh",
            "startup-web-article-analysis",
        ),
    )


def _twelvedata_jobs() -> tuple[tuple[str, str, str, dict[str, Any]], ...]:
    return (
        (
            "twelvedata_xauusd_dispatch",
            "Twelve Data XAUUSD 多周期串行校验",
            "twelvedata_xauusd_dispatch_refresh",
            {"minute": "1,6,11,16,21,26,31,36,41,46,51,56", "second": 30, "timezone": "UTC"},
        ),
    )


def start_jin10_cache_refresh_scheduler() -> BackgroundScheduler:
    """Register periodic refreshes and run the existing eager refreshes asynchronously."""
    scheduler = BackgroundScheduler(daemon=True)
    configured_jobs = _configured_refresh_jobs()
    scheduled_jobs = 0
    refresh_jobs = _refresh_jobs()
    for task_type, task_name, refresher, minutes, job_id, startup_thread_name in refresh_jobs:
        if not _job_is_enabled(task_type, configured_jobs):
            continue
        scheduler.add_job(
            partial(record_jin10_refresh, task_type, task_name, refresher),
            "interval",
            minutes=minutes,
            id=job_id,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=30,
        )
        scheduled_jobs += 1
        if startup_thread_name is not None:
            Thread(target=refresher, daemon=True, name=startup_thread_name).start()

    for task_type, task_name, job_id, cron_kwargs in _twelvedata_jobs():
        if not _twelvedata_dispatch_is_enabled(configured_jobs):
            continue
        scheduler.add_job(
            partial(record_jin10_refresh, task_type, task_name, refresh_due_twelvedata_xauusd),
            "cron",
            id=job_id,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=120,
            **cron_kwargs,
        )
        scheduled_jobs += 1

    scheduler.start()
    logger.info("Market cache refresh scheduler started: %s jobs", scheduled_jobs)
    return scheduler


def stop_jin10_cache_refresh_scheduler(scheduler: Any) -> None:
    """Stop the process-local scheduler without waiting for refresh work."""
    scheduler.shutdown(wait=False)
    logger.info("Jin10 cache refresh scheduler stopped")
