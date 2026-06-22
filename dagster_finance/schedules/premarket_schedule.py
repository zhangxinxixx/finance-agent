"""Dagster schedule for the premarket pipeline.

Runs at 08:30 Beijing time (00:30 UTC) every weekday.
"""

from dagster import SkipReason, schedule

from dagster_finance.jobs.premarket_job import premarket_job
from apps.api.services import pipeline_contract_service


@schedule(
    job=premarket_job,
    cron_schedule="30 0 * * 1-5",  # 00:30 UTC = 08:30 Beijing, Mon-Fri
    execution_timezone="UTC",
    name="premarket_daily",
    description="Run premarket pipeline at 08:30 Beijing time on weekdays",
)
def premarket_daily_schedule(context):
    source_readiness = pipeline_contract_service.build_premarket_pipeline_source_readiness()
    blocked = source_readiness["source_readiness_summary"]["decision_counts"].get("blocked", 0)
    if blocked > 0:
        return SkipReason("Premarket source readiness is blocked")
    return {}
