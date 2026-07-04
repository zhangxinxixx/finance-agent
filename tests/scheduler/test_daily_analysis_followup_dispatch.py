from __future__ import annotations

import uuid
from pathlib import Path

from database.models.task import TaskStatus


class _FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _ImmediateThread:
    def __init__(self, *, target, daemon, name):
        self._target = target
        self.daemon = daemon
        self.name = name

    def start(self) -> None:
        self._target()


def test_dispatch_daily_analysis_followup_task_calls_worker(monkeypatch, tmp_path: Path) -> None:
    from apps.scheduler import runner
    from apps.worker.pipelines import daily_analysis_followup
    from database.models import engine

    task_id = uuid.uuid4()
    calls: dict[str, object] = {}

    def fake_run(db, received_task_id, *, storage_root):
        calls["db"] = db
        calls["task_id"] = received_task_id
        calls["storage_root"] = storage_root
        return TaskStatus.pending

    monkeypatch.setattr(runner.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(engine, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(daily_analysis_followup, "run_daily_analysis_followup_task", fake_run)

    runner.dispatch_daily_analysis_followup_task(task_id, storage_root=tmp_path)

    assert isinstance(calls["db"], _FakeSession)
    assert calls["task_id"] == task_id
    assert calls["storage_root"] == tmp_path
