"""Lifecycle-owned Jin10 cache refresh scheduler for the FastAPI process."""

from __future__ import annotations

import logging
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
    refresh_market_candle_daily_cache,
)
from apps.scheduler.task_wrapper import record_jin10_refresh

logger = logging.getLogger(__name__)

def _refresh_jobs() -> tuple[tuple[str, str, Any, int, str, str | None], ...]:
    return (
        ("jin10_quotes", "Jin10 行情刷新", refresh_jin10_quotes_cache, 15, "jin10_quotes_refresh", "startup-quotes"),
        ("jin10_kline", "Jin10 K线刷新", refresh_jin10_kline_cache, 1, "jin10_kline_refresh", "startup-kline"),
        (
            "market_candles_daily",
            "市场日线补缺刷新",
            refresh_market_candle_daily_cache,
            60,
            "market_candles_daily_refresh",
            "startup-market-candles",
        ),
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


def start_jin10_cache_refresh_scheduler() -> BackgroundScheduler:
    """Register periodic refreshes and run the existing eager refreshes asynchronously."""
    scheduler = BackgroundScheduler(daemon=True)
    refresh_jobs = _refresh_jobs()
    for task_type, task_name, refresher, minutes, job_id, startup_thread_name in refresh_jobs:
        scheduler.add_job(
            partial(record_jin10_refresh, task_type, task_name, refresher),
            "interval",
            minutes=minutes,
            id=job_id,
            replace_existing=True,
        )
        if startup_thread_name is not None:
            Thread(target=refresher, daemon=True, name=startup_thread_name).start()

    scheduler.start()
    logger.info("Jin10 cache refresh scheduler started: %s jobs", len(refresh_jobs))
    return scheduler


def stop_jin10_cache_refresh_scheduler(scheduler: Any) -> None:
    """Stop the process-local scheduler without waiting for refresh work."""
    scheduler.shutdown(wait=False)
    logger.info("Jin10 cache refresh scheduler stopped")
