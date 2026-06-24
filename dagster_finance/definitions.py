"""Dagster definitions for the finance-agent pipeline.

Entry point for dagster-webserver. Defines all jobs, schedules, sensors,
and resources.
"""

from dagster import Definitions

from dagster_finance.jobs.premarket_job import premarket_job
from dagster_finance.schedules.premarket_schedule import premarket_daily_schedule
from dagster_finance.resources.db import DbSessionResource


defs = Definitions(
    jobs=[premarket_job],
    schedules=[premarket_daily_schedule],
    resources={
        "db_session": DbSessionResource(),
    },
)
