"""Dagster schedules for Automation Orchestrator."""

from dagster import schedule

from dagster_finance.jobs.automation_orchestration_job import automation_orchestration_job


def _launch_config(trigger: str) -> dict[str, object]:
    return {"ops": {"automation_orchestration_op": {"config": {"trigger": trigger}}}}


@schedule(
    job=automation_orchestration_job,
    cron_schedule="0 * * * *",
    execution_timezone="Asia/Shanghai",
    name="automation_hourly",
    description="Run hourly data-control and orchestration checks",
)
def automation_hourly_schedule(_context):
    return _launch_config("hourly")


@schedule(
    job=automation_orchestration_job,
    cron_schedule="*/5 * * * *",
    execution_timezone="Asia/Shanghai",
    name="automation_event_sla",
    description="Run event SLA checks every five minutes",
)
def automation_event_sla_schedule(_context):
    return _launch_config("event_sla")


@schedule(
    job=automation_orchestration_job,
    cron_schedule="0 20 * * *",
    execution_timezone="Asia/Shanghai",
    name="automation_pre_analysis",
    description="Run pre-analysis readiness orchestration at 20:00 Beijing time",
)
def automation_pre_analysis_schedule(_context):
    return _launch_config("pre_analysis")


@schedule(
    job=automation_orchestration_job,
    cron_schedule="*/5 * * * *",
    execution_timezone="Asia/Shanghai",
    name="automation_notification_retry",
    description="Retry queued notifications every five minutes",
)
def automation_notification_retry_schedule(_context):
    return _launch_config("notification_retry")
