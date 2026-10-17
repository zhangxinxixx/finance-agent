"""Dagster definitions for the finance-agent pipeline.

Entry point for dagster-webserver. Defines all jobs, schedules, sensors,
and resources.
"""

from dagster import Definitions
from dagster_finance.jobs.gold_macro_daily_job import gold_macro_daily_job
from dagster_finance.schedules.gold_macro_daily_schedule import gold_macro_daily_weekday_noon

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
from dagster_finance.schedules.afternoon_analysis_schedule import daily_afternoon_analysis_schedule
from dagster_finance.schedules.data_quality_schedule import data_quality_monitor_daily_schedule
from dagster_finance.schedules.premarket_schedule import premarket_daily_schedule
from dagster_finance.schedules.xauusd_shadow_schedule import xauusd_shadow_summary_daily_schedule
from dagster_finance.resources.db import DbSessionResource
from dagster_finance.jobs.fedwatch_job import fedwatch_refresh_job
from dagster_finance.schedules.fedwatch_schedule import fedwatch_free_schedule
from dagster_finance.jobs.cme_settlement_job import cme_settlement_job
from dagster_finance.jobs.daily_analysis_followup_job import daily_analysis_followup_job
from dagster_finance.schedules.cme_settlement_schedule import cme_settlement_schedule
from dagster_finance.jobs.warehouse_maintenance_job import warehouse_maintenance_job
from dagster_finance.schedules.warehouse_maintenance_schedule import warehouse_maintenance_schedule


defs = Definitions(
    jobs=[premarket_job, automation_orchestration_job, data_quality_monitor_job, xauusd_shadow_summary_job, fedwatch_refresh_job, cme_settlement_job, warehouse_maintenance_job, daily_analysis_followup_job, gold_macro_daily_job],
    schedules=[
        gold_macro_daily_weekday_noon,
        warehouse_maintenance_schedule,
        cme_settlement_schedule,
        fedwatch_free_schedule,
        premarket_daily_schedule,
        daily_afternoon_analysis_schedule,
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
