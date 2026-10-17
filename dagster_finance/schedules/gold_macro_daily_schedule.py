"""Weekday noon candidate schedule. Stopped until an approved Canary enables it."""
import os

from dagster import DefaultScheduleStatus, RunRequest, SkipReason, schedule

from apps.worker.pipelines.gold_macro_daily_scheduled import noon_slot
from dagster_finance.jobs.gold_macro_daily_job import gold_macro_daily_job


@schedule(job=gold_macro_daily_job, cron_schedule='0 12 * * 1-5', execution_timezone='Asia/Shanghai',
          name='gold_macro_daily_weekday_noon', default_status=DefaultScheduleStatus.STOPPED)
def gold_macro_daily_weekday_noon(context):
    at = context.scheduled_execution_time
    try:
        cutoff, key = noon_slot(at.isoformat() if at else '')
    except ValueError:
        return SkipReason('No valid weekday noon tick')
    paths = {key: os.environ.get('FINANCE_AGENT_MACRO_DAILY_' + key.upper())
             for key in ('storage_root', 'source_root', 'prior_report_root')}
    if not all(paths.values()):
        return SkipReason('Explicit macro daily directories are not configured')
    provider = os.environ.get('FINANCE_AGENT_MACRO_DAILY_PROVIDER')
    enabled = os.environ.get('FINANCE_AGENT_MACRO_DAILY_MODEL_AUTHORIZED') == '1'
    if enabled and not provider:
        return SkipReason('Authorized model provider is not configured')
    resource_config = {'enabled': enabled}
    if provider:
        resource_config['provider'] = provider
    return RunRequest(run_key=key, tags={'research_slot': key, 'scheduled_for': cutoff.isoformat()},
        run_config={'ops': {'gold_macro_daily_noon_op': {'config': {'scheduled_for': cutoff.isoformat(), **paths}}},
                    'resources': {'macro_daily_gateway': {'config': resource_config}}})
