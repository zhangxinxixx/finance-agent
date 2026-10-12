"""A bounded data-ingestion job in the existing Dagster control plane."""

from datetime import UTC, datetime
from pathlib import Path
import json

from dagster import Config, job, op

from apps.worker.fedwatch import refresh_fedwatch
from database.models.task import TaskRun, TaskStatus, TaskStep, StepStatus, ensure_task_tables


class FedWatchConfig(Config):
    storage_root: str = "./storage"
    event_window: bool = False
    scheduled_for: str | None = None


def run_fedwatch_refresh(session, *, storage_root, event_window=False, **kwargs):
    """Own the task transaction; usable by scheduler and isolated smoke tests."""
    ensure_task_tables(session)
    run = TaskRun(name="CME FedWatch free ingestion", task_type="fedwatch_refresh",
                  status=TaskStatus.running, started_at=datetime.now(UTC))
    session.add(run)
    session.flush()
    step = TaskStep(task_run_id=run.id, name="fedwatch_collect_normalize_factor",
                    stage="collect", status=StepStatus.running, started_at=datetime.now(UTC), step_order=1)
    session.add(step)
    session.commit()  # durable execution identity before network work
    try:
        view = refresh_fedwatch(session, storage_root=storage_root, event_window=event_window, run_id=str(run.id), **kwargs)
        ok = view["source_health"]["status"] == "fresh"
        run.status = TaskStatus.success if ok else TaskStatus.degraded
        step.status = StepStatus.success if ok else StepStatus.failed
        step.error = None if ok else view["source_health"].get("reason", "fedwatch_unavailable")
        step.output_json = json.dumps({"snapshot_id": view.get("snapshot_id"), "source_health": view["source_health"],
                                      "warehouse": view.get("warehouse")})
        step.source_refs = json.dumps(view["source_refs"])
        run.snapshot_id = view.get("snapshot_id")
        step.finished_at = run.ended_at = datetime.now(UTC)
        session.commit()
        return {**view, "task_run_id": str(run.id)}
    except Exception as exc:
        session.rollback()
        run.status, step.status = TaskStatus.failed, StepStatus.failed
        run.error_summary = step.error = "fedwatch_worker_" + type(exc).__name__
        step.finished_at = run.ended_at = datetime.now(UTC)
        session.commit()
        raise


@op(required_resource_keys={"db_session"}, tags={"pipeline": "macro", "source": "fedwatch"})
def fedwatch_refresh_op(context, config: FedWatchConfig):
    return run_fedwatch_refresh(context.resources.db_session, storage_root=Path(config.storage_root),
                               event_window=config.event_window, scheduled_for=config.scheduled_for)


@job(tags={"pipeline": "macro", "source": "fedwatch"})
def fedwatch_refresh_job():
    fedwatch_refresh_op()
