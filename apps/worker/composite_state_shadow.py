"""Observe-only state+delta shadow support for the composite pipeline."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Literal

from pydantic import BaseModel

from apps.analysis.context_bundle import AnalysisContextBundle, assemble_context_bundle
from apps.analysis.evidence_delta import EvidenceDeltaDecision, RecommendedAction, adapt_figure_fact
from apps.analysis.figure_facts import project_confirmed_evidence
from apps.analysis.state import (
    ANALYSIS_STATE_MACHINE_VERSION,
    AnalysisStateDocumentV1,
    AnalysisStateDocumentV11,
    StateScope,
    TransitionCandidate,
    parse_analysis_state_document,
    review_transition_candidate_scoped,
)
from apps.output.context_bundle import (
    ContextBundleWriteResult,
    load_context_bundle,
    write_context_bundle,
)


LEGACY_CONTEXT_MODE = "legacy_full_context"
STATE_DELTA_CONTEXT_MODE = "state_delta_context"
CONTEXT_MODE_ENV = "FINANCE_AGENT_ANALYSIS_CONTEXT_MODE"
ContextMode = Literal["legacy_full_context", "state_delta_context"]
StateDeltaAnalyzer = Callable[[AnalysisContextBundle], TransitionCandidate | dict[str, Any]]


@dataclass(frozen=True, slots=True)
class CompositeStateShadowRuntime:
    bundle: AnalysisContextBundle
    artifact: ContextBundleWriteResult
    previous_state: AnalysisStateDocumentV1 | AnalysisStateDocumentV11
    state_scope: StateScope
    state_machine_version: str
    session: str
    trade_date: date
    available_evidence_refs: list[dict[str, Any]]
    run_id: str
    evidence_delta_decision: EvidenceDeltaDecision
    no_material_delta: bool
    assembly_latency_ms: int


def resolve_analysis_context_mode(value: str | None = None) -> ContextMode:
    normalized = str(value or os.environ.get(CONTEXT_MODE_ENV) or LEGACY_CONTEXT_MODE).strip()
    if normalized not in {LEGACY_CONTEXT_MODE, STATE_DELTA_CONTEXT_MODE}:
        raise ValueError(f"unsupported analysis context mode: {normalized}")
    return normalized  # type: ignore[return-value]


def prepare_composite_state_shadow(
    *,
    storage_root: Path,
    run_id: str,
    created_at: datetime,
    shadow_input: dict[str, Any],
) -> CompositeStateShadowRuntime:
    """Build and persist exactly one bundle for one shadow composite run."""

    started = perf_counter()
    state_scope = _state_scope(shadow_input.get("state_scope"))
    canonical_payload = shadow_input["canonical_state"]
    if isinstance(canonical_payload, dict) and "schema_version" not in canonical_payload:
        canonical_payload = {**canonical_payload, "schema_version": "1.0"}
    previous_state = parse_analysis_state_document(canonical_payload)
    if isinstance(previous_state, AnalysisStateDocumentV11):
        if previous_state.state_scope != state_scope:
            raise ValueError("shadow canonical state belongs to a different state_scope")
        state_machine_version = previous_state.state_machine_version
        session = previous_state.session
        trade_date = previous_state.trade_date
    else:
        if state_scope != "daily_close":
            raise ValueError("legacy v1 canonical state is only valid for daily_close shadow")
        state_machine_version = ANALYSIS_STATE_MACHINE_VERSION
        session = str(shadow_input.get("expected_session") or "daily_close").strip()
        if not session:
            raise ValueError("shadow session must not be blank")
    confirmed_facts = []
    delta_facts = []
    for raw_fact in shadow_input.get("figure_facts") or []:
        confirmed = project_confirmed_evidence(raw_fact)
        if confirmed is not None:
            confirmed_facts.append(confirmed.model_dump(mode="json"))
            delta_facts.append(
                adapt_figure_fact(
                    confirmed.model_dump(mode="json"),
                    observed_at=_datetime_value(shadow_input.get("cutoff_at") or created_at),
                )
            )
    cutoff_at = _datetime_value(shadow_input.get("cutoff_at") or created_at)
    assembled_at = _datetime_value(shadow_input.get("assembled_at") or created_at)
    if isinstance(previous_state, AnalysisStateDocumentV1):
        trade_date = cutoff_at.date()
    recovery = _recovery_inputs(
        storage_root=storage_root,
        shadow_input=shadow_input,
        asset=previous_state.asset,
        state_scope=state_scope,
        canonical_state_id=str(shadow_input["canonical_state_id"]),
    )
    bundle = assemble_context_bundle(
        run_id=run_id,
        asset=previous_state.asset,
        state_scope=state_scope,
        canonical_state_id=str(shadow_input["canonical_state_id"]),
        canonical_state=previous_state.model_dump(mode="json"),
        evidence=list(shadow_input.get("evidence") or []),
        evidence_cursors=dict(shadow_input.get("evidence_cursors") or {}),
        cutoff_at=cutoff_at,
        assembled_at=assembled_at,
        facts=confirmed_facts,
        delta_facts=delta_facts,
        **recovery,
        expected_session=shadow_input.get("expected_session"),
        max_alignment_seconds=int(shadow_input.get("max_alignment_seconds") or 86_400),
        budget_tokens=int(shadow_input.get("budget_tokens") or 15_000),
    )
    artifact = write_context_bundle(storage_root=storage_root, bundle=bundle)
    delta_block = next(block for block in bundle.blocks if block.name == "delta_evidence")
    facts_block = next(block for block in bundle.blocks if block.name == "facts")
    available_refs = [
        dict(item.get("source_ref") or {})
        for item in delta_block.payload
        if isinstance(item, dict) and item.get("source_ref")
    ]
    available_refs.extend(
        dict(item.get("source_ref") or {})
        for item in facts_block.payload
        if isinstance(item, dict) and item.get("source_ref")
    )
    if bundle.evidence_delta_decision is None:  # pragma: no cover - v3 schema contract
        raise ValueError("shadow context bundle is missing evidence delta decision")
    decision = EvidenceDeltaDecision.model_validate(bundle.evidence_delta_decision)
    no_material_delta = decision.recommended_action is RecommendedAction.NO_OP
    return CompositeStateShadowRuntime(
        bundle=bundle,
        artifact=artifact,
        previous_state=previous_state,
        state_scope=state_scope,
        state_machine_version=state_machine_version,
        session=session,
        trade_date=trade_date,
        available_evidence_refs=available_refs,
        run_id=run_id,
        evidence_delta_decision=decision,
        no_material_delta=no_material_delta,
        assembly_latency_ms=max(0, round((perf_counter() - started) * 1000)),
    )


def execute_composite_state_shadow(
    *,
    runtime: CompositeStateShadowRuntime,
    analyzer: StateDeltaAnalyzer | None,
) -> dict[str, Any]:
    """Run only the shadow candidate path; never materialize or advance canonical state."""

    base = _base_trace(runtime)
    action = runtime.evidence_delta_decision.recommended_action
    if action is RecommendedAction.NO_OP:
        return {
            **base,
            "status": "no_material_delta",
            "model_invocation": "skipped",
            "shadow_review_status": "not_required",
            "transition_diff": [],
        }
    if action is RecommendedAction.UPDATE_CONTEXT_ONLY:
        return {
            **base,
            "status": "context_updated_only",
            "model_invocation": "skipped",
            "shadow_review_status": "not_required",
            "transition_diff": [],
        }
    if action is RecommendedAction.MANUAL_REVIEW:
        return {
            **base,
            "status": "manual_review_required",
            "model_invocation": "skipped",
            "shadow_review_status": "needs_review",
            "transition_diff": [],
            "review_items": [_manual_review_item(runtime)],
        }
    if action is not RecommendedAction.RUN_TRANSITION_ANALYSIS:  # pragma: no cover - enum contract
        raise ValueError(f"unsupported evidence delta action: {action}")
    if analyzer is None:
        return {
            **base,
            "status": "awaiting_shadow_analyzer",
            "model_invocation": "not_configured",
            "shadow_review_status": "needs_review",
            "transition_diff": [],
        }

    started = perf_counter()
    try:
        raw_candidate = analyzer(runtime.bundle)
        candidate_payload = (
            raw_candidate.model_dump(mode="json")
            if isinstance(raw_candidate, BaseModel)
            else raw_candidate
        )
        candidate = TransitionCandidate.model_validate(candidate_payload)
        review = review_transition_candidate_scoped(
            candidate=candidate,
            previous_state_id=runtime.bundle.canonical_state_id,
            previous_state=runtime.previous_state,
            available_evidence_refs=runtime.available_evidence_refs,
            state_scope=runtime.state_scope,
            state_machine_version=runtime.state_machine_version,
            session=runtime.session,
            trade_date=runtime.trade_date,
        )
    except Exception as exc:
        return {
            **base,
            "status": "candidate_rejected",
            "model_invocation": "executed",
            "shadow_review_status": "needs_review",
            "transition_diff": [],
            "reason": f"{type(exc).__name__}:{str(exc)[:200]}",
            "analyzer_latency_ms": max(0, round((perf_counter() - started) * 1000)),
        }
    return {
        **base,
        "status": "candidate_accepted_shadow_only",
        "model_invocation": "executed",
        "shadow_review_status": "accepted",
        "transition_diff": [
            change.model_dump(mode="json") for change in review.transition.changes
        ],
        "shadow_core_thesis": review.next_state.core_thesis,
        "review_hash": review.next_state_content_hash,
        "analyzer_latency_ms": max(0, round((perf_counter() - started) * 1000)),
    }


def finalize_composite_state_shadow(
    trace: dict[str, Any],
    *,
    legacy_coordinator: Any,
    agent_loop_decision: Any,
    consumer_names: list[str],
) -> dict[str, Any]:
    legacy_summary = str(getattr(legacy_coordinator, "summary", "") or "")
    shadow_summary = str(trace.get("shadow_core_thesis") or "")
    publish_allowed = bool(getattr(agent_loop_decision, "publish_allowed", False))
    bundle_id = trace.get("bundle_id")
    return {
        **trace,
        "bundle_consumers": {
            name: bundle_id for name in consumer_names if bundle_id
        },
        "conclusion_diff": {
            "legacy": legacy_summary,
            "shadow": shadow_summary,
            "changed": bool(shadow_summary and shadow_summary != legacy_summary),
        },
        "quality_distribution": {
            "legacy": "accepted" if publish_allowed else "needs_review",
            "shadow": trace["shadow_review_status"],
        },
        "production_canonical_write_allowed": False,
    }


def _base_trace(runtime: CompositeStateShadowRuntime) -> dict[str, Any]:
    return {
        "schema_version": "composite_state_shadow.v3",
        "mode": STATE_DELTA_CONTEXT_MODE,
        "asset": runtime.bundle.asset,
        "state_scope": runtime.state_scope,
        "canonical_state_id": runtime.bundle.canonical_state_id,
        "bundle_id": runtime.bundle.bundle_id,
        "bundle_content_hash": runtime.bundle.content_hash,
        "bundle_path": runtime.artifact.storage_relative_path,
        "evidence_delta_decision_id": runtime.evidence_delta_decision.decision_id,
        "evidence_delta_action": runtime.evidence_delta_decision.recommended_action.value,
        "bundle_recovered": not runtime.artifact.written,
        "bundle_estimated_tokens": runtime.bundle.budget_trace.estimated_tokens,
        "assembly_latency_ms": runtime.assembly_latency_ms,
    }


_RECOVERY_FIELDS = (
    "previous_semantic_hashes",
    "deferred_queue",
    "processed_above_frontier",
    "freshness_sla_seconds",
    "default_freshness_sla_seconds",
)


def _recovery_inputs(
    *,
    storage_root: Path,
    shadow_input: dict[str, Any],
    asset: str,
    state_scope: StateScope,
    canonical_state_id: str,
) -> dict[str, Any]:
    previous_bundle_path = shadow_input.get("previous_bundle_path")
    if previous_bundle_path is None:
        return {
            field: shadow_input[field]
            for field in _RECOVERY_FIELDS
            if field in shadow_input
        }
    ambiguous = [field for field in _RECOVERY_FIELDS if field in shadow_input]
    if ambiguous:
        raise ValueError(
            "previous_bundle_path cannot be combined with explicit recovery fields: "
            + ", ".join(ambiguous)
        )
    previous = load_context_bundle(
        storage_root=storage_root,
        storage_relative_path=str(previous_bundle_path),
    )
    if previous.schema_version != "analysis_context_bundle.v3":
        raise ValueError("previous context bundle must use analysis_context_bundle.v3")
    if (
        previous.asset != asset
        or previous.state_scope != state_scope
        or previous.canonical_state_id != canonical_state_id
    ):
        raise ValueError("previous context bundle identity does not match shadow input")
    if previous.evidence_delta_decision is None:  # pragma: no cover - v3 schema contract
        raise ValueError("previous context bundle is missing evidence delta decision")
    decision = EvidenceDeltaDecision.model_validate(previous.evidence_delta_decision)
    hashes: dict[str, str] = {}
    for item in decision.evaluated_items:
        existing = hashes.get(item.evidence_key)
        if existing is not None and existing != item.semantic_hash:
            raise ValueError("previous context bundle has ambiguous semantic hashes")
        hashes[item.evidence_key] = item.semantic_hash
    return {
        "previous_semantic_hashes": hashes,
        "deferred_queue": tuple(previous.deferred_queue),
        "processed_above_frontier": {
            source: tuple(pointers)
            for source, pointers in previous.processed_above_frontier.items()
        },
        "freshness_sla_seconds": dict(previous.freshness_sla_seconds),
        "default_freshness_sla_seconds": previous.default_freshness_sla_seconds,
    }


def build_state_delta_review_item(
    *,
    run_id: str,
    review_id: str,
    source_step_id: str,
    reason: str,
    severity: str = "error",
    impact_modules: list[str] | None = None,
    suggested_action: str | None = None,
    evidence_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the stable, runner-persistable review payload for shadow failures."""

    return {
        "review_id": review_id,
        "run_id": run_id,
        "source_module": "state_delta_shadow",
        "source_step_id": source_step_id,
        "severity": severity,
        "reason": reason,
        "impact_modules": impact_modules or ["analysis_state", "state_delta_shadow"],
        "suggested_action": suggested_action
        or "Review conflicting or unverified evidence before transition analysis.",
        "status": "pending",
        "evidence_refs": evidence_refs or [],
    }


def build_state_delta_setup_failure_review_item(
    *,
    run_id: str,
    failure_kind: str,
) -> dict[str, Any]:
    """Build a safe review item without reflecting untrusted shadow input."""

    reason = f"State-delta shadow setup failed: {failure_kind}"
    reason_digest = hashlib.sha256(reason.encode("utf-8")).hexdigest()[:16]
    return build_state_delta_review_item(
        run_id=run_id,
        review_id=f"state_delta_setup:{run_id}:{reason_digest}",
        source_step_id="state_delta_shadow_setup",
        reason=reason,
        suggested_action="Review the trusted state-delta setup inputs before retrying shadow analysis.",
    )


def _manual_review_item(runtime: CompositeStateShadowRuntime) -> dict[str, Any]:
    decision = runtime.evidence_delta_decision
    evidence_refs = [
        ref.model_dump(mode="json")
        for item in decision.evaluated_items
        for ref in item.evidence_refs
    ]
    return build_state_delta_review_item(
        run_id=runtime.run_id,
        review_id=f"evidence_delta:{decision.decision_id}",
        source_step_id="evidence_delta_decision",
        reason="Evidence delta requires manual review: " + "; ".join(decision.trigger_reasons),
        evidence_refs=evidence_refs,
    )


def _datetime_value(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("shadow timestamps must be timezone-aware")
    return parsed.astimezone(UTC)


def _state_scope(value: Any) -> StateScope:
    normalized = str(value or "").strip()
    if normalized not in {"intraday", "daily_close", "weekly_fundamental"}:
        raise ValueError("shadow state_scope is required and must be valid")
    return normalized  # type: ignore[return-value]
