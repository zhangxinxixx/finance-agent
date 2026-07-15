from __future__ import annotations

from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from time import sleep

import pytest
from dagster import Failure, build_op_context, build_schedule_context

from dagster_finance.definitions import defs
from dagster_finance.ops.automation_orchestration import (
    AutomationOrchestrationConfig,
    automation_orchestration_op,
)
from dagster_finance.schedules.automation_orchestration_schedule import (
    automation_event_sla_schedule,
    automation_hourly_schedule,
    automation_notification_retry_schedule,
    automation_pre_analysis_schedule,
)


def test_definitions_register_automation_orchestration_job_and_schedules() -> None:
    assert defs.get_job_def("automation_orchestration_job").name == "automation_orchestration_job"
    for schedule_name in {
        "automation_hourly",
        "automation_event_sla",
        "automation_pre_analysis",
        "automation_notification_retry",
    }:
        assert defs.get_schedule_def(schedule_name).name == schedule_name


def test_automation_schedules_launch_the_expected_trigger_config() -> None:
    scheduled_at = datetime(2026, 7, 8, 10, 30, tzinfo=timezone.utc)
    context = build_schedule_context(scheduled_execution_time=scheduled_at)

    requests = {
        "hourly": automation_hourly_schedule(context),
        "event_sla": automation_event_sla_schedule(context),
        "pre_analysis": automation_pre_analysis_schedule(context),
        "notification_retry": automation_notification_retry_schedule(context),
    }
    for trigger, request in requests.items():
        assert request.run_config == {
            "ops": {"automation_orchestration_op": {"config": {"trigger": trigger}}}
        }
        assert request.run_key == f"automation:{trigger}:2026-07-08T10:30:00+00:00"
        assert request.tags["automation/trigger"] == trigger


def test_automation_op_uses_single_concurrency_pool() -> None:
    assert automation_orchestration_op._pool == "automation_orchestration"


def test_automation_op_serializes_formal_orchestration_runs(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    active = 0
    max_active = 0
    guard = Lock()

    def run_hourly_orchestration(**_kwargs):
        nonlocal active, max_active
        with guard:
            active += 1
            max_active = max(max_active, active)
        sleep(0.05)
        with guard:
            active -= 1
        return {"status": "normal"}

    monkeypatch.setattr(
        "dagster_finance.ops.automation_orchestration.run_hourly_orchestration",
        run_hourly_orchestration,
    )

    def run_once(_index: int):
        return automation_orchestration_op(
            build_op_context(),
            AutomationOrchestrationConfig(trigger="hourly", storage_root=str(tmp_path)),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(run_once, range(2)))

    assert max_active == 1


def test_automation_op_dispatches_the_selected_existing_wrapper(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    called: list[dict[str, object]] = []
    expected = {"status": "completed", "trigger": "event_sla"}

    def run_event_sla_orchestration(**kwargs):
        called.append(kwargs)
        return expected

    monkeypatch.setattr(
        "dagster_finance.ops.automation_orchestration.run_event_sla_orchestration",
        run_event_sla_orchestration,
    )

    context = build_op_context()
    result = automation_orchestration_op(
        context,
        AutomationOrchestrationConfig(trigger="event_sla", storage_root=str(tmp_path)),
    )

    assert result == expected
    assert called == [
        {
            "storage_root": tmp_path,
            "send_notifications": True,
            "record_task_run": True,
            "run_id": context.run_id,
        }
    ]


def test_automation_op_raises_when_wrapper_reports_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "dagster_finance.ops.automation_orchestration.run_hourly_orchestration",
        lambda **_kwargs: {"status": "failed"},
    )

    with pytest.raises(Failure, match="returned failed"):
        automation_orchestration_op(build_op_context(), AutomationOrchestrationConfig(trigger="hourly"))
