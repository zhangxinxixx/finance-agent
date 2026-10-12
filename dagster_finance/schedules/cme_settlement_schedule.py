"""Daily archive plus same-date reconciliation; no implicit runtime activation."""

import os
from dagster import RunRequest, SkipReason, schedule

from database.queries.cme_settlement import expected_trade_date
from dagster_finance.jobs.cme_settlement_job import cme_settlement_job


@schedule(
    job=cme_settlement_job,
    cron_schedule="0 6,12 * * *",
    execution_timezone="America/Chicago",
    name="cme_fed_funds_settlement",
    description="Daily settlement archive and revision check",
)
def cme_settlement_schedule(context):
    at = context.scheduled_execution_time
    if at is None:
        return SkipReason("scheduled_execution_time_missing")
    return RunRequest(
        run_key="cme-settlement:" + at.isoformat(),
        run_config={
            "ops": {
                "cme_settlement_op": {
                    "config": {
                        "storage_root": os.environ.get("CME_SETTLEMENT_STORAGE_ROOT", "./storage"),
                        "trade_date": expected_trade_date(at).isoformat(),
                    }
                }
            }
        },
        tags={"source": "cme_settlement"},
    )
