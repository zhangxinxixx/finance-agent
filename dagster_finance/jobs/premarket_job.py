"""Dagster job definitions for the premarket pipeline."""

from dagster import EnvVar, job

from dagster_finance.graphs.premarket import premarket_graph
from dagster_finance.ops.task_run_lifecycle import premarket_task_run_failure_hook
from dagster_finance.resources.db import DbSessionResource


@job(
    name="premarket_job",
    description="Full premarket pipeline: 3 sub-pipelines in parallel → canonical analysis → strategy card",
    resource_defs={
        "db_session": DbSessionResource(database_url=EnvVar("DATABASE_URL")),
    },
    hooks={premarket_task_run_failure_hook},
    tags={"pipeline": "premarket", "type": "scheduled"},
)
def premarket_job():
    """Execute the complete premarket pipeline."""
    premarket_graph()
