from __future__ import annotations

import logging
import os
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from apps.runtime.state_machine import ACTIVE_DAGSTER_RUN_STATUSES, transition_task_run
from database.models.engine import SessionLocal
from database.models.task import TaskRun, TaskStatus

logger = logging.getLogger(__name__)

DEFAULT_ACTIVE_TASK_STALE_AFTER = timedelta(
    hours=int(os.getenv("PREMARKET_ACTIVE_TASK_STALE_AFTER_HOURS", "6"))
)


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


SessionFactory = Callable[[], Session]
ReadinessBuilder = Callable[[], dict[str, Any]]
DagsterActiveRunFinder = Callable[[str], dict[str, str] | None]


def normalize_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def premarket_active_task_ref_time(task: TaskRun) -> datetime | None:
    return normalize_utc(task.updated_at or task.started_at or task.created_at)


def classify_premarket_active_legacy_tasks(
    db: Session,
    *,
    now: datetime | None = None,
    active_task_stale_after: timedelta = DEFAULT_ACTIVE_TASK_STALE_AFTER,
) -> tuple[TaskRun | None, list[TaskRun]]:
    """Return the newest active legacy premarket task plus stale rows without mutating state."""
    current_time = normalize_utc(now) or datetime.now(timezone.utc)
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
        ref_time = premarket_active_task_ref_time(task)
        if ref_time is not None and current_time - ref_time > active_task_stale_after:
            stale_runs.append(task)
            continue
        return task, stale_runs

    return None, stale_runs


def cleanup_stale_active_premarket_tasks(
    db: Session,
    *,
    now: datetime | None = None,
    active_task_stale_after: timedelta = DEFAULT_ACTIVE_TASK_STALE_AFTER,
) -> TaskRun | None:
    """Return the newest still-active premarket task, marking stale legacy rows along the way."""
    current_time = normalize_utc(now) or datetime.now(timezone.utc)
    active_task, stale_tasks = classify_premarket_active_legacy_tasks(
        db,
        now=current_time,
        active_task_stale_after=active_task_stale_after,
    )

    for task in stale_tasks:
        transition_task_run(
            db,
            task,
            TaskStatus.stale,
            source="api",
            reason=f"active_timeout_exceeded:{active_task_stale_after}",
            error_message=task.error or "Legacy premarket task timed out before Dagster migration verification.",
        )

    if stale_tasks:
        db.commit()
    return active_task


def task_to_premarket_active_task_ref(task: TaskRun) -> PremarketActiveTaskRef:
    return PremarketActiveTaskRef(
        task_id=str(task.id),
        status=task.status.value,
        updated_at=premarket_active_task_ref_time(task),
    )


def source_readiness_block_count(source_readiness_summary: dict[str, Any] | None) -> int:
    if not isinstance(source_readiness_summary, dict):
        return 0
    decision_counts = source_readiness_summary.get("decision_counts")
    if not isinstance(decision_counts, dict):
        return 0
    try:
        return max(int(decision_counts.get("blocked", 0) or 0), 0)
    except (TypeError, ValueError):
        return 0


def source_readiness_block_message(source_readiness_summary: dict[str, Any] | None) -> str:
    blocked_sources = source_readiness_summary.get("blocked_sources") if isinstance(source_readiness_summary, dict) else None
    if isinstance(blocked_sources, list) and blocked_sources:
        return f"Source readiness blocked premarket launch: {', '.join(str(source) for source in blocked_sources)}"
    return "Source readiness blocked premarket launch"


def premarket_launch_error_detail(
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


def find_active_dagster_premarket_run(dagster_url: str) -> dict[str, str] | None:
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


def build_premarket_launch_preflight(
    *,
    force: bool = False,
    session_factory: SessionFactory = SessionLocal,
    readiness_builder: ReadinessBuilder,
    dagster_url: str | None = None,
    find_active_dagster_run: DagsterActiveRunFinder = find_active_dagster_premarket_run,
) -> PremarketLaunchPreflightResponse:
    readiness = readiness_builder()
    source_readiness_summary = readiness.get("source_readiness_summary")
    source_readiness_blocked = source_readiness_block_count(source_readiness_summary) > 0

    with session_factory() as session:
        active_legacy_task, stale_legacy_tasks = classify_premarket_active_legacy_tasks(session)

    dagster_check_error: str | None = None
    active_dagster_run: dict[str, str] | None = None
    try:
        active_dagster_run = find_active_dagster_run(dagster_url or _default_dagster_url())
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
            None if active_legacy_task is None else task_to_premarket_active_task_ref(active_legacy_task)
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


def trigger_premarket_launch(
    *,
    force: bool = False,
    session_factory: SessionFactory = SessionLocal,
    readiness_builder: ReadinessBuilder,
    dagster_url: str | None = None,
    find_active_dagster_run: DagsterActiveRunFinder = find_active_dagster_premarket_run,
) -> TaskCreateResponse:
    dagster_url = dagster_url or _default_dagster_url()

    with session_factory() as session:
        if not force:
            existing = cleanup_stale_active_premarket_tasks(session)
            if existing:
                readiness = readiness_builder()
                raise HTTPException(
                    status_code=409,
                    detail=premarket_launch_error_detail(
                        message=f"已有进行中的 premarket 任务: {existing.id} (status={existing.status.value})",
                        reason="legacy_active_task",
                        force=force,
                        source_readiness_summary=readiness.get("source_readiness_summary"),
                        active_legacy_task=task_to_premarket_active_task_ref(existing),
                    ),
                )

    if not force:
        try:
            active_dagster_run = find_active_dagster_run(dagster_url)
        except Exception as exc:
            logger.warning("Failed to check active Dagster premarket runs: %s", exc)
        else:
            if active_dagster_run:
                readiness = readiness_builder()
                raise HTTPException(
                    status_code=409,
                    detail=premarket_launch_error_detail(
                        message=(
                            "Dagster 已有进行中的 premarket_job: "
                            f"{active_dagster_run['run_id']} (status={active_dagster_run['status']})"
                        ),
                        reason="dagster_active_run",
                        force=force,
                        source_readiness_summary=readiness.get("source_readiness_summary"),
                        active_dagster_run=PremarketDagsterRunRef(
                            run_id=active_dagster_run["run_id"],
                            status=active_dagster_run["status"],
                        ),
                    ),
                )

    readiness = readiness_builder()
    source_readiness_summary = readiness.get("source_readiness_summary")
    if source_readiness_block_count(source_readiness_summary) > 0:
        raise HTTPException(
            status_code=409,
            detail=premarket_launch_error_detail(
                message=source_readiness_block_message(source_readiness_summary),
                reason="source_readiness_blocked",
                force=force,
                source_readiness_summary=source_readiness_summary,
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
            return TaskCreateResponse(
                task_id=run_id,
                name="premarket",
                status="running",
                source_readiness_summary=source_readiness_summary,
            )
        error_msg = result.get("message", str(result))
        raise HTTPException(
            status_code=500,
            detail=premarket_launch_error_detail(
                message=f"Dagster launch failed: {error_msg}",
                reason="dagster_launch_failed",
                force=force,
                source_readiness_summary=source_readiness_summary,
            ),
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=premarket_launch_error_detail(
                message=f"Dagster unavailable: {exc}",
                reason="dagster_unavailable",
                force=force,
                source_readiness_summary=source_readiness_summary,
                dagster_check_error=str(exc),
            ),
        )


def _default_dagster_url() -> str:
    return os.getenv("DAGSTER_GRAPHQL_URL", "http://127.0.0.1:3333/graphql")
