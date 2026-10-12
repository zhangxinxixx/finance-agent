from datetime import UTC, datetime

from dagster import DefaultScheduleStatus, SkipReason, build_schedule_context

from dagster_finance.definitions import defs
from dagster_finance.schedules.warehouse_maintenance_schedule import warehouse_maintenance_schedule


def test_maintenance_is_registered_and_enabled_for_new_installations():
    schedule = defs.get_schedule_def("warehouse_maintenance")
    assert schedule.job is defs.get_job_def("warehouse_maintenance_job")
    assert schedule.default_status == DefaultScheduleStatus.RUNNING
    assert schedule.execution_timezone == "Asia/Shanghai"


def test_cleanup_runs_in_beijing_daily_slot_even_if_context_uses_utc(tmp_path, monkeypatch):
    monkeypatch.setenv("FINANCE_AGENT_STORAGE_ROOT", str(tmp_path))
    context = build_schedule_context(scheduled_execution_time=datetime(2026, 10, 9, 19, 15, tzinfo=UTC))
    request = warehouse_maintenance_schedule(context)
    config = request.run_config["ops"]["warehouse_maintenance_op"]["config"]
    assert config == {"storage_root": str(tmp_path), "apply_retention": True, "retention_days": 30}
    daytime = build_schedule_context(scheduled_execution_time=datetime(2026, 10, 10, 3, 15, tzinfo=UTC))
    request = warehouse_maintenance_schedule(daytime)
    assert request.run_config["ops"]["warehouse_maintenance_op"]["config"]["apply_retention"] is False
    assert isinstance(warehouse_maintenance_schedule(build_schedule_context()), SkipReason)
