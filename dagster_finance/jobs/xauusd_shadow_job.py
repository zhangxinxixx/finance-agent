"""Dagster job for the XAU/USD provider shadow summary."""

from dagster import job

from dagster_finance.ops.xauusd_shadow import (
    xauusd_live_strategy_history_op,
    xauusd_shadow_evaluation_op,
    xauusd_shadow_summary_op,
)
from dagster_finance.resources.db import DbSessionResource


@job(
    name="xauusd_shadow_summary_job",
    description="Build the finalized daily XAU/USD provider shadow summary",
    resource_defs={"db_session": DbSessionResource.configure_at_launch()},
    tags={"pipeline": "xauusd_shadow", "type": "scheduled"},
)
def xauusd_shadow_summary_job() -> None:
    history_freeze = xauusd_live_strategy_history_op()
    xauusd_shadow_evaluation_op(history_freeze)
    xauusd_shadow_summary_op()
