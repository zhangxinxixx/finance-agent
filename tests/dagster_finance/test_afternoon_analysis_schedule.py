from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from dagster import DefaultScheduleStatus, SkipReason, build_schedule_context
from dagster._utils.schedules import schedule_execution_time_iterator

from dagster_finance.definitions import defs
from dagster_finance.jobs.premarket_job import premarket_job
from dagster_finance.schedules.afternoon_analysis_schedule import daily_afternoon_analysis_schedule
from dagster_finance.schedules.premarket_schedule import premarket_daily_schedule


def test_afternoon_schedule_runs_daily_at_14_beijing_including_weekends() -> None:
    schedule_def = daily_afternoon_analysis_schedule
    assert schedule_def.name == "daily_afternoon_analysis"
    assert schedule_def.cron_schedule == "0 14 * * *"
    assert schedule_def.execution_timezone == "Asia/Shanghai"
    assert schedule_def.default_status == DefaultScheduleStatus.RUNNING

    start = datetime(2026, 10, 9, 5, 59, tzinfo=timezone.utc)
    ticks = schedule_execution_time_iterator(
        start.timestamp(), schedule_def.cron_schedule, schedule_def.execution_timezone
    )
    scheduled_at = [next(ticks) for _ in range(4)]
    assert [tick.astimezone(timezone.utc) for tick in scheduled_at] == [
        datetime(2026, 10, day, 6, tzinfo=timezone.utc) for day in (9, 10, 11, 12)
    ]
    assert all(tick.astimezone(ZoneInfo("Asia/Shanghai")).hour == 14 for tick in scheduled_at)


@pytest.mark.parametrize("readiness", ["ready", "degraded"])
def test_afternoon_schedule_runs_when_sources_are_not_blocked(
    monkeypatch: pytest.MonkeyPatch, readiness: str
) -> None:
    monkeypatch.setattr(
        "apps.api.services.pipeline_contract_service.build_premarket_pipeline_source_readiness",
        lambda: {"source_readiness_summary": {"decision_counts": {readiness: 1, "blocked": 0}}},
    )

    assert daily_afternoon_analysis_schedule(build_schedule_context()) == {}


def test_afternoon_schedule_skips_when_source_readiness_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "apps.api.services.pipeline_contract_service.build_premarket_pipeline_source_readiness",
        lambda: {"source_readiness_summary": {"decision_counts": {"blocked": 1}}},
    )

    result = daily_afternoon_analysis_schedule(build_schedule_context())
    assert isinstance(result, SkipReason)
    assert "blocked" in result.skip_message


def test_afternoon_schedule_is_registered_for_existing_premarket_job() -> None:
    assert defs.get_job_def("premarket_job") is premarket_job
    assert defs.get_schedule_def("daily_afternoon_analysis") is daily_afternoon_analysis_schedule
    assert daily_afternoon_analysis_schedule.job is premarket_job
    assert defs.get_schedule_def("premarket_daily") is premarket_daily_schedule
    assert premarket_daily_schedule.cron_schedule == "30 0 * * 1-5"
    assert premarket_daily_schedule.default_status == DefaultScheduleStatus.RUNNING
