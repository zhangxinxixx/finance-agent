"""Premarket control-plane routes extracted from the main FastAPI entrypoint."""

from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from apps.api.services import pipeline_contract_service, premarket_launch_service, premarket_task_service
from apps.premarket import sort_premarket_steps
from database.models.engine import SessionLocal, get_db
from database.models.task import TaskRun

router = APIRouter()


@router.get("/api/pipelines/premarket/contract")
def api_premarket_pipeline_contract():
    """Return the read-only canonical premarket step topology contract."""
    return pipeline_contract_service.build_premarket_pipeline_contract()


@router.get("/api/pipelines/premarket/readiness")
def api_premarket_pipeline_readiness():
    """Return the current source-readiness view for the canonical premarket pipeline."""
    return pipeline_contract_service.build_premarket_pipeline_source_readiness()


@router.get("/api/tasks/premarket/preflight")
def api_premarket_launch_preflight(force: bool = False):
    """Return read-only launch preflight truth for the premarket task trigger."""
    return premarket_launch_service.build_premarket_launch_preflight(
        force=force,
        session_factory=SessionLocal,
        readiness_builder=pipeline_contract_service.build_premarket_pipeline_source_readiness,
        find_active_dagster_run=premarket_launch_service.find_active_dagster_premarket_run,
    )


@router.post("/tasks/premarket")
@router.post("/api/tasks/premarket")
def trigger_premarket(force: bool = False):
    """触发盘前主链 — 通过 Dagster GraphQL launchRun。"""
    return premarket_launch_service.trigger_premarket_launch(
        force=force,
        session_factory=SessionLocal,
        readiness_builder=pipeline_contract_service.build_premarket_pipeline_source_readiness,
        find_active_dagster_run=premarket_launch_service.find_active_dagster_premarket_run,
    )


@router.get("/tasks/{task_id}")
@router.get("/api/tasks/{task_id}")
def get_task(task_id: str, db: Session = Depends(get_db)):
    """查询任务状态。"""
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task_id format")

    if premarket_task_service.database_reachable():
        task = db.get(TaskRun, tid)
        if task:
            steps = [premarket_task_service.step_to_out(s) for s in sort_premarket_steps(task.steps)]
            return premarket_task_service.TaskOut(
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
        dagster_task = premarket_task_service.get_dagster_task_view(task_id, dagster_url)
    except Exception:
        dagster_task = None
    else:
        if dagster_task is not None:
            return dagster_task

    raise HTTPException(status_code=404, detail="Task not found")


@router.get("/tasks/{task_id}/logs")
@router.get("/api/tasks/{task_id}/logs")
def get_task_logs(task_id: str, db: Session = Depends(get_db)):
    """查询任务步骤日志。"""
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task_id format")

    if not premarket_task_service.database_reachable():
        raise HTTPException(status_code=404, detail="Task not found")

    task = db.get(TaskRun, tid)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return [premarket_task_service.step_to_out(s) for s in sort_premarket_steps(task.steps)]
