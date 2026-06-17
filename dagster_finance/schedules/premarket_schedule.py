"""Dagster schedule for the premarket pipeline.

Runs at 08:30 Beijing time (00:30 UTC) every weekday.
"""

from dagster import schedule

from dagster_finance.jobs.premarket_job import premarket_job


@schedule(
    job=premarket_job,
    cron_schedule="30 0 * * 1-5",  # 00:30 UTC = 08:30 Beijing, Mon-Fri
    execution_timezone="UTC",
    name="premarket_daily",
    description="Run premarket pipeline at 08:30 Beijing time on weekdays",
)
def premarket_daily_schedule(context):
    return {}
