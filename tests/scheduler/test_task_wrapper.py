from __future__ import annotations

from apps.scheduler import task_wrapper


def test_should_record_samples_high_frequency_jin10_tasks(monkeypatch) -> None:
    monkeypatch.setattr(task_wrapper, "_last_record_time", {})

    assert task_wrapper._should_record("jin10_flash") is True
    assert task_wrapper._should_record("jin10_flash") is False
