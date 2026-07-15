"""Dagster definitions for the finance-agent pipeline.

Entry point for dagster-webserver. Defines all jobs, schedules, sensors,
and resources.
"""

from dagster import Definitions

from dagster_finance.jobs.automation_orchestration_job import automation_orchestration_job
from dagster_finance.jobs.data_quality_job import data_quality_monitor_job
from dagster_finance.jobs.premarket_job import premarket_job
from dagster_finance.jobs.xauusd_shadow_job import xauusd_shadow_summary_job
from dagster_finance.schedules.automation_orchestration_schedule import (
    automation_event_sla_schedule,
    automation_hourly_schedule,
    automation_notification_retry_schedule,
    automation_pre_analysis_schedule,
)
from dagster_finance.schedules.data_quality_schedule import data_quality_monitor_daily_schedule
from dagster_finance.schedules.premarket_schedule import premarket_daily_schedule
from dagster_finance.schedules.xauusd_shadow_schedule import xauusd_shadow_summary_daily_schedule
from dagster_finance.resources.db import DbSessionResource


defs = Definitions(
    jobs=[premarket_job, automation_orchestration_job, data_quality_monitor_job, xauusd_shadow_summary_job],
    schedules=[
        premarket_daily_schedule,
        data_quality_monitor_daily_schedule,
        automation_hourly_schedule,
        automation_event_sla_schedule,
        automation_pre_analysis_schedule,
        automation_notification_retry_schedule,
        xauusd_shadow_summary_daily_schedule,
    ],
    resources={
        "db_session": DbSessionResource(),
    },
)
