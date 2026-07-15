"""UTC schedule for finalized XAU/USD provider shadow summaries."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from dagster import DefaultScheduleStatus, RunRequest, schedule

from dagster_finance.jobs.xauusd_shadow_job import xauusd_shadow_summary_job


@schedule(
    job=xauusd_shadow_summary_job,
    cron_schedule="20 0 * * 2-6",
    execution_timezone="UTC",
    name="xauusd_shadow_summary_daily",
    description="Finalize the previous UTC weekday XAU/USD shadow summary",
    default_status=DefaultScheduleStatus.RUNNING,
)
def xauusd_shadow_summary_daily_schedule(context) -> RunRequest:
    scheduled_at = context.scheduled_execution_time or datetime.now(UTC)
    scheduled_at = scheduled_at.astimezone(UTC)
    trade_date = scheduled_at.date() - timedelta(days=1)
    trade_date_value = trade_date.isoformat()
    as_of_value = scheduled_at.isoformat()
    return RunRequest(
        run_key=f"xauusd-shadow:{trade_date_value}",
        run_config={
            "ops": {
                "xauusd_live_strategy_history_op": {
                    "config": {
                        "as_of": as_of_value,
                        "storage_root": "./storage",
                    }
                },
                "xauusd_shadow_evaluation_op": {
                    "config": {
                        "evaluated_at": as_of_value,
                        "storage_root": "./storage",
                        "history_limit": 20,
                    }
                },
                "xauusd_shadow_summary_op": {
                    "config": {
                        "trade_date": trade_date_value,
                        "storage_root": "./storage",
                    }
                }
            }
        },
        tags={"xauusd_shadow/trade_date": trade_date_value},
    )
