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

from apps.runtime.artifact_registry import register_step_artifacts
from apps.runtime.execution_event_bridge import emit_task_event
from apps.runtime.state_machine import derive_task_run_status, coerce_step_status, transition_task_run, transition_task_step
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

    def _succeed(self):
        if not self._run_id or not self._session:
            return
        run = self._session.get(TaskRun, self._run_id)
        if run:
            latest_status_by_name = {
                name: status
                for name, status in self._session.query(TaskStep.name, TaskStep.status)
                .filter(TaskStep.task_run_id == self._run_id)
                .order_by(TaskStep.step_order.asc())
            }
            final_status = (
                derive_task_run_status(latest_status_by_name.values())
                if latest_status_by_name
                else TaskStatus.success
            )
            transition_task_run(
                self._session,
                run,
                final_status,
                source="task_recorder",
                reason="run_finished",
                progress=1.0,
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
        step_id: str | None = None,
    ) -> str | None:
        """记录或收尾一个步骤。返回 step_id 字符串。

        A caller that needs a running-to-terminal transition can pass the id
        returned by the first call back as ``step_id``.  This keeps one
        ``TaskStep`` row and lets the state machine record the transition on
        the same step instead of appending a second row with the same name.
        """
        if not self._session or not self._run_id:
            return None

        step_status = coerce_step_status(status)

        if step_id is None:
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
        else:
            try:
                existing_step_id = uuid.UUID(step_id)
            except (ValueError, AttributeError) as exc:
                raise ValueError(f"Unknown task step id: {step_id!r}") from exc
            step = self._session.get(TaskStep, existing_step_id)
            if step is None or step.task_run_id != self._run_id:
                raise ValueError(f"Task step {step_id!r} does not belong to this task run")
            if step.name != step_name:
                raise ValueError(
                    f"Task step {step_id!r} name mismatch: {step.name!r} != {step_name!r}"
                )
            # Preserve the original order and execution metadata, while
            # allowing terminal calls to attach their final refs.
            if stage is not None:
                step.stage = stage
            if task_kind is not None:
                step.task_kind = task_kind
            if input_refs is not None:
                step.input_refs = json.dumps(input_refs)
            if output_refs is not None:
                step.output_refs = json.dumps(output_refs)
            if source_refs is not None:
                step.source_refs = json.dumps(source_refs)
            if artifact_refs is not None:
                step.artifact_refs = json.dumps(artifact_refs)
            if output_ref is not None:
                step.output_ref = output_ref

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
            return

        persisted = register_step_artifacts(
            self._session,
            run_id=run_id,
            step=step,
            output_refs=output_refs,
            artifact_refs=artifact_refs,
            output_ref=output_ref,
            source_refs=source_refs,
        )
        for artifact in persisted:
            emit_task_event(
                self._session,
                run_id,
                task_id,
                "ARTIFACT_WRITTEN",
                {
                    "step_name": step.name,
                    "step_status": step.status.value,
                    "stage": step.stage,
                    "step_order": step.step_order,
                    "artifact_role": "registry",
                    "artifact_id": str(artifact.artifact_id),
                    "artifact_type": artifact.artifact_type,
                    "file_path": artifact.file_path,
                    "sha256": artifact.sha256,
                    "artifact_metadata": artifact.artifact_metadata or {},
                },
            )


def record_task(task_type: str, task_name: str, trade_date: str | None = None) -> TaskRecorder:
    """便捷工厂函数，返回 TaskRecorder 上下文管理器。"""
    return TaskRecorder(
        task_type=task_type,
        task_name=task_name,
        trade_date=trade_date,
    )
