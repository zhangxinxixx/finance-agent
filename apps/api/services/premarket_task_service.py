"""Task-observability helpers used by the premarket control-plane routes."""

from __future__ import annotations

import socket
from datetime import datetime, timezone
from typing import Any

import httpx
from pydantic import BaseModel
from sqlalchemy.engine import make_url

from apps.runtime.state_machine import map_dagster_status_to_task_status
from database.models.engine import SessionLocal
from database.models.task import TaskStep


class StepOut(BaseModel):
    id: str
    name: str
    status: str
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    step_order: int | None = None
    input_json: dict | None = None
    output_json: dict | None = None
    error_json: dict | None = None
    retryable: bool = True
    blocked_reason: str | None = None
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


def database_reachable(timeout: float = 0.2) -> bool:
    try:
        bind = SessionLocal.kw.get("bind")
        if bind is None:
            return False
        url = make_url(str(bind.url))
        if not url.drivername.startswith("postgresql") or not url.host or not url.port:
            return True
        with socket.create_connection((url.host, int(url.port)), timeout=timeout):
            return True
    except OSError:
        return False
    except Exception:
        return True


def step_to_out(step: TaskStep) -> StepOut:
    return StepOut(
        id=str(step.id), name=step.name, status=step.status.value, error=step.error,
        started_at=step.started_at, finished_at=step.finished_at, step_order=step.step_order,
        input_json=_parse_json(step.input_json), output_json=_parse_json(step.output_json), error_json=_parse_json(step.error_json),
        retryable=bool(step.retryable), blocked_reason=step.blocked_reason, input_hash=step.input_hash,
        output_ref=step.output_ref, error_type=step.error_type, retry_count=step.retry_count or 0,
    )


def get_dagster_task_view(task_id: str, dagster_url: str) -> TaskOut | None:
    query = "query RunTaskView($runId: ID!) { runOrError(runId: $runId) { __typename ... on Run { runId status startTime endTime stepStats { stepKey status startTime endTime } } } }"
    response = httpx.post(dagster_url, json={"query": query, "variables": {"runId": task_id}}, timeout=10)
    response.raise_for_status()
    run = response.json().get("data", {}).get("runOrError", {})
    if run.get("__typename") != "Run":
        return None
    created_at = _timestamp(run.get("startTime")) or datetime.now(timezone.utc)
    updated_at = _timestamp(run.get("endTime")) or datetime.now(timezone.utc)
    steps = [
        StepOut(id=str(item.get("stepKey") or f"step_{index}"), name=str(item.get("stepKey") or f"step_{index}").rsplit(".", 1)[-1], status=map_dagster_status_to_task_status(item.get("status")), started_at=_timestamp(item.get("startTime")), finished_at=_timestamp(item.get("endTime")), step_order=index)
        for index, item in enumerate(run.get("stepStats") or [])
    ]
    return TaskOut(id=str(run.get("runId") or task_id), name="premarket", status=map_dagster_status_to_task_status(run.get("status")), created_at=created_at, updated_at=updated_at, steps=steps)


def _parse_json(raw: str | None) -> dict | None:
    if raw is None:
        return None
    try:
        import json
        return json.loads(raw)
    except Exception:
        return None


def _timestamp(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc) if value is not None else None
    except (TypeError, ValueError, OSError):
        return None
