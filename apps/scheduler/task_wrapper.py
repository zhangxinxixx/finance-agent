"""Record each compatibility refresh before execution, including failures."""
from __future__ import annotations

from datetime import datetime, timezone
from apps.runtime.task_recorder import TaskRecorder


def record_jin10_refresh(task_key: str, task_name: str, fn, *args, **kwargs):
    """An invocation requires a task record; execution failure is never success."""
    with TaskRecorder(task_type=f"jin10_refresh_{task_key}", task_name=task_name,
                      trade_date=datetime.now(timezone.utc).strftime("%Y-%m-%d")) as rec:
        step_name = f"refresh_{task_key}"
        step_id = rec.step(step_name, status="running")
        try:
            result = fn(*args, **kwargs)
        except Exception as exc:
            rec.step(step_name, status="failed", error=type(exc).__name__, step_id=step_id)
            raise
        outcome = result.get("status") if isinstance(result, dict) else None
        status = {"failed": "failed", "error": "failed", "blocked": "blocked", "unavailable": "blocked",
                  "disabled": "skipped", "skipped": "skipped", "partial": "blocked", "degraded": "blocked"}.get(outcome, "success")
        rec.step(step_name, status=status, step_id=step_id)
        return result
