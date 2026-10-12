"""Daily 14:00 Beijing refresh through the existing premarket pipeline."""

from dagster import DefaultScheduleStatus, SkipReason, schedule

from apps.api.services import pipeline_contract_service
from dagster_finance.jobs.premarket_job import premarket_job


@schedule(
    job=premarket_job,
    cron_schedule="0 14 * * *",
    execution_timezone="Asia/Shanghai",
    name="daily_afternoon_analysis",
    description="Refresh CME and canonical analysis daily at 14:00 Beijing time",
    default_status=DefaultScheduleStatus.RUNNING,
)
def daily_afternoon_analysis_schedule(context):
    source_readiness = pipeline_contract_service.build_premarket_pipeline_source_readiness()
    blocked = source_readiness["source_readiness_summary"]["decision_counts"].get("blocked", 0)
    if blocked > 0:
        return SkipReason("Premarket source readiness is blocked")
    return {}
