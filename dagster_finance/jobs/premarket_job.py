"""Dagster job definitions for the premarket pipeline."""

from dagster import job

from dagster_finance.graphs.premarket import premarket_graph
from dagster_finance.resources.db import DbSessionResource


@job(
    name="premarket_job",
    description="Full premarket pipeline: 3 sub-pipelines in parallel → C4 agents → strategy card",
    resource_defs={
        "db_session": DbSessionResource.configure_at_launch(),
    },
    tags={"pipeline": "premarket", "type": "scheduled"},
)
def premarket_job():
    """Execute the complete premarket pipeline."""
    premarket_graph()
