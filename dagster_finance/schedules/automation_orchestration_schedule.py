"""Dagster schedules for Automation Orchestrator."""

from datetime import datetime, timezone

from dagster import RunRequest, schedule

from dagster_finance.jobs.automation_orchestration_job import automation_orchestration_job


def _launch_request(context, trigger: str) -> RunRequest:
    scheduled_at = context.scheduled_execution_time or datetime.now(timezone.utc)
    tick = scheduled_at.astimezone(timezone.utc).isoformat()
    return RunRequest(
        run_key=f"automation:{trigger}:{tick}",
        run_config={"ops": {"automation_orchestration_op": {"config": {"trigger": trigger}}}},
        tags={"automation/trigger": trigger, "automation/tick": tick},
    )


@schedule(
    job=automation_orchestration_job,
    cron_schedule="0 * * * *",
    execution_timezone="Asia/Shanghai",
    name="automation_hourly",
    description="Run hourly data-control and orchestration checks",
)
def automation_hourly_schedule(context):
    return _launch_request(context, "hourly")


@schedule(
    job=automation_orchestration_job,
    cron_schedule="*/5 * * * *",
    execution_timezone="Asia/Shanghai",
    name="automation_event_sla",
    description="Run event SLA checks every five minutes",
)
def automation_event_sla_schedule(context):
    return _launch_request(context, "event_sla")


@schedule(
    job=automation_orchestration_job,
    cron_schedule="0 20 * * *",
    execution_timezone="Asia/Shanghai",
    name="automation_pre_analysis",
    description="Run pre-analysis readiness orchestration at 20:00 Beijing time",
)
def automation_pre_analysis_schedule(context):
    return _launch_request(context, "pre_analysis")


@schedule(
    job=automation_orchestration_job,
    cron_schedule="*/5 * * * *",
    execution_timezone="Asia/Shanghai",
    name="automation_notification_retry",
    description="Retry queued notifications every five minutes",
)
def automation_notification_retry_schedule(context):
    return _launch_request(context, "notification_retry")
