"""FastAPI 入口。"""

from __future__ import annotations

import json
import logging
import os
import socket
import sys
import time
import tomllib
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import func, desc
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from apps.api.schemas.data_source import (
    DataSourceActionRequest,
    DataSourceActionResponse,
    DataSourceTestRequest,
    DataSourceTestResponse,
    ManualUploadRequest,
)
from apps.api.schemas.event_flow import EventFlowActionRequest, EventFlowActionResponse, EventFlowBriefLinkRequest
from apps.api.schemas.review import ReviewActionRequest, ReviewItem
from apps.api.schemas.settings import (
    SettingsActionResponse,
    SettingsHistoryResponse,
    SettingsPreferencesResetRequest,
    SettingsPreferencesUpdateRequest,
    SettingsRollbackRequest,
    SettingsSecretResetRequest,
    SettingsSecretUpdateRequest,
    SettingsSourceResetRequest,
    SettingsSourceUpdateRequest,
)
from apps.api.schemas.agent import (
    PromptFeedbackCreate,
    PromptVersionActivate,
    PromptVersionCreate,
)
from apps.api.schemas.playbook import (
    PlaybookTemplateCreateRequest,
    PlaybookTemplateDetailResponse,
    PlaybookTemplateListResponse,
    PlaybookTemplateVersion,
)
from apps.api.schemas.artifact import ArtifactDetailResponse
from apps.api.schemas.strategy import StrategyAssetListResponse
from apps.api.schemas.source_trace import SourceTraceResponse
from apps.api.schemas.report import ReportAnalysisInputs, ReportArtifact, ReportDetail
from apps.api.schemas.task_run import TaskRunResponse
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
    review_service,
    settings_service,
    task_service,
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
from apps.api.services.execution_event_api import get_run_events
from apps.api.services.feishu_jin10_message_monitor_service import get_feishu_jin10_message_monitor
from apps.api.services.artifact_service import get_artifact_detail_response
from apps.api.services.source_service import get_data_status_summary
from apps.api.services.source_trace_service import (
    get_source_trace_by_artifact_id,
    get_source_trace_by_report_id,
    get_source_trace_by_snapshot_id,
    get_source_trace_by_strategy_card_id,
)
from apps.api.services.report_service import (
    get_report_analysis_inputs,
    get_report_analysis,
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
from database.models.engine import SessionLocal, get_db
from database.models.analysis import ensure_analysis_tables
from database.models.execution import ensure_execution_tables
from database.models.report import ensure_report_tables
from database.models.task import TaskRun, TaskStatus, TaskStep, ensure_task_tables

_should_skip_background_jobs_ref = None  # set by lifespan

logger = logging.getLogger(__name__)

_JIN10_FLASH_CACHE_PATH = Path("./storage/outputs/jin10/flash_cache.json")
_JIN10_FLASH_CACHE_MAX_AGE_SECONDS = 60
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
    active_runs = (
        db.query(TaskRun)
        .filter(
            TaskRun.name == "premarket",
            TaskRun.status.in_([TaskStatus.pending, TaskStatus.running]),
        )
        .order_by(desc(TaskRun.updated_at), desc(TaskRun.created_at))
        .all()
    )

    stale_marked = False
    for task in active_runs:
        ref_time = _premarket_active_task_ref_time(task)
        if ref_time is not None and current_time - ref_time > _PREMARKET_ACTIVE_TASK_STALE_AFTER:
            transition_task_run(
                db,
                task,
                TaskStatus.stale,
                source="api",
                reason=f"active_timeout_exceeded:{_PREMARKET_ACTIVE_TASK_STALE_AFTER}",
                error_message=task.error or "Legacy premarket task timed out before Dagster migration verification.",
            )
            stale_marked = True
            continue
        if stale_marked:
            db.commit()
        return task

    if stale_marked:
        db.commit()
    return None


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
        db = SessionLocal()
        try:
            ensure_task_tables(db)
            ensure_execution_tables(db)
            ensure_analysis_tables(db)
            ensure_report_tables(db)
        except Exception:
            logger.exception("Startup additive migrations failed")
        finally:
            db.close()

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


@app.get("/health")
@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/memory/context", response_model=MemoryContextResponse)
def api_memory_context(task: str) -> MemoryContextResponse:
    """Codex Mem0 接入程序：按任务描述预取长期记忆上下文。"""
    try:
        context = build_codex_memory_context(task)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return MemoryContextResponse(
        task=task,
        context=context,
        source="codex_mem0_adapter",
    )


PREMARKET_STEPS = PREMARKET_STEP_ORDER


@app.get("/api/pipelines/premarket/contract")
def api_premarket_pipeline_contract() -> dict[str, Any]:
    """Return the read-only canonical premarket step topology contract."""
    return pipeline_contract_service.build_premarket_pipeline_contract()


@app.post("/tasks/premarket", response_model=TaskCreateResponse)
@app.post("/api/tasks/premarket", response_model=TaskCreateResponse)
def trigger_premarket(force: bool = False) -> TaskCreateResponse:
    """触发盘前主链 — 通过 Dagster GraphQL launchRun。

    默认拒绝重复触发（已有 pending/running 的 premarket 任务时返回 409）。
    force=True 可跳过锁检查。
    """
    # Check for existing running tasks (legacy DB check for backward compat)
    with SessionLocal() as session:
        if not force:
            existing = _cleanup_stale_active_premarket_tasks(session)
            if existing:
                raise HTTPException(
                    status_code=409,
                    detail=f"已有进行中的 premarket 任务: {existing.id} (status={existing.status.value})",
                )

    # Launch via Dagster GraphQL
    dagster_url = os.getenv("DAGSTER_GRAPHQL_URL", "http://127.0.0.1:3333/graphql")
    if not force:
        try:
            active_dagster_run = _find_active_dagster_premarket_run(dagster_url)
        except Exception as exc:
            logger.warning("Failed to check active Dagster premarket runs: %s", exc)
        else:
            if active_dagster_run:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Dagster 已有进行中的 premarket_job: "
                        f"{active_dagster_run['run_id']} (status={active_dagster_run['status']})"
                    ),
                )

    mutation = """
        mutation LaunchRun($jobName: String!) {
            launchPipelineExecution(
                executionParams: {
                    selector: {
                        pipelineName: $jobName
                        repositoryName: "__repository__"
                        repositoryLocationName: "dagster_finance.definitions"
                    }
                    mode: "default"
                }
            ) {
                ... on LaunchRunSuccess {
                    run { runId status }
                }
                ... on PythonError { message }
                ... on RunConfigValidationInvalid { errors { message } }
            }
        }
    """
    try:
        import httpx

        resp = httpx.post(
            dagster_url,
            json={"query": mutation, "variables": {"jobName": "premarket_job"}},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        result = data.get("data", {}).get("launchPipelineExecution", {})
        if "run" in result:
            run_id = result["run"]["runId"]
            return TaskCreateResponse(task_id=run_id, name="premarket", status="running")
        error_msg = result.get("message", str(result))
        raise HTTPException(status_code=500, detail=f"Dagster launch failed: {error_msg}")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Dagster unavailable: {exc}")


@app.get("/tasks/{task_id}", response_model=TaskOut)
@app.get("/api/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: str, db: Session = Depends(get_db)) -> TaskOut:
    """查询任务状态。"""
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task_id format")

    if _database_reachable():
        task = db.get(TaskRun, tid)
        if task:
            steps = [_step_to_out(s) for s in sort_premarket_steps(task.steps)]

            return TaskOut(
                id=str(task.id),
                name=task.name,
                status=task.status.value,
                error=task.error,
                trade_date=task.trade_date,
                created_at=task.created_at,
                updated_at=task.updated_at,
                steps=steps,
            )

    dagster_url = os.getenv("DAGSTER_GRAPHQL_URL", "http://127.0.0.1:3333/graphql")
    try:
        dagster_task = _get_dagster_task_view(task_id, dagster_url)
    except Exception as exc:
        logger.warning("Failed to query Dagster task view for %s: %s", task_id, exc)
    else:
        if dagster_task is not None:
            return dagster_task

    raise HTTPException(status_code=404, detail="Task not found")


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


@app.get("/tasks/{task_id}/logs", response_model=list[StepOut])
@app.get("/api/tasks/{task_id}/logs", response_model=list[StepOut])
def get_task_logs(task_id: str, db: Session = Depends(get_db)) -> list[StepOut]:
    """查询任务步骤日志。"""
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task_id format")

    if not _database_reachable():
        raise HTTPException(status_code=404, detail="Task not found")

    task = db.get(TaskRun, tid)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return [_step_to_out(s) for s in sort_premarket_steps(task.steps)]


# ---- Dashboard Routes (只读) ----

# ── API: Options ──


@app.get("/api/options/snapshot")
def api_options_snapshot(date: str | None = None, db: Session = Depends(get_db)):
    """返回 CME 期权分析 JSON snapshot。不传 date 则返回最新。"""
    data = get_options_snapshot(date, db=db)
    if data is None:
        raise HTTPException(status_code=404, detail="Options snapshot not found")
    return data


@app.get("/api/options/report")
def api_options_report(date: str | None = None):
    """返回 CME 期权分析 Markdown 报告原文。"""
    md = get_options_report_md(date)
    if md is None:
        raise HTTPException(status_code=404, detail="Options report not found")
    return {"content": md, "format": "markdown"}


@app.get("/api/options/dates")
def api_options_dates():
    """列出所有已生成报告的日期。"""
    return {"dates": list_options_report_dates()}


@app.get("/api/options/visual-report/latest")
def api_options_visual_report_latest():
    """返回最新 CME visual report HTML。"""
    data = get_options_visual_report_html()
    if data is None:
        raise HTTPException(status_code=404, detail="Options visual report not found")
    return data


@app.get("/api/options/visual-report")
def api_options_visual_report(date: str | None = None, run_id: str | None = None):
    """按日期/run_id 返回 CME visual report HTML。"""
    data = get_options_visual_report_html(date, run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Options visual report not found")
    return data


# ── API: Macro ──


@app.get("/api/macro/latest")
def api_macro_latest():
    """返回最新宏观指标 JSON snapshot。"""
    data = get_macro_latest()
    if data is None:
        raise HTTPException(status_code=404, detail="Macro snapshot not found")
    return data


@app.get("/api/macro/report")
def api_macro_report(date: str | None = None):
    """返回宏观指标 Markdown 报告。"""
    md = get_macro_report_md(date)
    if md is None:
        raise HTTPException(status_code=404, detail="Macro report not found")
    return {"content": md, "format": "markdown"}


# ── API: Tasks ──


@app.get("/api/tasks")
def api_tasks(limit: int = 20):
    """列出最近的任务。"""
    return {"tasks": list_recent_tasks(min(limit, 100))}


@app.get("/api/runs")
def api_runs(limit: int = 20, db: Session = Depends(get_db)):
    """列出最近的任务运行，供 Agent Tasks Run 控制台读取。"""
    runs = task_service.list_task_runs(db, limit=min(limit, 100))
    return {"runs": [run.model_dump(mode="json") for run in runs]}


@app.get("/api/runs/{run_id}", response_model=TaskRunResponse)
def api_run_detail(run_id: str, db: Session = Depends(get_db)) -> TaskRunResponse:
    """按 run_id 返回单次运行详情。"""
    try:
        uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid run_id format")

    run = task_service.get_task_run_response(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@app.get("/api/runs/{run_id}/steps")
def api_run_steps(run_id: str, db: Session = Depends(get_db)):
    """返回某次运行的步骤详情。"""
    try:
        uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid run_id format")

    steps = task_service.get_task_run_steps(db, run_id)
    if steps is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"run_id": run_id, "steps": [step.model_dump(mode="json") for step in steps]}


@app.get("/api/runs/{run_id}/logs")
def api_run_logs(run_id: str, db: Session = Depends(get_db)):
    """返回某次运行的步骤日志兼容结构。"""
    try:
        uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid run_id format")

    logs = task_service.get_task_run_logs(db, run_id)
    if logs is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return logs


@app.get("/api/runs/{run_id}/artifacts")
def api_run_artifacts(run_id: str, db: Session = Depends(get_db)):
    """聚合某次运行的输出产物引用。"""
    try:
        uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid run_id format")

    artifacts = task_service.get_task_run_artifacts(db, run_id)
    if artifacts is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return artifacts


@app.get("/api/artifacts/{artifact_id}", response_model=ArtifactDetailResponse)
def api_artifact_detail(artifact_id: str, db: Session = Depends(get_db)) -> ArtifactDetailResponse:
    """返回单个 registry artifact 的上下文详情。"""
    try:
        uuid.UUID(artifact_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid artifact_id format")

    artifact = get_artifact_detail_response(db, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return artifact


@app.get("/api/runs/{run_id}/events")
def api_run_events(run_id: str, db: Session = Depends(get_db)):
    """返回某次运行的执行事件时间线。"""
    try:
        uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid run_id format")

    run = task_service.get_task_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return get_run_events(db, run_id)


# ── API: Scheduler Center ──


@app.get("/api/scheduler/overview")
def api_scheduler_overview(days: int = 7, limit: int = 50, db: Session = Depends(get_db)):
    """调度中心全景视图：任务运行、数据源状态、产出物。"""
    return get_scheduler_overview(db, days=min(days, 90), limit=min(limit, 200))


@app.post("/api/scheduler/run-all-collectors")
def api_run_all_collectors():
    """手动触发全部数据采集器（异步）。采集结果写入 task_runs。"""
    from apps.api.services.collector_trigger import run_all_collectors_async
    return run_all_collectors_async()


@app.get("/api/source-trace/by-report/{report_id}", response_model=SourceTraceResponse)
def api_source_trace_by_report(report_id: str, db: Session = Depends(get_db)) -> SourceTraceResponse:
    """按 report_id 反查 snapshot/run/artifact 溯源视图。"""
    trace = get_source_trace_by_report_id(db, report_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Source trace not found")
    return trace


@app.get("/api/source-trace/by-strategy/{strategy_card_id}", response_model=SourceTraceResponse)
def api_source_trace_by_strategy(strategy_card_id: str, db: Session = Depends(get_db)) -> SourceTraceResponse:
    """按 strategy_card_id 反查关联 run/snapshot/source/artifact。"""
    trace = get_source_trace_by_strategy_card_id(db, strategy_card_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Source trace not found")
    return trace


@app.get("/api/source-trace/by-artifact/{artifact_id}", response_model=SourceTraceResponse)
def api_source_trace_by_artifact(artifact_id: str, db: Session = Depends(get_db)) -> SourceTraceResponse:
    """按 artifact_id 反查关联 snapshot/source/artifact 溯源视图。"""
    try:
        uuid.UUID(artifact_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid artifact_id format")

    trace = get_source_trace_by_artifact_id(db, artifact_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Source trace not found")
    return trace


@app.get("/api/source-trace/{snapshot_id}", response_model=SourceTraceResponse)
def api_source_trace_detail(snapshot_id: str, db: Session = Depends(get_db)) -> SourceTraceResponse:
    """按 snapshot_id 返回 Phase 3 source trace 只读溯源视图。"""
    trace = get_source_trace_by_snapshot_id(db, snapshot_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Source trace not found")
    return trace


# ── API: Dashboard Summary ──


@app.get("/api/dashboard/summary")
def api_dashboard_summary():
    """返回 Dashboard 聚合摘要。"""
    return get_dashboard_summary()


@app.get("/api/data-sources/status")
def api_data_sources_status():
    """返回数据源 configured/raw/parsed/analysis_ready 四层状态。"""
    return get_data_source_statuses()


@app.get("/api/data-status/summary")
def api_data_status_summary():
    """返回全局数据状态摘要，供前端 DataStatusBar 使用。"""
    return get_data_status_summary()


# ── API: Data Ingestion Actions ──


@app.post("/api/ingestion/sources/{source_key}/retry", response_model=DataSourceActionResponse)
def api_ingestion_source_retry(
    source_key: str,
    body: DataSourceActionRequest | None = None,
    db: Session = Depends(get_db),
) -> DataSourceActionResponse:
    """登记数据源重试请求，返回可追踪 task_run。"""
    return ingestion_action_service.create_ingestion_retry(db, source_key, body)


@app.post("/api/ingestion/sources/{source_key}/test", response_model=DataSourceTestResponse)
def api_ingestion_source_test(
    source_key: str,
    body: DataSourceTestRequest | None = None,
    db: Session = Depends(get_db),
) -> DataSourceTestResponse:
    """执行轻量数据源 probe，返回页面预览并写入 probe 审计。"""
    return ingestion_source_test_service.run_ingestion_source_test(db, source_key, body)


@app.post("/api/ingestion/manual-upload", response_model=DataSourceActionResponse)
def api_ingestion_manual_upload(
    body: ManualUploadRequest,
    db: Session = Depends(get_db),
) -> DataSourceActionResponse:
    """登记手工上传 raw/staging artifact；解析后续必须回主链。"""
    return ingestion_action_service.register_manual_upload(db, body)


# ── API: Review Queue ──


@app.get("/api/reviews")
def api_reviews(
    status: str | None = None,
    source_module: str | None = None,
    run_id: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """列出待人工复核项，供 Review Center / Agent Tasks 读取。"""
    reviews = review_service.list_review_item_responses(
        db,
        status=status,
        source_module=source_module,
        run_id=run_id,
        limit=min(limit, 200),
    )
    return {"reviews": [item.model_dump(mode="json") for item in reviews], "total": len(reviews)}


@app.get("/api/reviews/{review_id}", response_model=ReviewItem)
def api_review_detail(review_id: str, db: Session = Depends(get_db)) -> ReviewItem:
    item = review_service.get_review_item_response(db, review_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Review item not found")
    return item


@app.post("/api/reviews/{review_id}/approve", response_model=ReviewItem)
def api_review_approve(
    review_id: str,
    body: ReviewActionRequest | None = None,
    db: Session = Depends(get_db),
) -> ReviewItem:
    return _resolve_review(review_id, status="approved", action="approve", body=body, db=db)


@app.post("/api/reviews/{review_id}/reject", response_model=ReviewItem)
def api_review_reject(
    review_id: str,
    body: ReviewActionRequest | None = None,
    db: Session = Depends(get_db),
) -> ReviewItem:
    return _resolve_review(review_id, status="rejected", action="reject", body=body, db=db)


@app.post("/api/reviews/{review_id}/rerun", response_model=ReviewItem)
def api_review_rerun(
    review_id: str,
    body: ReviewActionRequest | None = None,
    db: Session = Depends(get_db),
) -> ReviewItem:
    return _resolve_review(review_id, status="rerun", action="rerun", body=body, db=db)


@app.post("/api/reviews/{review_id}/use-fallback", response_model=ReviewItem)
def api_review_use_fallback(
    review_id: str,
    body: ReviewActionRequest | None = None,
    db: Session = Depends(get_db),
) -> ReviewItem:
    return _resolve_review(review_id, status="approved", action="use_fallback", body=body, db=db)


def _resolve_review(
    review_id: str,
    *,
    status: str,
    action: str,
    body: ReviewActionRequest | None,
    db: Session,
) -> ReviewItem:
    try:
        item = review_service.resolve_review_item(
            db,
            review_id,
            status=status,
            resolution_action=action,
            resolution_note=(body.reason or body.note) if body else None,
            resolution_actor=body.actor if body else None,
            resolution_request_id=body.request_id if body else None,
            expected_status=body.expected_status if body else None,
        )
    except review_service.ReviewStatusConflictError as exc:
        raise HTTPException(status_code=409, detail="Review item status conflict") from exc
    if item is None:
        raise HTTPException(status_code=404, detail="Review item not found")
    return item


# ── API: Market Tickers ──


@app.get("/api/market/tickers")
def api_market_tickers():
    """返回市场指标实时快照（XAUUSD/DXY/宏观指标）。"""
    return get_market_tickers()


@app.get("/api/market/monitor")
def api_market_monitor():
    """返回市场监控页只读聚合视图。"""
    return get_market_monitor_overview()


@app.get("/api/market/monitor/history")
def api_market_monitor_history(limit: int = 30, timeframe: str = "1M"):
    """返回市场监控页历史序列。"""
    return get_market_monitor_history(limit=limit, timeframe=timeframe)


# ── API: C4 Final Report ──


@app.get("/api/final-report/latest")
def api_final_report_latest():
    """返回最新的 final_report.md 内容。"""
    data = get_final_report_latest()
    if data is None:
        raise HTTPException(status_code=404, detail="Final report not found")
    return data


@app.get("/api/final-report")
def api_final_report(date: str, run_id: str):
    """按日期和 run_id 返回 final_report.md 内容。"""
    data = get_final_report(date=date, run_id=run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Final report not found")
    return data


# ── API: C4 Strategy Card ──


@app.get("/api/strategy-card/latest")
def api_strategy_card_latest():
    """返回最新的 strategy_card.json + strategy_card.md。"""
    data = get_strategy_card_latest()
    if data is None:
        raise HTTPException(status_code=404, detail="Strategy card not found")
    return data


@app.get("/api/strategy-card")
def api_strategy_card(date: str, run_id: str):
    """按日期和 run_id 返回 strategy_card.json + strategy_card.md。"""
    data = get_strategy_card(date=date, run_id=run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Strategy card not found")
    return data


# ── API: Strategy Cards (read model) ──


@app.get("/api/strategy-cards")
def api_strategy_cards(asset: str = "XAUUSD", limit: int = 20):
    """返回策略卡摘要列表，按最新日期排序。"""
    return list_strategy_cards(asset=asset, limit=limit)


@app.get("/api/strategy-cards/assets", response_model=StrategyAssetListResponse)
def api_strategy_card_assets() -> StrategyAssetListResponse:
    """返回可用于策略校准的资产列表与样本规模。"""
    return list_strategy_assets()


@app.get("/api/strategy-cards/latest")
def api_strategy_cards_latest(asset: str = "XAUUSD"):
    """返回最新策略卡详情（复数 read model）。"""
    data = get_strategy_card_read_model_latest(asset=asset)
    if data is None:
        raise HTTPException(status_code=404, detail="Strategy card not found")
    return data


@app.get("/api/strategy-cards/{strategy_card_id}")
def api_strategy_card_detail(strategy_card_id: str, asset: str = "XAUUSD"):
    """按 strategy_card_id / run_id / snapshot_id 返回策略卡详情。"""
    data = get_strategy_card_by_id(strategy_card_id, asset=asset)
    if data is None:
        raise HTTPException(status_code=404, detail="Strategy card not found")
    return data


# ── Event Flow ──


@app.get("/api/events/flow/overview")
def api_event_flow_overview():
    """返回事件流只读 overview（Jin10 快讯 + 财经日历 + 文章）。"""
    from apps.api.services.event_flow_service import build_event_flow_overview

    return build_event_flow_overview()


@app.get("/api/events/briefs")
def api_event_flow_briefs():
    """返回事件流当日快讯 / 金十文章只读 read model。"""
    from apps.api.services.event_flow_service import build_event_flow_briefs

    return build_event_flow_briefs()


@app.get("/api/events")
def api_event_flow_events():
    """返回事件流事件列表只读 read model。"""
    from apps.api.services.event_flow_service import build_event_flow_events

    return build_event_flow_events()


@app.get("/api/events/report-inputs")
def api_event_flow_report_inputs():
    """返回事件流报告输入只读 read model。"""
    from apps.api.services.event_flow_service import build_event_flow_report_inputs

    return build_event_flow_report_inputs()


@app.get("/api/events/{event_id}")
def api_event_flow_event_detail(event_id: str):
    """返回单条事件详情 read model。"""
    from apps.api.services.event_flow_service import build_event_flow_event_detail

    data = build_event_flow_event_detail(event_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return data


@app.get("/api/events/{event_id}/impact")
def api_event_flow_event_impact(event_id: str):
    """返回单条事件影响分析 read model。"""
    from apps.api.services.event_flow_service import build_event_flow_impact

    data = build_event_flow_impact(event_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return data


@app.get("/api/events/{event_id}/market-reaction")
def api_event_flow_event_market_reaction(event_id: str):
    """返回单条事件行情反应 read model。"""
    from apps.api.services.event_flow_service import build_event_flow_market_reaction

    data = build_event_flow_market_reaction(event_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return data


@app.post("/api/events/briefs/{brief_id}/link", response_model=EventFlowActionResponse)
def api_event_flow_brief_link(
    brief_id: str,
    body: EventFlowBriefLinkRequest,
    db: Session = Depends(get_db),
) -> EventFlowActionResponse:
    """登记 brief -> event 归并请求。"""
    return event_flow_action_service.register_brief_link(db, brief_id, body)


@app.post("/api/events/briefs/{brief_id}/ignore", response_model=EventFlowActionResponse)
def api_event_flow_brief_ignore(
    brief_id: str,
    body: EventFlowActionRequest,
    db: Session = Depends(get_db),
) -> EventFlowActionResponse:
    """登记 brief 忽略请求。"""
    return event_flow_action_service.register_brief_ignore(db, brief_id, body)


@app.post("/api/events/report-inputs/{input_id}/include", response_model=EventFlowActionResponse)
def api_event_flow_report_input_include(
    input_id: str,
    body: EventFlowActionRequest,
    db: Session = Depends(get_db),
) -> EventFlowActionResponse:
    """登记 report input 纳入请求。"""
    return event_flow_action_service.register_report_input_include(db, input_id, body)


@app.post("/api/events/report-inputs/{input_id}/exclude", response_model=EventFlowActionResponse)
def api_event_flow_report_input_exclude(
    input_id: str,
    body: EventFlowActionRequest,
    db: Session = Depends(get_db),
) -> EventFlowActionResponse:
    """登记 report input 排除请求。"""
    return event_flow_action_service.register_report_input_exclude(db, input_id, body)


@app.post("/api/events/{event_id}/review", response_model=EventFlowActionResponse)
def api_event_flow_event_review(
    event_id: str,
    body: EventFlowActionRequest,
    db: Session = Depends(get_db),
) -> EventFlowActionResponse:
    """登记单事件人工复核请求。"""
    return event_flow_action_service.register_event_review(db, event_id, body)


# ── Knowledge Base ──


@app.get("/api/knowledge/items")
def api_knowledge_items():
    """返回知识库只读列表。"""
    from apps.api.services.knowledge_service import build_knowledge_items

    return build_knowledge_items()


@app.get("/api/knowledge/items/{item_id}")
def api_knowledge_item(item_id: str):
    """返回单条知识详情。"""
    from apps.api.services.knowledge_service import build_knowledge_item

    data = build_knowledge_item(item_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Knowledge item not found")
    return data


# ── Playbook Registry ──


@app.post("/api/playbooks", response_model=PlaybookTemplateVersion)
def api_create_playbook(
    body: PlaybookTemplateCreateRequest,
    db: Session = Depends(get_db),
) -> PlaybookTemplateVersion:
    """登记新的 Playbook 模板版本。"""
    try:
        return playbook_service.create_playbook_template(db, body)
    except playbook_service.PlaybookConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/playbooks", response_model=PlaybookTemplateListResponse)
def api_playbooks(db: Session = Depends(get_db)) -> PlaybookTemplateListResponse:
    """返回 Playbook 模板最新版本列表。"""
    return playbook_service.list_playbook_templates(db)


@app.get("/api/playbooks/{playbook_id}", response_model=PlaybookTemplateDetailResponse)
def api_playbook_detail(playbook_id: str, db: Session = Depends(get_db)) -> PlaybookTemplateDetailResponse:
    """返回单个 Playbook 模板族的最新版本和历史版本。"""
    data = playbook_service.get_playbook_template_detail(db, playbook_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Playbook template not found")
    return data


@app.get("/api/playbooks/{playbook_id}/versions", response_model=PlaybookTemplateListResponse)
def api_playbook_versions(playbook_id: str, db: Session = Depends(get_db)) -> PlaybookTemplateListResponse:
    """返回单个 Playbook 模板族的版本列表。"""
    versions = playbook_service.list_playbook_template_versions(db, playbook_id)
    return PlaybookTemplateListResponse(items=versions, total=len(versions))


# ── Settings ──


@app.get("/api/settings/status")
def api_settings_status(db: Session = Depends(get_db)):
    """返回配置状态概览（密钥已脱敏）。"""
    return settings_service.build_settings_status(db=db)


@app.post("/api/settings/preferences", response_model=SettingsActionResponse)
def api_settings_update_preferences(
    body: SettingsPreferencesUpdateRequest,
    db: Session = Depends(get_db),
) -> SettingsActionResponse:
    """写入非敏感全局偏好配置。"""
    try:
        return settings_service.update_preferences(db, body)
    except settings_service.SettingsValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/settings/preferences/reset", response_model=SettingsActionResponse)
def api_settings_reset_preferences(
    body: SettingsPreferencesResetRequest,
    db: Session = Depends(get_db),
) -> SettingsActionResponse:
    """将指定全局偏好回退为默认值。"""
    try:
        return settings_service.reset_preferences(db, body)
    except settings_service.SettingsValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/settings/sources/{source_key}", response_model=SettingsActionResponse)
def api_settings_update_source(
    source_key: str,
    body: SettingsSourceUpdateRequest,
    db: Session = Depends(get_db),
) -> SettingsActionResponse:
    """写入数据源 enable/disable 请求，不改变 runtime connectivity 检测。"""
    try:
        return settings_service.update_source_enabled(db, source_key, body)
    except settings_service.SettingsSourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Settings source not found") from exc


@app.post("/api/settings/sources/{source_key}/reset", response_model=SettingsActionResponse)
def api_settings_reset_source(
    source_key: str,
    body: SettingsSourceResetRequest,
    db: Session = Depends(get_db),
) -> SettingsActionResponse:
    """清除数据源 enable/disable overlay，回退到默认检测值。"""
    try:
        return settings_service.reset_source_enabled(db, source_key, body)
    except settings_service.SettingsSourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Settings source not found") from exc
    except settings_service.SettingsValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/settings/secrets/{source_key}", response_model=SettingsActionResponse)
def api_settings_update_secret(
    source_key: str,
    body: SettingsSecretUpdateRequest,
    db: Session = Depends(get_db),
) -> SettingsActionResponse:
    """写入加密 secret storage，仅回显 masked/configured 元数据。"""
    try:
        return settings_service.update_secret(db, source_key, body)
    except settings_service.SettingsSourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Settings source not found") from exc
    except settings_service.SettingsValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except settings_service.SettingsSecretStorageNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail="Settings secret storage is not configured") from exc


@app.post("/api/settings/secrets/{source_key}/reset", response_model=SettingsActionResponse)
def api_settings_reset_secret(
    source_key: str,
    body: SettingsSecretResetRequest,
    db: Session = Depends(get_db),
) -> SettingsActionResponse:
    """清除加密 secret storage 中保存的密钥。"""
    try:
        return settings_service.reset_secret(db, source_key, body)
    except settings_service.SettingsSourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Settings source not found") from exc
    except settings_service.SettingsValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/settings/history", response_model=SettingsHistoryResponse)
def api_settings_history(
    limit: int = 50,
    setting_key: str | None = None,
    source_key: str | None = None,
    scope: str | None = None,
    action: str | None = None,
    actor: str | None = None,
    q: str | None = None,
    days: int | None = None,
    db: Session = Depends(get_db),
) -> SettingsHistoryResponse:
    """返回 Settings 最近配置变更历史。"""
    return settings_service.build_settings_history(
        db,
        limit=limit,
        setting_key=setting_key,
        source_key=source_key,
        scope=scope,
        action=action,
        actor=actor,
        q=q,
        days=days,
    )


@app.post("/api/settings/history/{audit_id}/rollback", response_model=SettingsActionResponse)
def api_settings_rollback_history_event(
    audit_id: str,
    body: SettingsRollbackRequest,
    db: Session = Depends(get_db),
) -> SettingsActionResponse:
    """按历史 audit_id 回滚非敏感设置。"""
    try:
        return settings_service.rollback_settings_event(db, audit_id, body)
    except settings_service.SettingsHistoryEventNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Settings history event not found") from exc
    except settings_service.SettingsValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/jin10/daily-report/latest")
def api_jin10_daily_report_latest():
    """返回最新的 Jin10 黄金每日报告。"""
    data = get_jin10_daily_report_latest()
    if data is None:
        raise HTTPException(status_code=404, detail="Jin10 daily report not found")
    return data


@app.get("/api/jin10/daily-report")
def api_jin10_daily_report(date: str, run_id: str):
    """按日期和 run_id 返回 Jin10 黄金每日报告。"""
    data = get_jin10_daily_report(date=date, run_id=run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Jin10 daily report not found")
    return data


@app.get("/api/jin10/weekly-report/latest")
def api_jin10_weekly_report_latest():
    """返回最新的 Jin10 黄金周报。"""
    data = get_jin10_weekly_report_latest()
    if data is None:
        raise HTTPException(status_code=404, detail="Jin10 weekly report not found")
    return data


@app.get("/api/jin10/weekly-report")
def api_jin10_weekly_report(date: str, run_id: str):
    """按日期和 run_id 返回 Jin10 黄金周报。"""
    data = get_jin10_weekly_report(date=date, run_id=run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Jin10 weekly report not found")
    return data


@app.get("/api/jin10/report-bundle/latest")
def api_jin10_report_bundle_latest():
    """返回最新的 Jin10 报告 bundle，默认优先 Agent 分析。"""
    data = get_jin10_report_bundle_latest()
    if data is None:
        raise HTTPException(status_code=404, detail="Jin10 report bundle not found")
    return data


@app.get("/api/jin10/report-bundle")
def api_jin10_report_bundle(date: str, run_id: str):
    """按日期和 run_id 返回 Jin10 报告 bundle。"""
    data = get_jin10_report_bundle(date=date, run_id=run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Jin10 report bundle not found")
    return data


@app.get("/api/jin10/report-bundle/{date}/{run_id}/asset/{asset_path:path}")
def api_jin10_report_bundle_asset(date: str, run_id: str, asset_path: str):
    """返回 Jin10 bundle 下的相对资源文件（图表、图片等）。"""
    path = get_jin10_report_bundle_asset_path(date=date, run_id=run_id, asset_path=asset_path)
    if path is None:
        raise HTTPException(status_code=404, detail="Jin10 report asset not found")
    return FileResponse(path)


@app.get("/api/jin10/article-briefs/latest")
def api_jin10_article_briefs_latest():
    """返回最新的 Jin10 文章小快讯 read model。"""
    data = get_jin10_article_briefs_latest()
    if data is None:
        raise HTTPException(status_code=404, detail="Jin10 article briefs not found")
    return data


@app.get("/api/jin10/article-briefs")
def api_jin10_article_briefs(date: str, run_id: str):
    """按日期和 run_id 返回 Jin10 文章小快讯 read model。"""
    data = get_jin10_article_briefs(date=date, run_id=run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Jin10 article briefs not found")
    return data


@app.get("/api/news/daily-analysis-triggers/latest")
def api_daily_analysis_triggers_latest():
    """返回最新的 daily analysis triggers read model。"""
    data = get_daily_analysis_triggers_latest()
    if data is None:
        raise HTTPException(status_code=404, detail="Daily analysis triggers not found")
    return data


@app.get("/api/news/daily-analysis-triggers")
def api_daily_analysis_triggers(date: str, run_id: str):
    """按日期和 run_id 返回 daily analysis triggers read model。"""
    data = get_daily_analysis_triggers(date=date, run_id=run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Daily analysis triggers not found")
    return data


@app.get("/api/news/daily-brief/latest")
def api_daily_brief_latest():
    """返回最新的稳定日报 read model。"""
    data = get_daily_brief_latest()
    if data is None:
        raise HTTPException(status_code=404, detail="Daily brief not found")
    return data


@app.get("/api/news/daily-brief")
def api_daily_brief(date: str, run_id: str):
    """按日期和 run_id 返回稳定日报 read model。"""
    data = get_daily_brief(date=date, run_id=run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Daily brief not found")
    return data


@app.get("/api/news/daily-analysis-followups/latest")
def api_daily_analysis_followups_latest():
    """返回最新的 daily analysis follow-up queue read model。"""
    data = get_daily_analysis_followups_latest()
    if data is None:
        raise HTTPException(status_code=404, detail="Daily analysis followups not found")
    return data


@app.get("/api/news/daily-analysis-followups")
def api_daily_analysis_followups(date: str, run_id: str):
    """按日期和 run_id 返回 daily analysis follow-up queue read model。"""
    data = get_daily_analysis_followups(date=date, run_id=run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Daily analysis followups not found")
    return data


@app.post("/api/news/daily-analysis-followups/tasks")
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


@app.get("/api/news/feishu-jin10/messages")
def api_feishu_jin10_message_monitor(date: str, db: Session = Depends(get_db)):
    """返回指定日期的 Feishu 金十消息采集与后续纳入状态清单。"""
    data = get_feishu_jin10_message_monitor(date=date, db=db)
    return data


# ── API: Jin10 MCP Quotes & Snapshot ──


def _jin10_unavailable(reason: str) -> dict:
    return {
        "status": "unavailable",
        "reason": reason,
        "quotes": {},
        "counts": {},
        "kline_codes": [],
    }


@app.get("/api/jin10/quotes/latest")
def api_jin10_quotes_latest():
    """返回最新的金十实时报价快照（来自 Analysis Snapshot 的 jin10 分区）。

    从最新的 premarket_snapshot.json 中提取 jin10 字段，
    包含实时行情报价、快讯/文章计数、K 线代码等。
    """
    import json

    storage_root = Path("./storage")
    snap_dir = storage_root / "features" / "snapshots" / "XAUUSD"
    if not snap_dir.exists():
        return _jin10_unavailable("No snapshots directory found")

    # Find latest date directory
    date_dirs = sorted(
        [d for d in snap_dir.iterdir() if d.is_dir()],
        reverse=True,
    )
    if not date_dirs:
        return _jin10_unavailable("No snapshot dates found")

    # Find latest run_id directory
    for date_dir in date_dirs:
        run_dirs = sorted(
            [d for d in date_dir.iterdir() if d.is_dir()],
            reverse=True,
        )
        for run_dir in run_dirs:
            snap_path = run_dir / "premarket_snapshot.json"
            if not snap_path.exists():
                continue
            try:
                snap = json.loads(snap_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            jin10_section = snap.get("jin10")
            if jin10_section:
                return jin10_section

    return _jin10_unavailable("Jin10 section not yet populated in analysis snapshot.")


@app.get("/api/jin10/calendar")
def api_jin10_calendar():
    """返回 Jin10 经济日历（高影响力 + 未来事件）。"""
    cache_path = Path("./storage/outputs/jin10/calendar_cache.json")
    if not cache_path.exists():
        try:
            from apps.scheduler.jin10_refresh import refresh_jin10_calendar_cache

            refresh_jin10_calendar_cache()
        except Exception:
            pass
    if not cache_path.exists():
        return {"status": "unavailable", "events": [], "message": "Calendar data not available"}
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        return data
    except Exception as exc:
        return {"status": "error", "events": [], "message": str(exc)}


@app.get("/api/jin10/flash")
def api_jin10_flash():
    """返回 Jin10 最新快讯。"""
    cache_path = _JIN10_FLASH_CACHE_PATH
    if not cache_path.exists() or _is_file_stale(cache_path, max_age_seconds=_JIN10_FLASH_CACHE_MAX_AGE_SECONDS):
        try:
            from apps.scheduler.jin10_refresh import refresh_jin10_flash_cache

            refresh_jin10_flash_cache()
        except Exception:
            pass
    if not cache_path.exists():
        return {"status": "unavailable", "items": [], "message": "Flash news not available"}
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        return data
    except Exception as exc:
        return {"status": "error", "items": [], "message": str(exc)}


def _is_file_stale(path: Path, *, max_age_seconds: int) -> bool:
    try:
        age_seconds = time.time() - path.stat().st_mtime
    except OSError:
        return True
    return age_seconds > max_age_seconds


@app.get("/api/jin10/kline")
def api_jin10_kline(
    symbol: str = "XAUUSD",
    timeframe: str = "1m",
    limit: int = 200,
):
    """返回 Jin10 K 线数据（从 market_candles 表读取），支持多周期聚合。"""
    from database.models.engine import SessionLocal
    from database.queries.market import list_market_candles

    VALID_TIMEFRAMES = {"1m", "5m", "15m", "30m", "1h", "4h", "1D"}
    if timeframe not in VALID_TIMEFRAMES:
        timeframe = "1m"

    if limit < 1 or limit > 1000:
        limit = max(1, min(limit, 1000))

    try:
        with SessionLocal() as session:
            # 默认用 Jin10 MCP 实时现货，不足时回退 Yahoo 期货
            kline_source = "jin10_mcp_kline_1m"
            if timeframe == "1m":
                rows = list_market_candles(session, asset=symbol, timeframe="1m", limit=limit, source=kline_source)
                if not rows:
                    rows = list_market_candles(session, asset=symbol, timeframe="1m", limit=limit, source="yahoo_finance_1m")
                candles = [_candle_to_dict(row) for row in rows]
            else:
                # 聚合：先用现货，不足再用期货
                fetch_limit = _aggregation_fetch_limit(timeframe, limit)
                rows = list_market_candles(session, asset=symbol, timeframe="1m", limit=fetch_limit, source=kline_source)
                if not rows:
                    rows = list_market_candles(session, asset=symbol, timeframe="1m", limit=fetch_limit, source="yahoo_finance_1m")
                candles = _aggregate_candles(rows, timeframe)[-limit:]

            return {
                "symbol": symbol,
                "timeframe": timeframe,
                "count": len(candles),
                "candles": candles,
            }
    except Exception as exc:
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "count": 0,
            "candles": [],
            "error": str(exc),
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


# ── API: Reports Index ──


@app.get("/api/reports/index")
def api_reports_index():
    """返回所有报告类型的索引列表。"""
    return list_reports_index()


@app.get("/api/reports/dates")
def api_reports_dates():
    """返回所有可用 trade_date 及其模块覆盖。"""
    return list_unified_dates()


@app.get("/api/reports/{report_id}", response_model=ReportDetail)
def api_report_detail(report_id: str, db: Session = Depends(get_db)) -> ReportDetail:
    """返回标准报告详情；优先读新 report tables，其次走 legacy adapter。"""
    detail = get_report_detail(db, report_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return detail


@app.get("/api/reports/{report_id}/artifacts", response_model=list[ReportArtifact])
def api_report_artifacts(report_id: str, db: Session = Depends(get_db)) -> list[ReportArtifact]:
    artifacts = get_report_artifacts(db, report_id)
    if artifacts is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return artifacts


@app.get("/api/reports/{report_id}/source")
def api_report_source(report_id: str, db: Session = Depends(get_db)):
    payload = get_report_source(db, report_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Report artifact not found")
    return payload


@app.get("/api/reports/{report_id}/analysis")
def api_report_analysis(report_id: str, db: Session = Depends(get_db)):
    payload = get_report_analysis(db, report_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Report artifact not found")
    return payload


@app.get("/api/reports/{report_id}/visual")
def api_report_visual(report_id: str, db: Session = Depends(get_db)):
    payload = get_report_visual(db, report_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Report artifact not found")
    return payload


@app.get("/api/reports/{report_id}/evidence")
def api_report_evidence(report_id: str, db: Session = Depends(get_db)):
    payload = get_report_evidence(db, report_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Report artifact not found")
    return payload


@app.get("/api/reports/{report_id}/analysis-inputs", response_model=ReportAnalysisInputs)
def api_report_analysis_inputs(report_id: str, db: Session = Depends(get_db)):
    payload = get_report_analysis_inputs(db, report_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Report analysis inputs not found")
    return payload


# ── API: Market Odds (P4-09) ──


@app.get("/api/market-odds/snapshot")
def api_market_odds_snapshot(date: str | None = None, run_id: str | None = None):
    """返回 market_odds section from analysis snapshot."""
    data = get_market_odds_snapshot(date_str=date, run_id=run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Market odds snapshot not found")
    return data


@app.get("/api/market-odds/report")
def api_market_odds_report(date: str | None = None, run_id: str | None = None):
    """返回 market_odds 结构化报告摘要。无数据时返回 unavailable 状态而非 404."""
    return get_market_odds_report(date_str=date, run_id=run_id)


# ── Agent Analysis unified endpoint ──


@app.get("/api/agent-analysis/latest")
def api_agent_analysis_latest():
    """返回最新日期的全部 agent 分析结果。

    从 agent_outputs 表读取，按 agent_name 分组返回。
    如果某 agent 无数据则返回 unavailable 状态。
    """
    from database.models.analysis import AgentOutput
    from database.models.engine import SessionLocal

    with SessionLocal() as db:
        # Find latest trade_date
        latest_date = db.query(func.max(AgentOutput.trade_date)).scalar()
        if not latest_date:
            return _empty_agent_analysis()

        return _build_agent_analysis_response(db, latest_date)


@app.get("/api/agents/registry")
def api_agents_registry():
    """返回 Agent 注册表与可审查 Prompt 模板。

    该接口只用于配置治理、Prompt 复核和开发调试；业务页面仍应消费页面级 read model。
    """
    from apps.analysis.agents.registry import build_agent_registry_response

    return build_agent_registry_response()


@app.get("/api/agents/registry/{agent_id}")
def api_agent_registry_detail(agent_id: str):
    """返回单个 Agent 的注册信息与 Prompt 模板。"""
    from apps.analysis.agents.registry import get_agent_registry

    agent = get_agent_registry(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent registry entry not found: {agent_id}")
    return agent


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


@app.get("/api/agents/prompts")
def api_prompt_versions_list(agent_id: str | None = None, status: str | None = None, db: Session = Depends(get_db)):
    """列出 prompt 版本记录。

    可选过滤：agent_id（按 Agent 筛选）、status（active/draft/deprecated）。
    """
    from database.models.analysis import PromptVersion

    query = db.query(PromptVersion).order_by(desc(PromptVersion.created_at))
    if agent_id:
        query = query.filter(PromptVersion.agent_id == agent_id)
    if status:
        query = query.filter(PromptVersion.status == status)

    rows = query.all()
    return {
        "source": "prompt_versions",
        "count": len(rows),
        "versions": [_prompt_version_item(r) for r in rows],
    }


@app.get("/api/agents/prompts/{agent_id}")
def api_prompt_versions_by_agent(agent_id: str, db: Session = Depends(get_db)):
    """返回某个 Agent 的所有 prompt 版本记录。"""
    from database.models.analysis import PromptVersion

    rows = (
        db.query(PromptVersion)
        .filter(PromptVersion.agent_id == agent_id)
        .order_by(desc(PromptVersion.created_at))
        .all()
    )
    if not rows:
        # fallback to registry for metadata
        from apps.analysis.agents.registry import get_agent_registry

        agent = get_agent_registry(agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
        return {
            "agent_id": agent_id,
            "name": agent["name"],
            "source": "prompt_versions",
            "count": 0,
            "versions": [],
            "note": "尚无持久化 prompt 版本，将在首次运行后自动落库。",
        }

    return {
        "agent_id": agent_id,
        "name": rows[0].agent_id,
        "source": "prompt_versions",
        "count": len(rows),
        "versions": [_prompt_version_item(r) for r in rows],
    }


@app.get("/api/agents/prompts/{agent_id}/active")
def api_prompt_versions_active(agent_id: str, db: Session = Depends(get_db)):
    """返回某个 Agent 当前激活的 prompt 版本。"""
    from database.models.analysis import PromptVersion

    row = (
        db.query(PromptVersion)
        .filter(PromptVersion.agent_id == agent_id, PromptVersion.status == "active", PromptVersion.enabled.is_(True))
        .order_by(desc(PromptVersion.created_at))
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"No active prompt version for agent: {agent_id}")
    return _prompt_version_item(row)


@app.post("/api/agents/prompts/{agent_id}")
def api_prompt_versions_create(
    agent_id: str,
    payload: PromptVersionCreate,
    db: Session = Depends(get_db),
):
    """为某个 Agent 创建新 prompt 版本。

    新版本默认 status=draft；旧 active 版本不会被自动禁用。
    """
    import hashlib  # noqa: E402
    import json  # noqa: E402

    from database.models.analysis import PromptVersion

    # Validate agent exists
    from apps.analysis.agents.registry import get_agent_registry

    agent = get_agent_registry(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    _validate_prompt_version_create_payload(payload)

    template_raw = json.dumps(payload.prompt_template, sort_keys=True, ensure_ascii=False)
    sha = hashlib.sha256(template_raw.encode()).hexdigest()

    # Determine next version label
    latest = (
        db.query(PromptVersion)
        .filter(PromptVersion.agent_id == agent_id)
        .order_by(desc(PromptVersion.created_at))
        .first()
    )
    if latest and latest.version.startswith("v"):
        try:
            latest_num = int(latest.version[1:])
            next_version = f"v{latest_num + 1}"
        except ValueError:
            next_version = "v2"
    else:
        next_version = "v1"

    pv = PromptVersion(
        id=str(uuid.uuid4()),
        agent_id=agent_id,
        version=next_version,
        prompt_kind=payload.prompt_kind or "llm",
        prompt_source=payload.prompt_source,
        prompt_template=payload.prompt_template,
        prompt_sha256=sha,
        status=payload.status or "draft",
        enabled=payload.enabled if payload.enabled is not None else True,
        model_routing=payload.model_routing,
        change_note=payload.change_note,
        created_by=payload.created_by,
        request_id=payload.request_id,
    )
    db.add(pv)
    db.commit()
    db.refresh(pv)
    return _prompt_version_item(pv)


@app.patch("/api/agents/prompts/{agent_id}/activate")
def api_prompt_versions_activate(
    agent_id: str,
    payload: PromptVersionActivate,
    db: Session = Depends(get_db),
):
    """激活某个 Agent 的指定版本，同时停用该 Agent 所有其他版本。"""
    from database.models.analysis import PromptVersion

    target = (
        db.query(PromptVersion)
        .filter(PromptVersion.agent_id == agent_id, PromptVersion.version == payload.version)
        .first()
    )
    if target is None:
        raise HTTPException(
            status_code=404,
            detail=f"Version not found: {agent_id} {payload.version}",
        )

    # Deactivate all versions for this agent, then activate the target
    db.query(PromptVersion).filter(PromptVersion.agent_id == agent_id).update(
        {"status": "deprecated" if PromptVersion.status != "deprecated" else "deprecated"},
    )
    target.status = "active"
    target.enabled = True
    if payload.reason:
        target.change_note = (target.change_note or "") + f"\n激活: {payload.reason}"
    db.commit()
    db.refresh(target)
    return _prompt_version_item(target)


# ── P2-11 Prompt Feedback API ──


@app.post("/api/agents/feedback")
def api_prompt_feedback_create(payload: PromptFeedbackCreate, db: Session = Depends(get_db)):
    """提交人工反馈（P2-11）。

    反馈永远是追加记录，不修改历史 AgentOutput。
    严重反馈可自动创建 ReviewItem 进行跟踪。
    """
    from database.models.analysis import PromptFeedback

    feedback = PromptFeedback(
        id=str(uuid.uuid4()),
        feedback_id=f"fb-{uuid.uuid4().hex[:12]}",
        agent_output_id=payload.agent_output_id,
        agent_id=payload.agent_id,
        prompt_version_id=payload.prompt_version_id,
        run_id=payload.run_id,
        rating=payload.rating,
        category=payload.category or "prompt_quality",
        comment=payload.comment,
        suggested_changes=payload.suggested_changes,
        status="open",
        submitted_by=payload.submitted_by,
        request_id=payload.request_id,
    )
    db.add(feedback)

    # Auto-create ReviewItem for severe feedback
    review_item: dict[str, Any] | None = None
    severe_categories = {"analysis_error", "missing_context"}
    if payload.category in severe_categories and payload.agent_output_id:
        from database.models.analysis import ReviewItem as _ReviewItem

        review = _ReviewItem(
            id=str(uuid.uuid4()),
            review_id=f"rv-{uuid.uuid4().hex[:12]}",
            run_id=payload.run_id,
            source_module="prompt_feedback",
            agent_output_id=payload.agent_output_id,
            severity="warning",
            reason=f"[{payload.category}] {payload.comment or '(无评注)'}",
            impact_modules=[],
            impact_report_ids=[],
            source_refs=[],
            evidence_refs=[],
            suggested_action="请人工审查反馈并决定是否需要调整 Prompt 或重新运行分析。",
            status="pending",
        )
        db.add(review)
        db.flush()
        feedback.review_item_id = review.review_id
        review_item = {
            "review_id": review.review_id,
            "status": review.status,
            "severity": review.severity,
        }

    db.commit()
    db.refresh(feedback)

    result = _prompt_feedback_item(feedback)
    if review_item:
        result["review_item"] = review_item
    return result


@app.get("/api/agents/feedback/{agent_id}")
def api_prompt_feedback_by_agent(
    agent_id: str,
    status: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """按 Agent 查询反馈记录。"""
    from database.models.analysis import PromptFeedback

    query = db.query(PromptFeedback).filter(PromptFeedback.agent_id == agent_id)
    if status:
        query = query.filter(PromptFeedback.status == status)
    query = query.order_by(desc(PromptFeedback.created_at)).limit(limit)

    rows = query.all()
    return {
        "agent_id": agent_id,
        "source": "prompt_feedback",
        "count": len(rows),
        "feedback": [_prompt_feedback_item(r) for r in rows],
    }


@app.get("/api/agents/feedback")
def api_prompt_feedback_list(
    agent_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """列出所有反馈记录，可选按 agent/status 过滤。"""
    from database.models.analysis import PromptFeedback

    query = db.query(PromptFeedback)
    if agent_id:
        query = query.filter(PromptFeedback.agent_id == agent_id)
    if status:
        query = query.filter(PromptFeedback.status == status)
    query = query.order_by(desc(PromptFeedback.created_at)).limit(limit)

    rows = query.all()
    return {
        "source": "prompt_feedback",
        "count": len(rows),
        "feedback": [_prompt_feedback_item(r) for r in rows],
    }


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


@app.get("/api/agent-analysis")
def api_agent_analysis_by_date(date: str | None = None, run_id: str | None = None):
    """按日期返回 agent 分析结果。"""
    from database.models.analysis import AgentOutput
    from database.models.engine import SessionLocal

    with SessionLocal() as db:
        if date:
            from datetime import date as date_type

            try:
                target_date = date_type.fromisoformat(date)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid date format: {date}")
        else:
            latest = db.query(func.max(AgentOutput.trade_date)).scalar()
            if not latest:
                return _empty_agent_analysis()
            target_date = latest

        return _build_agent_analysis_response(db, target_date, run_id=run_id)


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


@app.get("/api/agent-analysis/inspect")
def api_agent_analysis_inspect(
    date: str | None = None,
    run_id: str | None = None,
):
    """返回 Agent 分析的 prompt/input/output 只读检查视图。

    该接口面向 Agent Tasks / 审计 / 人工纠偏，不作为业务页面 read model。
    历史 AgentOutput 若未记录 prompt，会显式返回 prompt.available=false。
    """
    from database.models.analysis import AgentOutput
    from database.models.engine import SessionLocal

    with SessionLocal() as db:
        if date:
            from datetime import date as date_type

            try:
                target_date = date_type.fromisoformat(date)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid date format: {date}")
        else:
            latest = db.query(func.max(AgentOutput.trade_date)).scalar()
            if not latest:
                return {
                    "trade_date": None,
                    "run_id": run_id,
                    "snapshot_id": None,
                    "agents": [],
                    "source": "agent_outputs",
                }
            target_date = latest

        return _build_agent_analysis_inspection(db, target_date, run_id=run_id)


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


@app.get("/api/agent-analysis/synthesis/latest")
def api_agent_analysis_synthesis_latest(
    date: str | None = None,
    run_id: str | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from database.models.analysis import AgentOutput

    query = (
        db.query(AgentOutput).filter(AgentOutput.agent_name == "synthesis_agent").order_by(desc(AgentOutput.created_at))
    )
    if run_id:
        query = query.filter(AgentOutput.run_id == run_id)
    if date:
        query = query.filter(AgentOutput.trade_date == date)

    row = query.first()
    if row is None:
        raise HTTPException(status_code=404, detail="No synthesis agent output found")
    return build_agent_output_summary(row)


@app.post("/api/agent-analysis/run")
def api_run_agent_analysis(
    agent: str = "all",
    date: str | None = None,
    force: bool = False,
):
    """手动触发 agent 分析。

    agent: "market_regime" | "event_impact" | "jin10_daily" | "cme_options" | "all"
    """

    target_date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if agent in ("market_regime", "all"):
        _run_market_regime_async(target_date)
    if agent in ("event_impact", "all"):
        _run_event_impact_async(target_date)

    return {"status": "dispatched", "agent": agent, "date": target_date}


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


@app.get("/assets/{asset_path:path}")
def serve_frontend_asset(asset_path: str) -> FileResponse:
    asset = _resolve_frontend_asset(asset_path)
    if asset is None:
        raise HTTPException(status_code=404, detail="Frontend asset not found")
    return FileResponse(asset)


@app.get("/favicon.svg")
def serve_frontend_favicon() -> FileResponse:
    asset = _resolve_frontend_root_asset("favicon.svg")
    if asset is None:
        raise HTTPException(status_code=404, detail="Frontend favicon not found")
    return FileResponse(asset, media_type="image/svg+xml")


@app.get("/dashboard")
def serve_dashboard():
    """本地稳定模式优先直接提供前端构建产物；dist 缺失时回退到 Vite。"""
    return _serve_frontend_entry("/dashboard")


@app.get("/dashboard/analysis")
def serve_dashboard_analysis():
    return _serve_frontend_entry("/dashboard/analysis")


@app.get("/data-ingestion")
def serve_data_ingestion():
    return _serve_frontend_entry("/data-ingestion")


@app.get("/data-sources/{path:path}")
def serve_data_sources_subpath(path: str):
    return _serve_frontend_entry(f"/data-sources/{path}")


@app.get("/market-monitor")
def serve_market_monitor():
    return _serve_frontend_entry("/market-monitor")


@app.get("/cme-options")
def serve_cme_options():
    return _serve_frontend_entry("/cme-options")


@app.get("/reports")
def serve_reports():
    return _serve_frontend_entry("/reports")


@app.get("/reports/{path:path}")
def serve_reports_subpath(path: str):
    return _serve_frontend_entry(f"/reports/{path}")


@app.get("/event-flow")
def serve_event_flow():
    return _serve_frontend_entry("/event-flow")


@app.get("/event-flow/{path:path}")
def serve_event_flow_subpath(path: str):
    return _serve_frontend_entry(f"/event-flow/{path}")


@app.get("/knowledge-base")
def serve_knowledge_base():
    return _serve_frontend_entry("/knowledge-base")


@app.get("/agent-tasks")
def serve_agent_tasks():
    return _serve_frontend_entry("/scheduler")


@app.get("/scheduler")
def serve_scheduler():
    return _serve_frontend_entry("/scheduler")


@app.get("/scheduler/{path:path}")
def serve_scheduler_subpath(path: str):
    return _serve_frontend_entry(f"/scheduler/{path}")


@app.get("/agent-tasks/{path:path}")
def serve_agent_tasks_subpath(path: str):
    return _serve_frontend_entry(f"/agent-tasks/{path}")


@app.get("/review-center")
def serve_review_center():
    return _serve_frontend_entry("/review-center")


@app.get("/settings")
def serve_settings():
    return _serve_frontend_entry("/settings")


@app.get("/settings/audit")
def serve_settings_audit():
    return _serve_frontend_entry("/settings/audit")


@app.get("/dashboard/system-status")
def system_status(db: Session = Depends(get_db)) -> dict:
    """返回轻量系统状态摘要（MVP 静态状态，非实时生产监控）。

    DB 可用时尝试列出最近 5 条任务；不可用时 recent_tasks 为空且 db_available=false。
    """
    recent_tasks: list[dict] = []
    db_available = False
    if _database_reachable():
        try:
            tasks = db.query(TaskRun).order_by(TaskRun.created_at.desc()).limit(5).all()
            recent_tasks = [
                {
                    "id": str(t.id),
                    "name": t.name,
                    "status": t.status.value,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                }
                for t in tasks
            ]
            db_available = True
        except Exception:
            db_available = False

    return {
        "service": "finance-agent",
        "version": _get_version(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db_available": db_available,
        "recent_tasks": recent_tasks,
        "phases": _get_phases(),
        "production_chain": [
            "api",
            "scheduler",
            "worker",
            "collectors",
            "parsers",
            "features",
            "analysis",
            "renderer",
            "output",
        ],
        "limitations": {
            "mvp_readonly": True,
            "no_realtime_monitoring": True,
            "no_raw_file_access_from_frontend": True,
            "no_auto_trading": True,
            "status_from_project_docs": True,
        },
    }
