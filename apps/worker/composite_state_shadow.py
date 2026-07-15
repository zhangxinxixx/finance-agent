"""Observe-only state+delta shadow support for the composite pipeline."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Literal

from pydantic import BaseModel

from apps.analysis.context_bundle import AnalysisContextBundle, assemble_context_bundle
from apps.analysis.figure_facts import project_confirmed_evidence
from apps.analysis.state import (
    AnalysisStateDocument,
    TransitionCandidate,
    review_transition_candidate,
)
from apps.output.context_bundle import ContextBundleWriteResult, write_context_bundle


LEGACY_CONTEXT_MODE = "legacy_full_context"
STATE_DELTA_CONTEXT_MODE = "state_delta_context"
CONTEXT_MODE_ENV = "FINANCE_AGENT_ANALYSIS_CONTEXT_MODE"
ContextMode = Literal["legacy_full_context", "state_delta_context"]
StateDeltaAnalyzer = Callable[[AnalysisContextBundle], TransitionCandidate | dict[str, Any]]


@dataclass(frozen=True, slots=True)
class CompositeStateShadowRuntime:
    bundle: AnalysisContextBundle
    artifact: ContextBundleWriteResult
    previous_state: AnalysisStateDocument
    available_evidence_refs: list[dict[str, Any]]
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
    previous_state = AnalysisStateDocument.model_validate(shadow_input["canonical_state"])
    confirmed_facts = []
    for raw_fact in shadow_input.get("figure_facts") or []:
        confirmed = project_confirmed_evidence(raw_fact)
        if confirmed is not None:
            confirmed_facts.append(confirmed.model_dump(mode="json"))
    cutoff_at = _datetime_value(shadow_input.get("cutoff_at") or created_at)
    assembled_at = _datetime_value(shadow_input.get("assembled_at") or created_at)
    bundle = assemble_context_bundle(
        run_id=run_id,
        asset=previous_state.asset,
        canonical_state_id=str(shadow_input["canonical_state_id"]),
        canonical_state=previous_state.model_dump(mode="json"),
        evidence=list(shadow_input.get("evidence") or []),
        evidence_cursors=dict(shadow_input.get("evidence_cursors") or {}),
        cutoff_at=cutoff_at,
        assembled_at=assembled_at,
        facts=confirmed_facts,
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
    no_material_delta = not delta_block.payload and not facts_block.payload
    return CompositeStateShadowRuntime(
        bundle=bundle,
        artifact=artifact,
        previous_state=previous_state,
        available_evidence_refs=available_refs,
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
    if runtime.no_material_delta:
        return {
            **base,
            "status": "no_material_delta",
            "model_invocation": "skipped",
            "shadow_review_status": "not_required",
            "transition_diff": [],
        }
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
        review = review_transition_candidate(
            candidate=candidate,
            previous_state_id=runtime.bundle.canonical_state_id,
            previous_state=runtime.previous_state,
            available_evidence_refs=runtime.available_evidence_refs,
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
        "schema_version": "composite_state_shadow.v1",
        "mode": STATE_DELTA_CONTEXT_MODE,
        "bundle_id": runtime.bundle.bundle_id,
        "bundle_content_hash": runtime.bundle.content_hash,
        "bundle_path": runtime.artifact.storage_relative_path,
        "bundle_recovered": not runtime.artifact.written,
        "bundle_estimated_tokens": runtime.bundle.budget_trace.estimated_tokens,
        "assembly_latency_ms": runtime.assembly_latency_ms,
    }


def _datetime_value(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("shadow timestamps must be timezone-aware")
    return parsed.astimezone(UTC)
