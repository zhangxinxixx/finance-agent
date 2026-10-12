"""Stopped by default; normal polling is configurable and worker-deduplicated."""

from datetime import UTC
from dagster import RunRequest, SkipReason, schedule
from apps.worker.fedwatch import fedwatch_settings
from dagster_finance.jobs.fedwatch_job import fedwatch_refresh_job


@schedule(job=fedwatch_refresh_job, cron_schedule="* * * * *", execution_timezone="UTC",
          name="fedwatch_free", description="Configured FedWatch interval; explicit activation required")
def fedwatch_free_schedule(context):
    at = context.scheduled_execution_time
    if at is None:
        return SkipReason("scheduled_execution_time_missing")
    interval = fedwatch_settings()["poll_interval_minutes"]
    minute = int(at.timestamp() // 60)
    if minute % interval:
        return SkipReason("fedwatch_interval_not_due")
    tick = at.astimezone(UTC).isoformat()
    return RunRequest(run_key="fedwatch:" + tick,
                      run_config={"ops": {"fedwatch_refresh_op": {"config": {"scheduled_for": tick}}}},
                      tags={"source": "fedwatch"})
