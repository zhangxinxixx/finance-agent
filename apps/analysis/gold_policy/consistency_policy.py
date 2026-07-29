"""Pure Analysis-Strategy consistency gate for the daily XAUUSD chain."""

from __future__ import annotations

import hashlib
import json

from pydantic import ValidationError

from apps.analysis.gold_policy.consistency_schemas import (
    AnalysisStrategyConsistencyDecision,
    AnalysisStrategyConsistencyInput,
    ConsistencyReasonCode,
    ConsistencyStatus,
    StrategyChangeKind,
    build_analysis_strategy_consistency_decision,
)
from apps.analysis.gold_policy.key_level_schemas import (
    KeyLevelLifecycle,
    KeyLevelTransitionAction,
)
from apps.analysis.gold_policy.schemas import SourceReference
from apps.analysis.gold_policy.state_schemas import AnalysisState, StateTransitionPolicyDecision
from apps.analysis.gold_policy.strategy_policy import evaluate_gold_strategy_policy
from apps.analysis.gold_policy.strategy_schemas import (
    NoTradeReasonCode,
    StrategyDecision,
    StrategyDirection,
    StrategyPolicyInput,
    StrategyStatus,
)


_INCONSISTENT_POLICY_INPUT_REASONS = {
    NoTradeReasonCode.INPUT_LINEAGE_INVALID,
    NoTradeReasonCode.INPUT_SCOPE_MISMATCH,
    NoTradeReasonCode.INPUT_TIME_INVALID,
    NoTradeReasonCode.INVALIDATION_NOT_CANONICAL,
}
_WATCH = {StrategyStatus.LONG_WATCH, StrategyStatus.SHORT_WATCH}
_TRIGGERED = {
    StrategyStatus.LONG_RESEARCH_TRIGGERED,
    StrategyStatus.SHORT_RESEARCH_TRIGGERED,
}


def evaluate_analysis_strategy_consistency(
    gate_input: AnalysisStrategyConsistencyInput,
) -> AnalysisStrategyConsistencyDecision:
    """Verify a candidate against formal policy proof and predecessor continuity."""

    current_input = gate_input.current_policy_input
    current_state = current_input.analysis_state
    transition = current_input.state_transition
    candidate = gate_input.candidate_strategy
    previous_policy_input = gate_input.previous_policy_input
    previous_state = gate_input.previous_state
    previous_transition = gate_input.previous_transition
    previous = gate_input.previous_strategy
    proof_hash = _proof_hash(gate_input)

    if not _identities_revalidate(gate_input):
        return _reject(
            gate_input,
            ConsistencyStatus.BLOCKED,
            ConsistencyReasonCode.IDENTITY_REVALIDATION_FAILED,
            proof_hash,
        )
    if transition.to_state_id != current_state.state_id or transition.to_stage is not current_state.stage:
        return _reject(
            gate_input,
            ConsistencyStatus.BLOCKED,
            ConsistencyReasonCode.CURRENT_STATE_TRANSITION_MISMATCH,
            proof_hash,
        )
    if candidate.analysis_state_id != current_state.state_id:
        return _reject(
            gate_input,
            ConsistencyStatus.BLOCKED,
            ConsistencyReasonCode.CURRENT_STRATEGY_STATE_MISMATCH,
            proof_hash,
        )
    if candidate.transition_decision_hash != transition.decision_hash:
        return _reject(
            gate_input,
            ConsistencyStatus.BLOCKED,
            ConsistencyReasonCode.CURRENT_STRATEGY_TRANSITION_MISMATCH,
            proof_hash,
        )
    if candidate.scope.value != current_state.scope.value or candidate.stage is not current_state.stage:
        return _reject(
            gate_input,
            ConsistencyStatus.BLOCKED,
            ConsistencyReasonCode.SCOPE_MISMATCH,
            proof_hash,
        )
    if candidate.decision_as_of != current_input.decision_as_of:
        return _reject(
            gate_input,
            ConsistencyStatus.BLOCKED,
            ConsistencyReasonCode.TIME_ORDER_INVALID,
            proof_hash,
        )
    if not _direction_matches_state(candidate, current_state):
        return _reject(
            gate_input,
            ConsistencyStatus.BLOCKED,
            ConsistencyReasonCode.STATE_DIRECTION_STRATEGY_CONFLICT,
            proof_hash,
        )

    expected = evaluate_gold_strategy_policy(current_input)
    if candidate.decision_id != expected.decision_id:
        return _reject(
            gate_input,
            ConsistencyStatus.BLOCKED,
            ConsistencyReasonCode.CURRENT_POLICY_OUTPUT_MISMATCH,
            proof_hash,
        )
    if candidate.no_trade_reason_code in _INCONSISTENT_POLICY_INPUT_REASONS:
        return _reject(
            gate_input,
            ConsistencyStatus.BLOCKED,
            ConsistencyReasonCode.CURRENT_INPUT_INCONSISTENT,
            proof_hash,
        )

    if previous_policy_input is None or previous_state is None or previous_transition is None or previous is None:
        if any(
            item is not None
            for item in (
                previous_policy_input,
                previous_state,
                previous_transition,
                previous,
            )
        ):
            return _reject(
                gate_input,
                ConsistencyStatus.UNVERIFIABLE,
                ConsistencyReasonCode.PREVIOUS_LINEAGE_MISSING,
                proof_hash,
            )
        if transition.from_state_id is not None or not transition.advance:
            return _reject(
                gate_input,
                ConsistencyStatus.UNVERIFIABLE,
                ConsistencyReasonCode.PREVIOUS_LINEAGE_MISSING,
                proof_hash,
            )
        return _accept(
            gate_input,
            StrategyChangeKind.BOOTSTRAP,
            ConsistencyReasonCode.BOOTSTRAP_ACCEPTED,
            proof_hash,
        )

    if (
        previous_policy_input.analysis_state.state_id != previous_state.state_id
        or previous_policy_input.state_transition.decision_hash != previous_transition.decision_hash
        or previous_policy_input.decision_as_of != previous.decision_as_of
    ):
        return _reject(
            gate_input,
            ConsistencyStatus.BLOCKED,
            ConsistencyReasonCode.PREVIOUS_POLICY_INPUT_MISMATCH,
            proof_hash,
        )
    if transition.from_state_id != previous_state.state_id:
        return _reject(
            gate_input,
            ConsistencyStatus.BLOCKED,
            ConsistencyReasonCode.PREVIOUS_STATE_TRANSITION_MISMATCH,
            proof_hash,
        )
    if previous.analysis_state_id != previous_state.state_id:
        return _reject(
            gate_input,
            ConsistencyStatus.BLOCKED,
            ConsistencyReasonCode.PREVIOUS_STRATEGY_STATE_MISMATCH,
            proof_hash,
        )
    if (
        previous_transition.to_state_id != previous_state.state_id
        or previous_transition.to_stage is not previous_state.stage
    ):
        return _reject(
            gate_input,
            ConsistencyStatus.BLOCKED,
            ConsistencyReasonCode.PREVIOUS_STATE_TRANSITION_MISMATCH,
            proof_hash,
        )
    if previous.transition_decision_hash != previous_transition.decision_hash:
        return _reject(
            gate_input,
            ConsistencyStatus.BLOCKED,
            ConsistencyReasonCode.PREVIOUS_STRATEGY_TRANSITION_MISMATCH,
            proof_hash,
        )
    if evaluate_gold_strategy_policy(previous_policy_input).decision_id != previous.decision_id:
        return _reject(
            gate_input,
            ConsistencyStatus.BLOCKED,
            ConsistencyReasonCode.PREVIOUS_POLICY_OUTPUT_MISMATCH,
            proof_hash,
        )
    if previous.scope.value != current_state.scope.value or previous_state.scope is not current_state.scope:
        return _reject(
            gate_input,
            ConsistencyStatus.BLOCKED,
            ConsistencyReasonCode.SCOPE_MISMATCH,
            proof_hash,
        )
    if (
        transition.evidence.scope is not current_state.scope
        or previous_transition.evidence.scope is not previous_state.scope
    ):
        return _reject(
            gate_input,
            ConsistencyStatus.BLOCKED,
            ConsistencyReasonCode.SCOPE_MISMATCH,
            proof_hash,
        )
    if candidate.decision_as_of < previous.decision_as_of:
        return _reject(
            gate_input,
            ConsistencyStatus.BLOCKED,
            ConsistencyReasonCode.TIME_ORDER_INVALID,
            proof_hash,
        )
    if (
        previous.decision_as_of < previous_state.as_of
        or previous_transition.evidence.as_of > previous.decision_as_of
        or (previous_transition.advance and previous_transition.evidence.as_of > previous_state.as_of)
        or current_state.as_of < previous_state.as_of
        or transition.evidence.as_of < previous_state.as_of
        or (transition.advance and transition.evidence.as_of > current_state.as_of)
    ):
        return _reject(
            gate_input,
            ConsistencyStatus.BLOCKED,
            ConsistencyReasonCode.TIME_ORDER_INVALID,
            proof_hash,
        )
    if candidate.decision_as_of == previous.decision_as_of and candidate.decision_id != previous.decision_id:
        return _reject(
            gate_input,
            ConsistencyStatus.BLOCKED,
            ConsistencyReasonCode.NON_IDEMPOTENT_REPLAY,
            proof_hash,
        )
    if not _direction_matches_state(previous, previous_state):
        return _reject(
            gate_input,
            ConsistencyStatus.BLOCKED,
            ConsistencyReasonCode.STATE_DIRECTION_STRATEGY_CONFLICT,
            proof_hash,
        )
    if _opposite_direction(previous.direction, candidate.direction):
        return _reject(
            gate_input,
            ConsistencyStatus.BLOCKED,
            ConsistencyReasonCode.DIRECT_DIRECTION_FLIP,
            proof_hash,
        )

    state_advanced = previous_state.state_id != current_state.state_id
    if state_advanced:
        if not transition.advance:
            return _reject(
                gate_input,
                ConsistencyStatus.BLOCKED,
                ConsistencyReasonCode.PREVIOUS_STATE_TRANSITION_MISMATCH,
                proof_hash,
            )
        if _level_disposition(previous) != _level_disposition(candidate) and not _all_changed_candidate_levels_proven(
            gate_input
        ):
            return _reject(
                gate_input,
                ConsistencyStatus.UNVERIFIABLE,
                ConsistencyReasonCode.UNSUPPORTED_READINESS_CHANGE,
                proof_hash,
            )
        if candidate.status in _TRIGGERED and previous.status not in _TRIGGERED:
            if not _verified_trigger_advance(gate_input):
                return _reject(
                    gate_input,
                    ConsistencyStatus.UNVERIFIABLE,
                    ConsistencyReasonCode.UNSUPPORTED_READINESS_CHANGE,
                    proof_hash,
                )
        if candidate.status is StrategyStatus.INVALIDATED and not _verified_invalidation(gate_input):
            return _reject(
                gate_input,
                ConsistencyStatus.UNVERIFIABLE,
                ConsistencyReasonCode.UNSUPPORTED_INVALIDATION,
                proof_hash,
            )
        return _accept(
            gate_input,
            StrategyChangeKind.STATE_ADVANCE,
            ConsistencyReasonCode.CANONICAL_STATE_ADVANCED,
            proof_hash,
        )

    if transition.advance:
        return _reject(
            gate_input,
            ConsistencyStatus.BLOCKED,
            ConsistencyReasonCode.PREVIOUS_STATE_TRANSITION_MISMATCH,
            proof_hash,
        )
    if candidate.decision_id == previous.decision_id:
        return _accept(
            gate_input,
            StrategyChangeKind.UNCHANGED,
            ConsistencyReasonCode.EXACT_DECISION_MAINTAINED,
            proof_hash,
        )
    if candidate.status == previous.status and candidate.direction is previous.direction:
        if _level_disposition(previous) == _level_disposition(candidate):
            return _accept(
                gate_input,
                StrategyChangeKind.STABLE_REFRESH,
                ConsistencyReasonCode.STABLE_STRATEGY_REFRESHED,
                proof_hash,
            )
        if not _all_changed_candidate_levels_proven(gate_input):
            return _reject(
                gate_input,
                ConsistencyStatus.UNVERIFIABLE,
                ConsistencyReasonCode.UNSUPPORTED_READINESS_CHANGE,
                proof_hash,
            )
        return _accept(
            gate_input,
            StrategyChangeKind.READINESS_CHANGED,
            ConsistencyReasonCode.TYPED_SUPPORT_CHANGED,
            proof_hash,
        )

    support_changed = _typed_support_changed(previous, candidate)
    if candidate.status is StrategyStatus.NO_TRADE:
        return _accept(
            gate_input,
            StrategyChangeKind.RISK_GATE_APPLIED,
            ConsistencyReasonCode.RISK_GATE_APPLIED,
            proof_hash,
        )
    if previous.status is StrategyStatus.NO_TRADE:
        if not support_changed:
            return _reject(
                gate_input,
                ConsistencyStatus.BLOCKED,
                ConsistencyReasonCode.UNSUPPORTED_STRATEGY_CHURN,
                proof_hash,
            )
        return _accept(
            gate_input,
            StrategyChangeKind.RISK_GATE_RELEASED,
            ConsistencyReasonCode.RISK_GATE_RELEASED,
            proof_hash,
        )
    if candidate.status in _TRIGGERED and previous.status in _WATCH:
        if not support_changed or not _verified_trigger_advance(gate_input):
            return _reject(
                gate_input,
                ConsistencyStatus.UNVERIFIABLE,
                ConsistencyReasonCode.UNSUPPORTED_READINESS_CHANGE,
                proof_hash,
            )
        return _accept(
            gate_input,
            StrategyChangeKind.READINESS_CHANGED,
            ConsistencyReasonCode.TYPED_SUPPORT_CHANGED,
            proof_hash,
        )
    if previous.status in _TRIGGERED and candidate.status in _WATCH:
        if not support_changed:
            return _reject(
                gate_input,
                ConsistencyStatus.BLOCKED,
                ConsistencyReasonCode.UNSUPPORTED_READINESS_CHANGE,
                proof_hash,
            )
        return _accept(
            gate_input,
            StrategyChangeKind.READINESS_CHANGED,
            ConsistencyReasonCode.TYPED_SUPPORT_CHANGED,
            proof_hash,
        )
    if candidate.status is StrategyStatus.INVALIDATED:
        if not _verified_invalidation(gate_input):
            return _reject(
                gate_input,
                ConsistencyStatus.UNVERIFIABLE,
                ConsistencyReasonCode.UNSUPPORTED_INVALIDATION,
                proof_hash,
            )
        return _accept(
            gate_input,
            StrategyChangeKind.INVALIDATED,
            ConsistencyReasonCode.FORMAL_INVALIDATION_CONFIRMED,
            proof_hash,
        )
    return _reject(
        gate_input,
        ConsistencyStatus.BLOCKED,
        ConsistencyReasonCode.UNSUPPORTED_STRATEGY_CHURN,
        proof_hash,
    )


def _direction_matches_state(decision: StrategyDecision, state: AnalysisState) -> bool:
    if decision.direction is StrategyDirection.LONG:
        return state.quality_status == "accepted" and state.directional_bias == "bullish"
    if decision.direction is StrategyDirection.SHORT:
        return state.quality_status == "accepted" and state.directional_bias == "bearish"
    return True


def _opposite_direction(previous: StrategyDirection, current: StrategyDirection) -> bool:
    return {previous, current} == {StrategyDirection.LONG, StrategyDirection.SHORT}


def _typed_support_changed(previous: StrategyDecision, current: StrategyDecision) -> bool:
    return any(
        (
            previous.feature_snapshot_id != current.feature_snapshot_id,
            previous.attribution_snapshot_ids != current.attribution_snapshot_ids,
            previous.options_snapshot_id != current.options_snapshot_id,
            previous.event_risk_snapshot_id != current.event_risk_snapshot_id,
            previous.key_level_state_ids != current.key_level_state_ids,
        )
    )


def _verified_trigger_advance(gate_input: AnalysisStrategyConsistencyInput) -> bool:
    previous = gate_input.previous_strategy
    candidate = gate_input.candidate_strategy
    if previous is None:
        return False
    trigger_refs = tuple(ref for ref in candidate.level_refs if ref.level_id in candidate.trigger_level_ids)
    return bool(trigger_refs) and all(
        any(
            (previous_ref.state_id == trigger_ref.state_id and previous_ref.lifecycle is KeyLevelLifecycle.HOLDING)
            or _level_chain_reaches(
                gate_input,
                level_id=trigger_ref.level_id,
                from_state_id=previous_ref.state_id,
                to_state_id=trigger_ref.state_id,
                final_action=KeyLevelTransitionAction.HOLD,
            )
            for previous_ref in previous.level_refs
            if previous_ref.level_id == trigger_ref.level_id
        )
        for trigger_ref in trigger_refs
    )


def _verified_invalidation(gate_input: AnalysisStrategyConsistencyInput) -> bool:
    transition = gate_input.current_policy_input.state_transition
    if transition.action.value == "invalidate" and transition.advance and transition.transition_allowed:
        return True
    candidate = gate_input.candidate_strategy
    previous = gate_input.previous_strategy
    if previous is None:
        return False
    invalidation_refs = tuple(
        ref
        for ref in candidate.level_refs
        if ref.level_id in candidate.invalidation_level_ids and ref.lifecycle is KeyLevelLifecycle.BROKEN
    )
    return bool(invalidation_refs) and all(
        any(
            _level_chain_reaches(
                gate_input,
                level_id=current_ref.level_id,
                from_state_id=previous_ref.state_id,
                to_state_id=current_ref.state_id,
                final_action=KeyLevelTransitionAction.BREAK,
            )
            for previous_ref in previous.level_refs
            if previous_ref.level_id == current_ref.level_id
        )
        for current_ref in invalidation_refs
    )


def _level_chain_reaches(
    gate_input: AnalysisStrategyConsistencyInput,
    *,
    level_id: str,
    from_state_id: str | None,
    to_state_id: str,
    final_action: KeyLevelTransitionAction | None = None,
) -> bool:
    reachable = {from_state_id}
    for decision in sorted(
        _key_level_proof(gate_input),
        key=lambda item: item.event.evidence.as_of,
    ):
        if (
            decision.event.spec.level_id == level_id
            and decision.advance
            and decision.from_state_id in reachable
            and decision.to_state_id is not None
        ):
            reachable.add(decision.to_state_id)
            if decision.to_state_id == to_state_id and (final_action is None or decision.action is final_action):
                return True
    return False


def _level_disposition(decision: StrategyDecision):
    return tuple(
        sorted(
            (
                ref.level_id,
                ref.state_id,
                ref.role.value,
                ref.comparator.value,
                ref.lifecycle.value,
            )
            for ref in decision.level_refs
        )
    )


def _all_changed_candidate_levels_proven(gate_input: AnalysisStrategyConsistencyInput) -> bool:
    previous = gate_input.previous_strategy
    if previous is None:
        return False
    previous_by_level = {ref.level_id: ref for ref in previous.level_refs}
    current_by_level = {ref.level_id: ref for ref in gate_input.candidate_strategy.level_refs}
    if set(previous_by_level).difference(current_by_level):
        return False
    changed = tuple(
        current_ref
        for level_id, current_ref in current_by_level.items()
        if level_id not in previous_by_level or previous_by_level[level_id].state_id != current_ref.state_id
    )
    return bool(changed) and all(
        _level_chain_reaches(
            gate_input,
            level_id=ref.level_id,
            from_state_id=(previous_by_level[ref.level_id].state_id if ref.level_id in previous_by_level else None),
            to_state_id=ref.state_id,
        )
        for ref in changed
    )


def _identities_revalidate(gate_input: AnalysisStrategyConsistencyInput) -> bool:
    try:
        StrategyPolicyInput.model_validate(gate_input.current_policy_input.model_dump(mode="json"))
        StrategyDecision.model_validate(gate_input.candidate_strategy.model_dump(mode="json"))
        AnalysisState.model_validate(gate_input.current_policy_input.analysis_state.model_dump(mode="json"))
        StateTransitionPolicyDecision.model_validate(
            gate_input.current_policy_input.state_transition.model_dump(mode="json")
        )
        if gate_input.previous_state is not None:
            AnalysisState.model_validate(gate_input.previous_state.model_dump(mode="json"))
        if gate_input.previous_policy_input is not None:
            StrategyPolicyInput.model_validate(gate_input.previous_policy_input.model_dump(mode="json"))
        if gate_input.previous_strategy is not None:
            StrategyDecision.model_validate(gate_input.previous_strategy.model_dump(mode="json"))
        if gate_input.previous_transition is not None:
            StateTransitionPolicyDecision.model_validate(gate_input.previous_transition.model_dump(mode="json"))
        for decision in gate_input.key_level_proof:
            type(decision).model_validate(decision.model_dump(mode="json"))
    except (ValidationError, ValueError):
        return False
    return True


def _proof_hash(gate_input: AnalysisStrategyConsistencyInput) -> str:
    current = gate_input.current_policy_input
    payload = {
        "previous_policy_input_hash": (
            _policy_input_hash(gate_input.previous_policy_input) if gate_input.previous_policy_input else None
        ),
        "previous_state_id": gate_input.previous_state.state_id if gate_input.previous_state else None,
        "previous_strategy_id": (gate_input.previous_strategy.decision_id if gate_input.previous_strategy else None),
        "previous_transition_hash": (
            gate_input.previous_transition.decision_hash if gate_input.previous_transition else None
        ),
        "current_state_id": current.analysis_state.state_id,
        "transition_hash": current.state_transition.decision_hash,
        "candidate_id": gate_input.candidate_strategy.decision_id,
        "feature_snapshot_id": current.feature_snapshot.snapshot_id,
        "attribution": _attribution_proof_payload(current),
        "options_snapshot_id": current.options_regime.snapshot_id,
        "event_risk_snapshot_id": current.event_risk.snapshot_id,
        "key_level_state_ids": sorted(level.state_id for level in current.key_levels),
        "key_level_decision_hashes": sorted(decision.decision_hash for decision in _key_level_proof(gate_input)),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _accept(
    gate_input: AnalysisStrategyConsistencyInput,
    kind: StrategyChangeKind,
    reason: ConsistencyReasonCode,
    proof_hash: str,
) -> AnalysisStrategyConsistencyDecision:
    return _decision(gate_input, ConsistencyStatus.CONSISTENT, kind, reason, proof_hash)


def _reject(
    gate_input: AnalysisStrategyConsistencyInput,
    status: ConsistencyStatus,
    reason: ConsistencyReasonCode,
    proof_hash: str,
) -> AnalysisStrategyConsistencyDecision:
    return _decision(gate_input, status, StrategyChangeKind.REJECTED, reason, proof_hash)


def _decision(
    gate_input: AnalysisStrategyConsistencyInput,
    status: ConsistencyStatus,
    kind: StrategyChangeKind,
    reason: ConsistencyReasonCode,
    proof_hash: str,
) -> AnalysisStrategyConsistencyDecision:
    candidate = gate_input.candidate_strategy
    refs = _source_refs(gate_input)
    consistent = status is ConsistencyStatus.CONSISTENT
    return build_analysis_strategy_consistency_decision(
        {
            "previous_state_id": (gate_input.previous_state.state_id if gate_input.previous_state else None),
            "previous_policy_input_hash": (
                _policy_input_hash(gate_input.previous_policy_input) if gate_input.previous_policy_input else None
            ),
            "previous_transition_decision_hash": (
                gate_input.previous_transition.decision_hash if gate_input.previous_transition else None
            ),
            "current_state_id": gate_input.current_policy_input.analysis_state.state_id,
            "previous_strategy_id": (
                gate_input.previous_strategy.decision_id if gate_input.previous_strategy else None
            ),
            "candidate_strategy_id": candidate.decision_id,
            "transition_decision_hash": gate_input.current_policy_input.state_transition.decision_hash,
            "proof_hash": proof_hash,
            "status": status,
            "change_kind": kind,
            "consistency_passed": consistent,
            "selected_strategy_decision_id": candidate.decision_id if consistent else None,
            "reason_codes": (reason,),
            "source_refs": refs,
        }
    )


def _source_refs(gate_input: AnalysisStrategyConsistencyInput) -> tuple[SourceReference, ...]:
    refs = [
        *gate_input.current_policy_input.analysis_state.source_refs,
        *gate_input.current_policy_input.state_transition.evidence.source_refs,
        *gate_input.candidate_strategy.source_refs,
    ]
    if gate_input.previous_state is not None:
        refs.extend(gate_input.previous_state.source_refs)
    if gate_input.previous_strategy is not None:
        refs.extend(gate_input.previous_strategy.source_refs)
    if gate_input.previous_transition is not None:
        refs.extend(gate_input.previous_transition.evidence.source_refs)
    refs.extend(ref for decision in gate_input.key_level_proof for ref in decision.event.evidence.source_refs)
    unique = {(ref.source, ref.reference, ref.retrieved_at): ref for ref in refs}
    return tuple(unique[key] for key in sorted(unique))


def _key_level_proof(gate_input: AnalysisStrategyConsistencyInput):
    decisions = {
        item.decision_hash: item
        for item in (
            *gate_input.current_policy_input.key_level_decisions,
            *gate_input.key_level_proof,
        )
    }
    return tuple(decisions[key] for key in sorted(decisions))


def _attribution_proof_payload(current: StrategyPolicyInput):
    payload = current.price_attribution.model_dump(mode="json")
    payload["source_refs"] = sorted(
        payload["source_refs"],
        key=lambda ref: (ref["source"], ref["reference"], ref["retrieved_at"]),
    )
    for group in ("primary_drivers", "secondary_drivers", "counter_drivers"):
        for driver in payload[group]:
            driver["source_refs"] = sorted(
                driver["source_refs"],
                key=lambda ref: (ref["source"], ref["reference"], ref["retrieved_at"]),
            )
    return payload


def _policy_input_hash(policy_input: StrategyPolicyInput) -> str:
    payload = policy_input.model_dump(mode="json")
    payload["price_attribution"] = _attribution_proof_payload(policy_input)
    payload["key_levels"] = sorted(payload["key_levels"], key=lambda level: level["state_id"])
    payload["key_level_decisions"] = sorted(
        payload["key_level_decisions"],
        key=lambda decision: decision["decision_hash"],
    )
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
