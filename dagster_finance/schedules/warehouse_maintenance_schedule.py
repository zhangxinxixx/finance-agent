"""Hourly bounded reconciliation; raw deletion is included in the daily slot."""

import os
from zoneinfo import ZoneInfo

from dagster import DefaultScheduleStatus, RunRequest, SkipReason, schedule
from dagster._check import CheckError

from dagster_finance.jobs.warehouse_maintenance_job import warehouse_maintenance_job


@schedule(job=warehouse_maintenance_job, cron_schedule="15 * * * *", execution_timezone="Asia/Shanghai",
          default_status=DefaultScheduleStatus.RUNNING,
          name="warehouse_maintenance", description="字段数仓补齐；03:15 清理已入仓且超过30天的原文件")
def warehouse_maintenance_schedule(context):
    try:
        at = context.scheduled_execution_time
    except CheckError:
        return SkipReason("scheduled_execution_time_missing")
    if at is None:
        return SkipReason("scheduled_execution_time_missing")
    return RunRequest(run_key="warehouse-maintenance:" + at.isoformat(),
                      run_config={"ops": {"warehouse_maintenance_op": {"config": {
                          "storage_root": os.environ.get("FINANCE_AGENT_STORAGE_ROOT", "./storage"),
                          "apply_retention": at.astimezone(ZoneInfo("Asia/Shanghai")).hour == 3,
                          "retention_days": 30,
                      }}}}, tags={"pipeline": "warehouse"})
