"""Dagster operation for Automation Orchestrator trigger wrappers."""

from pathlib import Path
from typing import Any

from dagster import Config, Failure, op

from apps.scheduler.automation_orchestration import (
    run_event_sla_orchestration,
    run_hourly_orchestration,
    run_notification_retry_queue,
    run_pre_analysis_orchestration,
)
from apps.orchestration.execution_lock import orchestration_run_lock


class AutomationOrchestrationConfig(Config):
    """Configuration selected by the schedule that launches this job."""

    trigger: str
    storage_root: str = "./storage"
    send_notifications: bool = True
    record_task_run: bool = True


@op(tags={"pipeline": "automation_orchestration"}, pool="automation_orchestration")
def automation_orchestration_op(context, config: AutomationOrchestrationConfig) -> dict[str, Any]:
    """Run the existing orchestration wrapper selected by a Dagster schedule."""
    storage_root = Path(config.storage_root)
    handlers = {
        "hourly": lambda: run_hourly_orchestration(
            storage_root=storage_root,
            send_notifications=config.send_notifications,
            record_task_run=config.record_task_run,
            run_id=context.run_id,
        ),
        "event_sla": lambda: run_event_sla_orchestration(
            storage_root=storage_root,
            send_notifications=config.send_notifications,
            record_task_run=config.record_task_run,
            run_id=context.run_id,
        ),
        "pre_analysis": lambda: run_pre_analysis_orchestration(
            storage_root=storage_root,
            send_notifications=config.send_notifications,
            record_task_run=config.record_task_run,
            run_id=context.run_id,
        ),
        "notification_retry": lambda: run_notification_retry_queue(storage_root=storage_root),
    }
    handler = handlers.get(config.trigger)
    if handler is None:
        raise Failure(description=f"Unsupported automation orchestration trigger: {config.trigger}")
    with orchestration_run_lock(storage_root=storage_root):
        result = handler()
    status = str(result.get("status") or "").lower()
    context.log.info("Automation orchestration trigger=%s status=%s", config.trigger, status or "completed")
    if status == "failed":
        raise Failure(description=f"Automation orchestration {config.trigger} returned failed")
    return result
