"""FastAPI 入口。"""
from __future__ import annotations

import json
import logging
import os
import socket
import sys
import time
import tomllib
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from apps.api.schemas.agent import (
    PromptVersionCreate,
)
from apps.analysis.memory import build_codex_memory_context
from apps.premarket import PREMARKET_STEP_ORDER, sort_premarket_steps
from apps.api.data_service import (
    get_dashboard_summary,
    get_data_source_statuses,
    get_final_report,
    get_final_report_latest,
    get_jin10_daily_report,
    get_jin10_daily_report_latest,
    get_jin10_report_bundle,
    get_jin10_report_bundle_asset_path,
    get_jin10_report_bundle_latest,
    get_jin10_weekly_report,
    get_jin10_weekly_report_latest,
    get_macro_latest,
    get_macro_report_md,
    get_market_odds_snapshot,
    get_market_odds_report,
    get_market_monitor_overview,
    get_market_monitor_history,
    get_market_tickers,
    get_options_report_md,
    get_options_snapshot,
    get_options_visual_report_html,
    get_strategy_card,
    get_strategy_card_by_id,
    get_strategy_card_latest,
    get_strategy_card_read_model_latest,
    list_options_report_dates,
    list_recent_tasks,
    list_reports_index,
    list_strategy_assets,
    list_strategy_cards,
    list_unified_dates,
)
from apps.api.services import (
    event_flow_action_service,
    ingestion_action_service,
    ingestion_source_test_service,
    pipeline_contract_service,
    playbook_service,
    settings_service,
)
from apps.api.services.jin10_article_brief_service import (
    get_jin10_article_briefs,
    get_jin10_article_briefs_latest,
)
from apps.api.services.daily_analysis_trigger_service import (
    get_daily_analysis_triggers,
    get_daily_analysis_triggers_latest,
)
from apps.api.services.daily_brief_service import (
    get_daily_brief,
    get_daily_brief_latest,
)
from apps.api.services.daily_analysis_followup_service import (
    get_daily_analysis_followups,
    get_daily_analysis_followups_latest,
)
from apps.api.services.daily_analysis_followup_task_service import create_daily_analysis_followup_tasks
from apps.api.services.feishu_jin10_message_monitor_service import (
    get_feishu_jin10_message_monitor,
    get_feishu_jin10_message_monitor_latest,
    list_feishu_jin10_message_monitor_dates,
)
from apps.api.services.gold_mainline_service import (
    get_gold_mainlines,
    get_gold_mainlines_latest,
)
from apps.api.routes import data_source_routes
from apps.api.routes import (
    agent_analysis_read_routes,
    agent_analysis_run_routes,
    agent_governance_read_routes,
    agent_governance_write_routes,
    event_flow_routes,
    execution_read_routes,
    frontend_compat_routes,
    gold_mainline_routes,
    health_routes,
    jin10_market_routes,
    jin10_report_routes,
    knowledge_routes,
    macro_routes,
    market_monitor_routes,
    market_odds_routes,
    news_routes,
    operations_routes,
    options_routes,
    premarket_routes,
    playbook_routes,
    reports_routes,
    review_routes,
    settings_read_routes,
    settings_write_routes,
    source_trace_routes,
    strategy_report_routes,
    system_status_routes,
)
from apps.api.services.source_service import (
    get_data_source_health_latest,
    get_data_source_history,
    get_data_sources_registry,
    get_data_status_summary,
)
from apps.api.services.report_service import (
    get_report_analysis_inputs,
    get_report_analysis,
    get_report_artifact_asset_path,
    get_report_artifacts,
    get_report_detail,
    get_report_evidence,
    get_report_source,
    get_report_visual,
)
from apps.api.services.agent_output_service import build_agent_output_summary
from apps.api.services._trace_refs import parse_source_refs
from apps.api.services.scheduler_service import get_scheduler_overview
from apps.runtime.state_machine import (
    ACTIVE_DAGSTER_RUN_STATUSES,
    map_dagster_status_to_task_status,
    transition_task_run,
)
from database.models.engine import SessionLocal
from database.migrations.runtime import run_database_migrations
from database.models.task import TaskRun, TaskStatus, TaskStep

_should_skip_background_jobs_ref = None  # set by lifespan

logger = logging.getLogger(__name__)

_JIN10_FLASH_CACHE_PATH = Path("./storage/outputs/jin10/flash_cache.json")
_JIN10_FLASH_CACHE_MAX_AGE_SECONDS = 60
_JIN10_CALENDAR_CACHE_PATH = Path("./storage/outputs/jin10/calendar_cache.json")
_JIN10_CALENDAR_CACHE_MAX_AGE_SECONDS = 18 * 60 * 60
_JIN10_CALENDAR_PAST_WINDOW_DAYS = 7
_JIN10_CALENDAR_FUTURE_WINDOW_DAYS = 14
_PREMARKET_ACTIVE_TASK_STALE_AFTER = timedelta(
    hours=int(os.getenv("PREMARKET_ACTIVE_TASK_STALE_AFTER_HOURS", "6"))
)


def _run_premarket_scheduled() -> None:
    """Dagster handles premarket scheduling via premarket_daily_schedule.
    This function is kept as a no-op stub for backward compatibility."""
    logger.info("Premarket scheduling is now handled by Dagster. This callback is a no-op.")


def _should_skip_background_jobs() -> bool:
    """Keep FastAPI startup deterministic in pytest and explicitly disabled envs."""
    if os.getenv("FINANCE_AGENT_DISABLE_BACKGROUND_JOBS") == "1":
        return True
    if os.getenv("PYTEST_CURRENT_TEST"):
        return True
    return "pytest" in sys.modules


def _normalize_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _premarket_active_task_ref_time(task: TaskRun) -> datetime | None:
    return _normalize_utc(task.updated_at or task.started_at or task.created_at)


def _cleanup_stale_active_premarket_tasks(db: Session, *, now: datetime | None = None) -> TaskRun | None:
    """Return the newest still-active premarket task, marking stale legacy rows along the way."""
    current_time = _normalize_utc(now) or datetime.now(timezone.utc)
    active_task, stale_tasks = _classify_premarket_active_legacy_tasks(db, now=current_time)

    for task in stale_tasks:
        transition_task_run(
            db,
            task,
            TaskStatus.stale,
            source="api",
            reason=f"active_timeout_exceeded:{_PREMARKET_ACTIVE_TASK_STALE_AFTER}",
            error_message=task.error or "Legacy premarket task timed out before Dagster migration verification.",
        )

    if stale_tasks:
        db.commit()
    return active_task


def _classify_premarket_active_legacy_tasks(
    db: Session,
    *,
    now: datetime | None = None,
) -> tuple[TaskRun | None, list[TaskRun]]:
    """Return the newest active legacy premarket task plus stale rows, without mutating state."""
    current_time = _normalize_utc(now) or datetime.now(timezone.utc)
    active_runs = (
        db.query(TaskRun)
        .filter(
            TaskRun.name == "premarket",
            TaskRun.status.in_([TaskStatus.pending, TaskStatus.running]),
        )
        .order_by(desc(TaskRun.updated_at), desc(TaskRun.created_at))
        .all()
    )

    stale_runs: list[TaskRun] = []
    for task in active_runs:
        ref_time = _premarket_active_task_ref_time(task)
        if ref_time is not None and current_time - ref_time > _PREMARKET_ACTIVE_TASK_STALE_AFTER:
            stale_runs.append(task)
            continue
        return task, stale_runs

    return None, stale_runs


def _task_to_premarket_active_task_ref(task: TaskRun) -> PremarketActiveTaskRef:
    return PremarketActiveTaskRef(
        task_id=str(task.id),
        status=task.status.value,
        updated_at=_premarket_active_task_ref_time(task),
    )


def _source_readiness_block_count(source_readiness_summary: dict[str, Any] | None) -> int:
    if not isinstance(source_readiness_summary, dict):
        return 0
    decision_counts = source_readiness_summary.get("decision_counts")
    if not isinstance(decision_counts, dict):
        return 0
    try:
        return max(int(decision_counts.get("blocked", 0) or 0), 0)
    except (TypeError, ValueError):
        return 0


def _source_readiness_block_message(source_readiness_summary: dict[str, Any] | None) -> str:
    blocked_sources = source_readiness_summary.get("blocked_sources") if isinstance(source_readiness_summary, dict) else None
    if isinstance(blocked_sources, list) and blocked_sources:
        return f"Source readiness blocked premarket launch: {', '.join(str(source) for source in blocked_sources)}"
    return "Source readiness blocked premarket launch"


def _build_premarket_launch_preflight(force: bool = False) -> PremarketLaunchPreflightResponse:
    readiness = pipeline_contract_service.build_premarket_pipeline_source_readiness()
    source_readiness_summary = readiness.get("source_readiness_summary")
    source_readiness_blocked = _source_readiness_block_count(source_readiness_summary) > 0

    with SessionLocal() as session:
        active_legacy_task, stale_legacy_tasks = _classify_premarket_active_legacy_tasks(session)

    dagster_url = os.getenv("DAGSTER_GRAPHQL_URL", "http://127.0.0.1:3333/graphql")
    dagster_check_error: str | None = None
    active_dagster_run: dict[str, str] | None = None
    try:
        active_dagster_run = _find_active_dagster_premarket_run(dagster_url)
    except Exception as exc:
        dagster_check_error = str(exc)

    blocking_reasons: list[str] = []
    if active_legacy_task is not None:
        blocking_reasons.append("legacy_active_task")
    if active_dagster_run is not None:
        blocking_reasons.append("dagster_active_run")
    if source_readiness_blocked:
        blocking_reasons.append("source_readiness_blocked")

    return PremarketLaunchPreflightResponse(
        force=force,
        can_launch=(force or not blocking_reasons) and not source_readiness_blocked,
        blocking_reasons=blocking_reasons,
        stale_legacy_task_ids=[str(task.id) for task in stale_legacy_tasks],
        active_legacy_task=(
            None if active_legacy_task is None else _task_to_premarket_active_task_ref(active_legacy_task)
        ),
        active_dagster_run=(
            None
            if active_dagster_run is None
            else PremarketDagsterRunRef(
                run_id=active_dagster_run["run_id"],
                status=active_dagster_run["status"],
            )
        ),
        dagster_check_error=dagster_check_error,
        source_readiness_summary=source_readiness_summary,
    )


def _premarket_launch_error_detail(
    *,
    message: str,
    reason: str,
    force: bool,
    source_readiness_summary: dict[str, Any] | None = None,
    active_legacy_task: PremarketActiveTaskRef | None = None,
    active_dagster_run: PremarketDagsterRunRef | None = None,
    dagster_check_error: str | None = None,
) -> dict[str, Any]:
    return {
        "message": message,
        "reason": reason,
        "force": force,
        "blocking_reasons": [
            reason
        ]
        if reason.startswith("dagster_") or reason.startswith("legacy_") or reason == "source_readiness_blocked"
        else [],
        "active_legacy_task": None if active_legacy_task is None else active_legacy_task.model_dump(mode="json"),
        "active_dagster_run": None if active_dagster_run is None else active_dagster_run.model_dump(mode="json"),
        "dagster_check_error": dagster_check_error,
        "source_readiness_summary": source_readiness_summary,
    }


def _find_active_dagster_premarket_run(dagster_url: str) -> dict[str, str] | None:
    import httpx

    query = """
        query ActivePremarketRuns($jobName: String!, $limit: Int!) {
            runsOrError(filter: { pipelineName: $jobName }, limit: $limit) {
                ... on Runs {
                    results {
                        runId
                        status
                    }
                }
            }
        }
    """
    resp = httpx.post(
        dagster_url,
        json={"query": query, "variables": {"jobName": "premarket_job", "limit": 10}},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    runs = data.get("data", {}).get("runsOrError", {}).get("results", [])
    for run in runs:
        status = str(run.get("status") or "").upper()
        if status in ACTIVE_DAGSTER_RUN_STATUSES:
            return {"run_id": str(run.get("runId")), "status": status}
    return None


def _dagster_status_to_task_status(status: str | None) -> str:
    return map_dagster_status_to_task_status(status)


def _timestamp_to_utc(value: float | int | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _get_dagster_task_view(task_id: str, dagster_url: str) -> TaskOut | None:
    import httpx

    query = """
        query RunTaskView($runId: ID!) {
            runOrError(runId: $runId) {
                __typename
                ... on Run {
                    runId
                    status
                    startTime
                    endTime
                    stepStats {
                        stepKey
                        status
                        startTime
                        endTime
                    }
                }
            }
        }
    """
    resp = httpx.post(
        dagster_url,
        json={"query": query, "variables": {"runId": task_id}},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    run = data.get("data", {}).get("runOrError", {})
    if run.get("__typename") != "Run":
        return None

    created_at = _timestamp_to_utc(run.get("startTime")) or datetime.now(timezone.utc)
    updated_at = _timestamp_to_utc(run.get("endTime")) or datetime.now(timezone.utc)

    steps: list[StepOut] = []
    for index, step in enumerate(run.get("stepStats") or []):
        step_key = str(step.get("stepKey") or f"step_{index}")
        step_started_at = _timestamp_to_utc(step.get("startTime"))
        step_finished_at = _timestamp_to_utc(step.get("endTime"))
        steps.append(
            StepOut(
                id=step_key,
                name=step_key.rsplit(".", 1)[-1],
                status=_dagster_status_to_task_status(step.get("status")),
                started_at=step_started_at,
                finished_at=step_finished_at,
                step_order=index,
            )
        )

    return TaskOut(
        id=str(run.get("runId") or task_id),
        name="premarket",
        status=_dagster_status_to_task_status(run.get("status")),
        trade_date=None,
        created_at=created_at,
        updated_at=updated_at,
        steps=steps,
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Startup / shutdown lifecycle — replaces deprecated on_event handlers."""
    global _should_skip_background_jobs_ref

    # ── Startup ──
    from database.models.engine import SessionLocal

    if _database_reachable():
        try:
            bind = SessionLocal.kw.get("bind")
            database_url = None
            if bind is not None:
                database_url = bind.url.render_as_string(hide_password=False)
            run_database_migrations(database_url)
        except Exception:
            logger.exception("Startup Alembic migration failed")

        # 初始化所有已知数据源状态到 data_source_status 表（供调度中心/数据接入消费）
        try:
            from apps.api.services.ds_status_init import init_data_source_status
            init_data_source_status()
        except Exception:
            logger.exception("Failed to init data source status records")

    if not _should_skip_background_jobs():
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apps.scheduler.jin10_refresh import (
                refresh_jin10_kline_cache,
                refresh_jin10_quotes_cache,
                refresh_jin10_calendar_cache,
                refresh_jin10_flash_cache,
            )

            def _recorded_jin10_quotes():
                from apps.scheduler.task_wrapper import record_jin10_refresh
                record_jin10_refresh("jin10_quotes", "Jin10 行情刷新", refresh_jin10_quotes_cache)

            def _recorded_jin10_kline():
                from apps.scheduler.task_wrapper import record_jin10_refresh
                record_jin10_refresh("jin10_kline", "Jin10 K线刷新", refresh_jin10_kline_cache)

            def _recorded_jin10_calendar():
                from apps.scheduler.task_wrapper import record_jin10_refresh
                record_jin10_refresh("jin10_calendar", "Jin10 财经日历刷新", refresh_jin10_calendar_cache)

            def _recorded_jin10_flash():
                from apps.scheduler.task_wrapper import record_jin10_refresh
                record_jin10_refresh("jin10_flash", "Jin10 快讯刷新", refresh_jin10_flash_cache)

            scheduler = BackgroundScheduler(daemon=True)
            scheduler.add_job(
                _recorded_jin10_quotes,
                "interval",
                minutes=15,
                id="jin10_quotes_refresh",
                replace_existing=True,
            )
            scheduler.add_job(
                _recorded_jin10_kline,
                "interval",
                minutes=1,
                id="jin10_kline_refresh",
                replace_existing=True,
            )
            scheduler.add_job(
                _recorded_jin10_calendar,
                "interval",
                minutes=60,
                id="jin10_calendar_refresh",
                replace_existing=True,
            )
            scheduler.add_job(
                _recorded_jin10_flash,
                "interval",
                minutes=15,
                id="jin10_flash_refresh",
                replace_existing=True,
            )
            scheduler.start()
            # 首次刷新移到后台线程，避免阻塞 API 启动
            import threading as _threading
            _threading.Thread(target=refresh_jin10_quotes_cache, daemon=True, name="startup-quotes").start()
            _threading.Thread(target=refresh_jin10_kline_cache, daemon=True, name="startup-kline").start()
            _threading.Thread(target=refresh_jin10_flash_cache, daemon=True, name="startup-flash").start()
            logger.info("Jin10 quotes refresh scheduler started (interval=15min)")
            logger.info("Jin10 kline refresh scheduler started (interval=1min)")
            logger.info("Jin10 flash refresh scheduler started (interval=15min)")
            logger.info("Premarket scheduling handled by Dagster (premarket_daily)")
            _app.state.jin10_scheduler = scheduler
        except Exception:
            logger.exception("Failed to start Jin10 quotes refresh scheduler")

    yield

    # ── Shutdown ──
    sched = getattr(_app.state, "jin10_scheduler", None)
    if sched is not None:
        sched.shutdown(wait=False)
        logger.info("Jin10 quotes refresh scheduler stopped")


app = FastAPI(title="finance-agent", version="0.1.0", lifespan=lifespan)
app.include_router(health_routes.router)
app.include_router(execution_read_routes.router)
app.include_router(data_source_routes.router)
app.include_router(review_routes.router)
app.include_router(source_trace_routes.router)
app.include_router(strategy_report_routes.router)
app.include_router(market_monitor_routes.router)
app.include_router(reports_routes.router)
app.include_router(market_odds_routes.router)
app.include_router(operations_routes.router)
app.include_router(macro_routes.router)
app.include_router(options_routes.router)
app.include_router(event_flow_routes.router)
app.include_router(playbook_routes.router)
app.include_router(knowledge_routes.router)
app.include_router(settings_read_routes.router)
app.include_router(settings_write_routes.router)
app.include_router(jin10_report_routes.router)
app.include_router(news_routes.router)
app.include_router(gold_mainline_routes.router)
app.include_router(jin10_market_routes.router)
app.include_router(premarket_routes.router)
app.include_router(agent_governance_read_routes.router)
app.include_router(agent_governance_write_routes.router)
app.include_router(frontend_compat_routes.router)
app.include_router(system_status_routes.router)
app.include_router(agent_analysis_read_routes.router)
app.include_router(agent_analysis_run_routes.router)

# Re-export modularized handlers so existing direct-import tests and local tools stay compatible.
api_runs = execution_read_routes.api_runs
api_run_detail = execution_read_routes.api_run_detail
api_run_steps = execution_read_routes.api_run_steps
api_run_logs = execution_read_routes.api_run_logs
api_run_artifacts = execution_read_routes.api_run_artifacts
api_artifact_detail = execution_read_routes.api_artifact_detail
api_run_events = execution_read_routes.api_run_events
api_source_trace_by_report = source_trace_routes.api_source_trace_by_report
api_source_trace_by_strategy = source_trace_routes.api_source_trace_by_strategy
api_source_trace_by_artifact = source_trace_routes.api_source_trace_by_artifact
api_source_trace_detail = source_trace_routes.api_source_trace_detail
api_data_sources_status = data_source_routes.api_data_sources_status
api_data_sources_registry = data_source_routes.api_data_sources_registry
api_data_status_summary = data_source_routes.api_data_status_summary
api_data_source_health_latest = data_source_routes.api_data_source_health_latest
api_data_source_health = data_source_routes.api_data_source_health
api_data_source_history = data_source_routes.api_data_source_history
api_ingestion_source_retry = data_source_routes.api_ingestion_source_retry
api_ingestion_source_test = data_source_routes.api_ingestion_source_test
api_ingestion_manual_upload = data_source_routes.api_ingestion_manual_upload
api_reviews = review_routes.api_reviews
api_review_detail = review_routes.api_review_detail
api_review_approve = review_routes.api_review_approve
api_review_reject = review_routes.api_review_reject
api_review_rerun = review_routes.api_review_rerun
api_review_use_fallback = review_routes.api_review_use_fallback
api_final_report_latest = strategy_report_routes.api_final_report_latest
api_final_report = strategy_report_routes.api_final_report
api_strategy_card_latest = strategy_report_routes.api_strategy_card_latest
api_strategy_card = strategy_report_routes.api_strategy_card
api_strategy_cards = strategy_report_routes.api_strategy_cards
api_strategy_card_assets = strategy_report_routes.api_strategy_card_assets
api_strategy_cards_latest = strategy_report_routes.api_strategy_cards_latest
api_strategy_card_detail = strategy_report_routes.api_strategy_card_detail
api_market_tickers = market_monitor_routes.api_market_tickers
api_market_monitor = market_monitor_routes.api_market_monitor
api_market_monitor_history = market_monitor_routes.api_market_monitor_history
api_reports_index = reports_routes.api_reports_index
api_reports_dates = reports_routes.api_reports_dates
api_report_detail = reports_routes.api_report_detail
api_report_artifacts = reports_routes.api_report_artifacts
api_report_source = reports_routes.api_report_source
api_report_analysis = reports_routes.api_report_analysis
api_report_artifact_asset = reports_routes.api_report_artifact_asset
api_report_visual = reports_routes.api_report_visual
api_report_evidence = reports_routes.api_report_evidence
api_report_analysis_inputs = reports_routes.api_report_analysis_inputs
api_market_odds_snapshot = market_odds_routes.api_market_odds_snapshot
api_market_odds_report = market_odds_routes.api_market_odds_report
api_tasks = operations_routes.api_tasks
api_scheduler_overview = operations_routes.api_scheduler_overview
api_run_all_collectors = operations_routes.api_run_all_collectors
api_dashboard_summary = operations_routes.api_dashboard_summary
api_macro_latest = macro_routes.api_macro_latest
api_macro_report = macro_routes.api_macro_report
api_options_snapshot = options_routes.api_options_snapshot
api_options_report = options_routes.api_options_report
api_options_dates = options_routes.api_options_dates
api_options_visual_report_latest = options_routes.api_options_visual_report_latest
api_options_visual_report = options_routes.api_options_visual_report
api_event_flow_overview = event_flow_routes.api_event_flow_overview
api_event_flow_briefs = event_flow_routes.api_event_flow_briefs
api_event_flow_events = event_flow_routes.api_event_flow_events
api_event_flow_report_inputs = event_flow_routes.api_event_flow_report_inputs
api_event_flow_event_detail = event_flow_routes.api_event_flow_event_detail
api_event_flow_event_impact = event_flow_routes.api_event_flow_event_impact
api_event_flow_event_market_reaction = event_flow_routes.api_event_flow_event_market_reaction
api_event_flow_brief_link = event_flow_routes.api_event_flow_brief_link
api_event_flow_brief_ignore = event_flow_routes.api_event_flow_brief_ignore
api_event_flow_report_input_include = event_flow_routes.api_event_flow_report_input_include
api_event_flow_report_input_exclude = event_flow_routes.api_event_flow_report_input_exclude
api_event_flow_event_review = event_flow_routes.api_event_flow_event_review
api_create_playbook = playbook_routes.api_create_playbook
api_playbooks = playbook_routes.api_playbooks
api_playbook_detail = playbook_routes.api_playbook_detail
api_playbook_versions = playbook_routes.api_playbook_versions
api_knowledge_items = knowledge_routes.api_knowledge_items
api_knowledge_item = knowledge_routes.api_knowledge_item
api_settings_status = settings_read_routes.api_settings_status
api_settings_history = settings_read_routes.api_settings_history
api_settings_update_preferences = settings_write_routes.api_settings_update_preferences
api_settings_reset_preferences = settings_write_routes.api_settings_reset_preferences
api_settings_update_source = settings_write_routes.api_settings_update_source
api_settings_reset_source = settings_write_routes.api_settings_reset_source
api_settings_update_secret = settings_write_routes.api_settings_update_secret
api_settings_reset_secret = settings_write_routes.api_settings_reset_secret
api_settings_rollback_history_event = settings_write_routes.api_settings_rollback_history_event
api_jin10_daily_report_latest = jin10_report_routes.api_jin10_daily_report_latest
api_jin10_daily_report = jin10_report_routes.api_jin10_daily_report
api_jin10_weekly_report_latest = jin10_report_routes.api_jin10_weekly_report_latest
api_jin10_weekly_report = jin10_report_routes.api_jin10_weekly_report
api_jin10_report_bundle_latest = jin10_report_routes.api_jin10_report_bundle_latest
api_jin10_report_bundle = jin10_report_routes.api_jin10_report_bundle
api_jin10_report_bundle_asset = jin10_report_routes.api_jin10_report_bundle_asset
api_jin10_article_briefs_latest = jin10_report_routes.api_jin10_article_briefs_latest
api_jin10_article_briefs = jin10_report_routes.api_jin10_article_briefs
api_daily_analysis_triggers_latest = news_routes.api_daily_analysis_triggers_latest
api_daily_analysis_triggers = news_routes.api_daily_analysis_triggers
api_daily_brief_latest = news_routes.api_daily_brief_latest
api_daily_brief = news_routes.api_daily_brief
api_daily_analysis_followups_latest = news_routes.api_daily_analysis_followups_latest
api_daily_analysis_followups = news_routes.api_daily_analysis_followups
api_create_daily_analysis_followup_tasks = news_routes.api_create_daily_analysis_followup_tasks
api_feishu_jin10_message_monitor_latest = news_routes.api_feishu_jin10_message_monitor_latest
api_feishu_jin10_message_monitor_dates = news_routes.api_feishu_jin10_message_monitor_dates
api_feishu_jin10_message_monitor = news_routes.api_feishu_jin10_message_monitor
api_gold_mainlines_latest = gold_mainline_routes.api_gold_mainlines_latest
api_gold_mainlines = gold_mainline_routes.api_gold_mainlines
api_gold_runtime_orchestration_contract = gold_mainline_routes.api_gold_runtime_orchestration_contract
api_gold_runtime_summary_preview = gold_mainline_routes.api_gold_runtime_summary_preview
api_jin10_quotes_latest = jin10_market_routes.api_jin10_quotes_latest
api_jin10_calendar = jin10_market_routes.api_jin10_calendar
api_jin10_flash = jin10_market_routes.api_jin10_flash
api_jin10_kline = jin10_market_routes.api_jin10_kline
api_premarket_pipeline_contract = premarket_routes.api_premarket_pipeline_contract
api_premarket_pipeline_readiness = premarket_routes.api_premarket_pipeline_readiness
api_premarket_launch_preflight = premarket_routes.api_premarket_launch_preflight
trigger_premarket = premarket_routes.trigger_premarket
get_task = premarket_routes.get_task
get_task_logs = premarket_routes.get_task_logs
health = health_routes.health
api_memory_context = health_routes.api_memory_context
api_agents_registry = agent_governance_read_routes.api_agents_registry
api_agent_registry_detail = agent_governance_read_routes.api_agent_registry_detail
api_prompt_versions_list = agent_governance_read_routes.api_prompt_versions_list
api_prompt_versions_by_agent = agent_governance_read_routes.api_prompt_versions_by_agent
api_prompt_versions_active = agent_governance_read_routes.api_prompt_versions_active
api_prompt_versions_create = agent_governance_write_routes.api_prompt_versions_create
api_prompt_versions_activate = agent_governance_write_routes.api_prompt_versions_activate
api_prompt_feedback_create = agent_governance_write_routes.api_prompt_feedback_create
api_prompt_feedback_by_agent = agent_governance_write_routes.api_prompt_feedback_by_agent
api_prompt_feedback_list = agent_governance_write_routes.api_prompt_feedback_list
api_agent_analysis_latest = agent_analysis_read_routes.api_agent_analysis_latest
api_agent_analysis_by_date = agent_analysis_read_routes.api_agent_analysis_by_date
api_agent_analysis_inspect = agent_analysis_read_routes.api_agent_analysis_inspect
api_agent_analysis_synthesis_latest = agent_analysis_read_routes.api_agent_analysis_synthesis_latest
api_run_agent_analysis = agent_analysis_run_routes.api_run_agent_analysis
serve_frontend_asset = frontend_compat_routes.serve_frontend_asset
serve_frontend_favicon = frontend_compat_routes.serve_frontend_favicon
serve_dashboard = frontend_compat_routes.serve_dashboard
serve_dashboard_analysis = frontend_compat_routes.serve_dashboard_analysis
serve_data_ingestion = frontend_compat_routes.serve_data_ingestion
serve_data_sources_subpath = frontend_compat_routes.serve_data_sources_subpath
serve_market_monitor = frontend_compat_routes.serve_market_monitor
serve_cme_options = frontend_compat_routes.serve_cme_options
serve_reports = frontend_compat_routes.serve_reports
serve_reports_subpath = frontend_compat_routes.serve_reports_subpath
serve_event_flow = frontend_compat_routes.serve_event_flow
serve_event_flow_subpath = frontend_compat_routes.serve_event_flow_subpath
serve_knowledge_base = frontend_compat_routes.serve_knowledge_base
serve_agent_tasks = frontend_compat_routes.serve_agent_tasks
serve_scheduler = frontend_compat_routes.serve_scheduler
serve_scheduler_subpath = frontend_compat_routes.serve_scheduler_subpath
serve_agent_tasks_subpath = frontend_compat_routes.serve_agent_tasks_subpath
serve_review_center = frontend_compat_routes.serve_review_center
serve_settings = frontend_compat_routes.serve_settings
serve_settings_audit = frontend_compat_routes.serve_settings_audit
system_status = system_status_routes.system_status

# Keep these globals explicit so modular route handlers and legacy tests can patch via apps.api.main.
_HEALTH_ROUTE_DEPENDENCIES = (
    build_codex_memory_context,
)
_DATA_SOURCE_ROUTE_DEPENDENCIES = (
    get_data_source_statuses,
    get_data_source_health_latest,
    get_data_source_history,
    get_data_sources_registry,
    get_data_status_summary,
    ingestion_action_service,
    ingestion_source_test_service,
)
_STRATEGY_REPORT_ROUTE_DEPENDENCIES = (
    get_final_report_latest,
    get_final_report,
    get_strategy_card_latest,
    get_strategy_card,
    list_strategy_cards,
    list_strategy_assets,
    get_strategy_card_read_model_latest,
    get_strategy_card_by_id,
)
_MARKET_MONITOR_ROUTE_DEPENDENCIES = (
    get_market_tickers,
    get_market_monitor_overview,
    get_market_monitor_history,
)
_REPORT_ROUTE_DEPENDENCIES = (
    list_reports_index,
    list_unified_dates,
    get_report_detail,
    get_report_artifacts,
    get_report_source,
    get_report_analysis,
    get_report_artifact_asset_path,
    get_report_visual,
    get_report_evidence,
    get_report_analysis_inputs,
)
_MARKET_ODDS_ROUTE_DEPENDENCIES = (
    get_market_odds_snapshot,
    get_market_odds_report,
)
_OPERATIONS_ROUTE_DEPENDENCIES = (
    list_recent_tasks,
    get_scheduler_overview,
    get_dashboard_summary,
)
_MACRO_ROUTE_DEPENDENCIES = (
    get_macro_latest,
    get_macro_report_md,
)
_OPTIONS_ROUTE_DEPENDENCIES = (
    get_options_snapshot,
    get_options_report_md,
    list_options_report_dates,
    get_options_visual_report_html,
)
_EVENT_FLOW_ROUTE_DEPENDENCIES = (
    event_flow_action_service,
)
_PLAYBOOK_ROUTE_DEPENDENCIES = (
    playbook_service,
)
_SETTINGS_READ_ROUTE_DEPENDENCIES = (
    settings_service,
)
_SETTINGS_WRITE_ROUTE_DEPENDENCIES = (
    settings_service,
)
_JIN10_REPORT_ROUTE_DEPENDENCIES = (
    get_jin10_daily_report_latest,
    get_jin10_daily_report,
    get_jin10_weekly_report_latest,
    get_jin10_weekly_report,
    get_jin10_report_bundle_latest,
    get_jin10_report_bundle,
    get_jin10_report_bundle_asset_path,
    get_jin10_article_briefs_latest,
    get_jin10_article_briefs,
)
_NEWS_ROUTE_DEPENDENCIES = (
    get_daily_analysis_triggers_latest,
    get_daily_analysis_triggers,
    get_daily_brief_latest,
    get_daily_brief,
    get_daily_analysis_followups_latest,
    get_daily_analysis_followups,
    create_daily_analysis_followup_tasks,
    get_feishu_jin10_message_monitor_latest,
    list_feishu_jin10_message_monitor_dates,
    get_feishu_jin10_message_monitor,
)
_GOLD_MAINLINE_ROUTE_DEPENDENCIES = (
    get_gold_mainlines_latest,
    get_gold_mainlines,
)


@app.middleware("http")
async def log_http_requests(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    logger.info(
        "HTTP request completed",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        },
    )
    return response


# ---- Frontend entrypoint ----
_FRONTEND_WEB_URL = os.environ.get("FRONTEND_WEB_URL", "http://localhost:8080").rstrip("/")
_ROOT = Path(__file__).resolve().parent.parent.parent
_FRONTEND_DIST_DIR = Path(os.environ.get("FINANCE_AGENT_FRONTEND_DIST_DIR", str(_ROOT / "apps/frontend-web" / "dist")))
_FRONTEND_PUBLIC_DIR = Path(os.environ.get("FINANCE_AGENT_FRONTEND_PUBLIC_DIR", str(_ROOT / "apps/frontend-web" / "public")))


# ---- Schemas ----


class TaskCreateResponse(BaseModel):
    task_id: str
    name: str
    status: str
    source_readiness_summary: dict[str, Any] | None = None


class PremarketActiveTaskRef(BaseModel):
    task_id: str
    status: str
    updated_at: datetime | None = None


class PremarketDagsterRunRef(BaseModel):
    run_id: str
    status: str


class PremarketLaunchPreflightResponse(BaseModel):
    force: bool = False
    can_launch: bool
    blocking_reasons: list[str]
    stale_legacy_task_ids: list[str] = []
    active_legacy_task: PremarketActiveTaskRef | None = None
    active_dagster_run: PremarketDagsterRunRef | None = None
    dagster_check_error: str | None = None
    source_readiness_summary: dict[str, Any] | None = None


class StepOut(BaseModel):
    id: str
    name: str
    status: str
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    # ── P4-03: task observability fields ──
    step_order: int | None = None
    input_json: dict | None = None
    output_json: dict | None = None
    error_json: dict | None = None
    retryable: bool = True
    blocked_reason: str | None = None
    # ── T1: state machine enhancement fields ──
    input_hash: str | None = None
    output_ref: str | None = None
    error_type: str | None = None
    retry_count: int = 0


class TaskOut(BaseModel):
    id: str
    name: str
    status: str
    error: str | None = None
    trade_date: str | None = None
    created_at: datetime
    updated_at: datetime
    steps: list[StepOut] = []


class MemoryContextResponse(BaseModel):
    task: str
    context: str
    source: str


# ---- Routes ----


PREMARKET_STEPS = PREMARKET_STEP_ORDER


def _step_to_out(s: TaskStep) -> StepOut:
    """Map a TaskStep ORM object to a StepOut response model."""
    return StepOut(
        id=str(s.id),
        name=s.name,
        status=s.status.value,
        error=s.error,
        started_at=s.started_at,
        finished_at=s.finished_at,
        # ── P4-03: observability fields ──
        step_order=s.step_order,
        input_json=_try_parse_json(s.input_json),
        output_json=_try_parse_json(s.output_json),
        error_json=_try_parse_json(s.error_json),
        retryable=bool(s.retryable),
        blocked_reason=s.blocked_reason,
        # ── T1: state machine enhancement fields ──
        input_hash=s.input_hash,
        output_ref=s.output_ref,
        error_type=s.error_type,
        retry_count=s.retry_count if s.retry_count is not None else 0,
    )


def _try_parse_json(raw: str | None) -> dict | None:
    """Safely parse a JSON string, returning None on failure."""
    if raw is None:
        return None
    try:
        import json as _json

        return _json.loads(raw)
    except Exception:
        return None


def _get_version() -> str:
    """Read project version from pyproject.toml, fallback to a safe default."""
    try:
        pyproject = _ROOT / "pyproject.toml"
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        return data["project"]["version"]
    except Exception:
        return "0.0.0"


def _get_phases() -> dict:
    """Read phase status mapping from configs/phases.json."""
    try:
        phases_path = _ROOT / "configs" / "phases.json"
        return json.loads(phases_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _database_reachable(timeout: float = 0.2) -> bool:
    """Best-effort fast reachability probe to avoid long DB hangs in local/no-DB environments."""
    try:
        bind = SessionLocal.kw.get("bind")
        if bind is None:
            return False

        url = make_url(str(bind.url))
        if not url.drivername.startswith("postgresql"):
            return True
        if not url.host or not url.port:
            return True

        with socket.create_connection((url.host, int(url.port)), timeout=timeout):
            return True
    except OSError:
        return False
    except Exception:
        return True


_PREMARKET_ROUTE_DEPENDENCIES = (
    pipeline_contract_service,
    SessionLocal,
    _cleanup_stale_active_premarket_tasks,
    _premarket_launch_error_detail,
    _task_to_premarket_active_task_ref,
    _find_active_dagster_premarket_run,
    _source_readiness_block_count,
    _source_readiness_block_message,
    _database_reachable,
    _get_dagster_task_view,
    _step_to_out,
    sort_premarket_steps,
)


# ---- Dashboard Routes (只读) ----

# ── API: Review Queue ──


# ── Settings ──


# ── API: Jin10 MCP Quotes & Snapshot ──


def _jin10_unavailable(reason: str) -> dict:
    return {
        "status": "unavailable",
        "reason": reason,
        "quotes": {},
        "counts": {},
        "kline_codes": [],
    }


def _is_file_stale(path: Path, *, max_age_seconds: int) -> bool:
    try:
        age_seconds = time.time() - path.stat().st_mtime
    except OSError:
        return True
    return age_seconds > max_age_seconds


def _refresh_jin10_calendar_cache() -> None:
    try:
        from apps.scheduler.jin10_refresh import refresh_jin10_calendar_cache

        refresh_jin10_calendar_cache()
    except Exception:
        pass


def _parse_jin10_calendar_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None

    normalized = value.strip().replace("Z", "+00:00")
    if "T" not in normalized and " " in normalized:
        normalized = normalized.replace(" ", "T", 1)

    candidates = [normalized]
    if len(normalized) == 16:
        candidates.append(f"{normalized}:00")

    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def _calendar_release_state(event: dict[str, Any]) -> str:
    return "upcoming" if event.get("actual") in (None, "") else "released"


def _normalize_jin10_calendar_event(event: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(event)
    parsed_time = _parse_jin10_calendar_time(event.get("pub_time"))
    if parsed_time is not None:
        normalized["pub_time"] = parsed_time.isoformat(timespec="minutes")
        normalized["event_date"] = parsed_time.date().isoformat()
        normalized["_sort_ts"] = parsed_time.timestamp()
    else:
        normalized["event_date"] = None
        normalized["_sort_ts"] = 0.0
    normalized["release_state"] = _calendar_release_state(event)
    normalized["is_high_impact"] = int(event.get("star") or 0) >= 4
    return normalized


def _jin10_calendar_window(now: datetime | None = None) -> tuple[str, str]:
    anchor = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date()
    return (
        (anchor - timedelta(days=_JIN10_CALENDAR_PAST_WINDOW_DAYS)).isoformat(),
        (anchor + timedelta(days=_JIN10_CALENDAR_FUTURE_WINDOW_DAYS)).isoformat(),
    )


def _is_jin10_calendar_event_in_window(event: dict[str, Any], *, window_start: str, window_end: str) -> bool:
    event_date = event.get("event_date")
    return isinstance(event_date, str) and window_start <= event_date <= window_end


def _calendar_event_sort_key(event: dict[str, Any]) -> tuple[int, float, int]:
    sort_ts = float(event.get("_sort_ts") or 0.0)
    star = int(event.get("star") or 0)
    if event.get("release_state") == "upcoming":
        return (0, sort_ts, -star)
    return (1, -sort_ts, -star)


def _calendar_cache_age_seconds(path: Path) -> int | None:
    try:
        return max(0, int(time.time() - path.stat().st_mtime))
    except OSError:
        return None


def _build_jin10_calendar_payload(data: dict[str, Any], cache_path: Path) -> dict[str, Any]:
    raw_events = data.get("events")
    events = [_normalize_jin10_calendar_event(item) for item in raw_events if isinstance(item, dict)] if isinstance(raw_events, list) else []
    window_start_date, window_end_date = _jin10_calendar_window()
    events = [
        event for event in events
        if _is_jin10_calendar_event_in_window(event, window_start=window_start_date, window_end=window_end_date)
    ]
    events.sort(key=_calendar_event_sort_key)

    upcoming_count = sum(1 for event in events if event.get("release_state") == "upcoming")
    released_count = len(events) - upcoming_count
    high_impact_count = sum(1 for event in events if event.get("is_high_impact"))
    event_dates = [event.get("event_date") for event in events if isinstance(event.get("event_date"), str)]
    earliest_event_date = min(event_dates) if event_dates else None
    latest_event_date = max(event_dates) if event_dates else None
    cache_age_seconds = _calendar_cache_age_seconds(cache_path)

    stale_by_age = _is_file_stale(cache_path, max_age_seconds=_JIN10_CALENDAR_CACHE_MAX_AGE_SECONDS)
    today_key = datetime.now(timezone.utc).date().isoformat()
    stale_by_window = upcoming_count == 0 and latest_event_date is not None and latest_event_date < today_key
    is_stale = stale_by_age or stale_by_window

    freshness_reason = "fresh"
    if stale_by_window:
        freshness_reason = "no_upcoming_events"
    elif stale_by_age:
        freshness_reason = "cache_too_old"

    for event in events:
        event.pop("_sort_ts", None)

    return {
        "status": "stale" if is_stale else "ok",
        "generated_at": data.get("generated_at"),
        "events": events,
        "stats": {
            "total": len(events),
            "upcoming": upcoming_count,
            "released": released_count,
            "high_impact": high_impact_count,
            "earliest_event_date": earliest_event_date,
            "latest_event_date": latest_event_date,
            "window_start_date": window_start_date,
            "window_end_date": window_end_date,
        },
        "freshness": {
            "is_stale": is_stale,
            "reason": freshness_reason,
            "cache_age_seconds": cache_age_seconds,
        },
    }


def _candle_to_dict(row) -> dict:
    return {
        "time": row.open_time.isoformat() if row.open_time else "",
        "open": row.open,
        "high": row.high,
        "low": row.low,
        "close": row.close,
        "volume": row.volume if row.volume else 0,
    }


def _aggregation_fetch_limit(timeframe: str, target_limit: int) -> int:
    """计算需要从 DB 拉取的 1m 原始行数。"""
    multipliers = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1D": 1440}
    return (target_limit + 4) * multipliers.get(timeframe, 1)


def _aggregate_candles(rows: list, timeframe: str) -> list[dict]:
    """将 1m 行按周期聚合成 OHLC。"""
    from datetime import datetime, timezone, timedelta

    if not rows:
        return []

    minutes = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1D": 1440}
    delta = timedelta(minutes=minutes.get(timeframe, 1))

    # 确保按时间排序
    sorted_rows = sorted(rows, key=lambda r: r.open_time if r.open_time else datetime.min.replace(tzinfo=timezone.utc))

    buckets: dict[datetime, list] = {}
    for row in sorted_rows:
        if not row.open_time:
            continue
        # 向下取整到周期边界
        ts = row.open_time.timestamp()
        bucket_ts = int(ts // (delta.total_seconds())) * int(delta.total_seconds())
        bucket_key = datetime.fromtimestamp(bucket_ts, tz=timezone.utc)
        if bucket_key not in buckets:
            buckets[bucket_key] = []
        buckets[bucket_key].append(row)

    result = []
    for bucket_key in sorted(buckets.keys()):
        group = buckets[bucket_key]
        opens = [r.open for r in group if r.open is not None]
        highs = [r.high for r in group if r.high is not None]
        lows = [r.low for r in group if r.low is not None]
        closes = [r.close for r in group if r.close is not None]
        volumes = [r.volume for r in group if r.volume is not None]

        if not opens:
            continue

        result.append({
            "time": bucket_key.isoformat(),
            "open": opens[0],
            "high": max(highs) if highs else opens[0],
            "low": min(lows) if lows else opens[0],
            "close": closes[-1],
            "volume": sum(volumes) if volumes else 0,
        })

    return result


# ── Agent Analysis unified endpoint ──


# ── P2-11 Prompt Versions API ──


_PROMPT_VERSION_STATUSES = {"draft", "active", "deprecated"}
_PROMPT_KINDS = {"llm", "hybrid", "rule", "vlm"}


def _validate_prompt_version_create_payload(payload: PromptVersionCreate) -> None:
    if not payload.prompt_template:
        raise HTTPException(status_code=400, detail="prompt_template must not be empty")
    status = payload.status or "draft"
    if status not in _PROMPT_VERSION_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid prompt status: {status}")
    kind = payload.prompt_kind or "llm"
    if kind not in _PROMPT_KINDS:
        raise HTTPException(status_code=400, detail=f"Invalid prompt kind: {kind}")


def _prompt_version_item(row) -> dict[str, Any]:
    return {
        "id": row.id,
        "agent_id": row.agent_id,
        "version": row.version,
        "prompt_kind": row.prompt_kind,
        "prompt_source": row.prompt_source,
        "prompt_template": row.prompt_template,
        "prompt_sha256": row.prompt_sha256,
        "status": row.status,
        "enabled": row.enabled,
        "model_routing": row.model_routing,
        "change_note": row.change_note,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


_AGENT_GOVERNANCE_READ_ROUTE_DEPENDENCIES = (
    _prompt_version_item,
)


def _prompt_feedback_item(row) -> dict[str, Any]:
    return {
        "feedback_id": row.feedback_id,
        "agent_output_id": row.agent_output_id,
        "agent_id": row.agent_id,
        "prompt_version_id": row.prompt_version_id,
        "run_id": row.run_id,
        "rating": row.rating,
        "category": row.category,
        "comment": row.comment,
        "suggested_changes": row.suggested_changes,
        "review_item_id": row.review_item_id,
        "status": row.status,
        "submitted_by": row.submitted_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _build_agent_analysis_response(db, target_date, run_id: str | None = None):
    """Build unified agent analysis response from DB."""
    from database.models.analysis import AgentOutput

    query = db.query(AgentOutput).filter(AgentOutput.trade_date == target_date).order_by(desc(AgentOutput.created_at))
    if run_id:
        query = query.filter(AgentOutput.run_id == run_id)

    rows = query.all()

    # Group by agent_name, take latest for each
    latest_by_agent: dict[str, Any] = {}
    for row in rows:
        if row.agent_name not in latest_by_agent:
            latest_by_agent[row.agent_name] = row

    agent_outputs = [build_agent_output_summary(row) for row in latest_by_agent.values()]
    agents = {
        item["agent_name"]: {
            **item,
            "summary": item["summary_zh"],
            "summary_raw": item["summary"],
        }
        for item in agent_outputs
    }

    # Build final summary from coordinator or latest agent
    coordinator = agents.get("coordinator") or agents.get("coordinator_agent") or {}
    final_bias = coordinator.get("bias", "neutral")
    final_confidence = coordinator.get("confidence", 0.0)
    final_summary = coordinator.get("summary", "")
    final_summary_raw = coordinator.get("summary_raw", "")

    return {
        "trade_date": target_date.isoformat() if hasattr(target_date, "isoformat") else str(target_date),
        "agent_outputs": agent_outputs,
        "agents": agents,
        "final": {
            "bias": final_bias,
            "confidence": final_confidence,
            "summary": final_summary,
            "summary_zh": final_summary,
            "summary_raw": final_summary_raw,
        },
    }


def _build_agent_analysis_inspection(db, target_date, run_id: str | None = None) -> dict[str, Any]:
    """Build prompt/input/output inspection view from persisted AgentOutput rows."""
    from database.models.analysis import AgentOutput, AnalysisSnapshot

    query = db.query(AgentOutput).filter(AgentOutput.trade_date == target_date).order_by(desc(AgentOutput.created_at))
    if run_id:
        query = query.filter(AgentOutput.run_id == run_id)

    rows = query.all()
    latest_by_agent: dict[str, Any] = {}
    for row in rows:
        if row.agent_name not in latest_by_agent:
            latest_by_agent[row.agent_name] = row

    snapshot_ids = {row.snapshot_id for row in latest_by_agent.values() if row.snapshot_id}
    snapshots = {
        snap.snapshot_id: snap
        for snap in (
            db.query(AnalysisSnapshot).filter(AnalysisSnapshot.snapshot_id.in_(snapshot_ids)).all()
            if snapshot_ids
            else []
        )
    }

    agents = [
        _agent_inspection_item(
            row, (snapshots.get(row.snapshot_id).payload if snapshots.get(row.snapshot_id) else None)
        )
        for row in latest_by_agent.values()
    ]
    first_row = next(iter(latest_by_agent.values()), None)

    return {
        "trade_date": target_date.isoformat() if hasattr(target_date, "isoformat") else str(target_date),
        "run_id": run_id or (first_row.run_id if first_row else None),
        "snapshot_id": first_row.snapshot_id if first_row else None,
        "agents": agents,
        "source": "agent_outputs",
    }


_AGENT_INPUT_SECTIONS: dict[str, list[str]] = {
    "macro_liquidity_agent": ["macro"],
    "cme_options_agent": ["options"],
    "risk_agent": ["macro", "options"],
    "technical_agent": ["technical"],
    "positioning_agent": ["positioning"],
    "news_agent": ["news"],
    "market_odds_agent": ["market_odds"],
    "coordinator_agent": ["macro", "options", "technical", "positioning", "news", "market_odds"],
    "coordinator": ["macro", "options", "technical", "positioning", "news", "market_odds"],
    "market_regime": ["macro", "options", "jin10"],
    "event_impact": ["news", "macro", "options", "jin10"],
    "jin10_daily": ["jin10"],
    "jin10_report_analysis_agent": ["jin10"],
    "fact_review_agent": ["agent_outputs"],
    "synthesis_agent": ["agent_outputs", "fact_review", "reviews"],
}


def _agent_inspection_item(row, snapshot_payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = row.payload or {}
    prompt_messages = payload.get("prompt_messages")
    input_payload = payload.get("input_payload") or _derive_agent_input(row.agent_name, snapshot_payload)
    generated_by = str(payload.get("generated_by") or "").lower()
    prompt_kind = "rule" if generated_by == "rule" else ("llm" if row.llm_model or prompt_messages else "rule")
    agent_summary = build_agent_output_summary(row)

    return {
        "agent_output_id": row.id,
        "agent_name": row.agent_name,
        "display_name": agent_summary["display_name"],
        "registry_id": agent_summary["registry_id"],
        "role": agent_summary["role"],
        "module": row.module,
        "version": row.version,
        "run_id": row.run_id,
        "snapshot_id": row.snapshot_id,
        "status": row.status,
        "bias": row.bias,
        "confidence": row.confidence,
        "prompt_version_id": row.prompt_version_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "prompt": {
            "kind": prompt_kind,
            "available": bool(prompt_messages),
            "messages": prompt_messages or [],
            "note": None
            if prompt_messages
            else (
                "规则型 Agent 未使用 LLM prompt。"
                if prompt_kind == "rule"
                else "历史 AgentOutput 未记录实际 prompt，需重新运行后查看。"
            ),
        },
        "input": {
            "input_snapshot_ids": row.input_snapshot_ids or {},
            "source_refs": [source_ref.model_dump(mode="json") for source_ref in parse_source_refs(row.source_refs)],
            "payload": input_payload,
        },
        "output": {
            "summary": row.summary,
            "summary_zh": agent_summary["summary_zh"],
            "key_findings": row.key_findings or [],
            "risk_points": row.risk_points or [],
            "watchlist": row.watchlist or [],
            "invalid_conditions": row.invalid_conditions or [],
            "claims": agent_summary["claims"],
            "claim_reviews": agent_summary["claim_reviews"],
            "payload": payload,
            "llm_raw_output": payload.get("llm_raw_output"),
        },
        "llm": {
            "model": row.llm_model,
            "usage": row.token_usage,
            "elapsed_seconds": row.llm_elapsed_seconds,
        },
    }


def _derive_agent_input(agent_name: str, snapshot_payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not snapshot_payload:
        return None
    sections = _AGENT_INPUT_SECTIONS.get(agent_name, [])
    if not sections:
        return {
            "snapshot_id": snapshot_payload.get("snapshot_id"),
            "trade_date": snapshot_payload.get("trade_date"),
            "available_sections": sorted(k for k, v in snapshot_payload.items() if isinstance(v, (dict, list))),
        }
    return {
        "snapshot_id": snapshot_payload.get("snapshot_id"),
        "trade_date": snapshot_payload.get("trade_date"),
        "sections": {section: snapshot_payload.get(section) for section in sections if section in snapshot_payload},
    }


def _empty_agent_analysis():
    return {
        "trade_date": None,
        "agent_outputs": [],
        "agents": {},
        "final": {"bias": "neutral", "confidence": 0.0, "summary": "", "summary_zh": "", "summary_raw": ""},
    }


def _run_market_regime_async(target_date: str):
    """Run market regime agent in background."""
    import threading

    def _run():
        try:
            from apps.analysis.agents.market_regime import run_market_regime_agent

            # Load macro snapshot from latest premarket run
            macro_snapshot = _load_macro_snapshot(target_date)
            options_intent = _load_options_intent(target_date)

            result = run_market_regime_agent(
                macro_snapshot,
                options_intent,
                snapshot_id=f"manual-{target_date}",
                run_id=f"manual-{target_date}",
            )

            # Save to DB
            _save_agent_output(result)
        except Exception:
            logger.exception("Market Regime Agent failed")

    threading.Thread(target=_run, daemon=True).start()


def _run_event_impact_async(target_date: str):
    """Run event impact agent in background."""
    import threading

    def _run():
        try:
            from apps.analysis.agents.event_impact import run_event_impact_agent

            # Load flash news from Jin10
            flash_news = _load_flash_news()
            macro_snapshot = _load_macro_snapshot(target_date)
            options_intent = _load_options_intent(target_date)

            result = run_event_impact_agent(
                flash_news,
                macro_snapshot,
                options_intent,
                current_price=_load_current_price(),
                snapshot_id=f"manual-{target_date}",
                run_id=f"manual-{target_date}",
            )

            _save_agent_output(result)
        except Exception:
            logger.exception("Event Impact Agent failed")

    threading.Thread(target=_run, daemon=True).start()


def _load_macro_snapshot(target_date: str) -> dict[str, Any]:
    """Load macro snapshot from storage."""
    from pathlib import Path
    import json

    features_dir = Path("storage/features/macro") / target_date
    if not features_dir.exists():
        # Try latest
        features_dir = Path("storage/features/macro")
        dates = sorted(
            [d.name for d in features_dir.iterdir() if d.is_dir() and d.name.startswith("2026")], reverse=True
        )
        if dates:
            features_dir = features_dir / dates[0]
        else:
            return {"indicators": {}}

    for run_dir in features_dir.iterdir():
        snapshot_file = run_dir / "macro_snapshot.json"
        if snapshot_file.exists():
            return json.loads(snapshot_file.read_text())

    return {"indicators": {}}


def _load_options_intent(target_date: str) -> dict[str, Any] | None:
    """Load CME options intent from storage."""
    from pathlib import Path
    import json

    features_dir = Path("storage/features/cme")
    if not features_dir.exists():
        return None

    dates = sorted([d.name for d in features_dir.iterdir() if d.is_dir() and d.name.startswith("2026")], reverse=True)
    for date_dir in dates:
        for run_dir in (features_dir / date_dir).iterdir():
            analysis_file = run_dir / "options_analysis.json"
            if analysis_file.exists():
                data = json.loads(analysis_file.read_text())
                intent = data.get("intent", {})
                gex = data.get("gex", {}).get("netgex_aggregate", {})
                return {
                    "type": intent.get("type", intent.get("primary_intent", {}).get("intent_type", "N/A")),
                    "score": intent.get("score", intent.get("confidence", 0)),
                    "gamma_zero": gex.get("gamma_zero", {}).get("price"),
                    "forward_price": data.get("parameters", {}).get("p0"),
                }
    return None


def _load_flash_news() -> list[dict[str, Any]]:
    """Load recent flash news from Jin10 MCP."""
    try:
        from apps.collectors.jin10.mcp_client import fetch_flash_news

        return fetch_flash_news(limit=30)
    except Exception:
        return []


def _load_current_price() -> float | None:
    """Load current XAUUSD price from Jin10 quotes cache."""
    from pathlib import Path
    import json

    cache_file = Path("storage/outputs/jin10/quotes_cache.json")
    if cache_file.exists():
        data = json.loads(cache_file.read_text())
        quotes = data.get("quotes", {})
        xau = quotes.get("XAUUSD", {})
        return xau.get("price")
    return None


def _save_agent_output(result):
    """Save AgentOutput to database, updating the existing unique row when present."""
    from database.models.analysis import AgentOutput as AgentOutputDB
    from database.models.engine import SessionLocal
    import uuid

    payload_dict = {
        "market_phase": result.market_phase,
        "regime_drivers": result.regime_drivers,
        "generated_by": (result.regime_drivers or {}).get("generated_by", "rule"),
        "data_category": result.data_category.value if result.data_category else None,
        "evidence_refs": result.evidence_refs,
        "prompt_messages": result.prompt_messages,
        "input_payload": result.input_payload,
        "llm_raw_output": result.llm_raw_output,
    }

    with SessionLocal() as db:
        db_row = (
            db.query(AgentOutputDB)
            .filter(
                AgentOutputDB.snapshot_id == result.snapshot_id,
                AgentOutputDB.agent_name == result.agent_name,
                AgentOutputDB.module == result.module,
                AgentOutputDB.version == result.version,
            )
            .one_or_none()
        )
        values = {
            "status": result.status.value,
            "bias": result.bias.value,
            "confidence": result.confidence,
            "input_snapshot_ids": result.input_snapshot_ids,
            "source_refs": result.source_refs,
            "key_findings": result.key_findings,
            "risk_points": result.risk_points,
            "watchlist": result.watchlist,
            "invalid_conditions": result.invalid_conditions,
            "summary": result.summary,
            "payload": payload_dict,
            "payload_sha256": "manual",
            "token_usage": result.llm_usage,
            "llm_model": result.llm_model,
            "llm_elapsed_seconds": (result.llm_latency_ms / 1000.0) if result.llm_latency_ms else None,
        }
        if db_row is None:
            db_row = AgentOutputDB(
                id=str(uuid.uuid4()),
                snapshot_id=result.snapshot_id,
                asset="XAUUSD",
                trade_date=result.created_at.date(),
                run_id=result.snapshot_id,
                agent_name=result.agent_name,
                module=result.module,
                version=result.version,
                **values,
            )
            db.add(db_row)
        else:
            for key, value in values.items():
                setattr(db_row, key, value)
        db.commit()


# ── Frontend compatibility redirect ──


def _serve_frontend_entry(request_path: str) -> FileResponse | RedirectResponse:
    index_path = _FRONTEND_DIST_DIR / "index.html"
    if index_path.is_file():
        return FileResponse(index_path)
    return RedirectResponse(url=f"{_FRONTEND_WEB_URL}{request_path}", status_code=307)


def _resolve_frontend_asset(asset_path: str) -> Path | None:
    assets_root = (_FRONTEND_DIST_DIR / "assets").resolve()
    candidate = (assets_root / asset_path).resolve()
    if not str(candidate).startswith(str(assets_root)):
        return None
    if not candidate.is_file():
        return None
    return candidate


def _resolve_frontend_root_asset(asset_name: str) -> Path | None:
    for root in (_FRONTEND_DIST_DIR, _FRONTEND_PUBLIC_DIR):
        root_resolved = root.resolve()
        candidate = (root_resolved / asset_name).resolve()
        if not str(candidate).startswith(str(root_resolved)):
            continue
        if candidate.is_file():
            return candidate
    return None


_FRONTEND_COMPAT_ROUTE_DEPENDENCIES = (
    _serve_frontend_entry,
    _resolve_frontend_asset,
    _resolve_frontend_root_asset,
)
