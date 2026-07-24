"""Deterministic assembly of canonical state plus per-source evidence deltas."""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from apps.analysis.context_bundle.selection import (
    DeferredEvidencePointer,
    EvidencePriority,
    EvidencePriorityClass,
    select_material_evidence,
)
from apps.analysis.context_bundle.schemas import (
    CONTEXT_BUNDLE_SCHEMA_VERSION,
    AnalysisContextBundle,
    ContextBlock,
    ContextBudgetTrace,
    EvidenceCursor,
    EvidenceItem,
    compute_bundle_content_hash,
)
from apps.analysis.evidence_delta import (
    DeltaEvidence,
    EvidenceDeltaDecision,
    FigureFactEvidence,
    Materiality,
    RecommendedAction,
    adapt_context_evidence,
    evaluate_evidence_delta,
)
from apps.analysis.state.schemas import StateScope


DEFAULT_CONTEXT_TOKEN_BUDGET = 15_000
DEFAULT_SOURCE_FRESHNESS_SLA_SECONDS = 86_400
_HISTORY_BODY_KEYS = frozenset(
    {
        "article_markdown",
        "full_report",
        "previous_report",
        "previous_analysis_report",
        "previous_daily",
        "previous_daily_analysis",
        "weekly_anchor",
        "weekly_report",
        "weekly_report_body",
    }
)
_TRANSPORT_KEYS = frozenset(
    {
        "provider",
        "provider_id",
        "thread",
        "thread_id",
        "conversation",
        "conversation_id",
        "messages",
    }
)


class ContextBundleBudgetExceeded(ValueError):
    def __init__(self, trace: dict[str, Any]) -> None:
        super().__init__(
            "context bundle budget exceeded: "
            f"estimated_tokens={trace['estimated_tokens']}; budget={trace['budget_tokens']}"
        )
        self.trace = trace


def select_incremental_evidence(
    evidence: list[EvidenceItem | dict[str, Any]],
    *,
    cursors: dict[str, EvidenceCursor | dict[str, Any]] | None,
    cutoff_at: datetime,
    trim_reasons: dict[str, list[str]] | None = None,
) -> list[EvidenceItem]:
    """Select evidence by each source's ingest cursor, not by business time."""

    _require_aware_datetime(cutoff_at, field="cutoff_at")
    normalized_cursors = {
        source: value if isinstance(value, EvidenceCursor) else EvidenceCursor.model_validate(value)
        for source, value in (cursors or {}).items()
    }
    selected: list[EvidenceItem] = []
    for raw_item in evidence:
        sanitized = _sanitize_value(
            raw_item.model_dump(mode="json") if isinstance(raw_item, EvidenceItem) else raw_item,
            trim_reasons=trim_reasons,
        )
        item = EvidenceItem.model_validate(sanitized)
        if item.ingested_at > cutoff_at:
            continue
        cursor = normalized_cursors.get(item.source)
        if cursor is not None and (item.ingested_at, item.evidence_id) <= (
            cursor.ingested_at,
            cursor.evidence_id,
        ):
            continue
        selected.append(item)
    return sorted(selected, key=lambda item: (item.ingested_at, item.evidence_id, item.source))


def assemble_context_bundle(
    *,
    run_id: str,
    asset: str,
    state_scope: StateScope,
    canonical_state_id: str,
    canonical_state: dict[str, Any],
    evidence: list[EvidenceItem | dict[str, Any]],
    evidence_cursors: dict[str, EvidenceCursor | dict[str, Any]] | None,
    cutoff_at: datetime,
    assembled_at: datetime,
    facts: list[dict[str, Any]] | None = None,
    delta_facts: list[DeltaEvidence] | None = None,
    previous_semantic_hashes: dict[str, str] | None = None,
    deferred_queue: tuple[DeferredEvidencePointer | dict[str, Any], ...] = (),
    processed_above_frontier: dict[
        str, tuple[DeferredEvidencePointer | dict[str, Any], ...]
    ]
    | None = None,
    freshness_sla_seconds: dict[str, int] | None = None,
    default_freshness_sla_seconds: int = DEFAULT_SOURCE_FRESHNESS_SLA_SECONDS,
    expected_session: str | None = None,
    max_alignment_seconds: int = 86_400,
    budget_tokens: int = DEFAULT_CONTEXT_TOKEN_BUDGET,
) -> AnalysisContextBundle:
    """Build a v3 bundle from one materiality-evaluated, gap-safe evidence set."""

    if budget_tokens < 1:
        raise ValueError("budget_tokens must be positive")
    if max_alignment_seconds < 0:
        raise ValueError("max_alignment_seconds must be non-negative")
    if (
        isinstance(default_freshness_sla_seconds, bool)
        or not isinstance(default_freshness_sla_seconds, int)
        or default_freshness_sla_seconds < 0
    ):
        raise ValueError("default_freshness_sla_seconds must be a non-negative integer")
    _require_aware_datetime(cutoff_at, field="cutoff_at")
    _require_aware_datetime(assembled_at, field="assembled_at")
    normalized_asset = str(asset).strip()
    if not normalized_asset:
        raise ValueError("asset must not be blank")
    _validate_canonical_state_identity(
        canonical_state,
        asset=normalized_asset,
        state_scope=state_scope,
    )

    trim_reasons: dict[str, list[str]] = defaultdict(list)
    state_payload = _compact_value(
        _sanitize_value(canonical_state, trim_reasons=trim_reasons, block="canonical_state"),
        trim_reasons=trim_reasons,
        block="canonical_state",
    )
    incremental = select_incremental_evidence(
        evidence,
        cursors=evidence_cursors,
        cutoff_at=cutoff_at,
        trim_reasons=trim_reasons,
    )
    processed = _normalize_processed(processed_above_frontier)
    processed_keys = {
        (pointer.source, pointer.evidence_id)
        for pointers in processed.values()
        for pointer in pointers
    }
    eligible = [
        item for item in incremental if (item.source, item.evidence_id) not in processed_keys
    ]
    compacted_evidence = {
        (item.source, item.evidence_id): _compact_value(
            item.model_dump(mode="json"),
            trim_reasons=trim_reasons,
            block="delta_evidence",
        )
        for item in incremental
    }
    facts_payload = [
        _compact_value(
            _sanitize_value(item, trim_reasons=trim_reasons, block="facts"),
            trim_reasons=trim_reasons,
            block="facts",
        )
        for item in (facts or [])
    ]

    normalized_cursors = {
        source: value if isinstance(value, EvidenceCursor) else EvidenceCursor.model_validate(value)
        for source, value in (evidence_cursors or {}).items()
    }
    normalized_delta_facts = _accepted_delta_facts(delta_facts or [])
    preliminary_decision = evaluate_evidence_delta(
        asset=normalized_asset,
        state_scope=state_scope,
        canonical_state_id=str(canonical_state_id).strip(),
        evidence=[*(adapt_context_evidence(item) for item in eligible), *normalized_delta_facts],
        previous_semantic_hashes=previous_semantic_hashes,
    )
    priorities = _priorities_from_decision(
        decision=preliminary_decision,
        evidence=eligible,
        compacted_evidence=compacted_evidence,
    )
    priorities.extend(
        _processed_priorities(
            processed=processed,
            incremental=incremental,
            compacted_evidence=compacted_evidence,
        )
    )

    empty_blocks = _build_blocks(
        state_payload=state_payload,
        evidence_payload=[],
        facts_payload=facts_payload,
        retained_evidence=[],
        trim_reasons=trim_reasons,
    )
    fixed_trace = _budget_trace(
        empty_blocks,
        budget_tokens=budget_tokens,
        trim_reasons=trim_reasons,
    )
    if not fixed_trace["within_budget"]:
        raise ContextBundleBudgetExceeded(fixed_trace)
    fixed_tokens = sum(
        block.estimated_tokens for block in empty_blocks if block.name != "delta_evidence"
    )
    selection = select_material_evidence(
        evidence=incremental,
        priorities=priorities,
        evidence_cursors=normalized_cursors,
        cutoff_at=cutoff_at,
        evidence_budget_tokens=max(0, budget_tokens - fixed_tokens - 1),
        deferred_queue=deferred_queue,
        processed_above_frontier=processed,
    )
    incremental_by_key = {(item.source, item.evidence_id): item for item in incremental}
    retained = [
        incremental_by_key[(key.source, key.evidence_id)]
        for key in selection.retained_evidence_keys
    ]
    evidence_payload = [
        compacted_evidence[(item.source, item.evidence_id)] for item in retained
    ]
    for decision in selection.decisions:
        if decision.outcome == "deferred":
            trim_reasons["delta_evidence"].append(
                f"budget_deferred:{decision.source}/{decision.evidence_id}"
            )
    blocks = _build_blocks(
        state_payload=state_payload,
        evidence_payload=evidence_payload,
        facts_payload=facts_payload,
        retained_evidence=retained,
        trim_reasons=trim_reasons,
    )
    trace = _budget_trace(blocks, budget_tokens=budget_tokens, trim_reasons=trim_reasons)
    if not trace["within_budget"]:
        raise ContextBundleBudgetExceeded(trace)

    final_decision = evaluate_evidence_delta(
        asset=normalized_asset,
        state_scope=state_scope,
        canonical_state_id=str(canonical_state_id).strip(),
        evidence=[*(adapt_context_evidence(item) for item in retained), *normalized_delta_facts],
        previous_semantic_hashes=previous_semantic_hashes,
    )
    normalized_slas = _normalize_freshness_slas(freshness_sla_seconds)
    freshness = _freshness(
        eligible,
        cutoff_at=cutoff_at,
        freshness_sla_seconds=normalized_slas,
        default_freshness_sla_seconds=default_freshness_sla_seconds,
    )
    session = _session_status(eligible, expected_session=expected_session)
    alignment = _alignment_status(eligible, max_alignment_seconds=max_alignment_seconds)
    source_refs = [dict(item.source_ref) for item in eligible if item.source_ref]
    source_refs.extend(
        dict(item["source_ref"])
        for item in facts_payload
        if isinstance(item, dict) and isinstance(item.get("source_ref"), dict)
    )
    base_payload = {
        "schema_version": CONTEXT_BUNDLE_SCHEMA_VERSION,
        "run_id": str(run_id).strip(),
        "asset": normalized_asset,
        "state_scope": state_scope,
        "canonical_state_id": str(canonical_state_id).strip(),
        "cutoff_at": _json_datetime(cutoff_at),
        "evidence_cursors": {
            source: cursor.model_dump(mode="json") for source, cursor in normalized_cursors.items()
        },
        "next_evidence_cursors": {
            source: cursor.model_dump(mode="json")
            for source, cursor in selection.next_evidence_cursors.items()
        },
        "freshness": freshness,
        "session": session,
        "alignment": alignment,
        "evidence_delta_decision": final_decision.model_dump(mode="json"),
        "deferred_queue": [item.model_dump(mode="json") for item in selection.deferred_queue],
        "processed_above_frontier": {
            source: [item.model_dump(mode="json") for item in pointers]
            for source, pointers in selection.processed_above_frontier.items()
        },
        "selection_decisions": [
            item.model_dump(mode="json") for item in selection.decisions
        ],
        "selection_trace": selection.trace.model_dump(mode="json"),
        "freshness_sla_seconds": normalized_slas,
        "default_freshness_sla_seconds": default_freshness_sla_seconds,
        "blocks": [block.model_dump(mode="json") for block in blocks],
        "budget_trace": trace,
        "source_refs": source_refs,
    }
    resolved_hash = compute_bundle_content_hash(base_payload)
    resolved_id = str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"finance-agent:context-bundle:{resolved_hash}")
    )
    return AnalysisContextBundle.model_validate(
        {
            **base_payload,
            "bundle_id": resolved_id,
            "content_hash": resolved_hash,
            "assembled_at": assembled_at,
        }
    )


def _accepted_delta_facts(items: list[DeltaEvidence]) -> list[FigureFactEvidence]:
    accepted: list[FigureFactEvidence] = []
    for item in items:
        if not isinstance(item, FigureFactEvidence):
            raise ValueError("delta_facts only accepts FigureFactEvidence")
        if item.quality_status != "accepted" or not item.has_direct_evidence:
            raise ValueError("only accepted FigureFact evidence may enter a context bundle")
        if item.source != "figure_fact" or item.evidence_id != item.figure_fact_id:
            raise ValueError("FigureFact delta evidence must use its canonical figure_fact identity")
        accepted.append(item)
    return accepted


def _priorities_from_decision(
    *,
    decision: EvidenceDeltaDecision,
    evidence: list[EvidenceItem],
    compacted_evidence: dict[tuple[str, str], dict[str, Any]],
) -> list[EvidencePriority]:
    evaluated_by_ref = {
        (ref.source, ref.evidence_id): item
        for item in decision.evaluated_items
        for ref in item.evidence_refs
    }
    priorities: list[EvidencePriority] = []
    for item in evidence:
        key = (item.source, item.evidence_id)
        evaluated = evaluated_by_ref.get(key)
        if evaluated is None:
            raise ValueError(f"evidence delta decision omitted eligible evidence: {item.source}/{item.evidence_id}")
        priority_class = _priority_class(evaluated)
        priorities.append(
            EvidencePriority(
                source=item.source,
                evidence_id=item.evidence_id,
                semantic_hash=evaluated.semantic_hash,
                priority_class=priority_class,
                materiality=evaluated.materiality.value,
                mandatory=priority_class is EvidencePriorityClass.MANDATORY_CRITICAL,
                reason_codes=tuple(evaluated.reasons),
                estimated_tokens=max(
                    1,
                    _estimate_tokens(_canonical_bytes(compacted_evidence[key])) + 1,
                ),
            )
        )
    return priorities


def _priority_class(evaluated: Any) -> EvidencePriorityClass:
    if (
        evaluated.materiality is Materiality.CRITICAL
        or evaluated.recommended_action is RecommendedAction.MANUAL_REVIEW
    ):
        return EvidencePriorityClass.MANDATORY_CRITICAL
    if (
        evaluated.recommended_action is RecommendedAction.RUN_TRANSITION_ANALYSIS
        and "invalidation_conditions" in evaluated.affected_state_fields
    ):
        return EvidencePriorityClass.CONFIRMED_INVALIDATION
    if (
        evaluated.evidence_type == "key_level_event"
        and evaluated.recommended_action is RecommendedAction.RUN_TRANSITION_ANALYSIS
    ):
        return EvidencePriorityClass.CONFIRMED_KEY_LEVEL
    if evaluated.evidence_type == "options_regime":
        return EvidencePriorityClass.MARKET_OPTIONS_REGIME
    if evaluated.materiality is Materiality.HIGH:
        return EvidencePriorityClass.LATEST_HIGH_QUALITY
    if evaluated.materiality is Materiality.MEDIUM:
        return EvidencePriorityClass.ORDINARY_CURRENT
    return EvidencePriorityClass.BACKLOG


def _normalize_processed(
    values: dict[str, tuple[DeferredEvidencePointer | dict[str, Any], ...]] | None,
) -> dict[str, tuple[DeferredEvidencePointer, ...]]:
    return {
        str(source).strip(): tuple(
            item
            if isinstance(item, DeferredEvidencePointer)
            else DeferredEvidencePointer.model_validate(item)
            for item in pointers
        )
        for source, pointers in sorted((values or {}).items())
    }


def _processed_priorities(
    *,
    processed: dict[str, tuple[DeferredEvidencePointer, ...]],
    incremental: list[EvidenceItem],
    compacted_evidence: dict[tuple[str, str], dict[str, Any]],
) -> list[EvidencePriority]:
    priorities: list[EvidencePriority] = []
    for pointers in processed.values():
        for pointer in pointers:
            key = (pointer.source, pointer.evidence_id)
            payload = compacted_evidence.get(key)
            estimated_tokens = (
                max(1, _estimate_tokens(_canonical_bytes(payload)) + 1)
                if payload is not None
                else 1
            )
            priorities.append(
                EvidencePriority(
                    source=pointer.source,
                    evidence_id=pointer.evidence_id,
                    semantic_hash=pointer.semantic_hash,
                    priority_class=EvidencePriorityClass.BACKLOG,
                    materiality="processed",
                    mandatory=False,
                    reason_codes=("already_processed_above_frontier",),
                    estimated_tokens=estimated_tokens,
                )
            )
    return priorities


def _normalize_freshness_slas(values: dict[str, int] | None) -> dict[str, int]:
    normalized: dict[str, int] = {}
    for raw_source, raw_sla in sorted((values or {}).items()):
        source = str(raw_source).strip()
        if not source:
            raise ValueError("freshness SLA source must not be blank")
        if isinstance(raw_sla, bool) or not isinstance(raw_sla, int) or raw_sla < 0:
            raise ValueError("freshness SLA seconds must be non-negative integers")
        normalized[source] = raw_sla
    return normalized


def _build_blocks(
    *,
    state_payload: Any,
    evidence_payload: list[dict[str, Any]],
    facts_payload: list[dict[str, Any]],
    retained_evidence: list[EvidenceItem],
    trim_reasons: dict[str, list[str]],
) -> list[ContextBlock]:
    values = [
        ("canonical_state", state_payload, []),
        ("delta_evidence", evidence_payload, [item.evidence_id for item in retained_evidence]),
        ("facts", facts_payload, []),
    ]
    blocks = []
    for name, payload, retained_ids in values:
        encoded = _canonical_bytes(payload)
        blocks.append(
            ContextBlock(
                name=name,
                payload=payload,
                utf8_bytes=len(encoded),
                estimated_tokens=_estimate_tokens(encoded),
                trim_reasons=list(trim_reasons.get(name) or []),
                retained_evidence_ids=retained_ids,
            )
        )
    return blocks


def _budget_trace(
    blocks: list[ContextBlock],
    *,
    budget_tokens: int,
    trim_reasons: dict[str, list[str]],
) -> dict[str, Any]:
    total_bytes = sum(block.utf8_bytes for block in blocks)
    estimated_tokens = sum(block.estimated_tokens for block in blocks)
    return ContextBudgetTrace(
        budget_tokens=budget_tokens,
        total_utf8_bytes=total_bytes,
        estimated_tokens=estimated_tokens,
        within_budget=estimated_tokens <= budget_tokens,
        blocks=[
            {
                "name": block.name,
                "utf8_bytes": block.utf8_bytes,
                "estimated_tokens": block.estimated_tokens,
                "retained_evidence_ids": list(block.retained_evidence_ids),
            }
            for block in blocks
        ],
        trim_reasons=[
            {"block": block, "reason": reason}
            for block in sorted(trim_reasons)
            for reason in trim_reasons[block]
        ],
    ).model_dump(mode="json")


def _sanitize_value(
    value: Any,
    *,
    trim_reasons: dict[str, list[str]] | None,
    block: str = "delta_evidence",
) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            normalized = str(key).lower()
            if normalized in _TRANSPORT_KEYS:
                continue
            if normalized in _HISTORY_BODY_KEYS:
                if trim_reasons is not None:
                    trim_reasons[block].append(f"omitted_field:{key}")
                continue
            result[str(key)] = _sanitize_value(
                item,
                trim_reasons=trim_reasons,
                block=block,
            )
        return result
    if isinstance(value, list):
        return [
            _sanitize_value(item, trim_reasons=trim_reasons, block=block) for item in value
        ]
    return value


def _compact_value(
    value: Any,
    *,
    trim_reasons: dict[str, list[str]],
    block: str,
    depth: int = 0,
) -> Any:
    if depth >= 8 and isinstance(value, (dict, list)):
        trim_reasons[block].append("nested_depth_limited")
        return "[nested data omitted]"
    if isinstance(value, dict):
        items = list(value.items())
        if len(items) > 80:
            trim_reasons[block].append("mapping_keys_limited")
            items = items[:80]
        return {
            str(key): _compact_value(
                item,
                trim_reasons=trim_reasons,
                block=block,
                depth=depth + 1,
            )
            for key, item in items
        }
    if isinstance(value, list):
        if len(value) > 80:
            trim_reasons[block].append("list_items_limited")
        return [
            _compact_value(
                item,
                trim_reasons=trim_reasons,
                block=block,
                depth=depth + 1,
            )
            for item in value[:80]
        ]
    if isinstance(value, str) and len(value) > 2_000:
        trim_reasons[block].append("text_value_limited")
        marker = "...[deterministic trim]..."
        remaining = 2_000 - len(marker)
        return f"{value[: remaining * 3 // 4]}{marker}{value[-remaining // 4 :]}"
    return value


def _freshness(
    items: list[EvidenceItem],
    *,
    cutoff_at: datetime,
    freshness_sla_seconds: dict[str, int],
    default_freshness_sla_seconds: int,
) -> dict[str, Any]:
    latest: dict[str, EvidenceItem] = {}
    for item in items:
        current = latest.get(item.source)
        if current is None or item.ingested_at > current.ingested_at:
            latest[item.source] = item
    result: dict[str, Any] = {}
    for source in sorted(set(latest) | set(freshness_sla_seconds)):
        sla_seconds = freshness_sla_seconds.get(source, default_freshness_sla_seconds)
        item = latest.get(source)
        if item is None:
            result[source] = {
                "status": "missing",
                "latest_ingested_at": None,
                "age_seconds": None,
                "sla_seconds": sla_seconds,
                "sla_policy": "explicit",
            }
            continue
        age_seconds = max(0.0, (cutoff_at - item.ingested_at).total_seconds())
        result[source] = {
            "status": "current" if age_seconds <= sla_seconds else "stale",
            "latest_ingested_at": _json_datetime(item.ingested_at),
            "age_seconds": age_seconds,
            "sla_seconds": sla_seconds,
            "sla_policy": "explicit" if source in freshness_sla_seconds else "default",
        }
    return result


def _session_status(
    items: list[EvidenceItem], *, expected_session: str | None
) -> dict[str, Any]:
    observed = sorted({item.session for item in items if item.session})
    if expected_session is None:
        status = "not_checked"
    elif not observed:
        status = "missing"
    elif observed == [expected_session]:
        status = "aligned"
    else:
        status = "mismatch"
    return {
        "status": status,
        "expected": expected_session,
        "observed": observed,
    }


def _alignment_status(
    items: list[EvidenceItem], *, max_alignment_seconds: int
) -> dict[str, Any]:
    if len(items) < 2:
        span = 0.0
    else:
        times = [item.business_time for item in items]
        span = (max(times) - min(times)).total_seconds()
    return {
        "status": "aligned" if span <= max_alignment_seconds else "misaligned",
        "business_time_span_seconds": span,
        "max_alignment_seconds": max_alignment_seconds,
    }


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _estimate_tokens(encoded: bytes) -> int:
    return (len(encoded) + 2) // 3


def _json_datetime(value: datetime) -> str:
    normalized = value.astimezone(UTC).isoformat()
    return normalized.replace("+00:00", "Z")


def _require_aware_datetime(value: datetime, *, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


def _validate_canonical_state_identity(
    canonical_state: dict[str, Any],
    *,
    asset: str,
    state_scope: StateScope,
) -> None:
    state_asset = str(canonical_state.get("asset") or "").strip()
    if state_asset != asset:
        raise ValueError("canonical state asset does not match bundle asset")
    declared_scope = canonical_state.get("state_scope")
    if declared_scope is None:
        if canonical_state.get("schema_version") != "1.0" or state_scope != "daily_close":
            raise ValueError("canonical state must explicitly match bundle state_scope")
        return
    if declared_scope != state_scope:
        raise ValueError("canonical state belongs to a different state_scope")
