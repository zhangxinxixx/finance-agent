"""Dagster operation for the existing data-quality monitor."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

from dagster import Config, op

from apps.monitoring.data_quality_agent import run_data_quality_monitor


class DataQualityConfig(Config):
    """Runtime inputs for one trade-date data-quality run."""

    trade_date: Optional[str] = None
    observed_at: Optional[str] = None
    storage_root: str = "./storage"
    record_task_run: bool = True
    run_source_probes: bool = False
    run_consistency_checks: bool = True


def _parse_observed_at(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("observed_at must include a timezone")
    return parsed.astimezone(UTC)


@op(tags={"pipeline": "data_quality", "step": "monitor"})
def data_quality_monitor_op(context, config: DataQualityConfig) -> dict[str, Any]:
    """Run the existing monitor without treating readiness states as failures."""
    result = run_data_quality_monitor(
        storage_root=Path(config.storage_root),
        trade_date=config.trade_date,
        observed_at=_parse_observed_at(config.observed_at),
        record_task_run=config.record_task_run,
        run_source_probes=config.run_source_probes,
        run_consistency_checks=config.run_consistency_checks,
    )
    readiness = result.get("downstream_readiness", {}).get("readiness", "unknown")
    context.log.info(
        "Data quality monitor completed: trade_date=%s readiness=%s",
        result.get("trade_date"),
        readiness,
    )
    return result
