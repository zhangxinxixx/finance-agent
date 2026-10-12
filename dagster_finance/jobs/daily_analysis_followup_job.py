"""Explicit daily-analysis follow-up execution under Dagster."""

from dagster import job

from dagster_finance.ops.daily_analysis_followup import daily_analysis_followup_op


@job(tags={"pipeline": "daily_analysis_followup", "task_scope": "explicit_ids"})
def daily_analysis_followup_job():
    daily_analysis_followup_op()
