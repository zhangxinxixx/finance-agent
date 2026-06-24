from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
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
