"""Dagster definitions for the finance-agent pipeline.

Entry point for dagster-webserver. Defines all jobs, schedules, sensors,
and resources.
"""

from dagster import Definitions

from dagster_finance.jobs.automation_orchestration_job import automation_orchestration_job
from dagster_finance.jobs.premarket_job import premarket_job
from dagster_finance.schedules.automation_orchestration_schedule import (
    automation_event_sla_schedule,
    automation_hourly_schedule,
    automation_notification_retry_schedule,
    automation_pre_analysis_schedule,
)
from dagster_finance.schedules.premarket_schedule import premarket_daily_schedule
from dagster_finance.resources.db import DbSessionResource


defs = Definitions(
    jobs=[premarket_job, automation_orchestration_job],
    schedules=[
        premarket_daily_schedule,
        automation_hourly_schedule,
        automation_event_sla_schedule,
        automation_pre_analysis_schedule,
        automation_notification_retry_schedule,
    ],
    resources={
        "db_session": DbSessionResource(),
    },
)
