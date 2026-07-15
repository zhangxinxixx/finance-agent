from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from dagster import DefaultScheduleStatus, build_op_context, build_schedule_context

from dagster_finance.definitions import defs
from dagster_finance.jobs.data_quality_job import data_quality_monitor_job
from dagster_finance.ops.data_quality import DataQualityConfig, data_quality_monitor_op
from dagster_finance.schedules.data_quality_schedule import data_quality_monitor_daily_schedule


def test_data_quality_schedule_builds_trade_date_request() -> None:
    scheduled_at = datetime(2026, 7, 20, 0, 15, tzinfo=timezone.utc)
    request = data_quality_monitor_daily_schedule(
        build_schedule_context(scheduled_execution_time=scheduled_at)
    )

    assert request.run_key == "data-quality:2026-07-20"
    assert request.run_config == {
        "ops": {
            "data_quality_monitor_op": {
                "config": {
                    "trade_date": "2026-07-20",
                    "observed_at": scheduled_at.isoformat(),
                    "storage_root": "./storage",
                    "record_task_run": True,
                    "run_source_probes": False,
                    "run_consistency_checks": True,
                }
            }
        }
    }
    assert request.tags == {"data_quality/trade_date": "2026-07-20"}


def test_data_quality_schedule_contract_and_definitions_registration() -> None:
    schedule_def = data_quality_monitor_daily_schedule
    assert schedule_def.name == "data_quality_monitor_daily"
    assert schedule_def.cron_schedule == "15 0 * * 1-5"
    assert schedule_def.execution_timezone == "UTC"
    assert schedule_def.default_status == DefaultScheduleStatus.RUNNING
    assert defs.get_job_def("data_quality_monitor_job") is data_quality_monitor_job
    assert defs.get_schedule_def("data_quality_monitor_daily") is schedule_def


def test_data_quality_job_contains_only_monitor_op() -> None:
    assert {node.name for node in data_quality_monitor_job.all_node_defs} == {
        "data_quality_monitor_op"
    }


@pytest.mark.parametrize("readiness", ["partial", "blocked"])
def test_data_quality_op_returns_non_ready_business_result(
    monkeypatch: pytest.MonkeyPatch,
    readiness: str,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_run_data_quality_monitor(**kwargs):
        calls.append(kwargs)
        return {
            "trade_date": "2026-07-20",
            "downstream_readiness": {"readiness": readiness},
            "artifacts": {"data_quality_report": "monitoring/2026-07-20/data_quality_report.json"},
        }

    monkeypatch.setattr(
        "dagster_finance.ops.data_quality.run_data_quality_monitor",
        fake_run_data_quality_monitor,
    )
    result = data_quality_monitor_op(
        build_op_context(),
        DataQualityConfig(
            trade_date="2026-07-20",
            observed_at="2026-07-20T00:15:00+00:00",
            storage_root="./isolated-storage",
        ),
    )

    assert result["downstream_readiness"]["readiness"] == readiness
    assert calls == [
        {
            "storage_root": Path("./isolated-storage"),
            "trade_date": "2026-07-20",
            "observed_at": datetime(2026, 7, 20, 0, 15, tzinfo=timezone.utc),
            "record_task_run": True,
            "run_source_probes": False,
            "run_consistency_checks": True,
        }
    ]


def test_data_quality_config_rejects_naive_observed_at() -> None:
    with pytest.raises(ValueError, match="observed_at must include a timezone"):
        data_quality_monitor_op(
            build_op_context(),
            DataQualityConfig(observed_at="2026-07-20T00:15:00"),
        )
