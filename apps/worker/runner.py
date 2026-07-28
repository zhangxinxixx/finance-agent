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
from collections.abc import Callable
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm import sessionmaker

from apps.analysis.snapshots.builder import build_analysis_snapshot, write_analysis_snapshot
from apps.output.context_bundle import load_context_bundle, write_context_bundle
from apps.output.artifacts import artifact_run_dir
from apps.premarket import (
    evaluate_premarket_step_readiness,
    get_premarket_step_contract,
    sort_premarket_steps,
)
from apps.runtime.state_machine import derive_task_run_status, transition_task_run, transition_task_step
from apps.runtime.immutable_artifact import immutable_json_item, write_immutable_artifact_bundle
from apps.runtime.artifact_registry import (
    register_artifact,
    select_canary_terminal_result_for_run,
    select_context_bundle_artifact_for_run,
    select_previous_context_bundle_artifact,
)
from apps.worker.artifact_registration import (
    coerce_lineage_input_snapshot_ids as _coerce_lineage_input_snapshot_ids,
    coerce_lineage_source_refs as _coerce_lineage_source_refs,
    enrich_runner_artifact_metadata as _enrich_runner_artifact_metadata,
    merge_lineage_input_snapshot_ids as _merge_lineage_input_snapshot_ids,
    merge_lineage_source_refs as _merge_lineage_source_refs,
    register_composite_output_artifacts as _register_composite_output_artifacts,
    register_context_bundle_artifact as _register_context_bundle_artifact,
    register_run_support_artifacts as _register_run_support_artifacts,
    register_runner_step_artifacts as _register_runner_step_artifacts,
)
from apps.worker.composite_analysis_pipeline import (
    accepted_coordinator_output as _accepted_coordinator_output,
    run_composite_analysis_pipeline as _run_composite_analysis_pipeline,
)
from apps.worker.composite_state_shadow import (
    CANARY_CONTEXT_MODE,
    LEGACY_CONTEXT_MODE,
    STATE_DELTA_CONTEXT_MODE,
    StateDeltaAnalyzer,
    resolve_analysis_context_mode,
)
from apps.worker.canary_materialization import (
    CanaryActivation,
    CanaryAuthorityPayload,
    CanaryMaterializationRequest,
    CanaryMaterializationResult,
    build_canary_recompute_registry_descriptor,
    failed_canary_materialization_result,
    mark_canary_recompute_result,
    materialize_canary_request,
    prepare_canary_recompute_shadow_input,
    resolve_canary_activation,
)
from apps.analysis.agents.quality_gate import AgentLoopDecision
from apps.analysis.agents.quality_gate_evaluator import QualityGateDecision
from apps.analysis.agents.schemas import AgentOutput
from apps.worker.db_persistence import (
    db_persist_agent_outputs as _db_persist_agent_outputs,
    db_persist_analysis_snapshot as _db_persist_analysis_snapshot,
    db_persist_final_result as _db_persist_final_result,
    ensure_review_items as _ensure_review_items,
    persist_review_items as _persist_review_items,
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
from dagster_finance.ops.premarket_gate import evaluate_premarket_readiness as _evaluate_premarket_readiness
from apps.worker import step_dispatcher as _step_dispatcher
from apps.analysis.agents.quality_gate_evaluator import evaluate_quality_gate
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
from database.queries.canary_approvals import (
    consume_canary_approval,
    load_canary_approval,
)
from database.queries.canary_attempts import (
    CanaryAttemptError,
    authorize_canary_recompute,
    create_or_resume_canary_attempt,
    load_canary_attempt,
    mark_canary_attempt_audit_persisted,
    mark_canary_attempt_terminal,
)

logger = logging.getLogger(__name__)

CME_STEP_NAMES = _step_dispatcher.CME_STEP_NAMES
MACRO_STEP_NAMES = _step_dispatcher.MACRO_STEP_NAMES
NEWS_STEP_NAMES = _step_dispatcher.NEWS_STEP_NAMES
_create_step_dispatch_state = _step_dispatcher.create_step_dispatch_state
_dispatch_premarket_step = _step_dispatcher.dispatch_premarket_step
_has_blocked_upstream_in_same_pipeline = _step_dispatcher.has_blocked_upstream_in_same_pipeline

__all__ = [
    "_coerce_lineage_input_snapshot_ids",
    "_coerce_lineage_source_refs",
    "_enrich_runner_artifact_metadata",
    "_merge_lineage_input_snapshot_ids",
    "_merge_lineage_source_refs",
    "_accepted_coordinator_output",
    "_db_persist_agent_outputs",
    "_db_persist_analysis_snapshot",
    "_db_persist_final_result",
    "_ensure_review_items",
    "_persist_review_items",
    "_register_composite_output_artifacts",
    "_register_composite_report_registry_entries",
    "_register_run_support_artifacts",
    "_register_runner_step_artifacts",
    "_run_composite_analysis_pipeline",
    "_create_step_dispatch_state",
    "_dispatch_premarket_step",
    "_has_blocked_upstream_in_same_pipeline",
    "evaluate_quality_gate",
    "upsert_agent_output",
    "upsert_analysis_snapshot",
    "upsert_final_analysis_result",
    "run_premarket",
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


_STEP_STATUS_SUCCESS = "success"
_STEP_STATUS_SKIPPED = "skipped"
_STEP_STATUS_FAILED = "failed"
_STEP_STATUS_PARTIAL_SUCCESS = "partial_success"
CanaryAttemptSessionFactory = Callable[[], DBSession]


def _canary_attempt_session_factory(db: DBSession) -> CanaryAttemptSessionFactory:
    """Build a truly separate short-session boundary for durable attempt checkpoints."""

    bind = db.get_bind()
    engine: Engine = bind.engine if isinstance(bind, Connection) else bind
    if engine.dialect.name == "sqlite" and str(engine.url.database or "") in {"", ":memory:"}:
        raise CanaryAttemptError("in-memory SQLite cannot provide an independent durable CanaryAttempt transaction")
    return sessionmaker(bind=engine, expire_on_commit=False)


def _durably_start_canary_attempt(
    factory: CanaryAttemptSessionFactory,
    *,
    activation: CanaryActivation,
    attempt_no: int,
    started_at: datetime,
) -> str:
    """Commit started in a short session without touching the Runner transaction."""

    with factory() as attempt_db, attempt_db.begin():
        attempt = create_or_resume_canary_attempt(
            attempt_db,
            run_id=activation.run_id,
            approval_id=activation.approval_id,
            approval_hash=activation.approval_hash,
            attempt_no=attempt_no,
            asset=activation.asset,
            state_scope=activation.state_scope,
            trade_date=activation.trade_date,
            requested_canonical_state_id=activation.canonical_state_id,
            expected_head_version=activation.expected_head_version,
            started_at=started_at,
        )
        attempt_id = attempt.attempt_id
    return attempt_id


def _canary_attempt_root(
    storage_root: Path,
    *,
    trade_date: str,
    run_id: str,
    attempt: int,
    attempt_id: str,
) -> Path:
    if attempt not in {0, 1}:
        raise ValueError("canary attempt must be 0 or 1")
    return (
        artifact_run_dir(
            storage_root,
            layer="outputs",
            domain="analysis_memory_canary",
            date=trade_date,
            run_id=run_id,
        )
        / f"attempt-{attempt}"
        / str(attempt_id)
        / "sandbox"
    )


def _run_canary_sidecar_attempt(
    *,
    storage_root: Path,
    snapshot: dict[str, Any],
    run_id: str,
    created_at: datetime,
    state_shadow_input: dict[str, Any],
    state_delta_analyzer: StateDeltaAnalyzer | None,
    canary_activation: CanaryActivation,
    attempt: int,
    attempt_id: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Run canary consumers in an isolated artifact namespace.

    Only the immutable ContextBundle is copied into the canonical Bundle store;
    report/card and agent artifacts remain sidecars and cannot replace legacy
    official outputs for the TaskRun.
    """

    trade_date = str(snapshot.get("trade_date") or "").strip()
    if not trade_date:
        raise ValueError("canary sidecar requires analysis snapshot trade_date")
    attempt_root = _canary_attempt_root(
        storage_root,
        trade_date=trade_date,
        run_id=run_id,
        attempt=attempt,
        attempt_id=attempt_id,
    )
    summaries, outputs = _run_composite_analysis_pipeline(
        storage_root=attempt_root,
        snapshot=snapshot,
        run_id=run_id,
        created_at=created_at,
        analysis_context_mode=CANARY_CONTEXT_MODE,
        state_shadow_input=state_shadow_input,
        state_delta_analyzer=state_delta_analyzer,
        canary_sidecar_attempt=attempt,
        canary_activation=canary_activation,
    )
    raw_descriptor = outputs.get("context_bundle_registry_artifact")
    if not isinstance(raw_descriptor, dict):
        return summaries, outputs
    sidecar_path = raw_descriptor.get("file_path")
    if not isinstance(sidecar_path, str) or not sidecar_path:
        raise ValueError("canary sidecar Bundle descriptor path is missing")
    bundle = load_context_bundle(
        storage_root=attempt_root,
        storage_relative_path=sidecar_path,
    )
    outputs["context_bundle_registry_artifact"] = write_context_bundle(
        storage_root=storage_root,
        bundle=bundle,
    ).registry_artifact
    outputs["canary_attempt_root"] = attempt_root
    outputs["canary_attempt_number"] = attempt
    outputs["canary_attempt_id"] = attempt_id
    return summaries, outputs


def _resolve_canary_runner_activation(
    db: DBSession,
    *,
    attempt_session_factory: CanaryAttemptSessionFactory,
    storage_root: Path,
    analysis_snapshot: dict[str, Any],
    run_id: str,
    state_shadow_input: dict[str, Any] | None,
    canary_approval_id: str | None,
    now: datetime,
) -> tuple[
    CanaryMaterializationResult | None,
    CanaryActivation | None,
    dict[str, Any] | None,
]:
    """Recover terminal evidence or validate persistent authority before any LLM call."""

    if not isinstance(state_shadow_input, dict):
        raise ValueError("canary sidecar requires state_shadow_input")
    normalized_approval_id = str(canary_approval_id or "").strip()
    if not normalized_approval_id:
        raise ValueError("canary_approval_id is required for canary context")
    forbidden_controls = {
        "canary_trade_dates",
        "canary_run_ids",
        "canary_manual_request",
        "canary_enabled",
    }.intersection(state_shadow_input)
    if forbidden_controls:
        raise ValueError(
            "caller-owned canary activation controls are forbidden: " + ", ".join(sorted(forbidden_controls))
        )
    with attempt_session_factory() as attempt_db:
        attempt0 = load_canary_attempt(attempt_db, run_id=run_id, attempt_no=0)
        attempt1 = load_canary_attempt(attempt_db, run_id=run_id, attempt_no=1)
        checkpoint = attempt1 or attempt0
        if attempt0 is not None:
            attempt_db.expunge(attempt0)
        if checkpoint is not None:
            if checkpoint is not attempt0:
                attempt_db.expunge(checkpoint)
    recovered = select_canary_terminal_result_for_run(
        db,
        run_id=run_id,
        storage_root=storage_root,
    )
    if checkpoint is None and recovered is not None:
        raise ValueError("terminal canary result has no persistent Attempt")
    if checkpoint is not None and recovered is not None:
        if recovered.approval_id != normalized_approval_id:
            raise ValueError("terminal canary approval_id does not match restart request")
        candidate, candidate_hash = _validate_canary_terminal_checkpoint(
            checkpoint,
            recovered=recovered,
            storage_root=storage_root,
            run_id=run_id,
            require_terminal_binding=checkpoint.status == "terminal",
        )
        if checkpoint.status != "terminal":
            with attempt_session_factory() as attempt_db, attempt_db.begin():
                checkpoint = mark_canary_attempt_terminal(
                    attempt_db,
                    attempt_id=checkpoint.attempt_id,
                    terminal_status=recovered.status,
                    artifact_path=str(candidate),
                    artifact_sha256=candidate_hash,
                    updated_at=_now(),
                )
        _validate_canary_terminal_checkpoint(
            checkpoint,
            recovered=recovered,
            storage_root=storage_root,
            run_id=run_id,
            require_terminal_binding=True,
        )
        return recovered, None, None
    recovered_attempt: dict[str, Any] | None = None
    if checkpoint is not None:
        if checkpoint.approval_id != normalized_approval_id:
            raise ValueError("persistent CanaryAttempt approval_id does not match restart request")
        if checkpoint.status == "failed":
            raise ValueError(f"persistent CanaryAttempt failed: {checkpoint.failure_code}")
        if checkpoint.status in {"audit_persisted", "recompute_authorized"}:
            recovered_attempt = _recover_canary_attempt_audit(
                checkpoint,
                storage_root=storage_root,
            )
        elif checkpoint.status == "started":
            recovered_attempt = {
                "attempt_id": checkpoint.attempt_id,
                "attempt_no": checkpoint.attempt_no,
            }
        else:
            raise ValueError("persistent CanaryAttempt is not safely resumable")
        if checkpoint.attempt_no == 1:
            if attempt0 is None or attempt0.status != "recompute_authorized":
                raise ValueError("attempt 1 has no durable recompute predecessor")
            conflict = _reconstruct_canary_recompute_conflict(
                attempt0,
                checkpoint,
                storage_root=storage_root,
            )
            recovered_attempt["conflict_result"] = conflict
            if checkpoint.status == "started":
                recovered_attempt["shadow_input"] = prepare_canary_recompute_shadow_input(
                    db,
                    conflict_result=conflict,
                    shadow_input=state_shadow_input,
                    created_at=now,
                    current_run_id=run_id,
                    storage_root=str(storage_root),
                )

    raw_trade_date = analysis_snapshot.get("trade_date")
    approval_trade_date = (
        raw_trade_date if isinstance(raw_trade_date, date) else date.fromisoformat(str(raw_trade_date))
    )
    approval = load_canary_approval(
        db,
        approval_id=normalized_approval_id,
        asset=str(analysis_snapshot.get("asset") or ""),
        state_scope=str(state_shadow_input.get("state_scope") or ""),
        trade_date=approval_trade_date,
        run_id=run_id,
        now=now,
    )
    activation = resolve_canary_activation(
        snapshot_asset=analysis_snapshot.get("asset"),
        snapshot_trade_date=approval_trade_date,
        run_id=run_id,
        shadow_input=state_shadow_input,
        approval=approval,
    )
    if checkpoint is not None:
        if (
            checkpoint.asset != activation.asset
            or checkpoint.state_scope != activation.state_scope
            or checkpoint.trade_date != activation.trade_date
            or checkpoint.approval_hash != activation.approval_hash
        ):
            raise ValueError("persistent CanaryAttempt authority identity changed")
        activation = activation.model_copy(
            update={
                "canonical_state_id": checkpoint.requested_canonical_state_id,
                "expected_head_version": checkpoint.expected_head_version,
            }
        )
    return None, activation, recovered_attempt


def _validate_canary_terminal_checkpoint(
    checkpoint: Any,
    *,
    recovered: CanaryMaterializationResult,
    storage_root: Path,
    run_id: str,
    require_terminal_binding: bool,
) -> tuple[Path, str]:
    """Bind a recovered terminal payload to its exact Attempt and artifact."""

    payload = recovered.model_dump(mode="json")
    content = (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    expected_path = (
        artifact_run_dir(
            storage_root,
            layer="outputs",
            domain="analysis_memory_canary",
            date=recovered.trade_date.isoformat(),
            run_id=run_id,
        )
        / "terminal-results"
        / f"{digest}.json"
    ).resolve()
    if not expected_path.is_file() or hashlib.sha256(expected_path.read_bytes()).hexdigest() != digest:
        raise ValueError("committed terminal artifact cannot be reconciled")
    expected_attempt_no = recovered.recompute_attempt_count
    expected_identity = {
        "run_id": run_id,
        "attempt_no": expected_attempt_no,
        "asset": recovered.asset,
        "state_scope": recovered.state_scope,
        "trade_date": recovered.trade_date,
        "approval_id": recovered.approval_id,
        "approval_hash": recovered.approval_hash,
        "requested_canonical_state_id": recovered.requested_canonical_state_id,
        "expected_head_version": recovered.expected_head_version,
        "context_bundle_id": recovered.context_bundle_id,
        "context_bundle_hash": recovered.context_bundle_hash,
        "authority_hash": recovered.authority_hash,
    }
    for field, value in expected_identity.items():
        if getattr(checkpoint, field) != value:
            raise ValueError(f"terminal CanaryAttempt identity mismatch: {field}")
    if recovered.run_id != run_id:
        raise ValueError("terminal canary run_id does not match restart request")
    if require_terminal_binding:
        if checkpoint.status != "terminal" or checkpoint.terminal_status != recovered.status:
            raise ValueError("terminal CanaryAttempt lifecycle identity is invalid")
        if (
            Path(str(checkpoint.terminal_artifact_path or "")).resolve() != expected_path
            or checkpoint.terminal_artifact_sha256 != digest
        ):
            raise ValueError("terminal CanaryAttempt artifact binding is invalid")
    return expected_path, digest


def _verify_canary_attempt_audit(attempt: Any, *, storage_root: Path) -> Path:
    """Verify the exact content-addressed audit before a fail-closed recovery."""

    raw_path = str(attempt.audit_artifact_path or "")
    digest = str(attempt.audit_artifact_sha256 or "")
    path = Path(raw_path).resolve()
    root = storage_root.resolve()
    expected = (
        root
        / "outputs"
        / "analysis_memory_canary"
        / attempt.trade_date.isoformat()
        / attempt.run_id
        / f"attempt-{attempt.attempt_no}"
        / attempt.attempt_id
        / f"{digest}.json"
    ).resolve()
    if (
        not raw_path
        or path != expected
        or not path.is_relative_to(root)
        or not path.is_file()
        or hashlib.sha256(path.read_bytes()).hexdigest() != digest
    ):
        raise ValueError("persistent CanaryAttempt audit artifact is invalid")
    return path


def _recover_canary_attempt_audit(attempt: Any, *, storage_root: Path) -> dict[str, Any]:
    """Rehydrate the exact audited authority without another LLM invocation."""

    path = _verify_canary_attempt_audit(attempt, storage_root=storage_root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("persistent CanaryAttempt audit JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError("persistent CanaryAttempt audit payload is invalid")
    if payload.get("schema_version") != "analysis_state_canary_attempt.v2":
        raise ValueError("persistent CanaryAttempt audit schema_version is unsupported")
    raw_agent_loop = payload.get("agent_loop")
    if isinstance(raw_agent_loop, dict):
        raw_agent_loop = dict(raw_agent_loop)
        raw_agent_loop.pop("accepted_outputs", None)
    request = CanaryMaterializationRequest.model_validate(payload.get("materialization_request"))
    if (
        request.run_id != attempt.run_id
        or request.approval_id != attempt.approval_id
        or request.approval_hash != attempt.approval_hash
        or request.context_bundle_id != attempt.context_bundle_id
        or request.context_bundle_hash != attempt.context_bundle_hash
        or request.authority_hash != attempt.authority_hash
    ):
        raise ValueError("persistent CanaryAttempt audit authority is mismatched")
    authority = CanaryAuthorityPayload.model_validate(payload.get("authority_payload"))
    if authority.authority_hash != request.authority_hash:
        raise ValueError("persistent CanaryAttempt authority payload is mismatched")
    consumer_outputs = payload.get("consumer_outputs")
    if not isinstance(consumer_outputs, dict):
        raise ValueError("persistent CanaryAttempt consumer outputs are invalid")
    for agent_name, bound_output in authority.agent_outputs.items():
        raw_output = consumer_outputs.get(agent_name)
        if raw_output is None or AgentOutput.model_validate(raw_output) != bound_output:
            raise ValueError(f"persistent CanaryAttempt consumer output is mismatched: {agent_name}")
    if AgentOutput.model_validate(payload.get("fact_review_output")) != authority.fact_review_output:
        raise ValueError("persistent CanaryAttempt FactReview output is mismatched")
    outputs = {
        "context_bundle_registry_artifact": payload.get("context_bundle"),
        "canary_materialization_request": request,
        "canary_authority_payload": authority,
        "agents": consumer_outputs,
        "post_coordinator_quality_gate_decision": QualityGateDecision.model_validate(payload.get("quality_gate")),
        "agent_loop_decision": AgentLoopDecision.model_validate(raw_agent_loop),
        "canary_attempt_number": attempt.attempt_no,
        "canary_attempt_id": attempt.attempt_id,
        "canary_attempt_audit": {
            "file_path": str(path),
            "sha256": attempt.audit_artifact_sha256,
            "attempt": attempt.attempt_no,
            "attempt_id": attempt.attempt_id,
        },
        "canary_attempt_audit_recovered": True,
    }
    summaries = payload.get("summaries")
    if not isinstance(summaries, dict):
        raise ValueError("persistent CanaryAttempt summaries are invalid")
    return {
        "attempt_id": attempt.attempt_id,
        "attempt_no": attempt.attempt_no,
        "summaries": summaries,
        "outputs": outputs,
    }


def _reconstruct_canary_recompute_conflict(
    predecessor_attempt: Any,
    recompute_attempt: Any,
    *,
    storage_root: Path,
) -> CanaryMaterializationResult:
    predecessor = _recover_canary_attempt_audit(
        predecessor_attempt,
        storage_root=storage_root,
    )
    request = CanaryMaterializationRequest.model_validate(predecessor["outputs"]["canary_materialization_request"])
    return CanaryMaterializationResult(
        status="recompute_required",
        asset=request.asset,
        trade_date=request.trade_date,
        run_id=request.run_id,
        state_scope=request.state_scope,
        approval_id=request.approval_id,
        approval_hash=request.approval_hash,
        activation_source=request.activation_source,
        activation_identity=request.activation_identity,
        context_bundle_id=request.context_bundle_id,
        context_bundle_hash=request.context_bundle_hash,
        requested_canonical_state_id=request.canonical_state_id,
        expected_head_version=request.expected_head_version,
        recompute_required=True,
        latest_canonical_state_id=recompute_attempt.requested_canonical_state_id,
        latest_head_version=recompute_attempt.expected_head_version,
        authority_hash=request.authority_hash,
        attempt_audit_path=predecessor_attempt.audit_artifact_path,
        attempt_audit_sha256=predecessor_attempt.audit_artifact_sha256,
    )


def _failed_terminal_from_durable_attempt(
    factory: CanaryAttemptSessionFactory,
    *,
    run_id: str,
    storage_root: Path,
    reason: str,
) -> tuple[str, CanaryMaterializationResult] | None:
    """Build a failed terminal only when an exact durable audit can authorize it."""

    with factory() as attempt_db:
        attempt0 = load_canary_attempt(attempt_db, run_id=run_id, attempt_no=0)
        attempt1 = load_canary_attempt(attempt_db, run_id=run_id, attempt_no=1)
        checkpoint = attempt1 or attempt0
        if attempt0 is not None:
            attempt_db.expunge(attempt0)
        if checkpoint is not None and checkpoint is not attempt0:
            attempt_db.expunge(checkpoint)
    if checkpoint is None or checkpoint.status not in {
        "audit_persisted",
        "recompute_authorized",
    }:
        return None
    recovered = _recover_canary_attempt_audit(checkpoint, storage_root=storage_root)
    request = CanaryMaterializationRequest.model_validate(recovered["outputs"]["canary_materialization_request"])
    failed = failed_canary_materialization_result(request, reason=reason).model_copy(
        update={
            "attempt_audit_path": checkpoint.audit_artifact_path,
            "attempt_audit_sha256": checkpoint.audit_artifact_sha256,
        }
    )
    if checkpoint.attempt_no == 1:
        if attempt0 is None or attempt0.status != "recompute_authorized":
            return None
        conflict = _reconstruct_canary_recompute_conflict(
            attempt0,
            checkpoint,
            storage_root=storage_root,
        )
        failed = mark_canary_recompute_result(
            failed,
            superseded=conflict,
            trace={
                "failed_attempt_id": checkpoint.attempt_id,
                "failed_after_durable_audit": True,
            },
        )
    return checkpoint.attempt_id, failed


def _json_safe(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _persist_canary_attempt_audit(
    db: DBSession,
    *,
    attempt_session_factory: CanaryAttemptSessionFactory,
    storage_root: Path,
    analysis_snapshot: dict[str, Any],
    run_id: str,
    report_step: Any,
    summaries: dict[str, dict[str, Any]],
    outputs: dict[str, Any],
) -> dict[str, Any]:
    """Seal and register the complete sidecar authority before any CAS write."""

    attempt = outputs.get("canary_attempt_number")
    if isinstance(attempt, bool) or attempt not in {0, 1}:
        raise ValueError("canary audit attempt is invalid")
    attempt_id = str(outputs.get("canary_attempt_id") or "").strip()
    if not attempt_id:
        raise ValueError("canary audit attempt_id is invalid")
    request = CanaryMaterializationRequest.model_validate(outputs.get("canary_materialization_request"))
    authority_payload = outputs.get("canary_authority_payload")
    agents = outputs.get("agents")
    fact_review_output = (
        agents.get("fact_review_agent")
        if isinstance(agents, dict)
        else getattr(authority_payload, "fact_review_output", None)
    )
    trade_date = str(analysis_snapshot.get("trade_date") or request.trade_date.isoformat())
    out_dir = artifact_run_dir(
        storage_root,
        layer="outputs",
        domain="analysis_memory_canary",
        date=trade_date,
        run_id=run_id,
    )
    payload = {
        "schema_version": "analysis_state_canary_attempt.v2",
        "attempt": attempt,
        "attempt_id": attempt_id,
        "run_id": run_id,
        "asset": request.asset,
        "trade_date": request.trade_date.isoformat(),
        "state_scope": request.state_scope,
        "official_output_isolated": True,
        "analysis_snapshot_id": analysis_snapshot.get("snapshot_id"),
        "context_bundle": outputs.get("context_bundle_registry_artifact"),
        "materialization_request": request,
        "authority_payload": authority_payload,
        "consumer_outputs": agents,
        "fact_review_output": fact_review_output,
        "quality_gate": outputs.get("post_coordinator_quality_gate_decision"),
        "agent_loop": outputs.get("agent_loop_decision"),
        "summaries": summaries,
    }
    safe_payload = _json_safe(payload)
    serialized = (
        json.dumps(safe_payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")
    payload_sha256 = hashlib.sha256(serialized).hexdigest()
    audit_path = out_dir / f"attempt-{attempt}" / attempt_id / f"{payload_sha256}.json"
    [written] = write_immutable_artifact_bundle(
        [immutable_json_item(audit_path, safe_payload)],
        storage_root=storage_root,
    )
    if written.content_sha256 != payload_sha256:
        raise ValueError("canary attempt audit content hash mismatch")
    with attempt_session_factory() as attempt_db, attempt_db.begin():
        mark_canary_attempt_audit_persisted(
            attempt_db,
            attempt_id=attempt_id,
            context_bundle_id=request.context_bundle_id,
            context_bundle_hash=request.context_bundle_hash,
            authority_hash=str(request.authority_hash or ""),
            artifact_path=written.target_path,
            artifact_sha256=written.content_sha256,
            updated_at=_now(),
        )
    _register_run_support_artifacts(
        db,
        run_id=run_id,
        steps=[report_step],
        artifacts=[
            {
                "artifact_id": f"{run_id}:analysis_state_canary_attempt:{attempt}:{attempt_id}",
                "artifact_type": "structured_json",
                "file_path": written.target_path,
                "sha256": written.content_sha256,
                "execution_mode": "analysis_state_canary_sidecar",
                "publish_allowed": False,
                "output_mode": "canary",
            }
        ],
        source_refs=_coerce_lineage_source_refs(analysis_snapshot.get("source_refs")),
        input_snapshot_ids=_coerce_lineage_input_snapshot_ids(analysis_snapshot.get("input_snapshot_ids")),
    )
    descriptor = {
        "artifact_id": f"{run_id}:analysis_state_canary_attempt:{attempt}:{attempt_id}",
        "file_path": written.target_path,
        "sha256": written.content_sha256,
        "attempt": attempt,
        "attempt_id": attempt_id,
    }
    outputs["canary_attempt_audit"] = descriptor
    return descriptor


def _persist_canary_terminal_result(
    db: DBSession,
    *,
    storage_root: Path,
    run_id: str,
    report_step: Any,
    result: CanaryMaterializationResult,
) -> dict[str, Any]:
    """Persist the terminal outcome in the same transaction as scoped CAS."""

    if result.status == "recompute_required":
        raise ValueError("recompute_required is not a terminal canary outcome")
    out_dir = artifact_run_dir(
        storage_root,
        layer="outputs",
        domain="analysis_memory_canary",
        date=result.trade_date.isoformat(),
        run_id=run_id,
    )
    result_payload = result.model_dump(mode="json")
    serialized = (
        json.dumps(
            result_payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    payload_sha256 = hashlib.sha256(serialized).hexdigest()
    target = out_dir / "terminal-results" / f"{payload_sha256}.json"
    [written] = write_immutable_artifact_bundle(
        [immutable_json_item(target, result_payload)],
        storage_root=storage_root,
    )
    registry_id = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"finance-agent:analysis-state-canary-terminal:{run_id}",
    )
    row = register_artifact(
        db,
        run_id=run_id,
        step=report_step,
        artifact_id=f"{run_id}:analysis_state_canary_terminal",
        artifact_type="structured_json",
        file_path=written.target_path,
        sha256=written.content_sha256,
        content_type="application/json",
        metadata={
            "artifact_family": "analysis_state_canary_terminal",
            "status": result.status,
            "recompute_attempt_count": result.recompute_attempt_count,
            "context_bundle_id": result.context_bundle_id,
            "authority_hash": result.authority_hash,
        },
        registry_artifact_id=registry_id,
        require_canonical_path=False,
    )
    if row is None or row.artifact_id != registry_id or row.sha256 != written.content_sha256:
        raise ValueError("canary terminal outcome registry identity mismatch")
    metadata = row.artifact_metadata or {}
    if metadata.get("artifact_family") != "analysis_state_canary_terminal":
        raise ValueError("canary terminal outcome registry metadata mismatch")
    return {
        "artifact_id": str(row.artifact_id),
        "file_path": written.target_path,
        "sha256": written.content_sha256,
        "status": result.status,
    }


def _materialize_canary_attempt(
    db: DBSession,
    *,
    request: CanaryMaterializationRequest,
    composite_outputs: dict[str, Any],
    run_id: str,
    snapshot_db_id: str | None,
) -> CanaryMaterializationResult:
    if snapshot_db_id is None:
        return failed_canary_materialization_result(
            request,
            reason="analysis_snapshot_db_id_unavailable",
        )
    registry_status = composite_outputs.get("context_bundle_registry_status")
    if not isinstance(registry_status, dict) or registry_status.get("status") != "registered":
        return failed_canary_materialization_result(
            request,
            reason="context_bundle_registry_not_authoritative",
        )
    if registry_status.get("bundle_id") != request.context_bundle_id:
        return failed_canary_materialization_result(
            request,
            reason="context_bundle_registry_identity_mismatch",
        )
    result = materialize_canary_request(
        db,
        request=request,
        quality_gate=composite_outputs["post_coordinator_quality_gate_decision"],
        agent_loop=composite_outputs["agent_loop_decision"],
        task_run_id=run_id,
        analysis_snapshot_db_id=snapshot_db_id,
        authority_payload=composite_outputs.get("canary_authority_payload"),
    )
    audit = composite_outputs.get("canary_attempt_audit")
    if isinstance(audit, dict):
        audit_path = str(audit.get("file_path") or "").strip()
        audit_sha256 = str(audit.get("sha256") or "").strip()
        if audit_path and len(audit_sha256) == 64:
            result = result.model_copy(
                update={
                    "attempt_audit_path": audit_path,
                    "attempt_audit_sha256": audit_sha256,
                }
            )
    return result


def _consume_canary_recompute_once(
    db: DBSession,
    *,
    conflict_result: CanaryMaterializationResult,
    analysis_snapshot: dict[str, Any],
    run_id: str,
    storage_root: Path,
    created_at: datetime,
    state_shadow_input: dict[str, Any],
    state_delta_analyzer: StateDeltaAnalyzer | None,
    canary_activation: CanaryActivation,
    report_step: Any,
    snapshot_db_id: str | None,
    attempt_session_factory: CanaryAttemptSessionFactory,
    superseded_attempt_id: str,
) -> CanaryMaterializationResult:
    """Run one complete fresh-Bundle canary attempt after a scoped CAS conflict."""

    refreshed_input = prepare_canary_recompute_shadow_input(
        db,
        conflict_result=conflict_result,
        shadow_input=state_shadow_input,
        created_at=created_at,
        current_run_id=run_id,
        storage_root=str(storage_root),
    )
    refreshed_activation = canary_activation.model_copy(
        update={
            "canonical_state_id": refreshed_input["canonical_state_id"],
            "expected_head_version": refreshed_input["expected_head_version"],
        }
    )
    with attempt_session_factory() as attempt_db, attempt_db.begin():
        authorize_canary_recompute(
            attempt_db,
            attempt_id=superseded_attempt_id,
            updated_at=_now(),
        )
        fresh_attempt = create_or_resume_canary_attempt(
            attempt_db,
            run_id=refreshed_activation.run_id,
            approval_id=refreshed_activation.approval_id,
            approval_hash=refreshed_activation.approval_hash,
            attempt_no=1,
            asset=refreshed_activation.asset,
            state_scope=refreshed_activation.state_scope,
            trade_date=refreshed_activation.trade_date,
            requested_canonical_state_id=refreshed_activation.canonical_state_id,
            expected_head_version=refreshed_activation.expected_head_version,
            started_at=_now(),
        )
        fresh_attempt_id = fresh_attempt.attempt_id
    fresh_summaries, fresh_outputs = _run_canary_sidecar_attempt(
        storage_root=storage_root,
        snapshot=analysis_snapshot,
        run_id=run_id,
        created_at=created_at,
        state_shadow_input=refreshed_input,
        state_delta_analyzer=state_delta_analyzer,
        canary_activation=refreshed_activation,
        attempt=1,
        attempt_id=fresh_attempt_id,
    )
    raw_descriptor = fresh_outputs.get("context_bundle_registry_artifact")
    if not isinstance(raw_descriptor, dict):
        return _failed_canary_recompute_result(
            conflict_result,
            reason="fresh_context_bundle_descriptor_missing",
        )
    descriptor = build_canary_recompute_registry_descriptor(
        raw_descriptor,
        conflict_result=conflict_result,
    )
    row = _register_context_bundle_artifact(
        db,
        run_id=run_id,
        step=report_step,
        descriptor=descriptor,
        storage_root=storage_root,
        allow_canary_recompute=True,
    )
    if row is None:
        return _failed_canary_recompute_result(
            conflict_result,
            reason="fresh_context_bundle_registry_unavailable",
        )
    fresh_outputs["context_bundle_registry_status"] = {
        "status": "registered",
        "bundle_id": descriptor["metadata"]["bundle_id"],
    }
    raw_request = fresh_outputs.get("canary_materialization_request")
    if raw_request is None:
        return _failed_canary_recompute_result(
            conflict_result,
            reason="fresh_canary_attempt_not_authoritative",
            descriptor=descriptor,
        )
    fresh_request = CanaryMaterializationRequest.model_validate(raw_request)
    _persist_canary_attempt_audit(
        db,
        attempt_session_factory=attempt_session_factory,
        storage_root=storage_root,
        analysis_snapshot=analysis_snapshot,
        run_id=run_id,
        report_step=report_step,
        summaries=fresh_summaries,
        outputs=fresh_outputs,
    )
    fresh_result = _materialize_canary_attempt(
        db,
        request=fresh_request,
        composite_outputs=fresh_outputs,
        run_id=run_id,
        snapshot_db_id=snapshot_db_id,
    )
    return mark_canary_recompute_result(
        fresh_result,
        superseded=conflict_result,
        trace={
            "fresh_context_bundle_id": fresh_request.context_bundle_id,
            "fresh_context_bundle_hash": fresh_request.context_bundle_hash,
            "fresh_consumer_projection_hashes": dict(fresh_request.consumer_projection_hashes),
            "fresh_fact_review_snapshot_id": fresh_request.fact_review_snapshot_id,
            "fresh_quality_gate_hash": fresh_request.quality_gate_hash,
            "fresh_agent_loop_hash": fresh_request.agent_loop_hash,
            "fresh_attempt_audit": fresh_outputs["canary_attempt_audit"],
            "superseded_attempt_audit": {
                "file_path": conflict_result.attempt_audit_path,
                "sha256": conflict_result.attempt_audit_sha256,
            },
        },
    )


def _failed_canary_recompute_result(
    conflict_result: CanaryMaterializationResult,
    *,
    reason: str,
    descriptor: dict[str, Any] | None = None,
) -> CanaryMaterializationResult:
    metadata = descriptor.get("metadata") if isinstance(descriptor, dict) else None
    payload = {
        **conflict_result.model_dump(mode="json"),
        "status": "failed",
        "recompute_required": False,
        "recompute_attempt_count": 1,
        "superseded_context_bundle_id": conflict_result.context_bundle_id,
        "superseded_context_bundle_hash": conflict_result.context_bundle_hash,
        "superseded_canonical_state_id": conflict_result.requested_canonical_state_id,
        "context_bundle_id": (
            str(metadata.get("bundle_id")) if isinstance(metadata, dict) else conflict_result.context_bundle_id
        ),
        "context_bundle_hash": (
            str(metadata.get("content_hash")) if isinstance(metadata, dict) else conflict_result.context_bundle_hash
        ),
        "requested_canonical_state_id": (
            str(metadata.get("canonical_state_id"))
            if isinstance(metadata, dict)
            else conflict_result.latest_canonical_state_id or conflict_result.requested_canonical_state_id
        ),
        "expected_head_version": conflict_result.latest_head_version or conflict_result.expected_head_version,
        "reason": str(reason)[:200],
        "recompute_trace": {"status": "failed", "reason": str(reason)[:200]},
    }
    return CanaryMaterializationResult.model_validate(payload)


def run_premarket(
    db: DBSession,
    task_id: uuid.UUID,
    *,
    storage_root: Path = Path("./storage"),
    product: str = "OG",
    analysis_context_mode: str | None = None,
    state_shadow_input: dict[str, Any] | None = None,
    state_delta_analyzer: StateDeltaAnalyzer | None = None,
    canary_approval_id: str | None = None,
    canary_attempt_session_factory: CanaryAttemptSessionFactory | None = None,
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

    run_id = str(task_id)
    step_dispatch_state = _create_step_dispatch_state()
    cme_state = step_dispatch_state.cme
    macro_state = step_dispatch_state.macro
    news_state = step_dispatch_state.news
    source_status_index = _load_premarket_source_status_index()

    ordered_steps = sort_premarket_steps(task.steps)

    had_failure = False
    had_degraded_readiness = False
    had_partial_summary = False
    had_non_failed_step = False
    terminal_attempt_reconciliation: tuple[str, dict[str, Any], str] | None = None

    for idx, step in enumerate(ordered_steps):
        # ── P4-03: record step_order and input context ─────────────────
        step.step_order = idx
        step.input_json = json.dumps(
            {"run_id": run_id, "step_name": step.name, "step_order": idx},
            ensure_ascii=False,
            default=str,
        )
        # ── T1.6: compute input_hash for idempotency ────────────────
        step.input_hash = hashlib.sha256(step.input_json.encode("utf-8")).hexdigest()
        step.retry_count = 0

        # ── T1.4: check upstream failure/blocking → block this step ──────
        # Only block steps within the SAME pipeline as the failed/blocked step.
        # CME, Macro, and News pipelines are independent; "other" steps are never blocked here.
        if _has_blocked_upstream_in_same_pipeline(ordered_steps, idx):
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
            summary = _dispatch_premarket_step(
                db=db,
                step_name=step.name,
                state=step_dispatch_state,
                storage_root=storage_root,
                run_id=run_id,
                product=product,
            )

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
        analysis_snapshot_path, analysis_snapshot = _persist_analysis_snapshot(
            storage_root,
            run_id,
            macro_state,
            cme_state,
            news_state,
            analysis_context_date=task.trade_date,
        )
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
        pre_analysis_gate = _load_pre_analysis_gate(storage_root=storage_root, analysis_snapshot=analysis_snapshot)
        if _pre_analysis_gate_blocks(pre_analysis_gate):
            had_partial_summary = True
            blocked_outputs = (
                pre_analysis_gate.get("blocked_outputs")
                if isinstance(pre_analysis_gate.get("blocked_outputs"), list)
                else []
            )
            macro_state.step_summaries["pre_analysis_gate"] = {
                "step": "pre_analysis_gate",
                "status": "blocked",
                "decision": pre_analysis_gate.get("decision"),
                "reason_code": pre_analysis_gate.get("reason_code"),
                "source_ref": pre_analysis_gate.get("source_ref"),
                "blocked_outputs": blocked_outputs,
            }
            macro_state.step_summaries["composite_analysis_pipeline"] = {
                "step": "composite_analysis_pipeline",
                "status": "blocked",
                "reason": "pre_analysis_gate_blocked",
                "blocked_outputs": blocked_outputs,
                "partial_summary": "Composite analysis was blocked by pre_analysis_gate; no final report or strategy card was written.",
            }
        else:
            if pre_analysis_gate:
                macro_state.step_summaries["pre_analysis_gate"] = {
                    "step": "pre_analysis_gate",
                    "status": "success",
                    "decision": pre_analysis_gate.get("decision"),
                    "source_ref": pre_analysis_gate.get("source_ref"),
                }
            try:
                composite_created_at = datetime.now(timezone.utc)
                resolved_shadow_input = state_shadow_input
                if resolve_analysis_context_mode(analysis_context_mode) in {
                    STATE_DELTA_CONTEXT_MODE,
                    CANARY_CONTEXT_MODE,
                }:
                    resolved_shadow_input = _resolve_state_shadow_registry_inputs(
                        db=db,
                        run_id=run_id,
                        storage_root=storage_root,
                        state_shadow_input=state_shadow_input,
                    )
                context_mode = resolve_analysis_context_mode(analysis_context_mode)
                canary_summaries: dict[str, dict[str, Any]] = {}
                canary_outputs: dict[str, Any] | None = None
                canary_setup_error: str | None = None
                recovered_canary_result: CanaryMaterializationResult | None = None
                canary_activation: CanaryActivation | None = None
                canary_attempt_factory: CanaryAttemptSessionFactory | None = None
                canary_attempt_id: str | None = None
                canary_attempt_recovery: dict[str, Any] | None = None
                if context_mode == CANARY_CONTEXT_MODE:
                    try:
                        canary_attempt_factory = canary_attempt_session_factory or _canary_attempt_session_factory(db)
                        recovered_canary_result, canary_activation, canary_attempt_recovery = (
                            _resolve_canary_runner_activation(
                                db,
                                attempt_session_factory=canary_attempt_factory,
                                storage_root=storage_root,
                                analysis_snapshot=analysis_snapshot,
                                run_id=run_id,
                                state_shadow_input=resolved_shadow_input,
                                canary_approval_id=canary_approval_id,
                                now=composite_created_at,
                            )
                        )
                    except Exception as canary_exc:
                        logger.exception("AnalysisState canary approval failed; legacy output remains authoritative")
                        canary_setup_error = f"{type(canary_exc).__name__}:canary_approval_failed"
                    composite_summaries, composite_outputs = _run_composite_analysis_pipeline(
                        storage_root=storage_root,
                        snapshot=analysis_snapshot,
                        run_id=run_id,
                        created_at=composite_created_at,
                        analysis_context_mode=LEGACY_CONTEXT_MODE,
                    )
                    if canary_setup_error is None and recovered_canary_result is None:
                        try:
                            if canary_activation is None:  # pragma: no cover - approval boundary
                                raise ValueError("validated canary activation is unavailable")
                            if canary_attempt_recovery is not None:
                                canary_attempt_id = str(canary_attempt_recovery["attempt_id"])
                                recovered_outputs = canary_attempt_recovery.get("outputs")
                                recovered_summaries = canary_attempt_recovery.get("summaries")
                                if isinstance(recovered_outputs, dict) and isinstance(recovered_summaries, dict):
                                    canary_outputs = recovered_outputs
                                    canary_summaries = recovered_summaries
                                else:
                                    resume_attempt = int(canary_attempt_recovery["attempt_no"])
                                    resume_shadow = canary_attempt_recovery.get("shadow_input", resolved_shadow_input)
                                    canary_summaries, canary_outputs = _run_canary_sidecar_attempt(
                                        storage_root=storage_root,
                                        snapshot=analysis_snapshot,
                                        run_id=run_id,
                                        created_at=composite_created_at,
                                        state_shadow_input=resume_shadow,
                                        state_delta_analyzer=state_delta_analyzer,
                                        canary_activation=canary_activation,
                                        attempt=resume_attempt,
                                        attempt_id=canary_attempt_id,
                                    )
                            else:
                                canary_attempt_id = _durably_start_canary_attempt(
                                    canary_attempt_factory,
                                    activation=canary_activation,
                                    attempt_no=0,
                                    started_at=composite_created_at,
                                )
                                canary_summaries, canary_outputs = _run_canary_sidecar_attempt(
                                    storage_root=storage_root,
                                    snapshot=analysis_snapshot,
                                    run_id=run_id,
                                    created_at=composite_created_at,
                                    state_shadow_input=resolved_shadow_input,
                                    state_delta_analyzer=state_delta_analyzer,
                                    canary_activation=canary_activation,
                                    attempt=0,
                                    attempt_id=canary_attempt_id,
                                )
                        except Exception as canary_exc:
                            logger.exception("AnalysisState canary sidecar failed; legacy output remains authoritative")
                            canary_setup_error = f"{type(canary_exc).__name__}:canary_sidecar_failed"
                else:
                    composite_summaries, composite_outputs = _run_composite_analysis_pipeline(
                        storage_root=storage_root,
                        snapshot=analysis_snapshot,
                        run_id=run_id,
                        created_at=composite_created_at,
                        analysis_context_mode=analysis_context_mode,
                        state_shadow_input=resolved_shadow_input,
                        state_delta_analyzer=state_delta_analyzer,
                    )
                macro_state.step_summaries.update(composite_summaries)
                if recovered_canary_result is not None:
                    macro_state.step_summaries["analysis_state_canary"] = {
                        "step": "analysis_state_canary",
                        **recovered_canary_result.model_dump(mode="json"),
                        "recovered_terminal_outcome": True,
                    }
                elif canary_setup_error is not None:
                    macro_state.step_summaries["analysis_state_canary"] = {
                        "step": "analysis_state_canary",
                        "status": "failed",
                        "reason": canary_setup_error,
                        "legacy_output_preserved": True,
                    }
                elif canary_outputs is not None:
                    canary_trace = canary_outputs.get("state_delta_shadow")
                    macro_state.step_summaries["analysis_state_canary_sidecar"] = {
                        "step": "analysis_state_canary_sidecar",
                        "status": "success",
                        "legacy_output_preserved": True,
                        "official_output_isolated": True,
                        "shadow_status": (canary_trace.get("status") if isinstance(canary_trace, dict) else None),
                        "domain_status": canary_summaries.get("domain_agents", {}).get("status"),
                    }

                # DB sink: persist agent outputs (additive, after file writes)
                snapshot_db_id: str | None = None
                try:
                    snapshot_db_id = _db_persist_agent_outputs(
                        db, analysis_snapshot, composite_outputs["agents"], run_id
                    )
                    shadow_reviews = (
                        composite_outputs.get("state_delta_shadow", {}).get("review_items", [])
                        if isinstance(composite_outputs.get("state_delta_shadow"), dict)
                        else []
                    )
                    _persist_review_items(db, shadow_reviews)
                    agent_loop_decision = composite_outputs.get("agent_loop_decision")
                    publish_allowed = bool(getattr(agent_loop_decision, "publish_allowed", False))
                    if publish_allowed:
                        _db_persist_final_result(db, analysis_snapshot, composite_outputs, snapshot_db_id)
                    else:
                        _ensure_review_items(
                            db,
                            run_id=run_id,
                            trade_date=str(analysis_snapshot.get("trade_date") or ""),
                            card=composite_outputs["strategy_card"],
                            agents=composite_outputs["agents"],
                        )
                        macro_state.step_summaries["db_persist_observation"] = {
                            "step": "db_persist_observation",
                            "status": "needs_review",
                            "publish_allowed": False,
                            "output_mode": "observe",
                            "reason_codes": list(getattr(agent_loop_decision, "reasons", []) or []),
                        }
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
                    storage_root=storage_root,
                )
                canary_materialization_outputs = canary_outputs or composite_outputs
                if canary_outputs is not None:
                    raw_canary_descriptor = canary_outputs.get("context_bundle_registry_artifact")
                    if isinstance(raw_canary_descriptor, dict):
                        report_step = next(
                            (step for step in ordered_steps if step.name == "report_render"),
                            None,
                        )
                        if report_step is not None:
                            try:
                                bundle_row = _register_context_bundle_artifact(
                                    db,
                                    run_id=run_id,
                                    step=report_step,
                                    descriptor=raw_canary_descriptor,
                                    storage_root=storage_root,
                                )
                                canary_outputs["context_bundle_registry_status"] = {
                                    "status": ("registered" if bundle_row is not None else "skipped_unavailable"),
                                    "bundle_id": (raw_canary_descriptor.get("metadata") or {}).get("bundle_id"),
                                }
                            except Exception as registry_exc:
                                logger.exception("Canary ContextBundle registry failed; legacy output remains valid")
                                canary_outputs["context_bundle_registry_status"] = {
                                    "status": "failed",
                                    "bundle_id": (raw_canary_descriptor.get("metadata") or {}).get("bundle_id"),
                                    "reason": (f"{type(registry_exc).__name__}:{str(registry_exc)[:200]}"),
                                }
                bundle_registry_status = canary_materialization_outputs.get("context_bundle_registry_status")
                if isinstance(bundle_registry_status, dict):
                    macro_state.step_summaries["context_bundle_registry"] = {
                        "step": "context_bundle_registry",
                        **bundle_registry_status,
                    }
                raw_canary_request = canary_materialization_outputs.get("canary_materialization_request")
                if raw_canary_request is not None:
                    canary_result: CanaryMaterializationResult
                    validated_canary_request = CanaryMaterializationRequest.model_validate(raw_canary_request)
                    try:
                        report_step = next(
                            (step for step in ordered_steps if step.name == "report_render"),
                            None,
                        )
                        if report_step is None:
                            raise ValueError("canary report step is unavailable")
                        with db.begin_nested():
                            if canary_attempt_factory is None or canary_attempt_id is None:
                                raise ValueError("durable canary attempt identity is unavailable")
                            if not canary_materialization_outputs.get("canary_attempt_audit_recovered"):
                                _persist_canary_attempt_audit(
                                    db,
                                    attempt_session_factory=canary_attempt_factory,
                                    storage_root=storage_root,
                                    analysis_snapshot=analysis_snapshot,
                                    run_id=run_id,
                                    report_step=report_step,
                                    summaries=canary_summaries,
                                    outputs=canary_materialization_outputs,
                                )
                            canary_result = _materialize_canary_attempt(
                                db,
                                request=validated_canary_request,
                                composite_outputs=canary_materialization_outputs,
                                run_id=run_id,
                                snapshot_db_id=snapshot_db_id,
                            )
                            recovered_conflict = (
                                canary_attempt_recovery.get("conflict_result")
                                if isinstance(canary_attempt_recovery, dict)
                                else None
                            )
                            if isinstance(recovered_conflict, CanaryMaterializationResult):
                                canary_result = mark_canary_recompute_result(
                                    canary_result,
                                    superseded=recovered_conflict,
                                    trace={
                                        "recovered_attempt_id": canary_attempt_id,
                                        "recovered_after_started": True,
                                    },
                                )
                            if canary_result.status == "recompute_required":
                                if not isinstance(state_shadow_input, dict):
                                    canary_result = failed_canary_materialization_result(
                                        validated_canary_request,
                                        reason="canary_recompute_shadow_input_unavailable",
                                    )
                                else:
                                    canary_result = _consume_canary_recompute_once(
                                        db,
                                        conflict_result=canary_result,
                                        analysis_snapshot=analysis_snapshot,
                                        run_id=run_id,
                                        storage_root=storage_root,
                                        created_at=composite_created_at,
                                        state_shadow_input=state_shadow_input,
                                        state_delta_analyzer=state_delta_analyzer,
                                        canary_activation=canary_activation,
                                        report_step=report_step,
                                        snapshot_db_id=snapshot_db_id,
                                        attempt_session_factory=canary_attempt_factory,
                                        superseded_attempt_id=canary_attempt_id,
                                    )
                            if canary_result.status == "canonical_advanced":
                                consume_canary_approval(
                                    db,
                                    approval_id=validated_canary_request.approval_id,
                                    expected_approval_hash=validated_canary_request.approval_hash,
                                    run_id=run_id,
                                    consumed_at=_now(),
                                )
                            terminal_descriptor = _persist_canary_terminal_result(
                                db,
                                storage_root=storage_root,
                                run_id=run_id,
                                report_step=report_step,
                                result=canary_result,
                            )
                            terminal_attempt_reconciliation = (
                                (
                                    str(canary_materialization_outputs.get("canary_attempt_id") or canary_attempt_id)
                                    if canary_result.recompute_attempt_count == 0
                                    else str(
                                        uuid.uuid5(
                                            uuid.NAMESPACE_URL,
                                            f"finance-agent:analysis-state-canary-attempt:{run_id}:1",
                                        )
                                    )
                                ),
                                terminal_descriptor,
                                canary_result.status,
                            )
                    except Exception as canary_exc:
                        logger.exception("Canary runner integration failed; legacy output remains valid")
                        canary_result = failed_canary_materialization_result(
                            validated_canary_request,
                            reason=f"{type(canary_exc).__name__}:canary_runner_integration_failed",
                        )
                        terminal_descriptor = None
                        try:
                            durable_failed_terminal = (
                                _failed_terminal_from_durable_attempt(
                                    canary_attempt_factory,
                                    run_id=run_id,
                                    storage_root=storage_root,
                                    reason=(f"{type(canary_exc).__name__}:canary_runner_integration_failed"),
                                )
                                if canary_attempt_factory is not None
                                else None
                            )
                        except Exception:
                            logger.exception("Canary failure has no valid durable audit checkpoint")
                            durable_failed_terminal = None
                        if durable_failed_terminal is not None:
                            failed_attempt_id, canary_result = durable_failed_terminal
                            try:
                                with db.begin_nested():
                                    terminal_descriptor = _persist_canary_terminal_result(
                                        db,
                                        storage_root=storage_root,
                                        run_id=run_id,
                                        report_step=report_step,
                                        result=canary_result,
                                    )
                                    terminal_attempt_reconciliation = (
                                        failed_attempt_id,
                                        terminal_descriptor,
                                        canary_result.status,
                                    )
                            except Exception:
                                logger.exception("Failed to persist audit-bound canary terminal outcome")
                    macro_state.step_summaries["analysis_state_canary"] = {
                        "step": "analysis_state_canary",
                        **canary_result.model_dump(mode="json"),
                        "terminal_outcome_artifact": terminal_descriptor,
                    }
                if bool(getattr(composite_outputs.get("agent_loop_decision"), "publish_allowed", False)):
                    try:
                        _register_composite_report_registry_entries(
                            db,
                            run_id=run_id,
                            composite_outputs=composite_outputs,
                            analysis_snapshot=analysis_snapshot,
                        )
                    except Exception as db_exc:
                        logger.exception(
                            "Report registry persist of composite analysis outputs failed (file artifacts are safe)"
                        )
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
    if terminal_attempt_reconciliation is not None:
        attempt_id, descriptor, terminal_status = terminal_attempt_reconciliation
        factory = canary_attempt_session_factory or _canary_attempt_session_factory(db)
        try:
            with factory() as attempt_db, attempt_db.begin():
                mark_canary_attempt_terminal(
                    attempt_db,
                    attempt_id=attempt_id,
                    terminal_status=terminal_status,
                    artifact_path=str(descriptor["file_path"]),
                    artifact_sha256=str(descriptor["sha256"]),
                    updated_at=_now(),
                )
        except Exception:
            logger.exception("Canary terminal transaction committed but Attempt reconciliation failed")
    return final_status


def _resolve_state_shadow_registry_inputs(
    *,
    db: DBSession,
    run_id: str,
    storage_root: Path,
    state_shadow_input: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Resolve restart/prior Bundle authority from RunArtifact, never a path scan."""

    if state_shadow_input is None:
        return None
    resolved = dict(state_shadow_input)
    for field in (
        "context_bundle_artifact",
        "previous_context_bundle_artifact",
        "previous_bundle_path",
    ):
        resolved.pop(field, None)

    same_run = select_context_bundle_artifact_for_run(
        db,
        run_id=run_id,
        storage_root=storage_root,
    )
    if same_run is not None:
        resolved["context_bundle_artifact"] = same_run
        return resolved

    canonical_state = resolved.get("canonical_state")
    asset = str(canonical_state.get("asset") or "").strip() if isinstance(canonical_state, dict) else ""
    state_scope = str(resolved.get("state_scope") or "").strip()
    canonical_state_id = str(resolved.get("canonical_state_id") or "").strip()
    if not all((asset, state_scope, canonical_state_id)):
        return resolved
    previous = select_previous_context_bundle_artifact(
        db,
        current_run_id=run_id,
        asset=asset,
        state_scope=state_scope,
        canonical_state_id=canonical_state_id,
        cutoff_at=_optional_aware_datetime(resolved.get("cutoff_at")),
        storage_root=storage_root,
    )
    if previous is not None:
        for field in (
            "previous_semantic_hashes",
            "deferred_queue",
            "processed_above_frontier",
            "freshness_sla_seconds",
            "default_freshness_sla_seconds",
        ):
            resolved.pop(field, None)
        resolved["previous_context_bundle_artifact"] = previous
    return resolved


def _optional_aware_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("state shadow cutoff_at must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _load_pre_analysis_gate(*, storage_root: Path, analysis_snapshot: dict[str, Any]) -> dict[str, Any]:
    trade_date = str(analysis_snapshot.get("trade_date") or "")
    if not trade_date:
        return {
            "decision": "block",
            "reason_code": "analysis_snapshot_trade_date_missing",
            "blocked_outputs": ["full analysis", "knowledge distillation"],
        }

    legacy_gate = _load_legacy_pre_analysis_gate(storage_root=storage_root, trade_date=trade_date)
    if _pre_analysis_gate_blocks(legacy_gate):
        return legacy_gate

    readiness_gate = _evaluate_premarket_readiness(
        storage_root=storage_root,
        trade_date=trade_date,
        observed_at=datetime.now(timezone.utc),
    )
    if _pre_analysis_gate_blocks(readiness_gate):
        return readiness_gate
    if legacy_gate:
        return {**legacy_gate, "readiness_gate": readiness_gate}
    return readiness_gate


def _load_legacy_pre_analysis_gate(*, storage_root: Path, trade_date: str) -> dict[str, Any]:
    date_root = storage_root / "orchestration" / trade_date
    compatibility_gate = _read_json_dict(date_root / "pre_analysis_gate.json")
    if compatibility_gate:
        return compatibility_gate

    latest = _read_json_dict(date_root / "latest.json")
    if str(latest.get("trade_date") or "") != trade_date:
        return {}
    artifacts = latest.get("artifacts")
    source_ref = artifacts.get("pre_analysis_gate") if isinstance(artifacts, dict) else None
    if not isinstance(source_ref, str) or not source_ref:
        return {}
    relative_path = Path(source_ref)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        return {}
    return _read_json_dict(storage_root / relative_path)


def _read_json_dict(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _pre_analysis_gate_blocks(gate: dict[str, Any]) -> bool:
    return gate.get("decision") == "block"


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
    *,
    analysis_context_date: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Build and write the unified Analysis Snapshot from in-memory pipeline states.

    Returns (written_path, snapshot_dict) so downstream composite analysis can consume
    the snapshot without re-reading from disk.
    """

    macro_snapshot = getattr(macro_state, "snapshot_dict", None)
    options_snapshot = getattr(cme_state, "snapshot_dict", None)
    trade_date = _resolve_analysis_trade_date(
        macro_snapshot,
        options_snapshot,
        analysis_context_date=analysis_context_date,
    )
    source_refs = list(getattr(macro_state, "all_source_refs", []) or [])
    source_refs.extend(_cme_source_refs(cme_state))
    source_refs.extend(getattr(news_state, "source_refs", []) or [])
    collected_points = [p.to_dict() for p in getattr(macro_state, "all_points", [])]
    news_snapshot = getattr(news_state, "snapshot_dict", None) if news_state is not None else None
    from apps.analysis.jin10.daily_context import build_daily_analysis_context

    gold_analysis_context = build_daily_analysis_context(
        trade_date=trade_date,
        storage_root=storage_root,
        asset="XAUUSD",
        preferred_run_id=run_id,
    )

    snapshot = build_analysis_snapshot(
        asset="XAUUSD",
        trade_date=trade_date,
        run_id=run_id,
        macro_snapshot=macro_snapshot,
        options_snapshot=options_snapshot,
        source_refs=source_refs,
        collected_points=collected_points,
        news_snapshot=news_snapshot,
        gold_analysis_context=gold_analysis_context,
    )
    path = write_analysis_snapshot(snapshot, storage_root=storage_root)
    return path, snapshot


def _resolve_analysis_trade_date(
    macro_snapshot: dict[str, Any] | None,
    options_snapshot: dict[str, Any] | None,
    *,
    analysis_context_date: str | None = None,
) -> str:
    """Resolve the analysis context date, preferring the task's explicit date."""

    if analysis_context_date and analysis_context_date.strip():
        return analysis_context_date.strip()
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
