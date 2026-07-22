"""Pure EvidenceDeltaEvaluator with deterministic aggregation and replay identity."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence

from .rules import RuleResult, evaluate_rule, semantic_hash, semantic_identity
from .schemas import (
    DeltaEvidence,
    EvidenceIdentity,
    EvaluatedEvidence,
    EvaluationOutcome,
    EvidenceDeltaDecision,
    Materiality,
    RecommendedAction,
    StateScope,
)


_MATERIALITY_RANK = {
    Materiality.NONE: 0,
    Materiality.LOW: 1,
    Materiality.MEDIUM: 2,
    Materiality.HIGH: 3,
    Materiality.CRITICAL: 4,
}
_ACTION_RANK = {
    RecommendedAction.NO_OP: 0,
    RecommendedAction.UPDATE_CONTEXT_ONLY: 1,
    RecommendedAction.RUN_TRANSITION_ANALYSIS: 2,
    RecommendedAction.MANUAL_REVIEW: 3,
}


def evaluate_evidence_delta(
    *,
    asset: str,
    state_scope: StateScope,
    canonical_state_id: str,
    evidence: Sequence[DeltaEvidence],
    previous_semantic_hashes: Mapping[str, str] | None = None,
) -> EvidenceDeltaDecision:
    """Evaluate already-adapted facts without I/O, clocks, models, or state mutation."""

    normalized_asset = _required_text(asset)
    normalized_state_id = _required_text(canonical_state_id)
    previous = _validate_previous_hashes(previous_semantic_hashes or {})
    grouped: dict[tuple[str, str], list[DeltaEvidence]] = defaultdict(list)
    by_identity_hashes: dict[str, set[str]] = defaultdict(set)
    authoritative_hashes: dict[tuple[str, str], set[str]] = defaultdict(set)

    for item in evidence:
        if item.asset != normalized_asset:
            raise ValueError(
                f"evidence asset mismatch: expected {normalized_asset}, got {item.asset} ({item.evidence_id})"
            )
        key = semantic_identity(item)
        item_hash = semantic_hash(item)
        grouped[(key, item_hash)].append(item)
        by_identity_hashes[key].add(item_hash)
        authoritative_hashes[(item.source, item.evidence_id)].add(item_hash)

    conflicting_semantic_keys = {
        key for key, hashes in by_identity_hashes.items() if len(hashes) > 1
    }
    conflicting_authoritative_keys = {
        key for key, hashes in authoritative_hashes.items() if len(hashes) > 1
    }
    evaluated: list[EvaluatedEvidence] = []
    semantic_hashes: dict[str, str] = {}
    for key, item_hash in sorted(grouped):
        items = grouped[(key, item_hash)]
        representative = min(items, key=lambda item: (item.evidence_id, item.source))
        has_authoritative_conflict = any(
            (item.source, item.evidence_id) in conflicting_authoritative_keys for item in items
        )
        if len(by_identity_hashes[key]) == 1 and not has_authoritative_conflict:
            semantic_hashes[key] = item_hash
        if has_authoritative_conflict:
            result = RuleResult(
                materiality=Materiality.HIGH,
                outcome=EvaluationOutcome.MANUAL_REVIEW,
                action=RecommendedAction.MANUAL_REVIEW,
                affected_state_fields=("unresolved_items",),
                reasons=("authoritative_evidence_key:conflicting_payload",),
            )
        elif key in conflicting_semantic_keys:
            result = RuleResult(
                materiality=Materiality.HIGH,
                outcome=EvaluationOutcome.MANUAL_REVIEW,
                action=RecommendedAction.MANUAL_REVIEW,
                affected_state_fields=("unresolved_items",),
                reasons=("semantic_identity:conflicting_payload",),
            )
        elif previous.get(key) == item_hash:
            result = RuleResult(
                materiality=Materiality.NONE,
                outcome=EvaluationOutcome.DUPLICATE,
                action=RecommendedAction.NO_OP,
                affected_state_fields=(),
                reasons=("semantic_content_unchanged",),
            )
        else:
            result = evaluate_rule(representative)
        evaluated.append(
            EvaluatedEvidence(
                evidence_key=key,
                evidence_type=representative.evidence_type,
                semantic_hash=item_hash,
                evidence_refs=[
                    EvidenceIdentity(source=source, evidence_id=evidence_id)
                    for source, evidence_id in sorted(
                        {(item.source, item.evidence_id) for item in items}
                    )
                ],
                materiality=result.materiality,
                outcome=result.outcome,
                recommended_action=result.action,
                affected_state_fields=sorted(set(result.affected_state_fields)),
                reasons=sorted(set(result.reasons)),
            )
        )

    if evaluated:
        action = max(
            (item.recommended_action for item in evaluated),
            key=lambda candidate: _ACTION_RANK[candidate],
        )
        materiality = max(
            (item.materiality for item in evaluated),
            key=lambda candidate: _MATERIALITY_RANK[candidate],
        )
        affected = sorted(
            {
                field
                for item in evaluated
                if item.recommended_action is not RecommendedAction.NO_OP
                for field in item.affected_state_fields
            }
        )
        reasons = sorted(
            {
                reason
                for item in evaluated
                for reason in item.reasons
                if item.recommended_action is action
            }
        )
    else:
        action = RecommendedAction.NO_OP
        materiality = Materiality.NONE
        affected = []
        reasons = ["no_evidence"]

    return EvidenceDeltaDecision.build(
        asset=normalized_asset,
        state_scope=state_scope,
        canonical_state_id=normalized_state_id,
        has_relevant_delta=action is not RecommendedAction.NO_OP,
        materiality=materiality,
        recommended_action=action,
        affected_state_fields=affected,
        trigger_reasons=reasons,
        evaluated_items=evaluated,
        semantic_hashes=semantic_hashes,
    )


def _validate_previous_hashes(values: Mapping[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for raw_key, raw_hash in values.items():
        key = _required_text(raw_key)
        digest = str(raw_hash).strip().lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError(f"previous semantic hash is invalid for {key}")
        normalized[key] = digest
    return normalized


def _required_text(value: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError("value must not be blank")
    return normalized
