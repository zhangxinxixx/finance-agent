from __future__ import annotations

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
    context = build_schedule_context()

    assert automation_hourly_schedule(context) == {
        "ops": {"automation_orchestration_op": {"config": {"trigger": "hourly"}}}
    }
    assert automation_event_sla_schedule(context) == {
        "ops": {"automation_orchestration_op": {"config": {"trigger": "event_sla"}}}
    }
    assert automation_pre_analysis_schedule(context) == {
        "ops": {"automation_orchestration_op": {"config": {"trigger": "pre_analysis"}}}
    }
    assert automation_notification_retry_schedule(context) == {
        "ops": {"automation_orchestration_op": {"config": {"trigger": "notification_retry"}}}
    }


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

    result = automation_orchestration_op(
        build_op_context(),
        AutomationOrchestrationConfig(trigger="event_sla", storage_root=str(tmp_path)),
    )

    assert result == expected
    assert called == [{"storage_root": tmp_path, "send_notifications": True, "record_task_run": True}]


def test_automation_op_raises_when_wrapper_reports_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "dagster_finance.ops.automation_orchestration.run_hourly_orchestration",
        lambda **_kwargs: {"status": "failed"},
    )

    with pytest.raises(Failure, match="returned failed"):
        automation_orchestration_op(build_op_context(), AutomationOrchestrationConfig(trigger="hourly"))
