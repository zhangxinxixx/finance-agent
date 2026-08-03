"""Bridge Dagster run lifecycle into the canonical task_runs read model."""

from __future__ import annotations

import json
import uuid
from typing import Any

from dagster import In, Nothing, Out, failure_hook, op

from apps.premarket import materialize_premarket_task_steps
from apps.runtime.state_machine import transition_task_run, transition_task_step
from database.models.task import StepStatus, TaskRun, TaskStatus, TaskStep

_GOLD_DAILY_REPORT_AUTHORITY_SCHEMA = "gold_daily_report_premarket_authority.v1"
_GOLD_DAILY_REPORT_AUTHORITY_SCOPE = "gold_daily_report_only"
_GOLD_DAILY_REPORT_BLOCK_REASONS = frozenset(
    {
        "downstream_full_analysis_blocked",
        "downstream_readiness_not_ready",
    }
)


@op(
    required_resource_keys={"db_session"},
    out=Out(Nothing),
    tags={"pipeline": "premarket", "step": "task_run_init"},
)
def premarket_task_run_init_op(context) -> None:
    """Create the TaskRun before any collector can register run artifacts."""

    _, missing_step_count = ensure_premarket_task_run(
        context.resources.db_session,
        run_id=context.run_id,
    )
    context.log.info(
        "TaskRun initialized before collectors: run_id=%s steps_added=%s",
        context.run_id,
        missing_step_count,
    )


def ensure_premarket_task_run(db: Any, *, run_id: str) -> tuple[TaskRun, int]:
    """Idempotently materialize the canonical DB lineage for one Dagster run."""

    run_uuid = uuid.UUID(run_id)
    run = db.query(TaskRun).filter(TaskRun.id == run_uuid).first()
    if run is None:
        run = TaskRun(
            id=run_uuid,
            name="premarket",
            task_type="premarket",
            status=TaskStatus.pending,
        )
        db.add(run)
        db.flush()

    existing_steps = {step.name for step in db.query(TaskStep).filter(TaskStep.task_run_id == run_uuid).all()}
    missing_steps = [step for step in materialize_premarket_task_steps(run_uuid) if step.name not in existing_steps]
    db.add_all(missing_steps)
    if run.status in {TaskStatus.pending, TaskStatus.running}:
        transition_task_run(
            db,
            run,
            TaskStatus.running,
            source="dagster",
            reason="premarket_job_started",
            progress=0.0,
        )
    db.commit()
    return run, len(missing_steps)


@op(
    required_resource_keys={"db_session"},
    ins={"analysis_result": In(Any)},
    out=Out(Nothing),
    tags={"pipeline": "premarket", "step": "task_run_complete"},
)
def premarket_task_run_complete_op(context, analysis_result: Any) -> None:
    """Close the TaskRun after every canonical Dagster dependency succeeded."""

    complete_premarket_task_run(
        context.resources.db_session,
        run_id=context.run_id,
        analysis_result=analysis_result,
    )
    context.log.info("TaskRun completed: run_id=%s", context.run_id)


def complete_premarket_task_run(
    db: Any,
    *,
    run_id: str,
    analysis_result: Any = None,
) -> TaskRun:
    """Close the canonical TaskRun without hiding a blocked analysis gate."""

    run_uuid = uuid.UUID(run_id)
    run = db.query(TaskRun).filter(TaskRun.id == run_uuid).first()
    if run is None:
        raise RuntimeError(f"TaskRun missing at premarket completion: {run_id}")

    steps = db.query(TaskStep).filter(TaskStep.task_run_id == run_uuid).all()
    blocked_reason = _blocked_analysis_reason(analysis_result)
    for step in steps:
        if step.status in {StepStatus.pending, StepStatus.running, StepStatus.blocked}:
            if blocked_reason is not None and step.name == "strategy_card":
                output = {
                    "output_mode": "blocked",
                    "reason_code": blocked_reason,
                    "publish_allowed": False,
                }
                limited_authority = _gold_daily_report_authority_receipt(
                    run=run,
                    analysis_result=analysis_result,
                    blocked_reason=blocked_reason,
                )
                if limited_authority is not None:
                    output["gold_daily_report_authority"] = limited_authority
                step.output_json = json.dumps(output, ensure_ascii=False, sort_keys=True)
                transition_task_step(
                    db,
                    step,
                    StepStatus.blocked,
                    source="dagster",
                    reason="premarket_analysis_blocked",
                    blocked_reason=blocked_reason,
                    retryable=True,
                )
                continue
            transition_task_step(
                db,
                step,
                StepStatus.success,
                source="dagster",
                reason="premarket_job_completed",
            )
    if blocked_reason is None:
        transition_task_run(
            db,
            run,
            TaskStatus.success,
            source="dagster",
            reason="premarket_job_completed",
            progress=1.0,
        )
    else:
        successful_steps = sum(step.status == StepStatus.success for step in steps)
        transition_task_run(
            db,
            run,
            TaskStatus.blocked,
            source="dagster",
            reason="premarket_analysis_blocked",
            error_message=blocked_reason,
            progress=successful_steps / len(steps) if steps else 0.0,
        )
    db.commit()
    return run


def _gold_daily_report_authority_receipt(
    *,
    run: TaskRun,
    analysis_result: Any,
    blocked_reason: str,
) -> dict[str, Any] | None:
    if blocked_reason not in _GOLD_DAILY_REPORT_BLOCK_REASONS:
        return None
    if not isinstance(analysis_result, dict):
        return None
    readiness_gate = analysis_result.get("premarket_readiness_gate")
    if not isinstance(readiness_gate, dict) or readiness_gate.get("decision") != "block":
        return None
    if readiness_gate.get("can_run_daily_report") is not True:
        return None
    if readiness_gate.get("can_run_full_analysis") is not False:
        return None
    if not run.snapshot_id or not run.trade_date:
        return None
    expected_source_ref = f"monitoring/{run.trade_date}/downstream_readiness.json"
    if readiness_gate.get("source_ref") != expected_source_ref:
        return None
    observed_at = readiness_gate.get("observed_at")
    if not isinstance(observed_at, str) or not observed_at.strip():
        return None
    return {
        "schema_version": _GOLD_DAILY_REPORT_AUTHORITY_SCHEMA,
        "authority_scope": _GOLD_DAILY_REPORT_AUTHORITY_SCOPE,
        "run_id": str(run.id),
        "snapshot_id": run.snapshot_id,
        "trade_date": run.trade_date,
        "readiness_decision": "block",
        "readiness": readiness_gate.get("readiness"),
        "reason_code": blocked_reason,
        "can_run_daily_report": True,
        "can_run_full_analysis": False,
        "publish_allowed": False,
        "source_ref": expected_source_ref,
        "observed_at": observed_at,
    }


def _blocked_analysis_reason(analysis_result: Any) -> str | None:
    if not isinstance(analysis_result, dict) or analysis_result.get("output_mode") != "blocked":
        return None
    readiness_gate = analysis_result.get("premarket_readiness_gate")
    if isinstance(readiness_gate, dict) and readiness_gate.get("reason_code"):
        return str(readiness_gate["reason_code"])
    quality_gate = analysis_result.get("quality_gate_decision")
    if isinstance(quality_gate, dict):
        reason_codes = quality_gate.get("reason_codes")
        if isinstance(reason_codes, list) and reason_codes:
            return str(reason_codes[0])
    return "premarket_readiness_blocked"


@failure_hook(required_resource_keys={"db_session"})
def premarket_task_run_failure_hook(context) -> None:
    """Mirror a Dagster op failure into TaskRun without masking the root error."""

    db = context.resources.db_session
    try:
        run_uuid = uuid.UUID(context.run_id)
        run = db.query(TaskRun).filter(TaskRun.id == run_uuid).first()
        if run is None or run.status not in {TaskStatus.pending, TaskStatus.running}:
            return
        error_message = str(context.op_exception or "Dagster premarket op failed")
        transition_task_run(
            db,
            run,
            TaskStatus.failed,
            source="dagster",
            reason=f"op_failed:{context.op.name}",
            error_message=error_message,
        )
        db.commit()
    except Exception:
        db.rollback()
        context.log.exception("Failed to mirror Dagster failure into TaskRun")
