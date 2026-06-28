from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from sqlalchemy.orm import Session, selectinload

from apps.runtime.artifact_registry import register_step_artifacts
from apps.runtime.state_machine import transition_task_run, transition_task_step
from database.models.task import StepStatus, TaskRun, TaskStatus, TaskStep

TASK_TYPE = "daily_analysis_followup"
INITIAL_STAGE = "news_followup"
DETAIL_FETCH_STEP = "detail_fetch"
VIP_BROWSER_FALLBACK_STEP = "vip_browser_fallback"
DAILY_ANALYSIS_STEP = "daily_analysis"
PLAN_VERSION = "daily-analysis-followup-plan-v1"
DEFAULT_JIN10_BROWSER_PROFILE = None
VIP_BROWSER_FALLBACK_SOURCE_KEY = "jin10_vip_browser_fallback"
VIP_FALLBACK_PARTIAL_SNAPSHOT_ERRORS = {
    "login_required",
    "profile_missing",
    "fetch_failed",
    "browser_unavailable",
}
DetailFetcher = Callable[..., Any]
VipBrowserFetcher = Callable[..., Any]


def run_daily_analysis_followup_task(
    db: Session,
    task_id: uuid.UUID | str,
    *,
    storage_root: Path = Path("./storage"),
    detail_fetcher: DetailFetcher | None = None,
    vip_browser_fetcher: VipBrowserFetcher | None = None,
) -> TaskStatus:
    """Expand a queued daily-analysis follow-up into auditable worker steps.

    This first worker slice intentionally does not call Jin10/Feishu, browser
    automation, or LLM analysis. It only turns the queued follow-up payload into
    traceable next steps so a later executor can consume them safely.
    """
    run = _load_run(db, task_id)
    if run is None or run.task_type != TASK_TYPE:
        return TaskStatus.failed

    if run.current_stage == DETAIL_FETCH_STEP:
        return _run_detail_fetch_stage(db, run=run, storage_root=storage_root, detail_fetcher=detail_fetcher)
    if run.current_stage == VIP_BROWSER_FALLBACK_STEP:
        return _run_vip_browser_fallback_stage(
            db,
            run=run,
            storage_root=storage_root,
            vip_browser_fetcher=vip_browser_fetcher,
        )
    if run.current_stage == DAILY_ANALYSIS_STEP:
        return _run_daily_analysis_stage(db, run=run, storage_root=storage_root)

    initial_step = _find_initial_step(run)
    if initial_step is None:
        transition_task_run(db, run, TaskStatus.failed, source=TASK_TYPE, reason="missing_initial_step")
        run.current_stage = INITIAL_STAGE
        run.error_summary = "daily_analysis_followup task has no queued input step"
        db.commit()
        return TaskStatus.failed

    transition_task_run(db, run, TaskStatus.running, source=TASK_TYPE, reason="expand_followup_plan")
    run.current_stage = INITIAL_STAGE
    run.progress = 0.1
    db.commit()

    payload = _parse_json(initial_step.input_json)
    if not isinstance(payload, dict):
        _fail_step(db, initial_step, "invalid_input_json", "initial follow-up step input_json is not an object")
        transition_task_run(db, run, TaskStatus.failed, source=TASK_TYPE, reason="invalid_initial_input")
        run.error_summary = "invalid follow-up input_json"
        db.commit()
        return TaskStatus.failed

    followup = payload.get("followup")
    if not isinstance(followup, dict):
        followup = {}

    source_url = str(followup.get("source_url") or "").strip()
    run_key = str(payload.get("run_id") or run.id)
    trade_date = str(payload.get("date") or run.trade_date or "")
    plan = _build_execution_plan(payload=payload, source_url=source_url, storage_root=storage_root)

    _complete_initial_step(db, initial_step, plan=plan)
    detail_step = _ensure_step(
        db,
        run=run,
        name=DETAIL_FETCH_STEP,
        order=1,
        status=StepStatus.pending if source_url else StepStatus.blocked,
        input_payload={
            "plan_version": PLAN_VERSION,
            "step": DETAIL_FETCH_STEP,
            "date": trade_date,
            "run_id": run_key,
            "source_url": source_url or None,
            "followup_id": followup.get("followup_id"),
            "source_artifact": followup.get("source_artifact"),
        },
        source_refs=initial_step.source_refs,
        input_refs=initial_step.input_refs,
        blocked_reason=None if source_url else "follow-up has no source_url for detail fetch",
        error_type=None if source_url else "data_unavailable",
    )
    _ensure_step(
        db,
        run=run,
        name=VIP_BROWSER_FALLBACK_STEP,
        order=2,
        status=StepStatus.blocked,
        input_payload={
            "plan_version": PLAN_VERSION,
            "step": VIP_BROWSER_FALLBACK_STEP,
            "date": trade_date,
            "run_id": run_key,
            "source_url": source_url or None,
            "blocked_on": DETAIL_FETCH_STEP,
        },
        source_refs=initial_step.source_refs,
        input_refs=initial_step.input_refs,
        blocked_reason="waiting for detail_fetch access_status",
    )
    _ensure_step(
        db,
        run=run,
        name=DAILY_ANALYSIS_STEP,
        order=3,
        status=StepStatus.blocked,
        input_payload={
            "plan_version": PLAN_VERSION,
            "step": DAILY_ANALYSIS_STEP,
            "date": trade_date,
            "run_id": run_key,
            "followup_id": followup.get("followup_id"),
            "blocked_on": DETAIL_FETCH_STEP,
        },
        source_refs=initial_step.source_refs,
        input_refs=initial_step.input_refs,
        blocked_reason="waiting for detail page artifacts and report inputs",
    )

    if detail_step.status == StepStatus.pending:
        transition_task_run(db, run, TaskStatus.pending, source=TASK_TYPE, reason="detail_fetch_queued")
        run.current_stage = DETAIL_FETCH_STEP
        run.progress = 0.25
        run.error_summary = None
        run.ended_at = None
    else:
        transition_task_run(db, run, TaskStatus.blocked, source=TASK_TYPE, reason="detail_fetch_blocked")
        run.current_stage = DETAIL_FETCH_STEP
        run.progress = 0.25
        run.error_summary = "detail_fetch blocked: source_url is missing"

    db.commit()
    return run.status


def run_pending_daily_analysis_followup_tasks(
    db: Session,
    *,
    limit: int = 10,
    storage_root: Path = Path("./storage"),
) -> dict[str, Any]:
    runs = (
        db.query(TaskRun)
        .filter(
            TaskRun.task_type == TASK_TYPE,
            TaskRun.status == TaskStatus.pending,
            TaskRun.current_stage == INITIAL_STAGE,
        )
        .order_by(TaskRun.created_at.asc())
        .limit(max(limit, 0))
        .all()
    )
    results = [
        {
            "run_id": str(run.id),
            "status": run_daily_analysis_followup_task(db, run.id, storage_root=storage_root).value,
        }
        for run in runs
    ]
    return {
        "status": "success",
        "matched_count": len(runs),
        "processed_count": len(results),
        "results": results,
    }


def _run_detail_fetch_stage(
    db: Session,
    *,
    run: TaskRun,
    storage_root: Path,
    detail_fetcher: DetailFetcher | None,
) -> TaskStatus:
    detail_step = _find_step(run, DETAIL_FETCH_STEP)
    if detail_step is None:
        transition_task_run(db, run, TaskStatus.failed, source=TASK_TYPE, reason="detail_fetch_step_missing")
        run.error_summary = "detail_fetch step is missing"
        db.commit()
        return TaskStatus.failed
    if detail_step.status == StepStatus.success:
        return run.status
    if detail_step.status == StepStatus.blocked:
        transition_task_run(db, run, TaskStatus.blocked, source=TASK_TYPE, reason="detail_fetch_already_blocked")
        run.error_summary = detail_step.blocked_reason or "detail_fetch is blocked"
        db.commit()
        return TaskStatus.blocked

    input_payload = _parse_json(detail_step.input_json)
    if not isinstance(input_payload, dict):
        _fail_step(db, detail_step, "invalid_input_json", "detail_fetch input_json is not an object")
        transition_task_run(db, run, TaskStatus.failed, source=TASK_TYPE, reason="invalid_detail_fetch_input")
        run.error_summary = "invalid detail_fetch input_json"
        db.commit()
        return TaskStatus.failed

    source_url = str(input_payload.get("source_url") or "").strip()
    if not source_url:
        transition_task_step(
            db,
            detail_step,
            StepStatus.blocked,
            source=TASK_TYPE,
            reason="detail_fetch_source_url_missing",
            blocked_reason="detail_fetch source_url is missing",
            error_type="data_unavailable",
            retryable=False,
        )
        transition_task_run(db, run, TaskStatus.blocked, source=TASK_TYPE, reason="detail_fetch_source_url_missing")
        run.error_summary = "detail_fetch blocked: source_url is missing"
        db.commit()
        return TaskStatus.blocked

    transition_task_run(db, run, TaskStatus.running, source=TASK_TYPE, reason="detail_fetch_started")
    run.current_stage = DETAIL_FETCH_STEP
    transition_task_step(db, detail_step, StepStatus.running, source=TASK_TYPE, reason="detail_fetch_started")
    db.commit()

    fetcher = detail_fetcher or _default_detail_fetcher()
    retrieved_date = str(input_payload.get("date") or run.trade_date or _now().date().isoformat())
    result = fetcher(url=source_url, storage_root=storage_root, retrieved_date=retrieved_date)
    result_payload = _detail_result_payload(result)
    detail_step.output_json = _dump_json(_detail_output_payload(run=run, input_payload=input_payload, result=result_payload))
    detail_step.output_refs = _dump_json(_detail_artifact_refs(result_payload))
    detail_step.artifact_refs = detail_step.output_refs
    detail_step.source_refs = _dump_json(_merge_source_refs(detail_step.source_refs, _detail_source_ref(source_url, result_payload)))
    _register_step_artifacts(db, run=run, step=detail_step, storage_root=storage_root)
    detail_step.finished_at = _now()
    detail_step.retryable = False

    status = str(result_payload.get("status") or "")
    access_status = str(result_payload.get("access_status") or "")
    vip_step = _find_step(run, VIP_BROWSER_FALLBACK_STEP)
    analysis_step = _find_step(run, DAILY_ANALYSIS_STEP)

    if status != "fetched":
        transition_task_step(
            db,
            detail_step,
            StepStatus.failed,
            source=TASK_TYPE,
            reason="detail_fetch_failed",
        )
        detail_step.error = str(result_payload.get("error_reason") or "detail fetch failed")
        detail_step.error_type = "network_timeout" if access_status == "unavailable" else "data_unavailable"
        detail_step.retryable = True
        transition_task_run(db, run, TaskStatus.failed, source=TASK_TYPE, reason="detail_fetch_failed")
        run.error_summary = "detail_fetch failed"
        db.commit()
        return TaskStatus.failed

    transition_task_step(db, detail_step, StepStatus.success, source=TASK_TYPE, reason="detail_fetch_succeeded")
    detail_step.error = None
    detail_step.error_type = None

    if access_status == "readable":
        _mark_step_skipped(db, vip_step, reason="detail page is readable; browser fallback not required")
        _mark_step_pending(db, analysis_step)
        transition_task_run(db, run, TaskStatus.pending, source=TASK_TYPE, reason="route_to_daily_analysis")
        run.current_stage = DAILY_ANALYSIS_STEP
        run.progress = 0.6
        run.error_summary = None
        run.ended_at = None
    elif access_status in {"vip_locked", "javascript_required"}:
        _mark_step_pending(db, vip_step)
        if analysis_step is not None:
            transition_task_step(
                db,
                analysis_step,
                StepStatus.blocked,
                source=TASK_TYPE,
                reason="waiting_for_vip_browser_fallback",
                blocked_reason="waiting for VIP/browser fallback artifact",
                retryable=False,
            )
        transition_task_run(db, run, TaskStatus.pending, source=TASK_TYPE, reason="route_to_vip_browser_fallback")
        run.current_stage = VIP_BROWSER_FALLBACK_STEP
        run.progress = 0.5
        run.error_summary = None
        run.ended_at = None
    else:
        if analysis_step is not None:
            transition_task_step(
                db,
                analysis_step,
                StepStatus.blocked,
                source=TASK_TYPE,
                reason="detail_fetch_unusable_access_status",
                blocked_reason=f"detail page access_status={access_status or 'unknown'}",
                retryable=False,
            )
        transition_task_run(db, run, TaskStatus.blocked, source=TASK_TYPE, reason="detail_fetch_unusable_access_status")
        run.current_stage = DAILY_ANALYSIS_STEP
        run.progress = 0.5
        run.error_summary = f"detail_fetch produced unusable access_status={access_status or 'unknown'}"

    db.commit()
    return run.status


def _run_vip_browser_fallback_stage(
    db: Session,
    *,
    run: TaskRun,
    storage_root: Path,
    vip_browser_fetcher: VipBrowserFetcher | None,
) -> TaskStatus:
    fallback_step = _find_step(run, VIP_BROWSER_FALLBACK_STEP)
    if fallback_step is None:
        transition_task_run(db, run, TaskStatus.failed, source=TASK_TYPE, reason="vip_fallback_step_missing")
        run.error_summary = "vip_browser_fallback step is missing"
        db.commit()
        return TaskStatus.failed
    if fallback_step.status == StepStatus.success:
        return run.status
    if fallback_step.status in {StepStatus.blocked, StepStatus.failed} and _can_use_preview_after_vip_fallback(
        fallback_step
    ):
        _mark_step_pending(db, _find_step(run, DAILY_ANALYSIS_STEP))
        _route_to_partial_daily_analysis_after_vip_unavailable(db, run)
        db.commit()
        return TaskStatus.pending
    if fallback_step.status == StepStatus.blocked:
        transition_task_run(db, run, TaskStatus.blocked, source=TASK_TYPE, reason="vip_fallback_already_blocked")
        run.error_summary = fallback_step.blocked_reason or "vip_browser_fallback is blocked"
        db.commit()
        return TaskStatus.blocked

    input_payload = _parse_json(fallback_step.input_json)
    if not isinstance(input_payload, dict):
        _fail_step(db, fallback_step, "invalid_input_json", "vip_browser_fallback input_json is not an object")
        transition_task_run(db, run, TaskStatus.failed, source=TASK_TYPE, reason="invalid_vip_fallback_input")
        run.error_summary = "invalid vip_browser_fallback input_json"
        db.commit()
        return TaskStatus.failed

    source_url = str(input_payload.get("source_url") or "").strip()
    article_id = _extract_jin10_article_id(source_url)
    if not article_id:
        _block_vip_fallback(
            db,
            fallback_step,
            error_type="fetch_failed",
            message="vip_browser_fallback cannot determine Jin10 article_id from source_url",
        )
        transition_task_run(db, run, TaskStatus.blocked, source=TASK_TYPE, reason="vip_fallback_article_id_missing")
        run.current_stage = VIP_BROWSER_FALLBACK_STEP
        run.error_summary = "vip_browser_fallback blocked: article_id is missing"
        db.commit()
        return TaskStatus.blocked

    profile_dir = _jin10_browser_profile_path()
    if not profile_dir.exists():
        _block_vip_fallback(
            db,
            fallback_step,
            error_type="profile_missing",
            message=f"browser profile is missing: {profile_dir}",
        )
        _mark_step_pending(db, _find_step(run, DAILY_ANALYSIS_STEP))
        _route_to_partial_daily_analysis_after_vip_unavailable(db, run)
        db.commit()
        return TaskStatus.pending

    transition_task_run(db, run, TaskStatus.running, source=TASK_TYPE, reason="vip_fallback_started")
    run.current_stage = VIP_BROWSER_FALLBACK_STEP
    transition_task_step(db, fallback_step, StepStatus.running, source=TASK_TYPE, reason="vip_fallback_started")
    db.commit()

    retrieved_date = str(input_payload.get("date") or run.trade_date or _now().date().isoformat())
    fetcher = vip_browser_fetcher or _default_vip_browser_fetcher()
    try:
        raw_result = fetcher(
            article_id=article_id,
            source_url=source_url,
            storage_root=storage_root,
            retrieved_date=retrieved_date,
            user_data_dir=profile_dir,
        )
    except Exception as exc:
        error_type = _map_vip_fetch_error(exc)
        _fail_step(db, fallback_step, error_type, f"{type(exc).__name__}: {exc}")
        if _can_use_preview_after_vip_fallback(fallback_step):
            _mark_step_pending(db, _find_step(run, DAILY_ANALYSIS_STEP))
            _route_to_partial_daily_analysis_after_vip_unavailable(db, run)
            db.commit()
            return TaskStatus.pending
        transition_task_run(db, run, TaskStatus.failed, source=TASK_TYPE, reason="vip_fallback_failed")
        run.current_stage = VIP_BROWSER_FALLBACK_STEP
        run.error_summary = f"vip_browser_fallback failed: {_error_summary_label(error_type)}"
        db.commit()
        return TaskStatus.failed

    result_payload = _vip_browser_result_payload(
        raw_result,
        storage_root=storage_root,
        retrieved_date=retrieved_date,
        article_id=article_id,
        source_url=source_url,
    )
    fallback_step.output_json = _dump_json(
        _vip_browser_output_payload(run=run, input_payload=input_payload, result=result_payload)
    )
    fallback_step.output_refs = _dump_json(_vip_browser_artifact_refs(result_payload))
    fallback_step.artifact_refs = fallback_step.output_refs
    fallback_step.source_refs = _dump_json(
        _merge_source_refs(fallback_step.source_refs, _vip_browser_source_ref(source_url, result_payload))
    )
    _register_step_artifacts(db, run=run, step=fallback_step, storage_root=storage_root)
    fallback_step.finished_at = _now()
    fallback_step.retryable = False

    usable, error_type, blocked_reason = _vip_browser_usability(result_payload)
    analysis_step = _find_step(run, DAILY_ANALYSIS_STEP)
    if usable:
        transition_task_step(db, fallback_step, StepStatus.success, source=TASK_TYPE, reason="vip_fallback_succeeded")
        fallback_step.error = None
        fallback_step.error_type = None
        fallback_step.blocked_reason = None
        _mark_step_pending(db, analysis_step)
        transition_task_run(db, run, TaskStatus.pending, source=TASK_TYPE, reason="vip_fallback_route_to_analysis")
        run.current_stage = DAILY_ANALYSIS_STEP
        run.progress = 0.7
        run.error_summary = None
        run.ended_at = None
    else:
        _block_vip_fallback(db, fallback_step, error_type=error_type, message=blocked_reason)
        if _can_use_preview_after_vip_fallback(fallback_step):
            _mark_step_pending(db, analysis_step)
            _route_to_partial_daily_analysis_after_vip_unavailable(db, run)
        else:
            if analysis_step is not None:
                transition_task_step(
                    db,
                    analysis_step,
                    StepStatus.blocked,
                    source=TASK_TYPE,
                    reason="waiting_for_usable_vip_fallback_artifact",
                    blocked_reason="waiting for usable VIP/browser fallback artifact",
                    retryable=False,
                )
            transition_task_run(
                db,
                run,
                TaskStatus.blocked if error_type in {"login_required", "profile_missing"} else TaskStatus.failed,
                source=TASK_TYPE,
                reason="vip_fallback_unusable_artifact",
            )
            run.current_stage = VIP_BROWSER_FALLBACK_STEP
            run.error_summary = f"vip_browser_fallback blocked: {blocked_reason}"

    db.commit()
    return run.status


def _can_use_preview_after_vip_fallback(fallback_step: TaskStep) -> bool:
    return str(fallback_step.error_type or "") in VIP_FALLBACK_PARTIAL_SNAPSHOT_ERRORS


def _route_to_partial_daily_analysis_after_vip_unavailable(db: Session, run: TaskRun) -> None:
    transition_task_run(db, run, TaskStatus.pending, source=TASK_TYPE, reason="vip_fallback_partial_snapshot")
    run.current_stage = DAILY_ANALYSIS_STEP
    run.progress = max(float(run.progress or 0.0), 0.7)
    run.error_summary = "vip_browser_fallback unavailable; will generate partial snapshot from preview"
    run.ended_at = None


def _run_daily_analysis_stage(
    db: Session,
    *,
    run: TaskRun,
    storage_root: Path,
) -> TaskStatus:
    analysis_step = _find_step(run, DAILY_ANALYSIS_STEP)
    if analysis_step is None:
        transition_task_run(db, run, TaskStatus.failed, source=TASK_TYPE, reason="daily_analysis_step_missing")
        run.error_summary = "daily_analysis step is missing"
        db.commit()
        return TaskStatus.failed
    if analysis_step.status == StepStatus.success:
        transition_task_run(db, run, TaskStatus.success, source=TASK_TYPE, reason="daily_analysis_already_success")
        run.current_stage = DAILY_ANALYSIS_STEP
        run.progress = 1.0
        db.commit()
        return TaskStatus.success
    if analysis_step.status not in {StepStatus.pending, StepStatus.running}:
        transition_task_run(db, run, TaskStatus.blocked, source=TASK_TYPE, reason="daily_analysis_not_runnable")
        run.error_summary = analysis_step.blocked_reason or "daily_analysis is not pending"
        db.commit()
        return TaskStatus.blocked

    initial_step = _find_initial_step(run)
    initial_payload = _parse_json(initial_step.input_json if initial_step is not None else None)
    if not isinstance(initial_payload, dict):
        _fail_step(db, analysis_step, "invalid_input_json", "initial follow-up input_json is not an object")
        transition_task_run(db, run, TaskStatus.failed, source=TASK_TYPE, reason="invalid_daily_analysis_input")
        run.error_summary = "invalid follow-up input_json"
        db.commit()
        return TaskStatus.failed

    transition_task_run(db, run, TaskStatus.running, source=TASK_TYPE, reason="daily_analysis_started")
    run.current_stage = DAILY_ANALYSIS_STEP
    transition_task_step(db, analysis_step, StepStatus.running, source=TASK_TYPE, reason="daily_analysis_started")
    db.commit()

    detail_step = _find_step(run, DETAIL_FETCH_STEP)
    fallback_step = _find_step(run, VIP_BROWSER_FALLBACK_STEP)
    snapshot = _build_daily_brief_input_snapshot(
        run=run,
        initial_payload=initial_payload,
        initial_step=initial_step,
        detail_step=detail_step,
        fallback_step=fallback_step,
    )
    snapshot_path = _archive_daily_brief_input_snapshot(
        storage_root=storage_root,
        date=str(snapshot["date"]),
        run_id=str(snapshot["run_id"]),
        snapshot=snapshot,
    )
    artifact_refs = [_artifact_ref("daily_brief_input_snapshot", "feature_json", snapshot_path)]

    transition_task_step(db, analysis_step, StepStatus.success, source=TASK_TYPE, reason="daily_analysis_succeeded")
    analysis_step.output_json = _dump_json(
        {
            "status": "success",
            "date": snapshot["date"],
            "run_id": snapshot["run_id"],
            "followup_id": snapshot.get("followup_id"),
            "daily_analysis": {
                "status": "input_snapshot_ready",
                "snapshot_path": snapshot_path,
                "report_mode": snapshot["report_mode"],
            },
            "snapshot_summary": {
                "status": snapshot["status"],
                "core_event_count": len(snapshot["core_events"]),
                "key_article_count": len(snapshot["key_articles"]),
                "source_ref_count": len(snapshot["source_refs"]),
                "quality_flags": snapshot["quality_flags"],
                "risk_flags": snapshot["risk_flags"],
            },
            "data_quality": snapshot["data_quality"],
        }
    )
    analysis_step.output_refs = _dump_json(artifact_refs)
    analysis_step.artifact_refs = analysis_step.output_refs
    analysis_step.source_refs = _dump_json(snapshot["source_refs"])
    analysis_step.input_refs = _dump_json(snapshot["input_refs"])
    _register_step_artifacts(db, run=run, step=analysis_step, storage_root=storage_root)
    analysis_step.finished_at = _now()
    analysis_step.retryable = False
    analysis_step.error = None
    analysis_step.error_type = None
    analysis_step.blocked_reason = None

    transition_task_run(db, run, TaskStatus.success, source=TASK_TYPE, reason="daily_analysis_completed")
    run.current_stage = DAILY_ANALYSIS_STEP
    run.progress = 1.0
    run.error_summary = None
    db.commit()
    return TaskStatus.success


def _build_daily_brief_input_snapshot(
    *,
    run: TaskRun,
    initial_payload: dict[str, Any],
    initial_step: TaskStep | None,
    detail_step: TaskStep | None,
    fallback_step: TaskStep | None,
) -> dict[str, Any]:
    followup = initial_payload.get("followup") if isinstance(initial_payload.get("followup"), dict) else {}
    followup = followup if isinstance(followup, dict) else {}
    date = str(initial_payload.get("date") or run.trade_date or _now().date().isoformat())
    run_id = str(initial_payload.get("run_id") or run.id)
    followup_id = followup.get("followup_id")
    source_url = str(followup.get("source_url") or "")
    article = _select_snapshot_article(followup=followup, detail_step=detail_step, fallback_step=fallback_step)
    partial = article["text_source"] == "preview"
    quality_flags = ["single_source", "supplemental_source"]
    risk_flags = ["single_source_not_confirmed", "supplemental_source"]
    if partial:
        quality_flags.append("vip_preview_only")
        risk_flags.append("vip_preview_only")

    source_refs = _snapshot_source_refs(
        initial_step=initial_step,
        detail_step=detail_step,
        fallback_step=fallback_step,
        article=article,
        source_url=source_url,
    )
    input_refs = _snapshot_input_refs(
        initial_step=initial_step,
        detail_step=detail_step,
        fallback_step=fallback_step,
    )
    artifact_refs = _snapshot_artifact_refs(detail_step=detail_step, fallback_step=fallback_step)
    created_at = _now().isoformat()

    return {
        "report_mode": "jin10_daily_brief",
        "snapshot_kind": "daily_brief_input_snapshot",
        "status": "partial" if partial else "complete",
        "created_at": created_at,
        "as_of": str(initial_payload.get("as_of") or created_at),
        "date": date,
        "run_id": run_id,
        "followup_id": followup_id,
        "core_events": [
            {
                "event_id": followup.get("source_event_id"),
                "event_type": followup.get("event_type"),
                "title": followup.get("source_title") or followup.get("title") or article["title"],
                "evidence_text": followup.get("evidence_text") or article["preview_text"],
                "impact_path": followup.get("impact_path"),
                "gold_impact": followup.get("gold_impact"),
                "asset_tags": _string_list(followup.get("asset_tags")),
                "topic_tags": _string_list(followup.get("topic_tags")),
                "verification_status": "single_source_supplemental",
                "source_status": "single_source",
            }
        ],
        "key_articles": [
            {
                "followup_id": followup_id,
                "title": article["title"],
                "source_url": article["source_url"] or source_url,
                "body_text": article["body_text"],
                "preview_text": article["preview_text"],
                "text_source": article["text_source"],
                "access_status": article["access_status"],
                "source_key": followup.get("source_key") or "jin10_feishu",
                "raw_text_chars": len(article["body_text"]),
            }
        ],
        "market_reactions": _list_of_dicts(followup.get("market_reactions")),
        "risk_flags": risk_flags,
        "source_refs": source_refs,
        "quality_flags": quality_flags,
        "input_refs": input_refs,
        "artifact_refs": artifact_refs,
        "lineage": {
            "task_run_id": str(run.id),
            "initial_step_id": str(initial_step.id) if initial_step is not None else None,
            "detail_step_id": str(detail_step.id) if detail_step is not None else None,
            "vip_browser_fallback_step_id": str(fallback_step.id) if fallback_step is not None else None,
        },
        "data_quality": {
            "partial": partial,
            "text_source": article["text_source"],
            "raw_text_chars": len(article["body_text"]),
            "source_ref_count": len(source_refs),
            "input_ref_count": len(input_refs),
            "artifact_ref_count": len(artifact_refs),
            "llm_invoked": False,
            "verification_status": "single_source_supplemental",
        },
    }


def _select_snapshot_article(
    *,
    followup: dict[str, Any],
    detail_step: TaskStep | None,
    fallback_step: TaskStep | None,
) -> dict[str, str]:
    fallback_payload = _parse_json(fallback_step.output_json if fallback_step is not None else None)
    fallback = fallback_payload.get(VIP_BROWSER_FALLBACK_STEP) if isinstance(fallback_payload, dict) else None
    if isinstance(fallback, dict) and str(fallback.get("access_status") or "") == "readable":
        raw_text = str(fallback.get("raw_text") or "").strip()
        if raw_text:
            return {
                "title": str(fallback.get("title") or followup.get("source_title") or followup.get("title") or ""),
                "source_url": str(fallback.get("source_url") or followup.get("source_url") or ""),
                "body_text": raw_text,
                "preview_text": _followup_preview_text(followup),
                "text_source": VIP_BROWSER_FALLBACK_STEP,
                "access_status": "readable",
            }

    detail_payload = _parse_json(detail_step.output_json if detail_step is not None else None)
    detail = detail_payload.get(DETAIL_FETCH_STEP) if isinstance(detail_payload, dict) else None
    if isinstance(detail, dict) and str(detail.get("access_status") or "") == "readable":
        raw_text = str(detail.get("raw_text") or "").strip()
        if raw_text:
            return {
                "title": str(detail.get("title") or followup.get("source_title") or followup.get("title") or ""),
                "source_url": str(detail.get("final_url") or detail.get("detail_url") or followup.get("source_url") or ""),
                "body_text": raw_text,
                "preview_text": _followup_preview_text(followup),
                "text_source": DETAIL_FETCH_STEP,
                "access_status": "readable",
            }

    preview = _followup_preview_text(followup)
    return {
        "title": str(followup.get("source_title") or followup.get("title") or ""),
        "source_url": str(followup.get("source_url") or ""),
        "body_text": preview,
        "preview_text": preview,
        "text_source": "preview",
        "access_status": "preview_only",
    }


def _followup_preview_text(followup: dict[str, Any]) -> str:
    parts = [
        str(followup.get("source_title") or "").strip(),
        str(followup.get("title") or "").strip(),
        str(followup.get("evidence_text") or "").strip(),
        str(followup.get("summary") or "").strip(),
    ]
    return "\n".join(part for part in parts if part) or "preview unavailable"


def _archive_daily_brief_input_snapshot(
    *,
    storage_root: Path,
    date: str,
    run_id: str,
    snapshot: dict[str, Any],
) -> str:
    target = (
        storage_root
        / "features"
        / "news"
        / _safe_path_token(date)
        / _safe_path_token(run_id)
        / "daily_brief_input_snapshot.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target.relative_to(storage_root).as_posix()


def _snapshot_source_refs(
    *,
    initial_step: TaskStep | None,
    detail_step: TaskStep | None,
    fallback_step: TaskStep | None,
    article: dict[str, str],
    source_url: str,
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for step in (initial_step, detail_step, fallback_step):
        parsed = _parse_json(step.source_refs if step is not None else None)
        if isinstance(parsed, list):
            refs.extend(dict(item) for item in parsed if isinstance(item, dict))
    source_name = {
        VIP_BROWSER_FALLBACK_STEP: VIP_BROWSER_FALLBACK_SOURCE_KEY,
        DETAIL_FETCH_STEP: "jin10_detail_pages",
        "preview": "jin10_feishu",
    }.get(article["text_source"], "jin10_feishu")
    refs.append(
        {
            "source_id": f"{source_name}:{_sha256(article['source_url'] or source_url or article['body_text'])[:16]}",
            "source_name": source_name,
            "source_type": "news_detail" if article["text_source"] != "preview" else "news_preview",
            "url": article["source_url"] or source_url or None,
            "access_status": article["access_status"],
        }
    )
    return _dedupe_dicts(refs)


def _snapshot_input_refs(
    *,
    initial_step: TaskStep | None,
    detail_step: TaskStep | None,
    fallback_step: TaskStep | None,
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for step in (initial_step, detail_step, fallback_step):
        parsed = _parse_json(step.input_refs if step is not None else None)
        if isinstance(parsed, list):
            refs.extend(dict(item) for item in parsed if isinstance(item, dict))
    return _dedupe_dicts(refs)


def _snapshot_artifact_refs(
    *,
    detail_step: TaskStep | None,
    fallback_step: TaskStep | None,
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for step in (detail_step, fallback_step):
        parsed = _parse_json(step.output_refs if step is not None else None)
        if isinstance(parsed, list):
            refs.extend(dict(item) for item in parsed if isinstance(item, dict))
    return _dedupe_dicts(refs)


def _dedupe_dicts(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for value in values:
        key = _dump_json(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item or "").strip()]


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _load_run(db: Session, task_id: uuid.UUID | str) -> TaskRun | None:
    try:
        run_uuid = task_id if isinstance(task_id, uuid.UUID) else uuid.UUID(str(task_id))
    except ValueError:
        return None
    return (
        db.query(TaskRun)
        .options(selectinload(TaskRun.steps))
        .filter(TaskRun.id == run_uuid)
        .first()
    )


def _find_initial_step(run: TaskRun) -> TaskStep | None:
    candidates = [
        step
        for step in run.steps
        if step.stage == INITIAL_STAGE and step.input_json and step.name not in {
            DETAIL_FETCH_STEP,
            VIP_BROWSER_FALLBACK_STEP,
            DAILY_ANALYSIS_STEP,
        }
    ]
    return sorted(candidates, key=lambda step: step.step_order or 0)[0] if candidates else None


def _find_step(run: TaskRun, name: str) -> TaskStep | None:
    return next((step for step in run.steps if step.name == name), None)


def _complete_initial_step(db: Session, step: TaskStep, *, plan: dict[str, Any]) -> None:
    transition_task_step(db, step, StepStatus.success, source=TASK_TYPE, reason="initial_step_completed")
    step.output_json = _dump_json(plan)
    step.finished_at = step.finished_at or _now()
    step.retryable = False
    step.error = None
    step.error_type = None


def _ensure_step(
    db: Session,
    *,
    run: TaskRun,
    name: str,
    order: int,
    status: StepStatus,
    input_payload: dict[str, Any],
    source_refs: str | None,
    input_refs: str | None,
    blocked_reason: str | None = None,
    error_type: str | None = None,
) -> TaskStep:
    existing = next((step for step in run.steps if step.name == name), None)
    input_json = _dump_json(input_payload)
    if existing is not None:
        existing.step_order = order
        existing.input_json = existing.input_json or input_json
        existing.input_hash = existing.input_hash or _sha256(existing.input_json)
        existing.source_refs = existing.source_refs or source_refs
        existing.input_refs = existing.input_refs or input_refs
        existing.blocked_reason = existing.blocked_reason or blocked_reason
        existing.error_type = existing.error_type or error_type
        return existing

    step = TaskStep(
        task_run_id=run.id,
        name=name,
        stage=INITIAL_STAGE,
        task_kind=name,
        status=status,
        step_order=order,
        input_json=input_json,
        input_hash=_sha256(input_json),
        input_refs=input_refs,
        output_refs=_dump_json([]),
        source_refs=source_refs,
        retry_count=0,
        retryable=status == StepStatus.pending,
        blocked_reason=blocked_reason,
        error_type=error_type,
    )
    if status == StepStatus.blocked:
        step.finished_at = _now()
    db.add(step)
    db.flush()
    run.steps.append(step)
    return step


def _register_step_artifacts(db: Session, *, run: TaskRun, step: TaskStep, storage_root: Path) -> None:
    output_refs = _parse_json(step.output_refs)
    artifact_refs = _parse_json(step.artifact_refs)
    enriched_output_refs = _enrich_artifact_refs_for_registry(storage_root=storage_root, refs=output_refs)
    enriched_artifact_refs = _enrich_artifact_refs_for_registry(storage_root=storage_root, refs=artifact_refs)
    register_step_artifacts(
        db,
        run_id=str(run.id),
        step=step,
        output_refs=enriched_output_refs,
        artifact_refs=enriched_artifact_refs,
        output_ref=step.output_ref,
        source_refs=_parse_json(step.source_refs) if isinstance(_parse_json(step.source_refs), list) else None,
    )


def _build_execution_plan(*, payload: dict[str, Any], source_url: str, storage_root: Path) -> dict[str, Any]:
    followup = payload.get("followup") if isinstance(payload.get("followup"), dict) else {}
    return {
        "plan_version": PLAN_VERSION,
        "status": "planned",
        "storage_root": str(storage_root),
        "date": payload.get("date"),
        "run_id": payload.get("run_id"),
        "followup_id": followup.get("followup_id"),
        "action": followup.get("action"),
        "queue_type": followup.get("queue_type"),
        "source_url": source_url or None,
        "steps": [
            {"name": DETAIL_FETCH_STEP, "status": "pending" if source_url else "blocked"},
            {"name": VIP_BROWSER_FALLBACK_STEP, "status": "blocked"},
            {"name": DAILY_ANALYSIS_STEP, "status": "blocked"},
        ],
        "execution_policy": {
            "network_calls": "deferred",
            "browser_login": "deferred",
            "llm_analysis": "deferred",
        },
    }


def _default_detail_fetcher() -> DetailFetcher:
    from apps.collectors.news.jin10_detail_fetcher import fetch_jin10_detail_page

    return fetch_jin10_detail_page


def _default_vip_browser_fetcher() -> VipBrowserFetcher:
    from apps.collectors.jin10.fetcher import fetch_svip_report_via_browser_profile

    def fetcher(**kwargs: Any) -> Any:
        return fetch_svip_report_via_browser_profile(
            article_id=str(kwargs["article_id"]),
            user_data_dir=kwargs["user_data_dir"],
        )

    return fetcher


def _detail_result_payload(result: Any) -> dict[str, Any]:
    if hasattr(result, "to_dict"):
        payload = result.to_dict()
    elif isinstance(result, dict):
        payload = dict(result)
    else:
        payload = {
            "status": "error",
            "access_status": "unknown",
            "error_reason": f"unsupported detail fetch result: {type(result).__name__}",
        }
    return payload if isinstance(payload, dict) else {}


def _detail_output_payload(*, run: TaskRun, input_payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "success" if result.get("status") == "fetched" else "failed",
        "date": input_payload.get("date") or run.trade_date,
        "run_id": input_payload.get("run_id") or str(run.id),
        "followup_id": input_payload.get("followup_id"),
        "source_url": input_payload.get("source_url"),
        "detail_fetch": {
            "status": result.get("status"),
            "access_status": result.get("access_status"),
            "detail_url": result.get("detail_url"),
            "final_url": result.get("final_url"),
            "title": result.get("title"),
            "raw_text": result.get("raw_text"),
            "raw_html_path": result.get("raw_html_path"),
            "parsed_path": result.get("parsed_path"),
            "image_asset_count": len(result.get("image_assets") or []),
            "vlm_insight_count": len(result.get("image_insights") or []),
            "error_reason": result.get("error_reason"),
        },
        "data_quality": {
            "verification_status": "single_source",
            "used_detail_text": bool(result.get("raw_text")),
            "raw_text_chars": len(str(result.get("raw_text") or "")),
            "fallback_required": result.get("access_status") in {"vip_locked", "javascript_required"},
        },
    }


def _detail_artifact_refs(result: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    raw_html_path = result.get("raw_html_path")
    parsed_path = result.get("parsed_path")
    if raw_html_path:
        refs.append(_artifact_ref("jin10_detail_raw_html", "raw_file", str(raw_html_path)))
    if parsed_path:
        refs.append(_artifact_ref("jin10_detail_parsed", "parsed_file", str(parsed_path)))
    for index, asset in enumerate(result.get("image_assets") or []):
        if not isinstance(asset, dict) or not asset.get("path"):
            continue
        refs.append(_artifact_ref(f"jin10_detail_image:{index}", "chart_snapshot", str(asset["path"])))
    return refs


def _artifact_ref(artifact_id: str, artifact_type: str, file_path: str) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "file_path": file_path,
    }


def _detail_source_ref(source_url: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": f"jin10_detail_pages:{_sha256(source_url)[:16]}",
        "source_name": "jin10_detail_pages",
        "source_type": "news_detail",
        "url": source_url,
        "status": result.get("status"),
        "access_status": result.get("access_status"),
        "file_path": result.get("parsed_path"),
    }


def _vip_browser_result_payload(
    result: Any,
    *,
    storage_root: Path,
    retrieved_date: str,
    article_id: str,
    source_url: str,
) -> dict[str, Any]:
    if isinstance(result, dict):
        payload = dict(result)
    else:
        payload = {
            "article_id": getattr(result, "article_id", article_id),
            "date": getattr(result, "date", retrieved_date),
            "title": getattr(result, "title", ""),
            "category": getattr(result, "category", ""),
            "report_type": getattr(result, "report_type", ""),
            "source_url": getattr(result, "source_url", source_url),
            "raw_text": getattr(result, "report_markdown", ""),
            "raw_html": getattr(result, "raw_html", ""),
            "image_urls": list(getattr(result, "image_urls", []) or []),
            "fetched_at": getattr(result, "fetched_at", ""),
        }

    payload.setdefault("status", "fetched")
    payload["article_id"] = str(payload.get("article_id") or article_id)
    payload["source_url"] = str(payload.get("source_url") or source_url)
    payload["title"] = str(payload.get("title") or "")
    payload["raw_text"] = str(payload.get("raw_text") or payload.get("report_markdown") or "")
    payload["raw_html"] = str(payload.get("raw_html") or "")
    payload["image_assets"] = _normalize_vip_image_assets(payload)
    payload["access_status"] = str(
        payload.get("access_status")
        or _classify_vip_browser_access(raw_text=payload["raw_text"], raw_html=payload["raw_html"])
    )
    payload["raw_text_chars"] = len(payload["raw_text"])

    raw_html_path, parsed_path = _write_vip_browser_artifacts(
        storage_root=storage_root,
        retrieved_date=retrieved_date,
        article_id=payload["article_id"],
        payload=payload,
    )
    payload["raw_html_path"] = payload.get("raw_html_path") or raw_html_path
    payload["parsed_path"] = payload.get("parsed_path") or parsed_path
    return payload


def _normalize_vip_image_assets(payload: dict[str, Any]) -> list[dict[str, Any]]:
    existing = payload.get("image_assets")
    if isinstance(existing, list):
        return [dict(item) for item in existing if isinstance(item, dict)]
    assets: list[dict[str, Any]] = []
    for index, url in enumerate(payload.get("image_urls") or [], start=1):
        if url:
            assets.append({"seq": index, "url": str(url)})
    return assets


def _write_vip_browser_artifacts(
    *,
    storage_root: Path,
    retrieved_date: str,
    article_id: str,
    payload: dict[str, Any],
) -> tuple[str | None, str]:
    safe_article_id = _safe_path_token(article_id)
    raw_html_path: str | None = str(payload.get("raw_html_path") or "") or None
    if payload.get("raw_html") and raw_html_path is None:
        raw_dir = storage_root / "raw" / "news" / VIP_BROWSER_FALLBACK_SOURCE_KEY / retrieved_date
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_target = raw_dir / f"{safe_article_id}.html"
        raw_target.write_text(str(payload["raw_html"]), encoding="utf-8", errors="ignore")
        raw_html_path = raw_target.relative_to(storage_root).as_posix()

    parsed_dir = storage_root / "parsed" / "news" / VIP_BROWSER_FALLBACK_SOURCE_KEY / retrieved_date
    parsed_dir.mkdir(parents=True, exist_ok=True)
    parsed_target = parsed_dir / f"{safe_article_id}.json"
    parsed_payload = {
        key: value
        for key, value in payload.items()
        if key not in {"raw_html"}
    }
    parsed_payload["raw_html_path"] = raw_html_path
    parsed_target.write_text(json.dumps(parsed_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return raw_html_path, parsed_target.relative_to(storage_root).as_posix()


def _vip_browser_output_payload(*, run: TaskRun, input_payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "success" if result.get("access_status") == "readable" else "blocked",
        "date": input_payload.get("date") or run.trade_date,
        "run_id": input_payload.get("run_id") or str(run.id),
        "source_url": input_payload.get("source_url"),
        "vip_browser_fallback": {
            "status": result.get("status"),
            "access_status": result.get("access_status"),
            "article_id": result.get("article_id"),
            "title": result.get("title"),
            "source_url": result.get("source_url"),
            "raw_text": result.get("raw_text"),
            "raw_text_chars": result.get("raw_text_chars"),
            "raw_html_path": result.get("raw_html_path"),
            "parsed_path": result.get("parsed_path"),
            "image_assets": result.get("image_assets") or [],
            "image_asset_count": len(result.get("image_assets") or []),
            "fetched_at": result.get("fetched_at"),
        },
        "data_quality": {
            "verification_status": "single_source",
            "used_vip_browser_text": bool(result.get("raw_text")),
            "raw_text_chars": result.get("raw_text_chars") or 0,
        },
    }


def _vip_browser_artifact_refs(result: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    raw_html_path = result.get("raw_html_path")
    parsed_path = result.get("parsed_path")
    if raw_html_path:
        refs.append(_artifact_ref("jin10_vip_browser_raw_html", "raw_file", str(raw_html_path)))
    if parsed_path:
        refs.append(_artifact_ref("jin10_vip_browser_parsed", "parsed_file", str(parsed_path)))
    for index, asset in enumerate(result.get("image_assets") or []):
        if not isinstance(asset, dict):
            continue
        file_path = asset.get("path") or asset.get("url")
        if file_path:
            refs.append(_artifact_ref(f"jin10_vip_browser_image:{index}", "chart_snapshot", str(file_path)))
    return refs


def _vip_browser_source_ref(source_url: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": f"jin10_vip_browser_fallback:{result.get('article_id') or _sha256(source_url)[:16]}",
        "source_name": VIP_BROWSER_FALLBACK_SOURCE_KEY,
        "source_type": "news_detail",
        "url": source_url,
        "article_id": result.get("article_id"),
        "status": result.get("status"),
        "access_status": result.get("access_status"),
        "file_path": result.get("parsed_path"),
    }


def _vip_browser_usability(result: dict[str, Any]) -> tuple[bool, str, str]:
    status = str(result.get("status") or "")
    access_status = str(result.get("access_status") or "")
    raw_text = str(result.get("raw_text") or "")
    if status not in {"fetched", "success", "ok"}:
        return False, "fetch_failed", str(result.get("error_reason") or "VIP browser fetch failed")
    if access_status in {"vip_locked", "login_required"}:
        return False, "login_required", "VIP browser profile is not logged in or only returned locked content"
    if access_status == "browser_unavailable":
        return False, "browser_unavailable", "VIP browser runtime is unavailable"
    if access_status != "readable":
        return False, "fetch_failed", f"VIP browser fetch produced unusable access_status={access_status or 'unknown'}"
    if not raw_text.strip():
        return False, "fetch_failed", "VIP browser fetch returned empty raw_text"
    return True, "", ""


def _classify_vip_browser_access(*, raw_text: str, raw_html: str) -> str:
    text = f"{raw_text}\n{raw_html}".strip()
    if not text:
        return "empty"
    login_required_markers = (
        "付费内容",
        "开通VIP阅读全文",
        "登录查看全文",
        "解锁文章",
        "登录后查看",
        "证据不足：仅抓取到详情页 HTML",
    )
    if any(marker in text for marker in login_required_markers):
        return "login_required"
    return "readable"


def _extract_jin10_article_id(source_url: str) -> str | None:
    match = re.search(r"/(?:details|news)/(\d+)(?:\D|$)", source_url)
    return match.group(1) if match else None


def _jin10_browser_profile_path() -> Path:
    raw_path = os.getenv("JIN10_BROWSER_PROFILE") or str(DEFAULT_JIN10_BROWSER_PROFILE or "")
    if not raw_path:
        return Path("__missing_jin10_browser_profile__")
    return Path(raw_path).expanduser()


def _map_vip_fetch_error(exc: Exception) -> str:
    message = f"{type(exc).__name__}: {exc}".lower()
    if "profile" in message and ("not found" in message or "missing" in message):
        return "profile_missing"
    if any(marker in message for marker in ("playwright", "chromium", "browser", "executable")):
        return "browser_unavailable"
    if any(marker in message for marker in ("login", "auth", "vip", "permission")):
        return "login_required"
    return "fetch_failed"


def _error_summary_label(error_type: str) -> str:
    return {
        "profile_missing": "browser profile is missing",
        "browser_unavailable": "browser unavailable",
        "login_required": "login required",
        "fetch_failed": "fetch failed",
    }.get(error_type, error_type)


def _safe_path_token(raw: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._") or "unknown"


def _merge_source_refs(raw_refs: str | None, extra_ref: dict[str, Any]) -> list[dict[str, Any]]:
    refs = _parse_json(raw_refs)
    normalized = [dict(item) for item in refs if isinstance(item, dict)] if isinstance(refs, list) else []
    key = (extra_ref.get("source_id"), extra_ref.get("url"))
    if not any((item.get("source_id"), item.get("url")) == key for item in normalized):
        normalized.append({key: value for key, value in extra_ref.items() if value is not None})
    return normalized


def _mark_step_pending(db: Session, step: TaskStep | None) -> None:
    if step is None:
        return
    transition_task_step(db, step, StepStatus.pending, source=TASK_TYPE, reason="step_requeued", retryable=True)
    step.blocked_reason = None
    step.error = None
    step.error_type = None
    step.retryable = True
    step.finished_at = None


def _mark_step_skipped(db: Session, step: TaskStep | None, *, reason: str) -> None:
    if step is None:
        return
    transition_task_step(db, step, StepStatus.skipped, source=TASK_TYPE, reason="step_skipped")
    step.output_json = _dump_json({"status": "skipped", "reason": reason})
    step.blocked_reason = None
    step.error = None
    step.error_type = None
    step.retryable = False


def _fail_step(db: Session, step: TaskStep, error_type: str, message: str) -> None:
    transition_task_step(db, step, StepStatus.failed, source=TASK_TYPE, reason="step_failed")
    step.error_type = error_type
    step.error = message
    step.error_json = _dump_json({"error_type": error_type, "message": message})
    step.retryable = False


def _block_vip_fallback(db: Session, step: TaskStep, *, error_type: str, message: str) -> None:
    transition_task_step(
        db,
        step,
        StepStatus.blocked,
        source=TASK_TYPE,
        reason="vip_fallback_blocked",
        blocked_reason=message,
        error_type=error_type,
        retryable=False,
    )
    step.error_type = error_type
    step.error = message
    step.error_json = _dump_json({"error_type": error_type, "message": message})
    step.blocked_reason = message


def _parse_json(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _dump_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)


def _enrich_artifact_refs_for_registry(*, storage_root: Path, refs: Any) -> list[dict[str, Any]] | None:
    if not isinstance(refs, list):
        return None

    enriched: list[dict[str, Any]] = []
    for item in refs:
        if not isinstance(item, dict):
            continue
        enriched_item = deepcopy(item)
        file_path = str(enriched_item.get("file_path") or "").strip()
        if file_path:
            file = _resolve_artifact_file(storage_root=storage_root, file_path=file_path)
            if file.is_file():
                enriched_item.setdefault("content_type", _guess_content_type(file))
                enriched_item.setdefault("byte_size", file.stat().st_size)
        enriched.append(enriched_item)
    return enriched


def _resolve_artifact_file(*, storage_root: Path, file_path: str) -> Path:
    path = Path(file_path)
    if path.is_absolute():
        return path
    return storage_root / path


def _guess_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "application/json"
    if suffix == ".html":
        return "text/html"
    if suffix == ".md":
        return "text/markdown"
    if suffix == ".png":
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    return "application/octet-stream"


def _sha256(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)
