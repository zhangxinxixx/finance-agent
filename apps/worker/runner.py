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
from apps.runtime.state_machine import derive_task_run_status, transition_task_run, transition_task_step
from apps.worker.artifact_registration import (
    coerce_lineage_input_snapshot_ids as _coerce_lineage_input_snapshot_ids,
    coerce_lineage_source_refs as _coerce_lineage_source_refs,
    enrich_runner_artifact_metadata as _enrich_runner_artifact_metadata,
    merge_lineage_input_snapshot_ids as _merge_lineage_input_snapshot_ids,
    merge_lineage_source_refs as _merge_lineage_source_refs,
    register_composite_output_artifacts as _register_composite_output_artifacts,
    register_run_support_artifacts as _register_run_support_artifacts,
    register_runner_step_artifacts as _register_runner_step_artifacts,
)
from apps.worker.composite_analysis_pipeline import (
    accepted_coordinator_output as _accepted_coordinator_output,
    run_composite_analysis_pipeline as _run_composite_analysis_pipeline,
)
from apps.worker.error_policy import (
    classify_error_type as _classify_error_type,
    is_retryable_error_type as _is_retryable_error_type,
)
from apps.worker.report_registry_sink import (
    register_composite_report_registry_entries as _register_composite_report_registry_entries,
)
from apps.worker.source_readiness_gate import (
    emit_source_readiness_events as _emit_source_readiness_events,
    format_source_readiness_blocked_reason as _format_source_readiness_blocked_reason,
    load_premarket_source_status_index as _load_premarket_source_status_index,
    should_apply_source_readiness_gate as _should_apply_source_readiness_gate,
)
from apps.api.services.quality_gate_service import evaluate_quality_gate
from database.models.task import StepStatus, TaskRun, TaskStatus

# ── DB persistence imports ────────────────────────────────────────────────
from database.models.analysis import ensure_analysis_tables
from database.models.report import ensure_report_tables
from database.models.task import ensure_task_tables
from database.queries.analysis import (
    upsert_analysis_snapshot,
    upsert_agent_output,
    upsert_final_analysis_result,
)

logger = logging.getLogger(__name__)

__all__ = [
    "_coerce_lineage_input_snapshot_ids",
    "_coerce_lineage_source_refs",
    "_enrich_runner_artifact_metadata",
    "_merge_lineage_input_snapshot_ids",
    "_merge_lineage_source_refs",
    "_accepted_coordinator_output",
    "_register_composite_output_artifacts",
    "_register_composite_report_registry_entries",
    "_register_run_support_artifacts",
    "_register_runner_step_artifacts",
    "_run_composite_analysis_pipeline",
    "evaluate_quality_gate",
    "run_premarket",
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


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
            step.retryable = _is_retryable_error_type(step.error_type)
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

    # ── Composite analysis: domain agents → final report → strategy card ───────
    if analysis_snapshot is not None:
        try:
            composite_created_at = datetime.now(timezone.utc)
            composite_summaries, composite_outputs = _run_composite_analysis_pipeline(
                storage_root=storage_root,
                snapshot=analysis_snapshot,
                run_id=run_id,
                created_at=composite_created_at,
            )
            macro_state.step_summaries.update(composite_summaries)

            # DB sink: persist agent outputs (additive, after file writes)
            try:
                snapshot_db_id = _db_persist_agent_outputs(
                    db, analysis_snapshot, composite_outputs["agents"], run_id
                )
                _db_persist_final_result(
                    db, analysis_snapshot, composite_outputs, snapshot_db_id
                )
            except Exception as db_exc:
                logger.exception("DB persist of composite analysis outputs failed (file artifacts are safe)")
                macro_state.step_summaries["db_persist_composite"] = {
                    "step": "db_persist_composite",
                    "status": "failed",
                    "error": str(db_exc),
                }
            _register_composite_output_artifacts(
                db,
                run_id=run_id,
                steps=ordered_steps,
                composite_outputs=composite_outputs,
                analysis_snapshot=analysis_snapshot,
            )
            try:
                _register_composite_report_registry_entries(
                    db,
                    run_id=run_id,
                    composite_outputs=composite_outputs,
                    analysis_snapshot=analysis_snapshot,
                )
            except Exception as db_exc:
                logger.exception("Report registry persist of composite analysis outputs failed (file artifacts are safe)")
                macro_state.step_summaries["db_persist_composite_report_registry"] = {
                    "step": "db_persist_composite_report_registry",
                    "status": "failed",
                    "error": str(db_exc),
                }
        except Exception as exc:
            logger.exception("Composite analysis pipeline failed")
            had_failure = True
            macro_state.step_summaries["composite_analysis_pipeline"] = {
                "step": "composite_analysis_pipeline",
                "status": "failed",
                "error": str(exc),
                "partial_summary": "Composite analysis pipeline failed after analysis snapshot was persisted; "
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


def _persist_analysis_snapshot(
    storage_root: Path,
    run_id: str,
    macro_state: object,
    cme_state: object,
    news_state: object | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Build and write the unified Analysis Snapshot from in-memory pipeline states.

    Returns (written_path, snapshot_dict) so downstream composite analysis can consume
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
    """Persist all composite-analysis agent outputs to DB via idempotent upsert.

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
    composite_outputs: dict[str, Any],
    snapshot_db_id: str | None,
) -> None:
    """Persist composite analysis final result via idempotent upsert."""
    import hashlib

    card = composite_outputs["strategy_card"]
    report_result = composite_outputs["report_result"]
    card_result = composite_outputs["card_result"]
    agents = composite_outputs["agents"]
    gold_runtime_summary = composite_outputs.get("gold_runtime_summary")

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
        "run_summaries": {"gold_runtime_summary": gold_runtime_summary} if isinstance(gold_runtime_summary, dict) else {},
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
