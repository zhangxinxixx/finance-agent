"""Dagster job for the daily data-quality monitor."""

from dagster import job

from dagster_finance.ops.data_quality import data_quality_monitor_op


@job(
    name="data_quality_monitor_job",
    description="Build daily source-health, data-quality, and downstream-readiness artifacts",
    tags={"pipeline": "data_quality", "type": "scheduled"},
)
def data_quality_monitor_job() -> None:
    data_quality_monitor_op()
