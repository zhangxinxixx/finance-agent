from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from collections.abc import Sequence
from typing import Any

from sqlalchemy.orm import Session

from apps.api.schemas.common import ArtifactType
from apps.api.services.daily_analysis_followup_service import (
    get_daily_analysis_followups,
    get_daily_analysis_followups_latest,
)
from database.models.task import StepStatus, TaskRun, TaskStatus, TaskStep

_TASK_TYPE = "daily_analysis_followup"
_STAGE = "news_followup"
_ACTIVE_STATUSES = (TaskStatus.pending, TaskStatus.running)
_DAGSTER_JOB_NAME = "daily_analysis_followup_job"
MAX_FOLLOWUP_TASK_IDS = 50


class DailyAnalysisFollowupDispatchError(RuntimeError):
    """A structured failure after follow-up rows have already been committed."""

    def __init__(
        self,
        *,
        status_code: int,
        reason: str,
        message: str,
        cause: str | None = None,
        detail_extra: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.reason = reason
        self.message = message
        self.cause = cause
        self.detail_extra = dict(detail_extra or {})

    def detail(self, *, task_ids: Sequence[str]) -> dict[str, Any]:
        detail = {
            "message": self.message,
            "reason": self.reason,
            "dispatch_status": "unavailable" if self.reason == "dagster_unavailable" else "failed",
            "task_ids": list(task_ids),
            "task_rows_preserved": True,
            "dagster_check_error": self.cause,
        }
        detail.update(self.detail_extra)
        return detail


def create_daily_analysis_followup_tasks(
    db: Session,
    *,
    date: str | None = None,
    run_id: str | None = None,
    project_root: Path | None = None,
) -> dict[str, Any] | None:
    """Create traceable queued task rows for daily analysis follow-ups.

    This service only records queued work. It does not execute downstream Jin10
    analysis and does not dispatch the worker.
    """
    if date and run_id:
        queue = get_daily_analysis_followups(date=date, run_id=run_id, project_root=project_root)
    else:
        queue = get_daily_analysis_followups_latest(project_root=project_root)
    if queue is None:
        return None

    followups = [dict(item) for item in queue.get("followups", []) if isinstance(item, dict)]
    queue_date = str(queue.get("date") or date or "")

    created_run_ids: list[str] = []
    existing_run_ids: list[str] = []
    now = datetime.now(UTC)

    for index, followup in enumerate(followups):
        input_payload = _build_input_payload(queue=queue, followup=followup)
        input_json = _dump_json(input_payload)
        input_hash = _sha256(input_json)
        existing = _find_existing_active_run(db, trade_date=queue_date, input_hash=input_hash)
        if existing is not None:
            existing_run_ids.append(str(existing.id))
            continue

        followup_id = str(followup.get("followup_id") or input_hash)
        action = str(followup.get("action") or "daily_analysis_followup")
        task_kind = str(followup.get("queue_type") or action or _TASK_TYPE)
        run = TaskRun(
            name=_run_name(followup_id),
            task_type=_TASK_TYPE,
            status=TaskStatus.pending,
            current_stage=_STAGE,
            progress=0.0,
            started_at=now,
            trade_date=queue_date or None,
        )
        db.add(run)
        db.flush()

        step = TaskStep(
            task_run_id=run.id,
            name=_step_name(action),
            stage=_STAGE,
            task_kind=task_kind,
            status=StepStatus.pending,
            started_at=now,
            step_order=index,
            input_refs=_dump_json(_artifact_refs(queue)),
            output_refs=_dump_json([]),
            source_refs=_dump_json(_source_refs(followup)),
            input_json=input_json,
            input_hash=input_hash,
            retry_count=0,
        )
        db.add(step)
        db.flush()
        created_run_ids.append(str(run.id))

    db.commit()
    return {
        "status": "accepted" if created_run_ids else ("empty" if not followups else "deduped"),
        "date": queue.get("date"),
        "run_id": queue.get("run_id"),
        "queue_status": queue.get("status"),
        "queue_count": len(followups),
        "created_task_count": len(created_run_ids),
        "skipped_existing_count": len(existing_run_ids),
        "created_run_ids": created_run_ids,
        "existing_run_ids": existing_run_ids,
    }


def launch_daily_analysis_followup_job(
    task_ids: Sequence[str | uuid.UUID],
    *,
    dagster_url: str | None = None,
    storage_root: str | None = None,
    max_stage_steps: int = 4,
) -> dict[str, Any]:
    """Launch one explicit task-id batch in the formal Dagster job.

    The API passes only IDs returned by ``create_daily_analysis_followup_tasks``.
    This helper never queries or discovers pending rows, and it deliberately has
    no schedule or worker fallback when Dagster is unavailable.
    """
    normalized_ids = _normalize_task_ids(task_ids)
    if not normalized_ids:
        return {
            "dispatch_status": "not_dispatched",
            "task_ids": [],
            "dagster_run_id": None,
            "dagster_status": None,
        }
    if len(normalized_ids) > MAX_FOLLOWUP_TASK_IDS:
        raise DailyAnalysisFollowupDispatchError(
            status_code=413,
            reason="task_batch_too_large",
            message=(
                f"daily analysis follow-up dispatch accepts at most {MAX_FOLLOWUP_TASK_IDS} task_ids; "
                f"received {len(normalized_ids)}"
            ),
        )

    try:
        import httpx
    except ImportError as exc:  # pragma: no cover - dependency is part of the API runtime
        raise DailyAnalysisFollowupDispatchError(
            status_code=500,
            reason="dagster_client_unavailable",
            message="Dagster dispatch client is unavailable",
            cause=str(exc),
        ) from exc

    configured_storage_root = storage_root or os.getenv("FINANCE_AGENT_STORAGE_ROOT", "./storage")
    bounded_stage_steps = min(max(int(max_stage_steps), 1), 4)
    task_set_hash = hashlib.sha256(",".join(normalized_ids).encode("utf-8")).hexdigest()
    mutation = """
        mutation LaunchDailyAnalysisFollowup($jobName: String!, $runConfigData: RunConfigData!, $taskSetHash: String!) {
            launchPipelineExecution(
                executionParams: {
                    selector: {
                        pipelineName: $jobName
                        repositoryName: "__repository__"
                        repositoryLocationName: "dagster_finance.definitions"
                    }
                    mode: "default"
                    runConfigData: $runConfigData
                    executionMetadata: {
                        tags: [
                            { key: "pipeline", value: "daily_analysis_followup" }
                            { key: "task_scope", value: "explicit_ids" }
                            { key: "task_set_hash", value: $taskSetHash }
                        ]
                    }
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
    variables = {
        "jobName": _DAGSTER_JOB_NAME,
        "taskSetHash": task_set_hash,
        "runConfigData": {
            "ops": {
                "daily_analysis_followup_op": {
                    "config": {
                        "task_ids": normalized_ids,
                        "storage_root": configured_storage_root,
                        "max_stage_steps": bounded_stage_steps,
                    }
                }
            }
        },
    }
    try:
        response = httpx.post(
            dagster_url or _default_dagster_url(),
            json={"query": mutation, "variables": variables},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as exc:
        raise DailyAnalysisFollowupDispatchError(
            status_code=502,
            reason="dagster_unavailable",
            message=f"Dagster unavailable: {exc}",
            cause=str(exc),
        ) from exc
    except (TypeError, ValueError) as exc:
        raise DailyAnalysisFollowupDispatchError(
            status_code=502,
            reason="dagster_unavailable",
            message=f"Dagster returned an unreadable response: {exc}",
            cause=str(exc),
        ) from exc

    graphql_errors = payload.get("errors") if isinstance(payload, dict) else None
    if graphql_errors:
        message = "; ".join(
            str(item.get("message") or "unknown GraphQL error")
            for item in graphql_errors
            if isinstance(item, dict)
        ) or "unknown GraphQL error"
        raise DailyAnalysisFollowupDispatchError(
            status_code=500,
            reason="dagster_launch_failed",
            message=f"Dagster launch failed: {message}",
            cause=message,
        )

    result = (payload.get("data") or {}).get("launchPipelineExecution", {}) if isinstance(payload, dict) else {}
    run = result.get("run") if isinstance(result, dict) else None
    if isinstance(run, dict) and run.get("runId"):
        return {
            "dispatch_status": "dispatched",
            "task_ids": normalized_ids,
            "dagster_run_id": str(run["runId"]),
            "dagster_status": str(run.get("status") or "QUEUED"),
            "dagster_job_name": _DAGSTER_JOB_NAME,
        }

    error_message = _dagster_result_error(result)
    raise DailyAnalysisFollowupDispatchError(
        status_code=500,
        reason="dagster_launch_failed",
        message=f"Dagster launch failed: {error_message}",
        cause=error_message,
    )


def dispatch_daily_analysis_followup_tasks(task_ids: Sequence[str | uuid.UUID]) -> dict[str, Any]:
    """Dispatch one explicit task-id set, chunking it into bounded Dagster runs."""
    selected_ids = _normalize_task_ids(task_ids)
    if not selected_ids:
        return {
            "dispatch_status": "not_dispatched",
            "task_ids": [],
            "dagster_run_id": None,
            "dagster_status": None,
        }

    dispatches: list[dict[str, Any]] = []
    dispatched_task_ids: list[str] = []
    for chunk_start in range(0, len(selected_ids), MAX_FOLLOWUP_TASK_IDS):
        chunk = selected_ids[chunk_start : chunk_start + MAX_FOLLOWUP_TASK_IDS]
        try:
            dispatch = launch_daily_analysis_followup_job(chunk)
        except DailyAnalysisFollowupDispatchError as exc:
            raise DailyAnalysisFollowupDispatchError(
                status_code=exc.status_code,
                reason=exc.reason,
                message=exc.message,
                cause=exc.cause,
                detail_extra={
                    "dispatch_status": "partial_failure" if dispatched_task_ids else exc.detail(task_ids=selected_ids)["dispatch_status"],
                    "dispatched_task_ids": dispatched_task_ids,
                    "remaining_task_ids": selected_ids[len(dispatched_task_ids) :],
                    "dagster_run_ids": [item.get("dagster_run_id") for item in dispatches],
                },
            ) from exc
        dispatches.append(dispatch)
        dispatched_task_ids.extend(str(task_id) for task_id in dispatch.get("task_ids", chunk))

    if len(dispatches) == 1:
        return dispatches[0]
    return {
        "dispatch_status": "dispatched",
        "task_ids": selected_ids,
        "dagster_run_id": None,
        "dagster_run_ids": [item.get("dagster_run_id") for item in dispatches],
        "dagster_status": "MIXED"
        if len({str(item.get("dagster_status")) for item in dispatches}) > 1
        else str(dispatches[0].get("dagster_status") or "QUEUED"),
        "dagster_statuses": [item.get("dagster_status") for item in dispatches],
        "dagster_job_name": dispatches[0].get("dagster_job_name"),
    }


def _normalize_task_ids(task_ids: Sequence[str | uuid.UUID]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_id in task_ids:
        try:
            value = str(uuid.UUID(str(raw_id)))
        except (AttributeError, TypeError, ValueError):
            continue
        if value not in seen:
            normalized.append(value)
            seen.add(value)
    return normalized


def _dagster_result_error(result: Any) -> str:
    if not isinstance(result, dict):
        return "invalid launch response"
    errors = result.get("errors")
    if isinstance(errors, list):
        messages = [
            str(item.get("message") or "unknown validation error")
            for item in errors
            if isinstance(item, dict)
        ]
        if messages:
            return "; ".join(messages)
    return str(result.get("message") or result or "missing Dagster run")


def _default_dagster_url() -> str:
    return os.getenv("DAGSTER_GRAPHQL_URL", "http://127.0.0.1:3333/graphql")


def _find_existing_active_run(db: Session, *, trade_date: str, input_hash: str) -> TaskRun | None:
    return (
        db.query(TaskRun)
        .join(TaskStep, TaskStep.task_run_id == TaskRun.id)
        .filter(
            TaskRun.task_type == _TASK_TYPE,
            TaskRun.trade_date == (trade_date or None),
            TaskRun.status.in_(_ACTIVE_STATUSES),
            TaskStep.input_hash == input_hash,
        )
        .first()
    )


def _build_input_payload(*, queue: dict[str, Any], followup: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": queue.get("date"),
        "run_id": queue.get("run_id"),
        "queue_source_artifact": queue.get("source_artifact"),
        "artifact_path": queue.get("artifact_path"),
        "artifact_paths": dict(queue.get("artifact_paths") or {}),
        "followup": followup,
    }


def _artifact_refs(queue: dict[str, Any]) -> list[dict[str, Any]]:
    artifact_paths = queue.get("artifact_paths")
    if isinstance(artifact_paths, dict) and artifact_paths:
        return [
            _artifact_ref(artifact_id=str(name), file_path=str(path))
            for name, path in sorted(artifact_paths.items())
            if path
        ]

    artifact_path = queue.get("artifact_path")
    if artifact_path:
        return [_artifact_ref(artifact_id=str(queue.get("source_artifact") or "daily_analysis_followups"), file_path=str(artifact_path))]
    return []


def _artifact_ref(*, artifact_id: str, file_path: str) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "artifact_type": ArtifactType.feature_json.value,
        "file_path": file_path,
    }


def _source_refs(followup: dict[str, Any]) -> list[dict[str, Any]]:
    refs = followup.get("source_refs")
    if isinstance(refs, list) and refs:
        return [dict(item) for item in refs if isinstance(item, dict)]

    source_key = str(followup.get("source_key") or "daily_analysis_followups")
    source_url = followup.get("source_url")
    return [
        {
            "source_id": source_key,
            "source_name": source_key,
            "source_type": "news",
            "url": source_url,
            "status": "queued",
        }
    ]


def _run_name(followup_id: str) -> str:
    raw = f"daily_analysis_followup:{followup_id}"
    if len(raw) <= 128:
        return raw
    return f"daily_analysis_followup:{_sha256(raw)[:32]}"


def _step_name(action: str) -> str:
    raw = action or "daily_analysis_followup"
    if len(raw) <= 128:
        return raw
    return raw[:128]


def _dump_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _sha256(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
