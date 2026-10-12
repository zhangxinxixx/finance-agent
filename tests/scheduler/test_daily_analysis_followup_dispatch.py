from __future__ import annotations

import threading
import uuid
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "function_name",
    ["dispatch_premarket_task", "dispatch_daily_analysis_followup_task"],
)
def test_retired_scheduler_dispatches_fail_before_starting_worker(
    function_name: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from apps.scheduler import runner
    from apps.worker import runner as worker_runner
    from apps.worker.pipelines import daily_analysis_followup
    from database.models import engine

    task_id = uuid.uuid4()
    calls: list[str] = []

    def _unexpected_thread(*_args, **_kwargs):
        calls.append("thread")

    def _unexpected_session(*_args, **_kwargs):
        calls.append("session")

    def _unexpected_worker(*_args, **_kwargs):
        calls.append("worker")

    monkeypatch.setattr(threading, "Thread", _unexpected_thread)
    monkeypatch.setattr(engine, "SessionLocal", _unexpected_session)
    monkeypatch.setattr(worker_runner, "run_premarket", _unexpected_worker)
    monkeypatch.setattr(daily_analysis_followup, "run_daily_analysis_followup_task", _unexpected_worker)

    with pytest.raises(runner.LegacySchedulerDispatchDisabled, match="Dagster"):
        getattr(runner, function_name)(task_id, storage_root=tmp_path)

    assert calls == []
