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
from typing import Any

from apps.runtime.artifact_registry import register_step_artifacts
from apps.runtime.execution_event_bridge import emit_run_event, emit_task_event
from apps.runtime.state_machine import coerce_step_status, transition_task_run, transition_task_step
from database.models.engine import SessionLocal
from database.models.task import TaskRun, TaskStatus, TaskStep, StepStatus
from sqlalchemy.orm import Session

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
            status=TaskStatus.pending,
            trade_date=self._trade_date,
        )
        self._session.add(run)
        self._session.flush()
        self._run_id = run.id
        self._started = True
        transition_task_run(
            self._session,
            run,
            TaskStatus.running,
            source="task_recorder",
            reason="run_started",
        )
        emit_run_event(
            self._session,
            str(self._run_id),
            "RUN_STARTED",
            {
                "task_name": self._task_name,
                "task_type": self._task_type,
                "trade_date": self._trade_date,
                "workspace_id": self._workspace_id,
            },
        )

    def _succeed(self):
        if not self._run_id or not self._session:
            return
        run = self._session.get(TaskRun, self._run_id)
        if run:
            transition_task_run(
                self._session,
                run,
                TaskStatus.success,
                source="task_recorder",
                reason="run_finished",
                progress=1.0,
            )
        emit_run_event(
            self._session,
            str(self._run_id),
            "RUN_FINISHED",
            {
                "status": TaskStatus.success.value,
                "progress": 1.0,
            },
        )
        self._session.commit()

    def _fail(self, error_message: str):
        if not self._run_id or not self._session:
            return
        run = self._session.get(TaskRun, self._run_id)
        if run:
            transition_task_run(
                self._session,
                run,
                TaskStatus.failed,
                source="task_recorder",
                reason="run_failed",
                error_message=error_message,
            )
        emit_run_event(
            self._session,
            str(self._run_id),
            "RUN_FAILED",
            {
                "status": TaskStatus.failed.value,
                "error_message": error_message,
            },
        )
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

        step_status = coerce_step_status(status)

        self._step_order_counter += 1

        step = TaskStep(
            task_run_id=self._run_id,
            name=step_name,
            stage=stage,
            task_kind=task_kind,
            status=StepStatus.pending,
            step_order=self._step_order_counter,
            input_refs=json.dumps(input_refs) if input_refs else None,
            output_refs=json.dumps(output_refs) if output_refs else None,
            source_refs=json.dumps(source_refs) if source_refs else None,
            artifact_refs=json.dumps(artifact_refs) if artifact_refs else None,
            output_ref=output_ref,
        )
        self._session.add(step)
        self._session.flush()
        transition_task_step(
            self._session,
            step,
            step_status,
            source="task_recorder",
            reason="step_recorded",
            error_message=error if step_status == StepStatus.failed else None,
            blocked_reason=error if step_status == StepStatus.blocked else None,
        )
        self._emit_step_events(
            step=step,
            status=status,
            error=error,
            output_refs=output_refs,
            source_refs=source_refs,
            artifact_refs=artifact_refs,
            output_ref=output_ref,
        )
        return str(step.id)

    def _emit_step_events(
        self,
        *,
        step: TaskStep,
        status: str,
        error: str | None,
        output_refs: list[dict] | None,
        source_refs: list[dict] | None,
        artifact_refs: list[dict] | None,
        output_ref: str | None,
    ) -> None:
        if not self._session or not self._run_id:
            return

        run_id = str(self._run_id)
        task_id = str(step.id)

        if status == "running":
            emit_task_event(
                self._session,
                run_id,
                task_id,
                "TASK_STARTED",
                {
                    "step_name": step.name,
                    "stage": step.stage,
                    "task_kind": step.task_kind,
                    "step_order": step.step_order,
                },
            )
            return

        if status == "failed":
            emit_task_event(
                self._session,
                run_id,
                task_id,
                "TASK_FAILED",
                {
                    "step_name": step.name,
                    "stage": step.stage,
                    "task_kind": step.task_kind,
                    "step_order": step.step_order,
                    "error_message": error,
                },
            )
            return

        if status != "success":
            return

        emit_task_event(
            self._session,
            run_id,
            task_id,
            "TASK_FINISHED",
            {
                "step_name": step.name,
                "stage": step.stage,
                "task_kind": step.task_kind,
                "step_order": step.step_order,
                "status": status,
            },
        )
        register_step_artifacts(
            self._session,
            run_id=run_id,
            step=step,
            output_refs=output_refs,
            artifact_refs=artifact_refs,
            output_ref=output_ref,
            source_refs=source_refs,
        )
        for artifact_payload in self._artifact_event_payloads(
            output_refs=output_refs,
            artifact_refs=artifact_refs,
            output_ref=output_ref,
        ):
            emit_task_event(
                self._session,
                run_id,
                task_id,
                "ARTIFACT_WRITTEN",
                {
                    "step_name": step.name,
                    "stage": step.stage,
                    "step_order": step.step_order,
                    **artifact_payload,
                },
            )

    @staticmethod
    def _artifact_event_payloads(
        *,
        output_refs: list[dict[str, Any]] | None,
        artifact_refs: list[dict[str, Any]] | None,
        output_ref: str | None,
    ) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []

        for role, refs in (("output_refs", output_refs), ("artifact_refs", artifact_refs)):
            for ref in refs or []:
                if not isinstance(ref, dict):
                    continue
                payloads.append({"artifact_role": role, **ref})

        if output_ref:
            payloads.append(
                {
                    "artifact_role": "output_ref",
                    "artifact_type": "output_ref",
                    "file_path": output_ref,
                }
            )

        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for payload in payloads:
            key = json.dumps(payload, sort_keys=True, ensure_ascii=False)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(payload)
        return deduped


def record_task(task_type: str, task_name: str, trade_date: str | None = None) -> TaskRecorder:
    """便捷工厂函数，返回 TaskRecorder 上下文管理器。"""
    return TaskRecorder(
        task_type=task_type,
        task_name=task_name,
        trade_date=trade_date,
    )
