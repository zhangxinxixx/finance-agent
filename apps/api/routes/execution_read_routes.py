"""Execution read-model routes extracted from the main FastAPI entrypoint."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from apps.api.schemas.artifact import ArtifactDetailResponse
from apps.api.schemas.task_run import TaskRunResponse
from apps.api.services.artifact_service import get_artifact_detail_response
from apps.api.services.execution_event_api import get_run_events
from apps.api.services import task_service
from database.models.engine import get_db

router = APIRouter()


def _require_uuid(value: str, field_name: str) -> None:
    try:
        uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name} format") from exc


@router.get("/api/runs")
def api_runs(limit: int = 20, db: Session = Depends(get_db)):
    """列出最近的任务运行，供 Agent Tasks Run 控制台读取。"""
    runs = task_service.list_task_runs(db, limit=min(limit, 100))
    return {"runs": [run.model_dump(mode="json") for run in runs]}


@router.get("/api/runs/{run_id}", response_model=TaskRunResponse)
def api_run_detail(run_id: str, db: Session = Depends(get_db)) -> TaskRunResponse:
    """按 run_id 返回单次运行详情。"""
    _require_uuid(run_id, "run_id")

    run = task_service.get_task_run_response(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/api/runs/{run_id}/steps")
def api_run_steps(run_id: str, db: Session = Depends(get_db)):
    """返回某次运行的步骤详情。"""
    _require_uuid(run_id, "run_id")

    steps = task_service.get_task_run_steps(db, run_id)
    if steps is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"run_id": run_id, "steps": [step.model_dump(mode="json") for step in steps]}


@router.get("/api/runs/{run_id}/logs")
def api_run_logs(run_id: str, db: Session = Depends(get_db)):
    """返回某次运行的步骤日志兼容结构。"""
    _require_uuid(run_id, "run_id")

    logs = task_service.get_task_run_logs(db, run_id)
    if logs is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return logs


@router.get("/api/runs/{run_id}/artifacts")
def api_run_artifacts(run_id: str, db: Session = Depends(get_db)):
    """聚合某次运行的输出产物引用。"""
    _require_uuid(run_id, "run_id")

    artifacts = task_service.get_task_run_artifacts(db, run_id)
    if artifacts is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return artifacts


@router.get("/api/artifacts/{artifact_id}", response_model=ArtifactDetailResponse)
def api_artifact_detail(artifact_id: str, db: Session = Depends(get_db)) -> ArtifactDetailResponse:
    """返回单个 registry artifact 的上下文详情。"""
    artifact = get_artifact_detail_response(db, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return artifact


@router.get("/api/runs/{run_id}/events")
def api_run_events(run_id: str, db: Session = Depends(get_db)):
    """返回某次运行的执行事件时间线。"""
    _require_uuid(run_id, "run_id")

    run = task_service.get_task_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return get_run_events(db, run_id)
