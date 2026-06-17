"""任务运行记录工具。

提供 TaskRecorder 上下文管理器，任务执行时自动写入 task_runs + task_steps。
支持装饰器模式和上下文管理器两种用法。

用法：
    with TaskRecorder(task_type="macro_collect", task_name="FRED 采集") as rec:
        rec.step("collect_fred", status="running")
        result = collect_fred_series(...)
        rec.step("collect_fred", status="success", output_refs=[...])
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from database.models.engine import SessionLocal
from database.models.task import TaskRun, TaskStatus, TaskStep, StepStatus
from sqlalchemy.orm import Session


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaskRecorder:
    """记录一次任务运行的全生命周期到 task_runs / task_steps 表。"""

    def __init__(
        self,
        task_type: str,
        task_name: str,
        trade_date: str | None = None,
        workspace_id: str | None = "finance-agent",
    ):
        self._task_type = task_type
        self._task_name = task_name
        self._trade_date = trade_date
        self._workspace_id = workspace_id
        self._run_id: uuid.UUID | None = None
        self._session: Session | None = None
        self._started = False
        self._step_order_counter = 0

    def __enter__(self) -> "TaskRecorder":
        self._session = SessionLocal()
        self._start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type is not None:
                self._fail(str(exc_val))
            else:
                self._succeed()
        finally:
            if self._session:
                self._session.close()
                self._session = None

    def run_id(self) -> str | None:
        return str(self._run_id) if self._run_id else None

    def _start(self):
        run = TaskRun(
            name=self._task_name,
            task_type=self._task_type,
            workspace_id=self._workspace_id,
            status=TaskStatus.running,
            trade_date=self._trade_date,
            started_at=utc_now(),
        )
        self._session.add(run)
        self._session.flush()
        self._run_id = run.id
        self._started = True

    def _succeed(self):
        if not self._run_id or not self._session:
            return
        run = self._session.get(TaskRun, self._run_id)
        if run:
            run.status = TaskStatus.success
            run.ended_at = utc_now()
            if run.started_at:
                run.progress = 1.0
        self._session.commit()

    def _fail(self, error_message: str):
        if not self._run_id or not self._session:
            return
        run = self._session.get(TaskRun, self._run_id)
        if run:
            run.status = TaskStatus.failed
            run.error = error_message
            run.error_summary = error_message[:500]
            run.ended_at = utc_now()
        self._session.commit()

    def step(
        self,
        step_name: str,
        status: str = "running",
        stage: str | None = None,
        task_kind: str | None = None,
        error: str | None = None,
        input_refs: list[dict] | None = None,
        output_refs: list[dict] | None = None,
        source_refs: list[dict] | None = None,
        artifact_refs: list[dict] | None = None,
        output_ref: str | None = None,
    ) -> str | None:
        """记录一个步骤。返回 step_id 字符串。"""
        if not self._session or not self._run_id:
            return None

        step_status = StepStatus.running
        if status == "success":
            step_status = StepStatus.success
        elif status == "failed":
            step_status = StepStatus.failed
        elif status == "skipped":
            step_status = StepStatus.skipped
        elif status == "blocked":
            step_status = StepStatus.blocked

        self._step_order_counter += 1

        step = TaskStep(
            task_run_id=self._run_id,
            name=step_name,
            stage=stage,
            task_kind=task_kind,
            status=step_status,
            error=error,
            step_order=self._step_order_counter,
            input_refs=json.dumps(input_refs) if input_refs else None,
            output_refs=json.dumps(output_refs) if output_refs else None,
            source_refs=json.dumps(source_refs) if source_refs else None,
            artifact_refs=json.dumps(artifact_refs) if artifact_refs else None,
            output_ref=output_ref,
            started_at=utc_now() if status == "running" else None,
            finished_at=utc_now() if status in ("success", "failed", "skipped", "blocked") else None,
        )
        self._session.add(step)
        self._session.flush()
        return str(step.id)


def record_task(task_type: str, task_name: str, trade_date: str | None = None) -> TaskRecorder:
    """便捷工厂函数，返回 TaskRecorder 上下文管理器。"""
    return TaskRecorder(
        task_type=task_type,
        task_name=task_name,
        trade_date=trade_date,
    )
