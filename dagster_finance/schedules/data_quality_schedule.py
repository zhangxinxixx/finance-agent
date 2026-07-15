"""UTC schedule for the daily data-quality monitor."""

from __future__ import annotations

from datetime import UTC, datetime

from dagster import DefaultScheduleStatus, RunRequest, schedule

from dagster_finance.jobs.data_quality_job import data_quality_monitor_job


@schedule(
    job=data_quality_monitor_job,
    cron_schedule="15 0 * * 1-5",
    execution_timezone="UTC",
    name="data_quality_monitor_daily",
    description="Run data-quality checks at 00:15 UTC on weekdays",
    default_status=DefaultScheduleStatus.RUNNING,
)
def data_quality_monitor_daily_schedule(context) -> RunRequest:
    scheduled_at = context.scheduled_execution_time or datetime.now(UTC)
    scheduled_at = scheduled_at.astimezone(UTC)
    trade_date = scheduled_at.date().isoformat()
    return RunRequest(
        run_key=f"data-quality:{trade_date}",
        run_config={
            "ops": {
                "data_quality_monitor_op": {
                    "config": {
                        "trade_date": trade_date,
                        "observed_at": scheduled_at.isoformat(),
                        "storage_root": "./storage",
                        "record_task_run": True,
                        "run_source_probes": False,
                        "run_consistency_checks": True,
                    }
                }
            }
        },
        tags={"data_quality/trade_date": trade_date},
    )
