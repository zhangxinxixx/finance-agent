"""Dagster job for Automation Orchestrator schedules."""

from dagster import job

from dagster_finance.ops.automation_orchestration import automation_orchestration_op


@job(
    name="automation_orchestration_job",
    description="Run scheduled data-control, event-SLA, and notification orchestration wrappers",
    tags={"pipeline": "automation_orchestration", "type": "scheduled"},
)
def automation_orchestration_job() -> None:
    automation_orchestration_op()
