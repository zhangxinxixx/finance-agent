"""Worker pipeline runner。

Phase 2: CME steps (cme_download, cme_parse, cme_ingest, option_wall) are
executed via the CME pipeline.

Phase 3: Macro steps (macro_collect, macro_feature, report_render) are
executed via the macro pipeline — producing real snapshot JSON + Markdown.

Other premarket steps remain as stubs (marked success without real logic)
until their pipelines are built.
"""

from __future__ import annotations

import hashlib
import json
import logging
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session as DBSession

from apps.analysis.snapshots.builder import build_analysis_snapshot, write_analysis_snapshot
from apps.output.artifacts import artifact_run_dir
from apps.premarket import (
    evaluate_premarket_step_readiness,
    get_premarket_step_contract,
    sort_premarket_steps,
)
from apps.runtime.artifact_storage import get_artifact_storage
from apps.runtime.execution_event_bridge import emit_task_event
from apps.runtime.artifact_registry import register_step_artifacts
from apps.runtime.state_machine import derive_task_run_status, transition_task_run, transition_task_step
from database.models.task import StepStatus, TaskRun, TaskStatus

# ── C4 agent pipeline imports (deterministic, no LLM / network / file reads) ──
from apps.analysis.agents.macro_liquidity import analyze_macro_liquidity
from apps.analysis.agents.cme_options import analyze_cme_options
from apps.analysis.agents.risk import analyze_risk
from apps.analysis.agents.technical import analyze_technical
from apps.analysis.agents.positioning import analyze_positioning
from apps.analysis.agents.news import analyze_news
from apps.analysis.agents.market_odds import analyze_market_odds
from apps.analysis.strategy.card import build_strategy_card
from apps.output.final_report import write_final_report, write_strategy_card
from apps.renderer.markdown.final_report import render_final_report_markdown, build_structured_report

# ── DB persistence imports ────────────────────────────────────────────────
from database.models.analysis import ensure_analysis_tables
from database.models.report import ensure_report_tables
from database.models.task import ensure_task_tables
from database.queries.analysis import (
    upsert_analysis_snapshot,
    upsert_agent_output,
    upsert_final_analysis_result,
)
from database.queries.report import upsert_report_artifact, upsert_report_item

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


_ARTIFACT_CONTENT_TYPES = {
    ".md": "text/markdown",
    ".json": "application/json",
    ".html": "text/html",
    ".pdf": "application/pdf",
}


# ---------------------------------------------------------------------------
# Step names by pipeline
# ---------------------------------------------------------------------------

CME_STEP_NAMES = {"cme_download", "cme_parse", "cme_ingest", "option_wall"}
MACRO_STEP_NAMES = {"macro_collect", "macro_feature", "report_render"}
NEWS_STEP_NAMES = {"news_collect", "news_feature", "news_brief"}
_STEP_STATUS_SUCCESS = "success"
_STEP_STATUS_SKIPPED = "skipped"
_STEP_STATUS_FAILED = "failed"
_STEP_STATUS_PARTIAL_SUCCESS = "partial_success"


def run_premarket(
    db: DBSession,
    task_id: uuid.UUID,
    *,
    storage_root: Path = Path("./storage"),
    product: str = "OG",
) -> TaskStatus:
    """Execute the premarket pipeline.

    - CME steps use the real CME pipeline (download → parse → ingest → options analysis).
    - Macro steps use the real macro pipeline (collect → feature → render).
    - Other steps remain as stubs (immediate success).
    - A task is ``partial_success`` when some steps fail and others do not.
    - A task is ``failed`` when every executed step fails.
    - All errors are recorded on the individual step.
    """
    task = db.get(TaskRun, task_id)
    if not task:
        return TaskStatus.failed

    transition_task_run(db, task, TaskStatus.running, source="worker", reason="worker_started")
    db.commit()

    # Ensure analysis DB tables exist (idempotent, additive sink)
    try:
        ensure_analysis_tables(db)
    except Exception:
        logger.exception("Failed to ensure analysis tables — DB sink disabled for this run")

    # Ensure task tables exist (idempotent, for new columns)
    try:
        ensure_task_tables(db)
    except Exception:
        logger.exception("Failed to ensure task tables — continuing without new columns")

    # Ensure report tables exist (idempotent, additive sink for new report registry)
    try:
        ensure_report_tables(db)
    except Exception:
        logger.exception("Failed to ensure report tables — continuing without report registry sink")

    # Shared CME pipeline state for this task run
    from apps.worker.pipelines.cme import CmePipelineState, run_cme_step

    cme_state = CmePipelineState()
    run_id = str(task_id)

    # Shared macro pipeline state for this task run
    from apps.worker.pipelines.macro import MacroPipelineState, run_macro_step

    macro_state = MacroPipelineState()

    # Shared news/event pipeline state for this task run
    from apps.worker.pipelines.news import NewsPipelineState, run_news_step

    news_state = NewsPipelineState()
    source_status_index = _load_premarket_source_status_index()

    ordered_steps = sort_premarket_steps(task.steps)

    had_failure = False
    had_degraded_readiness = False
    had_partial_summary = False
    had_non_failed_step = False

    for idx, step in enumerate(ordered_steps):
        # ── P4-03: record step_order and input context ─────────────────
        step.step_order = idx
        step.input_json = json.dumps(
            {"run_id": run_id, "step_name": step.name, "step_order": idx},
            ensure_ascii=False,
            default=str,
        )
        # ── T1.6: compute input_hash for idempotency ────────────────
        step.input_hash = hashlib.sha256(
            step.input_json.encode("utf-8")
        ).hexdigest()
        step.retry_count = 0

        # ── T1.4: check upstream failure/blocking → block this step ──────
        # Only block steps within the SAME pipeline as the failed/blocked step.
        # CME, Macro, and News pipelines are independent; "other" steps are never blocked here.
        step_pipeline = (
            "cme" if step.name in CME_STEP_NAMES
            else "macro" if step.name in MACRO_STEP_NAMES
            else "news" if step.name in NEWS_STEP_NAMES
            else None
        )
        if step_pipeline is not None:
            same_pipeline_blocked = any(
                s.status in {StepStatus.failed, StepStatus.blocked}
                and (
                    "cme" if s.name in CME_STEP_NAMES
                    else "macro" if s.name in MACRO_STEP_NAMES
                    else "news" if s.name in NEWS_STEP_NAMES
                    else None
                ) == step_pipeline
                for s in ordered_steps[:idx]
            )
            if same_pipeline_blocked:
                transition_task_step(
                    db,
                    step,
                    StepStatus.blocked,
                    source="worker",
                    reason="upstream_failed",
                    retryable=False,
                    blocked_reason="同管线内上游步骤失败或阻塞，跳过执行",
                )
                db.commit()
                continue

        contract = get_premarket_step_contract(step.name)
        if contract is not None and _should_apply_source_readiness_gate(contract, source_status_index):
            readiness = evaluate_premarket_step_readiness(contract, source_status_index)
            _emit_source_readiness_events(db, run_id=run_id, step=step, readiness=readiness)
            if readiness.decision == "blocked":
                transition_task_step(
                    db,
                    step,
                    StepStatus.blocked,
                    source="worker",
                    reason="source_readiness_blocked",
                    retryable=False,
                    blocked_reason=_format_source_readiness_blocked_reason(readiness),
                    error_type="data_unavailable",
                )
                db.commit()
                continue
            if readiness.decision == "degraded_allowed":
                had_degraded_readiness = True

        transition_task_step(db, step, StepStatus.running, source="worker", reason="step_started")
        db.commit()

        try:
            summary: dict[str, object] | None
            if step.name in CME_STEP_NAMES:
                summary = run_cme_step(
                    step.name,
                    cme_state,
                    db=db,
                    storage_root=storage_root,
                    run_id=run_id,
                    product=product,
                )
            elif step.name in MACRO_STEP_NAMES:
                summary = run_macro_step(
                    step.name,
                    macro_state,
                    storage_root=storage_root,
                    run_id=run_id,
                    db_session=db,
                )
            elif step.name in NEWS_STEP_NAMES:
                summary = run_news_step(
                    step.name,
                    news_state,
                    storage_root=storage_root,
                    run_id=run_id,
                    db_session=db,
                )
            else:
                # Stub: non-CME non-macro steps are stubs
                logger.info("Step %s: stub — marking success", step.name)
                summary = None

            # ── P4-03: record output payload ──────────────────────
            if summary is not None:
                try:
                    step.output_json = json.dumps(summary, ensure_ascii=False, default=str)
                except (TypeError, ValueError):
                    pass  # non-serializable summary is fine to skip

            # ── T1.6: set output_ref from summary ─────────────────
            if summary and isinstance(summary, dict):
                for key in ("path", "raw_path", "artifact_path"):
                    ref = summary.get(key)
                    if isinstance(ref, (str, Path)):
                        step.output_ref = str(ref)
                        break

            summary_status = _apply_step_summary_status(db, step, summary)
            if step.status in {StepStatus.success, StepStatus.skipped}:
                _register_runner_step_artifacts(db, run_id=run_id, step=step, summary=summary)
            # ── T1.3: successful steps are not retryable ───────────
            step.retryable = False
            if summary_status == _STEP_STATUS_FAILED:
                had_failure = True
            elif summary_status == _STEP_STATUS_PARTIAL_SUCCESS:
                had_partial_summary = True
                had_non_failed_step = True
            else:
                had_non_failed_step = True
        except Exception as exc:
            logger.exception("Step %s failed: %s", step.name, exc)
            # ── P4-03: structured error payload ────────────────────
            step.error_json = json.dumps(
                {
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                },
                ensure_ascii=False,
            )
            # ── T1.3: classify error_type and retryable semantics ──
            step.error_type = _classify_error_type(exc)
            step.retryable = step.error_type in (
                "network_timeout", "data_unavailable",
            )
            transition_task_step(
                db,
                step,
                StepStatus.failed,
                source="worker",
                reason="step_exception",
                error_message=str(exc),
                error_type=step.error_type,
                retryable=step.retryable,
            )
            had_failure = True

        if step.status != StepStatus.failed:
            had_non_failed_step = True

        step.finished_at = _now()
        db.commit()

    # Persist unified Analysis Snapshot before generic provenance so failures are reflected.
    analysis_snapshot: dict[str, Any] | None = None
    try:
        analysis_snapshot_path, analysis_snapshot = _persist_analysis_snapshot(storage_root, run_id, macro_state, cme_state, news_state)
        macro_state.step_summaries["analysis_snapshot"] = {
            "step": "analysis_snapshot",
            "status": "success",
            "path": str(analysis_snapshot_path),
        }
    except Exception as exc:
        logger.exception("Failed to write analysis snapshot artifact")
        had_failure = True
        macro_state.step_summaries["analysis_snapshot"] = {
            "step": "analysis_snapshot",
            "status": "failed",
            "error": str(exc),
        }
    else:
        # DB sink: persist analysis snapshot (additive, after file write)
        try:
            _db_persist_analysis_snapshot(db, analysis_snapshot, analysis_snapshot_path)
        except Exception as db_exc:
            logger.exception("DB persist of analysis snapshot failed (file artifact is safe)")
            macro_state.step_summaries["db_persist_snapshot"] = {
                "step": "db_persist_snapshot",
                "status": "failed",
                "error": str(db_exc),
            }
        _register_run_support_artifacts(
            db,
            run_id=run_id,
            steps=ordered_steps,
            artifacts=[
                {
                    "artifact_id": f"{run_id}:analysis_snapshot",
                    "artifact_type": "feature_json",
                    "file_path": str(analysis_snapshot_path),
                }
            ],
            source_refs=_coerce_lineage_source_refs(analysis_snapshot.get("source_refs")),
            input_snapshot_ids=_coerce_lineage_input_snapshot_ids(analysis_snapshot.get("input_snapshot_ids")),
        )

    # ── C4: agent pipeline (C3 agents → final report → strategy card) ──────────
    if analysis_snapshot is not None:
        try:
            c4_created_at = datetime.now(timezone.utc)
            c4_summaries, c4_outputs = _run_c4_agent_pipeline(
                storage_root=storage_root,
                snapshot=analysis_snapshot,
                run_id=run_id,
                created_at=c4_created_at,
            )
            macro_state.step_summaries.update(c4_summaries)

            # DB sink: persist agent outputs (additive, after file writes)
            try:
                snapshot_db_id = _db_persist_agent_outputs(
                    db, analysis_snapshot, c4_outputs["agents"], run_id
                )
                _db_persist_final_result(
                    db, analysis_snapshot, c4_outputs, snapshot_db_id
                )
            except Exception as db_exc:
                logger.exception("DB persist of C4 outputs failed (file artifacts are safe)")
                macro_state.step_summaries["db_persist_c4"] = {
                    "step": "db_persist_c4",
                    "status": "failed",
                    "error": str(db_exc),
                }
            _register_c4_output_artifacts(
                db,
                run_id=run_id,
                steps=ordered_steps,
                c4_outputs=c4_outputs,
                analysis_snapshot=analysis_snapshot,
            )
            try:
                _register_c4_report_registry_entries(
                    db,
                    run_id=run_id,
                    c4_outputs=c4_outputs,
                    analysis_snapshot=analysis_snapshot,
                )
            except Exception as db_exc:
                logger.exception("Report registry persist of C4 outputs failed (file artifacts are safe)")
                macro_state.step_summaries["db_persist_c4_report_registry"] = {
                    "step": "db_persist_c4_report_registry",
                    "status": "failed",
                    "error": str(db_exc),
                }
        except Exception as exc:
            logger.exception("C4 agent pipeline failed")
            had_failure = True
            macro_state.step_summaries["c4_agent_pipeline"] = {
                "step": "c4_agent_pipeline",
                "status": "failed",
                "error": str(exc),
                "partial_summary": "C4 agent pipeline failed after analysis snapshot was persisted; "
                                  "no final report or strategy card was written.",
            }

    # Persist step summaries and run provenance as durable artifacts
    try:
        step_summaries_path = _persist_step_summaries(
            storage_root,
            run_id,
            cme_state.step_summaries,
            macro_state.step_summaries,
            news_state.step_summaries,
        )
        _register_run_support_artifacts(
            db,
            run_id=run_id,
            steps=ordered_steps,
            artifacts=[
                {
                    "artifact_id": f"{run_id}:step_summaries",
                    "artifact_type": "structured_json",
                    "file_path": str(step_summaries_path),
                }
            ],
            source_refs=_coerce_lineage_source_refs(analysis_snapshot.get("source_refs"))
            if isinstance(analysis_snapshot, dict)
            else None,
            input_snapshot_ids=_coerce_lineage_input_snapshot_ids(analysis_snapshot.get("input_snapshot_ids"))
            if isinstance(analysis_snapshot, dict)
            else None,
        )
    except Exception:
        logger.exception("Failed to write step summaries artifact")

    try:
        run_provenance_path = _persist_run_provenance(
            storage_root,
            run_id,
            cme_state,
            macro_state,
            task_id=task_id,
            news_state=news_state,
        )
        _register_run_support_artifacts(
            db,
            run_id=run_id,
            steps=ordered_steps,
            artifacts=[
                {
                    "artifact_id": f"{run_id}:run_provenance",
                    "artifact_type": "structured_json",
                    "file_path": str(run_provenance_path),
                }
            ],
            source_refs=_coerce_lineage_source_refs(analysis_snapshot.get("source_refs"))
            if isinstance(analysis_snapshot, dict)
            else None,
            input_snapshot_ids=_coerce_lineage_input_snapshot_ids(analysis_snapshot.get("input_snapshot_ids"))
            if isinstance(analysis_snapshot, dict)
            else None,
        )
    except Exception:
        logger.exception("Failed to write run provenance artifact")

    final_status = derive_task_run_status(
        (step.status for step in ordered_steps),
        has_partial_signal=had_partial_summary,
        has_degraded_signal=had_degraded_readiness,
    )
    if had_failure and not had_non_failed_step:
        final_status = TaskStatus.failed
    elif had_failure and final_status == TaskStatus.success:
        final_status = TaskStatus.partial_success
    transition_task_run(db, task, final_status, source="worker", reason="step_rollup")
    db.commit()
    return final_status


def _load_premarket_source_status_index() -> dict[str, dict[str, Any]]:
    """Load source readiness facts once per run without hard-failing the worker."""
    try:
        from apps.api.services.source_service import get_data_source_status_index

        return get_data_source_status_index()
    except Exception:
        logger.exception("Failed to load data source status index for premarket gating")
        return {}


def _should_apply_source_readiness_gate(
    contract: Any,
    source_status_index: dict[str, dict[str, Any]],
) -> bool:
    required_sources = tuple(getattr(contract, "required_sources", ()) or ())
    if not required_sources:
        return False

    observed_rows = [
        source_status_index[source_key]
        for source_key in required_sources
        if source_key in source_status_index
    ]
    if not observed_rows:
        return False

    return any(_source_row_has_runtime_signal(row) for row in observed_rows)


def _source_row_has_runtime_signal(row: dict[str, Any]) -> bool:
    return bool(
        row.get("readiness_state")
        or row.get("raw_ingested")
        or row.get("parsed")
        or row.get("analysis_ready")
        or row.get("latest_health_at")
        or row.get("latest_update_time")
        or row.get("last_run_id")
        or row.get("error_message")
    )


def _format_source_readiness_blocked_reason(readiness: Any) -> str:
    blocked_sources = list(getattr(readiness, "blocked_sources", ()) or ())
    gating_reason = str(getattr(readiness, "gating_reason", "") or "source_readiness_blocked")
    if blocked_sources:
        return f"source readiness blocked: {', '.join(blocked_sources)} ({gating_reason})"
    return f"source readiness blocked ({gating_reason})"


def _emit_source_readiness_events(
    db: DBSession,
    *,
    run_id: str,
    step: Any,
    readiness: Any,
) -> None:
    payload = {
        "decision": getattr(readiness, "decision", None),
        "gating_reason": getattr(readiness, "gating_reason", None),
        "required_sources": list(getattr(readiness, "required_sources", ()) or ()),
        "degraded_sources": list(getattr(readiness, "degraded_sources", ()) or ()),
        "blocked_sources": list(getattr(readiness, "blocked_sources", ()) or ()),
        "step_name": getattr(step, "name", None),
        "stage": getattr(step, "stage", None),
        "task_kind": getattr(step, "task_kind", None),
        "source": "worker",
    }
    emit_task_event(db, run_id, str(step.id), "SOURCE_READINESS_EVALUATED", payload)

    decision = str(getattr(readiness, "decision", "") or "")
    if decision == "blocked":
        emit_task_event(db, run_id, str(step.id), "SOURCE_BLOCKED_TASK", payload)
    elif decision == "degraded_allowed":
        emit_task_event(db, run_id, str(step.id), "SOURCE_FALLBACK_USED", payload)


def _classify_error_type(exc: Exception) -> str:
    """Classify an exception into a structured error type for observability."""
    exc_name = type(exc).__name__
    exc_msg = str(exc).lower()

    # Network / connectivity errors
    if exc_name in (
        "ConnectionError", "TimeoutError", "ConnectTimeout",
        "ReadTimeout", "ConnectionResetError", "SocketError",
    ) or "timeout" in exc_msg or "connection" in exc_msg:
        return "network_timeout"

    # Data unavailable (source returned no data / 404)
    if exc_name in ("DataUnavailableError",) or "not found" in exc_msg or "unavailable" in exc_msg:
        return "data_unavailable"

    # Parse / validation errors (bad data, won't fix on retry)
    if exc_name in (
        "ValueError", "TypeError", "KeyError",
        "JSONDecodeError", "ValidationError",
    ) or "parse" in exc_msg:
        return "parse_failure"

    # Config / setup errors (won't fix on retry)
    if exc_name in (
        "ConfigError", "EnvironmentError", "KeyError",
    ) or "config" in exc_msg or "api key" in exc_msg:
        return "config_error"

    # Default: unknown, conservatively retryable
    return "unknown"


def _apply_step_summary_status(db: DBSession, step, summary: dict[str, object] | None) -> str:
    """Map a pipeline summary status onto the persisted step status."""
    if summary is None:
        step.error = None
        step.retryable = False
        transition_task_step(db, step, StepStatus.success, source="worker", reason="step_finished", retryable=False)
        return _STEP_STATUS_SUCCESS

    status = str(summary.get("status", _STEP_STATUS_SUCCESS))
    if status == _STEP_STATUS_SKIPPED:
        step.error = None
        transition_task_step(db, step, StepStatus.skipped, source="worker", reason="step_skipped", retryable=False)
    elif status == _STEP_STATUS_FAILED:
        error_message = str(summary.get("error")) if summary.get("error") is not None else None
        transition_task_step(
            db,
            step,
            StepStatus.failed,
            source="worker",
            reason="step_failed",
            error_message=error_message,
        )
    elif status in {_STEP_STATUS_SUCCESS, _STEP_STATUS_PARTIAL_SUCCESS}:
        step.error = None
        transition_task_step(db, step, StepStatus.success, source="worker", reason="step_finished", retryable=False)
    else:
        unknown_status = f"Unknown pipeline summary status: {status}"
        transition_task_step(
            db,
            step,
            StepStatus.failed,
            source="worker",
            reason="unknown_step_status",
            error_message=unknown_status,
        )
        logger.warning("Step %s returned %s", getattr(step, "name", "<unknown>"), unknown_status)
        return _STEP_STATUS_FAILED
    return status


def _register_runner_step_artifacts(
    db: DBSession,
    *,
    run_id: str,
    step,
    summary: dict[str, object] | None,
) -> None:
    if not isinstance(summary, dict) and not step.output_ref:
        return
    output_refs = summary.get("output_refs") if isinstance(summary, dict) else None
    artifact_refs = summary.get("artifact_refs") if isinstance(summary, dict) else None
    register_step_artifacts(
        db,
        run_id=run_id,
        step=step,
        output_refs=output_refs if isinstance(output_refs, list) else None,
        artifact_refs=artifact_refs if isinstance(artifact_refs, list) else None,
        output_ref=step.output_ref,
        source_refs=_coerce_lineage_source_refs(summary.get("source_refs")) if isinstance(summary, dict) else None,
        input_snapshot_ids=_coerce_lineage_input_snapshot_ids(summary.get("input_snapshot_ids"))
        if isinstance(summary, dict)
        else None,
    )


def _register_c4_output_artifacts(
    db: DBSession,
    *,
    run_id: str,
    steps: list[Any],
    c4_outputs: dict[str, Any],
    analysis_snapshot: dict[str, Any] | None = None,
) -> None:
    report_step = next((step for step in steps if step.name == "report_render"), None)
    if report_step is None:
        return

    report_result = c4_outputs.get("report_result") if isinstance(c4_outputs, dict) else None
    card_result = c4_outputs.get("card_result") if isinstance(c4_outputs, dict) else None
    card = c4_outputs.get("strategy_card") if isinstance(c4_outputs, dict) else None

    artifacts: list[dict[str, Any]] = []
    if isinstance(report_result, dict):
        report_paths = report_result.get("paths")
        if isinstance(report_paths, list):
            for index, path in enumerate(report_paths):
                if not isinstance(path, str):
                    continue
                artifacts.append(
                    _enrich_runner_artifact_metadata(
                        {
                        "artifact_id": f"{run_id}:final_report:{index}",
                        "artifact_type": "analysis_md" if path.endswith(".md") else "structured_json",
                        "file_path": path,
                        }
                    )
                )
    if isinstance(card_result, dict):
        card_paths = card_result.get("paths")
        if isinstance(card_paths, list):
            for index, path in enumerate(card_paths):
                if not isinstance(path, str):
                    continue
                artifacts.append(
                    _enrich_runner_artifact_metadata(
                        {
                        "artifact_id": f"{run_id}:strategy_card:{index}",
                        "artifact_type": "analysis_md" if path.endswith(".md") else "structured_json",
                        "file_path": path,
                        }
                    )
                )
    if not artifacts:
        return

    source_refs = _merge_lineage_source_refs(
        analysis_snapshot.get("source_refs") if isinstance(analysis_snapshot, dict) else None,
        list(getattr(card, "source_refs", []) or []) if card is not None else None,
    )
    input_snapshot_ids = _merge_lineage_input_snapshot_ids(
        analysis_snapshot.get("input_snapshot_ids") if isinstance(analysis_snapshot, dict) else None,
        dict(getattr(card, "input_snapshot_ids", {}) or {}) if card is not None else None,
    )

    register_step_artifacts(
        db,
        run_id=run_id,
        step=report_step,
        output_refs=artifacts,
        artifact_refs=None,
        output_ref=None,
        source_refs=source_refs,
        input_snapshot_ids=input_snapshot_ids,
    )


def _register_run_support_artifacts(
    db: DBSession,
    *,
    run_id: str,
    steps: list[Any],
    artifacts: list[dict[str, Any]],
    source_refs: list[dict[str, Any]] | None = None,
    input_snapshot_ids: dict[str, Any] | None = None,
) -> None:
    """Register run support files without introducing a separate storage backend."""
    if not artifacts:
        return
    enriched_artifacts = [_enrich_runner_artifact_metadata(artifact) for artifact in artifacts]
    step = next((item for item in steps if item.name == "report_render"), None)
    if step is None and steps:
        step = steps[-1]
    if step is None:
        return
    register_step_artifacts(
        db,
        run_id=run_id,
        step=step,
        output_refs=enriched_artifacts,
        artifact_refs=None,
        output_ref=None,
        source_refs=source_refs,
        input_snapshot_ids=input_snapshot_ids,
    )


def _register_c4_report_registry_entries(
    db: DBSession,
    *,
    run_id: str,
    c4_outputs: dict[str, Any],
    analysis_snapshot: dict[str, Any] | None = None,
) -> None:
    report_result = c4_outputs.get("report_result") if isinstance(c4_outputs, dict) else None
    card_result = c4_outputs.get("card_result") if isinstance(c4_outputs, dict) else None
    card = c4_outputs.get("strategy_card") if isinstance(c4_outputs, dict) else None

    snapshot_id = analysis_snapshot.get("snapshot_id") if isinstance(analysis_snapshot, dict) else None
    trade_date = analysis_snapshot.get("trade_date") if isinstance(analysis_snapshot, dict) else None
    asset = analysis_snapshot.get("asset", "XAUUSD") if isinstance(analysis_snapshot, dict) else "XAUUSD"
    source_refs = _merge_lineage_source_refs(
        analysis_snapshot.get("source_refs") if isinstance(analysis_snapshot, dict) else None,
        list(getattr(card, "source_refs", []) or []) if card is not None else None,
    ) or []
    input_snapshot_ids = _merge_lineage_input_snapshot_ids(
        analysis_snapshot.get("input_snapshot_ids") if isinstance(analysis_snapshot, dict) else None,
        dict(getattr(card, "input_snapshot_ids", {}) or {}) if card is not None else None,
    ) or {}

    report_specs = [
        {
            "report_id": f"final_report:{run_id}",
            "family": "final_report_markdown",
            "report_type": "final_report",
            "title": f"{asset} 综合报告（{trade_date}）" if trade_date else f"{asset} 综合报告",
            "paths": report_result.get("paths") if isinstance(report_result, dict) else None,
            "primary_name": "final_report.md",
            "metadata": {
                "input_snapshot_ids": input_snapshot_ids,
                "writer": "run_premarket",
            },
        },
        {
            "report_id": f"strategy_card:{run_id}",
            "family": "strategy_card",
            "report_type": "strategy_card",
            "title": f"{asset} 策略卡片（{trade_date}）" if trade_date else f"{asset} 策略卡片",
            "paths": card_result.get("paths") if isinstance(card_result, dict) else None,
            "primary_name": "strategy_card.json",
            "metadata": {
                "input_snapshot_ids": input_snapshot_ids,
                "writer": "run_premarket",
                "strategy_card_id": getattr(card, "strategy_card_id", None),
            },
        },
    ]

    with db.begin_nested():
        for spec in report_specs:
            raw_paths = spec.get("paths")
            if not isinstance(raw_paths, list):
                continue
            existing_paths = [Path(path) for path in raw_paths if isinstance(path, str) and path]
            existing_paths = [path for path in existing_paths if path.exists()]
            if not existing_paths:
                continue

            upsert_report_item(
                db,
                {
                    "report_id": spec["report_id"],
                    "family": spec["family"],
                    "report_type": spec["report_type"],
                    "title": spec["title"],
                    "asset": asset,
                    "trade_date": trade_date,
                    "run_id": run_id,
                    "snapshot_id": snapshot_id,
                    "data_status": "live",
                    "lifecycle_status": "generated",
                    "source_refs": source_refs,
                    "metadata": spec["metadata"],
                },
            )

            for index, path in enumerate(existing_paths):
                artifact = _enrich_runner_artifact_metadata(
                    {
                        "artifact_id": f"{spec['report_id']}:{index}",
                        "artifact_type": "analysis_md" if path.suffix.lower() == ".md" else "structured_json",
                        "file_path": str(path),
                    }
                )
                artifact["sha256"] = get_artifact_storage().compute_sha256(str(path))
                artifact["storage_backend"] = "local_fs"
                artifact["report_id"] = spec["report_id"]
                artifact["source_refs"] = source_refs
                artifact["metadata"] = {
                    "run_id": run_id,
                    "snapshot_id": snapshot_id,
                    "input_snapshot_ids": input_snapshot_ids,
                }
                artifact["is_primary"] = path.name == spec["primary_name"]
                upsert_report_artifact(db, artifact)
        db.flush()


def _enrich_runner_artifact_metadata(artifact: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(artifact)
    file_path = enriched.get("file_path")
    if not isinstance(file_path, str) or not file_path:
        return enriched

    path = Path(file_path)
    try:
        stat_result = path.stat()
    except OSError:
        return enriched

    suffix = path.suffix.lower()
    enriched.setdefault("content_type", _ARTIFACT_CONTENT_TYPES.get(suffix, "application/octet-stream"))
    enriched.setdefault("byte_size", stat_result.st_size)
    enriched.setdefault("generated_at", datetime.fromtimestamp(stat_result.st_mtime, tz=timezone.utc).isoformat())
    return enriched


def _coerce_lineage_source_refs(raw: Any) -> list[dict[str, Any]] | None:
    if not isinstance(raw, list):
        return None
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        normalized = dict(item)
        identity = _first_lineage_ref_value(normalized, ("source_ref", "source_id", "source_name", "source", "source_key"))
        trace_detail = _first_lineage_ref_value(
            normalized,
            (
                "article_id",
                "captured_at",
                "data_date",
                "endpoint",
                "file_path",
                "raw_path",
                "ref",
                "report_date",
                "sha256",
                "snapshot_id",
                "source_ref",
                "source_type",
                "source_url",
                "status",
                "symbol",
                "url",
            ),
        )
        if identity is not None and trace_detail is None:
            normalized["source_ref"] = identity
        dedupe_key = json.dumps(normalized, ensure_ascii=False, sort_keys=True, default=str)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        refs.append(normalized)
    return refs or None


def _first_lineage_ref_value(ref: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = ref.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return None


def _coerce_lineage_input_snapshot_ids(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    normalized = {str(key): value for key, value in raw.items() if str(key)}
    return normalized or None


def _merge_lineage_source_refs(*raw_groups: Any) -> list[dict[str, Any]] | None:
    merged: list[dict[str, Any]] = []
    for raw in raw_groups:
        refs = _coerce_lineage_source_refs(raw)
        if refs:
            merged.extend(refs)
    return _coerce_lineage_source_refs(merged)


def _merge_lineage_input_snapshot_ids(*raw_payloads: Any) -> dict[str, Any] | None:
    merged: dict[str, Any] = {}
    for raw in raw_payloads:
        payload = _coerce_lineage_input_snapshot_ids(raw)
        if payload:
            merged.update(payload)
    return merged or None


def _persist_analysis_snapshot(
    storage_root: Path,
    run_id: str,
    macro_state: object,
    cme_state: object,
    news_state: object | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Build and write the unified Analysis Snapshot from in-memory pipeline states.

    Returns (written_path, snapshot_dict) so downstream C4 rendering can consume
    the snapshot without re-reading from disk.
    """

    macro_snapshot = getattr(macro_state, "snapshot_dict", None)
    options_snapshot = getattr(cme_state, "snapshot_dict", None)
    trade_date = _resolve_analysis_trade_date(macro_snapshot, options_snapshot)
    source_refs = list(getattr(macro_state, "all_source_refs", []) or [])
    source_refs.extend(_cme_source_refs(cme_state))
    source_refs.extend(getattr(news_state, "source_refs", []) or [])
    collected_points = [p.to_dict() for p in getattr(macro_state, "all_points", [])]
    news_snapshot = getattr(news_state, "snapshot_dict", None) if news_state is not None else None

    snapshot = build_analysis_snapshot(
        asset="XAUUSD",
        trade_date=trade_date,
        run_id=run_id,
        macro_snapshot=macro_snapshot,
        options_snapshot=options_snapshot,
        source_refs=source_refs,
        collected_points=collected_points,
        news_snapshot=news_snapshot,
    )
    path = write_analysis_snapshot(snapshot, storage_root=storage_root)
    return path, snapshot


def _resolve_analysis_trade_date(
    macro_snapshot: dict[str, Any] | None,
    options_snapshot: dict[str, Any] | None,
) -> str:
    """Prefer options trade_date, then macro as_of, then current UTC date."""

    if options_snapshot and options_snapshot.get("trade_date"):
        return str(options_snapshot["trade_date"])
    if macro_snapshot and macro_snapshot.get("as_of"):
        return str(macro_snapshot["as_of"])
    return datetime.now(timezone.utc).date().isoformat()


def _cme_source_refs(cme_state: object) -> list[dict[str, Any]]:
    """Extract CME provenance refs for the unified analysis snapshot."""

    refs: list[dict[str, Any]] = []
    raw_file = getattr(cme_state, "raw_file", None)
    if raw_file is not None:
        ref = {
            "source": "cme_daily_bulletin",
            "source_url": getattr(raw_file, "source_url", None),
            "raw_path": getattr(raw_file, "raw_path", None),
            "sha256": getattr(raw_file, "sha256", None),
            "report_date": getattr(raw_file, "report_date", None),
        }
        refs.append({key: value for key, value in ref.items() if value is not None})

    parse_result = getattr(cme_state, "parse_result", None)
    if parse_result is not None and getattr(parse_result, "trade_date", None):
        refs.append(
            {
                "source": "cme_pg64_parse",
                "trade_date": getattr(parse_result, "trade_date"),
                "status": getattr(parse_result, "status", None),
            }
        )
    return refs


# ---------------------------------------------------------------------------
# C4 agent pipeline (C3 agents → final report → strategy card)
# ---------------------------------------------------------------------------


def _run_c4_agent_pipeline(
    *,
    storage_root: Path,
    snapshot: dict[str, Any],
    run_id: str,
    created_at: datetime | None = None,
    macro_output_prebuilt: Any = None,
    options_output_prebuilt: Any = None,
    risk_output_prebuilt: Any = None,
    technical_output_prebuilt: Any = None,
    positioning_output_prebuilt: Any = None,
    news_output_prebuilt: Any = None,
    coordinator_output_prebuilt: Any = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Run the C4 agent pipeline on an already-persisted analysis snapshot.

    Steps (deterministic, no LLM, no network, no file reads):
      1. Run C3 pseudo-agents (macro, options, risk) against the snapshot.
      2. Coordinate their outputs into one read-only final view.
      3. Render the final report Markdown.
      4. Build the strategy card from coordinator + risk.
      5. Write both artifacts to disk.

    Returns a tuple of (step_summaries, c4_outputs) where c4_outputs contains:
      ``agents`` — dict of agent_name → AgentOutput for the 4 C3 agents,
      ``strategy_card`` — the StrategyCardOutput,
      ``report_result`` — the write_final_report result dict,
      ``card_result`` — the write_strategy_card result dict.

    If prebuilt agent outputs are provided, steps 1-2 are skipped.
    """

    created_at = created_at or _now()
    summaries: dict[str, dict[str, Any]] = {}
    trade_date = snapshot.get("trade_date", "")
    snapshot_id = snapshot.get("snapshot_id", "unknown")

    # ── 1. C3 agents ──────────────────────────────────────────────────────
    macro_output = analyze_macro_liquidity(snapshot, created_at=created_at)
    options_output = analyze_cme_options(snapshot, created_at=created_at)
    risk_output = analyze_risk(
        snapshot,
        macro_output=macro_output,
        options_output=options_output,
        created_at=created_at,
    )
    technical_output = analyze_technical(snapshot, created_at=created_at)
    positioning_output = analyze_positioning(snapshot, created_at=created_at)
    news_output = analyze_news(snapshot, created_at=created_at)
    market_odds_output = analyze_market_odds(snapshot, created_at=created_at)
    from apps.analysis.agents.coordinator import coordinate_agent_outputs

    coordinator_output = coordinate_agent_outputs(
        snapshot,
        macro_output=macro_output,
        options_output=options_output,
        risk_output=risk_output,
        technical_output=technical_output,
        positioning_output=positioning_output,
        news_output=news_output,
        market_odds_output=market_odds_output,
        created_at=created_at,
    )

    summaries["c3_agents"] = {
        "step": "c3_agents",
        "status": "success",
        "macro_status": macro_output.status.value,
        "options_status": options_output.status.value,
        "risk_status": risk_output.status.value,
        "technical_status": technical_output.status.value,
        "positioning_status": positioning_output.status.value,
        "news_status": news_output.status.value,
        "market_odds_status": market_odds_output.status.value,
        "coordinator_status": coordinator_output.status.value,
    }

    # ── 2. Final report ───────────────────────────────────────────────────
    markdown = render_final_report_markdown(
        snapshot=snapshot,
        macro_output=macro_output,
        options_output=options_output,
        risk_output=risk_output,
        technical_output=technical_output,
        positioning_output=positioning_output,
        news_output=news_output,
        coordinator_output=coordinator_output,
        created_at=created_at,
    )

    # P4-04: build structured report JSON alongside Markdown
    try:
        structured = build_structured_report(
            snapshot=snapshot,
            macro_output=macro_output,
            options_output=options_output,
            risk_output=risk_output,
            technical_output=technical_output,
            positioning_output=positioning_output,
            news_output=news_output,
            coordinator_output=coordinator_output,
            created_at=created_at,
        )
        structured_dict = structured.model_dump(mode="json")
    except Exception:
        logger.exception("Failed to build structured report — writing Markdown only")
        structured_dict = None

    report_result = write_final_report(
        storage_root=storage_root,
        markdown=markdown,
        asset="XAUUSD",
        trade_date=str(trade_date),
        run_id=run_id,
        structured_report=structured_dict,
    )
    summaries["final_report"] = {
        "step": "final_report",
        "status": "success",
        "snapshot_id": str(snapshot_id),
        "paths": report_result.get("paths", []),
    }

    # ── 3. Strategy card ──────────────────────────────────────────────────
    card = build_strategy_card(
        snapshot=snapshot,
        coordinator_output=coordinator_output,
        risk_output=risk_output,
        created_at=created_at,
    )
    card_result = write_strategy_card(
        storage_root=storage_root,
        card=card,
    )
    summaries["strategy_card"] = {
        "step": "strategy_card",
        "status": "success",
        "snapshot_id": str(snapshot_id),
        "input_snapshot_ids": dict(card.input_snapshot_ids),
        "paths": card_result.get("paths", []),
    }

    # ── Pack agent outputs for DB persistence ─────────────────────────
    c4_outputs: dict[str, Any] = {
        "agents": {
            "macro_liquidity_agent": macro_output,
            "cme_options_agent": options_output,
            "risk_agent": risk_output,
            "technical_agent": technical_output,
            "positioning_agent": positioning_output,
            "news_agent": news_output,
            "market_odds_agent": market_odds_output,
            "coordinator_agent": coordinator_output,
        },
        "strategy_card": card,
        "report_result": report_result,
        "card_result": card_result,
    }

    return summaries, c4_outputs


# ---------------------------------------------------------------------------
# DB persistence helpers (additive sink — file artifacts remain canonical)
# ---------------------------------------------------------------------------


def _db_persist_analysis_snapshot(
    db: DBSession,
    snapshot: dict[str, Any],
    artifact_path: Path,
) -> str:
    """Persist analysis snapshot to DB via idempotent upsert.

    Returns the DB snapshot id for FK linking.
    """
    payload = {
        "snapshot_id": snapshot["snapshot_id"],
        "asset": snapshot.get("asset", "XAUUSD"),
        "trade_date": snapshot["trade_date"],
        "run_id": snapshot["run_id"],
        "snapshot_time": snapshot.get("snapshot_time"),
        "status": snapshot.get("status", "success"),
        "input_snapshot_ids": snapshot.get("input_snapshot_ids", {}),
        "source_refs": snapshot.get("source_refs", []),
        "macro": snapshot.get("macro"),
        "options": snapshot.get("options"),
        "positioning": snapshot.get("positioning"),
        "news": snapshot.get("news"),
        "technical": snapshot.get("technical"),
        "payload": snapshot,
    }
    result = upsert_analysis_snapshot(db, payload, str(artifact_path))
    db.commit()
    logger.info("DB: persisted analysis snapshot %s", result.snapshot_id)
    return result.id


def _db_persist_agent_outputs(
    db: DBSession,
    snapshot: dict[str, Any],
    agents: dict[str, Any],  # agent_name → AgentOutput
    run_id: str,
) -> str | None:
    """Persist all C3 agent outputs to DB via idempotent upsert.

    Returns the DB snapshot id for FK linking, or None if no snapshot exists.
    """
    from database.queries.analysis import get_analysis_snapshot

    snapshot_id = snapshot.get("snapshot_id", "")
    trade_date = snapshot.get("trade_date", "")

    # Look up the DB snapshot id for FK linking
    snap = get_analysis_snapshot(db, "XAUUSD", trade_date, run_id)
    snapshot_db_id = snap.id if snap else None

    for agent_name, ao in agents.items():
        # AgentOutput from apps.analysis.agents.schemas
        if ao is None:
            continue
        payload = {
            "snapshot_id": snapshot_id,
            "analysis_snapshot_db_id": snapshot_db_id,
            "asset": "XAUUSD",
            "trade_date": trade_date,
            "run_id": run_id,
            "agent_name": ao.agent_name,
            "module": ao.module,
            "version": ao.version,
            "status": ao.status.value,
            "bias": ao.bias.value,
            "confidence": float(ao.confidence),
            "input_snapshot_ids": dict(ao.input_snapshot_ids),
            "source_refs": list(ao.source_refs),
            "key_findings": list(ao.key_findings),
            "risk_points": list(ao.risk_points),
            "watchlist": list(ao.watchlist),
            "invalid_conditions": list(ao.invalid_conditions),
            "summary": ao.summary,
            "payload": ao.model_dump(mode="json"),
        }
        upsert_agent_output(db, payload)
        logger.info("DB: persisted agent output %s/%s", agent_name, ao.module)

    db.commit()
    return snapshot_db_id


def _db_persist_final_result(
    db: DBSession,
    snapshot: dict[str, Any],
    c4_outputs: dict[str, Any],
    snapshot_db_id: str | None,
) -> None:
    """Persist C4 final result (report + strategy card) to DB via idempotent upsert."""
    import hashlib

    card = c4_outputs["strategy_card"]
    report_result = c4_outputs["report_result"]
    card_result = c4_outputs["card_result"]
    agents = c4_outputs["agents"]

    trade_date = snapshot.get("trade_date", "")
    run_id = snapshot["run_id"]
    snapshot_id = snapshot.get("snapshot_id", "")

    # Extract file paths
    report_paths = report_result.get("paths", [])
    card_paths = card_result.get("paths", [])
    final_report_path = report_paths[0] if report_paths else None
    sc_json_path = card_paths[0] if len(card_paths) > 0 else None
    sc_md_path = card_paths[1] if len(card_paths) > 1 else None

    # Compute content hashes
    final_report_sha256 = None
    if final_report_path:
        try:
            final_report_sha256 = hashlib.sha256(
                Path(final_report_path).read_bytes()
            ).hexdigest()
        except Exception:
            pass

    strategy_card_sha256 = None
    if sc_json_path:
        try:
            strategy_card_sha256 = hashlib.sha256(
                Path(sc_json_path).read_bytes()
            ).hexdigest()
        except Exception:
            pass

    # Collect source_agent_outputs (list of agent names + snapshot_ids)
    source_agent_outputs: list[dict[str, Any]] = []
    for agent_name, ao in agents.items():
        if ao is not None:
            source_agent_outputs.append({
                "agent_name": ao.agent_name,
                "module": ao.module,
                "snapshot_id": ao.snapshot_id,
                "bias": ao.bias.value,
                "confidence": ao.confidence,
            })

    payload = {
        "asset": "XAUUSD",
        "trade_date": trade_date,
        "run_id": run_id,
        "snapshot_id": snapshot_id,
        "analysis_snapshot_db_id": snapshot_db_id,
        "final_bias": card.bias.value,
        "confidence": float(card.confidence),
        "market_state": "premarket",
        "scenario_summary": card.scenario_summary,
        "is_trade_instruction": False,
        "input_snapshot_ids": dict(card.input_snapshot_ids),
        "source_refs": list(card.source_refs),
        "source_agent_outputs": source_agent_outputs,
        "risk_points": list(card.risk_points),
        "watchlist": list(card.watchlist),
        "invalid_conditions": list(card.invalid_conditions),
        "strategy_card": card.model_dump(mode="json"),
        "run_summaries": {},
        "payload": card.model_dump(mode="json"),
    }

    paths = {
        "final_report_path": final_report_path,
        "strategy_card_json_path": sc_json_path,
        "strategy_card_md_path": sc_md_path,
        "run_summary_path": None,
        "final_report_sha256": final_report_sha256,
        "strategy_card_sha256": strategy_card_sha256,
    }

    upsert_final_analysis_result(db, payload, paths)
    db.commit()
    logger.info("DB: persisted final analysis result for run %s", run_id)

    # ── Auto-create review items for low-confidence / data-gap runs ──
    _ensure_review_items(
        db,
        run_id=run_id,
        trade_date=trade_date,
        card=card,
        agents=agents,
    )


def _ensure_review_items(
    db,
    *,
    run_id: str,
    trade_date: str,
    card,
    agents: dict[str, Any],
) -> None:
    """Auto-create review items for low-confidence or data-gap premarket runs.

    Creates review items when:
      - Strategy card confidence < 0.5
      - Any agent output is missing or has confidence < 0.3
      - Risk points indicate missing/unavailable data
    """
    from database.queries.review import upsert_review_item

    review_batch: list[dict[str, Any]] = []

    # ── Low-confidence strategy card ──
    if card.confidence < 0.5:
        review_batch.append({
            "review_id": f"{run_id}:low_confidence",
            "run_id": run_id,
            "source_module": "coordinator",
            "source_step_id": "strategy_card",
            "severity": "warning",
            "reason": f"策略卡置信度 {card.confidence:.0%}，低于 50% 阈值",
            "impact_modules": ["dashboard", "strategy"],
            "suggested_action": "人工复核策略结论与数据来源",
            "status": "pending",
        })

    # ── Missing / low-confidence agent outputs ──
    for agent_name, ao in agents.items():
        if ao is None:
            review_batch.append({
                "review_id": f"{run_id}:agent_missing:{agent_name}",
                "run_id": run_id,
                "source_module": agent_name,
                "source_step_id": agent_name,
                "severity": "error",
                "reason": f"Agent {agent_name} 输出缺失",
                "impact_modules": ["dashboard", "strategy"],
                "suggested_action": "检查上游采集器与解析链路",
                "status": "pending",
            })
        elif ao.confidence is not None and ao.confidence < 0.3:
            review_batch.append({
                "review_id": f"{run_id}:agent_low_confidence:{agent_name}",
                "run_id": run_id,
                "source_module": agent_name,
                "source_step_id": agent_name,
                "severity": "warning",
                "reason": f"Agent {agent_name} 置信度 {ao.confidence:.0%}，低于 30%",
                "impact_modules": ["dashboard"],
                "suggested_action": "确认输入数据质量",
                "status": "pending",
            })

    # ── Data gap indicators from risk_points ──
    for rp in card.risk_points:
        if "unavailable" in str(rp).lower() or "missing" in str(rp).lower():
            risk_digest = hashlib.sha256(str(rp).encode("utf-8")).hexdigest()[:12]
            review_batch.append({
                "review_id": f"{run_id}:data_gap:{risk_digest}",
                "run_id": run_id,
                "source_module": "coordinator",
                "source_step_id": "strategy_card",
                "severity": "warning",
                "reason": f"数据缺口: {str(rp)[:200]}",
                "impact_modules": ["data_ingestion"],
                "suggested_action": "检查对应数据源状态",
                "status": "pending",
            })

    for rv in review_batch:
        try:
            upsert_review_item(db, rv)
        except Exception:
            logger.exception("Failed to upsert review item %s", rv.get("review_id"))
    if review_batch:
        db.commit()
        logger.info("Auto-created %d review items for run %s", len(review_batch), run_id)


def _persist_step_summaries(
    storage_root: Path,
    run_id: str,
    cme_summaries: dict[str, dict[str, Any]],
    macro_summaries: dict[str, dict[str, Any]],
    news_summaries: dict[str, dict[str, Any]] | None = None,
) -> Path:
    """Write combined step summaries JSON artifact."""
    all_steps: dict[str, dict[str, Any]] = {}
    all_steps.update(cme_summaries)
    all_steps.update(macro_summaries)
    all_steps.update(news_summaries or {})

    out_dir = artifact_run_dir(
        storage_root,
        layer="outputs",
        domain="run",
        date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        run_id=run_id,
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "run_id": run_id,
        "written_at": _now().isoformat(),
        "steps": all_steps,
    }
    path = out_dir / "step_summaries.json"
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    logger.info("Wrote step summaries to %s", path)
    return path


def _persist_run_provenance(
    storage_root: Path,
    run_id: str,
    cme_state: object,  # CmePipelineState (avoid circular import)
    macro_state: object,  # MacroPipelineState
    task_id: uuid.UUID,
    news_state: object | None = None,
) -> Path:
    """Write cross-pipeline run provenance artifact."""
    out_dir = artifact_run_dir(
        storage_root,
        layer="outputs",
        domain="run",
        date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        run_id=run_id,
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    # Collect source_refs from macro pipeline
    source_refs: list[dict[str, Any]] = []
    if hasattr(macro_state, "all_source_refs"):
        source_refs = macro_state.all_source_refs
    if news_state is not None and hasattr(news_state, "source_refs"):
        source_refs = [*source_refs, *getattr(news_state, "source_refs", [])]

    # Collect input snapshot IDs from CME pipeline
    input_snapshot_ids: dict[str, str] = {}
    if hasattr(cme_state, "raw_file") and cme_state.raw_file:
        input_snapshot_ids["cme_raw_file_sha256"] = cme_state.raw_file.sha256
        input_snapshot_ids["cme_raw_path"] = cme_state.raw_file.raw_path
    if hasattr(cme_state, "ingest_result") and cme_state.ingest_result:
        ir = cme_state.ingest_result
        if ir.raw_file_id:
            input_snapshot_ids["cme_raw_file_id"] = str(ir.raw_file_id)
        if ir.parse_run_id:
            input_snapshot_ids["cme_parse_run_id"] = ir.parse_run_id
    if hasattr(cme_state, "parse_result") and cme_state.parse_result:
        input_snapshot_ids["cme_parse_status"] = cme_state.parse_result.status

    # Unavailable symbols from macro
    unavailable: list[str] = []
    if hasattr(macro_state, "all_unavailable"):
        unavailable = macro_state.all_unavailable

    payload = {
        "run_id": run_id,
        "task_id": str(task_id),
        "written_at": _now().isoformat(),
        "source_refs": source_refs,
        "input_snapshot_ids": input_snapshot_ids,
        "unavailable_symbols": unavailable,
    }
    path = out_dir / "run_provenance.json"
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    logger.info("Wrote run provenance to %s", path)
    return path
