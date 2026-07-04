"""Premarket control-plane routes extracted from the main FastAPI entrypoint."""

from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.models.engine import get_db

router = APIRouter()


@router.get("/api/pipelines/premarket/contract")
def api_premarket_pipeline_contract():
    """Return the read-only canonical premarket step topology contract."""
    from apps.api import main as api_main

    return api_main.pipeline_contract_service.build_premarket_pipeline_contract()


@router.get("/api/pipelines/premarket/readiness")
def api_premarket_pipeline_readiness():
    """Return the current source-readiness view for the canonical premarket pipeline."""
    from apps.api import main as api_main

    return api_main.pipeline_contract_service.build_premarket_pipeline_source_readiness()


@router.get("/api/tasks/premarket/preflight")
def api_premarket_launch_preflight(force: bool = False):
    """Return read-only launch preflight truth for the premarket task trigger."""
    from apps.api import main as api_main

    return api_main._build_premarket_launch_preflight(force=force)


@router.post("/tasks/premarket")
@router.post("/api/tasks/premarket")
def trigger_premarket(force: bool = False):
    """触发盘前主链 — 通过 Dagster GraphQL launchRun。"""
    from apps.api import main as api_main

    with api_main.SessionLocal() as session:
        if not force:
            existing = api_main._cleanup_stale_active_premarket_tasks(session)
            if existing:
                readiness = api_main.pipeline_contract_service.build_premarket_pipeline_source_readiness()
                raise HTTPException(
                    status_code=409,
                    detail=api_main._premarket_launch_error_detail(
                        message=f"已有进行中的 premarket 任务: {existing.id} (status={existing.status.value})",
                        reason="legacy_active_task",
                        force=force,
                        source_readiness_summary=readiness.get("source_readiness_summary"),
                        active_legacy_task=api_main._task_to_premarket_active_task_ref(existing),
                    ),
                )

    dagster_url = os.getenv("DAGSTER_GRAPHQL_URL", "http://127.0.0.1:3333/graphql")
    if not force:
        try:
            active_dagster_run = api_main._find_active_dagster_premarket_run(dagster_url)
        except Exception as exc:
            api_main.logger.warning("Failed to check active Dagster premarket runs: %s", exc)
        else:
            if active_dagster_run:
                readiness = api_main.pipeline_contract_service.build_premarket_pipeline_source_readiness()
                raise HTTPException(
                    status_code=409,
                    detail=api_main._premarket_launch_error_detail(
                        message=(
                            "Dagster 已有进行中的 premarket_job: "
                            f"{active_dagster_run['run_id']} (status={active_dagster_run['status']})"
                        ),
                        reason="dagster_active_run",
                        force=force,
                        source_readiness_summary=readiness.get("source_readiness_summary"),
                        active_dagster_run=api_main.PremarketDagsterRunRef(
                            run_id=active_dagster_run["run_id"],
                            status=active_dagster_run["status"],
                        ),
                    ),
                )

    readiness = api_main.pipeline_contract_service.build_premarket_pipeline_source_readiness()
    source_readiness_summary = readiness.get("source_readiness_summary")
    if api_main._source_readiness_block_count(source_readiness_summary) > 0:
        raise HTTPException(
            status_code=409,
            detail=api_main._premarket_launch_error_detail(
                message=api_main._source_readiness_block_message(source_readiness_summary),
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
            return api_main.TaskCreateResponse(
                task_id=run_id,
                name="premarket",
                status="running",
                source_readiness_summary=source_readiness_summary,
            )
        error_msg = result.get("message", str(result))
        raise HTTPException(
            status_code=500,
            detail=api_main._premarket_launch_error_detail(
                message=f"Dagster launch failed: {error_msg}",
                reason="dagster_launch_failed",
                force=force,
                source_readiness_summary=source_readiness_summary,
            ),
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=api_main._premarket_launch_error_detail(
                message=f"Dagster unavailable: {exc}",
                reason="dagster_unavailable",
                force=force,
                source_readiness_summary=source_readiness_summary,
                dagster_check_error=str(exc),
            ),
        )


@router.get("/tasks/{task_id}")
@router.get("/api/tasks/{task_id}")
def get_task(task_id: str, db: Session = Depends(get_db)):
    """查询任务状态。"""
    from apps.api import main as api_main

    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task_id format")

    if api_main._database_reachable():
        task = db.get(api_main.TaskRun, tid)
        if task:
            steps = [api_main._step_to_out(s) for s in api_main.sort_premarket_steps(task.steps)]
            return api_main.TaskOut(
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
        dagster_task = api_main._get_dagster_task_view(task_id, dagster_url)
    except Exception as exc:
        api_main.logger.warning("Failed to query Dagster task view for %s: %s", task_id, exc)
    else:
        if dagster_task is not None:
            return dagster_task

    raise HTTPException(status_code=404, detail="Task not found")


@router.get("/tasks/{task_id}/logs")
@router.get("/api/tasks/{task_id}/logs")
def get_task_logs(task_id: str, db: Session = Depends(get_db)):
    """查询任务步骤日志。"""
    from apps.api import main as api_main

    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task_id format")

    if not api_main._database_reachable():
        raise HTTPException(status_code=404, detail="Task not found")

    task = db.get(api_main.TaskRun, tid)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return [api_main._step_to_out(s) for s in api_main.sort_premarket_steps(task.steps)]
