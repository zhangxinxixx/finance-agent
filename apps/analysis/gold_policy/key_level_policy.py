"""Deterministic lifecycle policy for formal XAUUSD key levels."""

from __future__ import annotations

from dataclasses import dataclass

from apps.analysis.gold_policy.key_level_schemas import (
    KeyLevelEvent,
    KeyLevelEventType,
    KeyLevelAuthorityStatus,
    KeyLevelCalculationMethod,
    KeyLevelComparator,
    KeyLevelEvidence,
    KeyLevelEvidenceFactor,
    KeyLevelLifecycle,
    KeyLevelLifecycleDecision,
    KeyLevelReadModel,
    KeyLevelPublicationStatus,
    KeyLevelQualificationClass,
    KeyLevelRetirementRule,
    KeyLevelRuleCode,
    KeyLevelSourceRole,
    KeyLevelTransitionAction,
    _build_key_level_read_model,
    build_key_level_lifecycle_decision,
    key_level_strategy_eligible,
)
from apps.analysis.gold_policy.schemas import SourceReference


_PROPOSAL_ONLY_ROLES = {
    KeyLevelSourceRole.CME_LARGE_OI,
    KeyLevelSourceRole.JIN10_SUPPLEMENTAL,
    KeyLevelSourceRole.LLM_EXTRACTED,
    KeyLevelSourceRole.MANUAL_OBSERVATION,
    KeyLevelSourceRole.VALIDATION_FALLBACK,
}
_MODEL_CONFIRMATION_FACTORS = {
    KeyLevelEvidenceFactor.GEX_WALL,
    KeyLevelEvidenceFactor.OI_CHANGE,
    KeyLevelEvidenceFactor.VOLUME,
    KeyLevelEvidenceFactor.PRICE_STRUCTURE,
    KeyLevelEvidenceFactor.REPEATED_REACTION,
}


@dataclass(frozen=True, slots=True)
class KeyLevelLifecycleResult:
    decision: KeyLevelLifecycleDecision
    state: KeyLevelReadModel | None


def evaluate_key_level_lifecycle(
    previous: KeyLevelReadModel | None,
    event: KeyLevelEvent,
) -> KeyLevelLifecycleResult:
    """Apply one typed event without I/O, clocks, prose, or caller-owned eligibility."""

    if previous is not None and event.spec.level_id != previous.spec.level_id:
        return _preserve(previous, event, reason="LEVEL_IDENTITY_MISMATCH")
    if previous is not None and event.evidence.as_of < previous.as_of:
        return _preserve(previous, event, reason="STALE_OR_REPLAYED_LEVEL_EVENT")
    if previous is not None and event.event_id == previous.last_event_id:
        return _preserve(
            previous,
            event,
            reason="DUPLICATE_LEVEL_EVENT",
            transition_allowed=True,
            action=KeyLevelTransitionAction.MAINTAIN,
        )
    if previous is not None and event.evidence.as_of == previous.as_of:
        return _preserve(previous, event, reason="CONFLICTING_SAME_TIME_EVENT")

    if previous is None:
        return _bootstrap(event)
    if event.event_type is KeyLevelEventType.NO_OP:
        return _preserve(
            previous,
            event,
            reason="NO_MATERIAL_LEVEL_EVENT",
            transition_allowed=True,
            action=KeyLevelTransitionAction.MAINTAIN,
        )
    if previous.lifecycle is KeyLevelLifecycle.RETIRED:
        return _preserve(previous, event, reason="RETIRED_LEVEL_IMMUTABLE")
    if not _evidence_ready(event.evidence):
        return _preserve(previous, event, reason="LEVEL_EVIDENCE_NOT_READY")

    event_type = event.event_type
    if event_type is KeyLevelEventType.DISCOVER:
        return _preserve(
            previous,
            event,
            reason="LEVEL_ALREADY_DISCOVERED",
            transition_allowed=True,
            action=KeyLevelTransitionAction.MAINTAIN,
        )
    if event_type is KeyLevelEventType.CONFIRM:
        if previous.lifecycle is not KeyLevelLifecycle.CANDIDATE:
            return _preserve(previous, event, reason="CONFIRM_REQUIRES_CANDIDATE")
        if not _confirmation_ready(event):
            return _preserve(previous, event, reason=_confirmation_rejection(event.evidence))
        return _advance(
            previous,
            event,
            lifecycle=KeyLevelLifecycle.CONFIRMED,
            action=KeyLevelTransitionAction.CONFIRM,
            test_count=0,
            reason="LEVEL_CONFIRMATION_SATISFIED",
        )
    if event_type is KeyLevelEventType.ACTIVATE:
        if previous.lifecycle is not KeyLevelLifecycle.CONFIRMED:
            return _preserve(previous, event, reason="ACTIVATION_REQUIRES_CONFIRMED")
        if event.evidence.as_of < previous.spec.effective_from:
            return _preserve(previous, event, reason="ACTIVATION_WINDOW_PENDING")
        if not _official_price_evidence(
            event,
            {KeyLevelEvidenceFactor.OFFICIAL_CLOSE, KeyLevelEvidenceFactor.PRICE_STRUCTURE},
            expected_rule="price_structure",
        ):
            return _preserve(previous, event, reason="ACTIVATION_REQUIRES_CANONICAL_XAUUSD")
        return _advance(
            previous,
            event,
            lifecycle=KeyLevelLifecycle.ACTIVE,
            action=KeyLevelTransitionAction.ACTIVATE,
            test_count=0,
            reason="LEVEL_ACTIVATED",
        )
    if event_type is KeyLevelEventType.APPROACH:
        return _preserve(
            previous,
            event,
            reason="LEVEL_APPROACH_ONLY",
            transition_allowed=True,
            action=KeyLevelTransitionAction.MAINTAIN,
        )
    if event_type is KeyLevelEventType.TOUCH:
        if previous.lifecycle not in {KeyLevelLifecycle.ACTIVE, KeyLevelLifecycle.HOLDING}:
            return _preserve(previous, event, reason="TOUCH_REQUIRES_ACTIVE_LEVEL")
        if not _official_price_evidence(
            event,
            {KeyLevelEvidenceFactor.PRICE_TOUCH},
            expected_rule="touch",
        ):
            return _preserve(previous, event, reason="TOUCH_REQUIRES_CANONICAL_XAUUSD")
        return _advance(
            previous,
            event,
            lifecycle=KeyLevelLifecycle.TESTED,
            action=KeyLevelTransitionAction.TEST,
            test_count=previous.test_count + 1,
            reason="LEVEL_TEST_STARTED",
        )
    if event_type is KeyLevelEventType.HOLD_CONFIRMED:
        if previous.lifecycle not in {KeyLevelLifecycle.TESTED, KeyLevelLifecycle.HOLDING}:
            return _preserve(previous, event, reason="HOLD_REQUIRES_TESTED_LEVEL")
        if not _official_price_evidence(
            event,
            {KeyLevelEvidenceFactor.OFFICIAL_CLOSE, KeyLevelEvidenceFactor.HOLD_WINDOW},
            expected_rule="hold",
        ):
            return _preserve(previous, event, reason="HOLD_REQUIRES_CANONICAL_WINDOW")
        return _advance(
            previous,
            event,
            lifecycle=KeyLevelLifecycle.HOLDING,
            action=KeyLevelTransitionAction.HOLD,
            test_count=max(1, previous.test_count),
            reason="LEVEL_HOLD_CONFIRMED",
        )
    if event_type is KeyLevelEventType.BREAK_CONFIRMED:
        if previous.lifecycle not in {
            KeyLevelLifecycle.ACTIVE,
            KeyLevelLifecycle.TESTED,
            KeyLevelLifecycle.HOLDING,
            KeyLevelLifecycle.RECLAIMED,
        }:
            return _preserve(previous, event, reason="BREAK_REQUIRES_LIVE_LEVEL")
        if not _official_price_evidence(
            event,
            {KeyLevelEvidenceFactor.OFFICIAL_CLOSE, KeyLevelEvidenceFactor.BREAK_WINDOW},
            expected_rule="break",
        ):
            return _preserve(previous, event, reason="BREAK_CONFIRMATION_PENDING")
        return _advance(
            previous,
            event,
            lifecycle=KeyLevelLifecycle.BROKEN,
            action=KeyLevelTransitionAction.BREAK,
            test_count=previous.test_count,
            reason="LEVEL_BREAK_CONFIRMED",
        )
    if event_type is KeyLevelEventType.RECLAIM_CONFIRMED:
        if previous.lifecycle is not KeyLevelLifecycle.BROKEN:
            return _preserve(previous, event, reason="RECLAIM_REQUIRES_BROKEN_LEVEL")
        if not _official_price_evidence(
            event,
            {KeyLevelEvidenceFactor.OFFICIAL_CLOSE, KeyLevelEvidenceFactor.RECLAIM_WINDOW},
            expected_rule="reclaim",
        ):
            return _preserve(previous, event, reason="RECLAIM_CONFIRMATION_PENDING")
        return _advance(
            previous,
            event,
            lifecycle=KeyLevelLifecycle.RECLAIMED,
            action=KeyLevelTransitionAction.RECLAIM,
            test_count=previous.test_count,
            reason="LEVEL_RECLAIM_CONFIRMED",
        )
    if event_type is KeyLevelEventType.RECLAIM_HOLD_CONFIRMED:
        if previous.lifecycle is not KeyLevelLifecycle.RECLAIMED:
            return _preserve(previous, event, reason="RECLAIM_HOLD_REQUIRES_RECLAIMED")
        if not _official_price_evidence(
            event,
            {KeyLevelEvidenceFactor.OFFICIAL_CLOSE, KeyLevelEvidenceFactor.HOLD_WINDOW},
            expected_rule="hold",
        ):
            return _preserve(previous, event, reason="RECLAIM_HOLD_CONFIRMATION_PENDING")
        return _advance(
            previous,
            event,
            lifecycle=KeyLevelLifecycle.HOLDING,
            action=KeyLevelTransitionAction.HOLD,
            test_count=max(1, previous.test_count),
            reason="RECLAIM_HOLD_CONFIRMED",
        )
    if event_type is KeyLevelEventType.RETIRE:
        if not _retirement_ready(previous, event):
            return _preserve(previous, event, reason="RETIREMENT_EVIDENCE_NOT_AUTHORIZED")
        return _advance(
            previous,
            event,
            lifecycle=KeyLevelLifecycle.RETIRED,
            action=KeyLevelTransitionAction.RETIRE,
            test_count=previous.test_count,
            reason=f"LEVEL_RETIRED:{event.retirement_rule.value}",
        )
    return _preserve(previous, event, reason="UNSUPPORTED_LEVEL_EVENT")


def _bootstrap(event: KeyLevelEvent) -> KeyLevelLifecycleResult:
    evidence = event.evidence
    if event.event_type is KeyLevelEventType.NO_OP:
        return _preserve(
            None,
            event,
            reason="INITIAL_NO_OP_HAS_NO_LEVEL",
            action=KeyLevelTransitionAction.MAINTAIN,
        )
    if event.event_type is not KeyLevelEventType.DISCOVER:
        return _preserve(None, event, reason="INITIAL_EVENT_MUST_DISCOVER")
    if evidence.quality_status == "blocked" or evidence.freshness_status == "missing":
        return _preserve(None, event, reason="INITIAL_LEVEL_EVIDENCE_BLOCKED")
    quality_status = (
        "accepted" if evidence.quality_status == "accepted" and evidence.freshness_status == "fresh" else "observe"
    )
    state = _state(
        previous=None,
        event=event,
        lifecycle=KeyLevelLifecycle.CANDIDATE,
        quality_status=quality_status,
        test_count=0,
    )
    reason = {
        KeyLevelSourceRole.JIN10_SUPPLEMENTAL: "PROPOSAL_ONLY_SOURCE",
        KeyLevelSourceRole.LLM_EXTRACTED: "LLM_LEVEL_CANDIDATE_ONLY",
        KeyLevelSourceRole.CME_LARGE_OI: "SINGLE_OI_OBSERVATION",
    }.get(evidence.source_role, "LEVEL_CANDIDATE_DISCOVERED")
    return _result(
        previous=None,
        state=state,
        event=event,
        action=KeyLevelTransitionAction.DISCOVER,
        transition_allowed=True,
        reason=reason,
    )


def _evidence_ready(evidence: KeyLevelEvidence) -> bool:
    return (
        evidence.quality_status == "accepted"
        and evidence.freshness_status == "fresh"
        and evidence.alignment_status == "aligned"
    )


def _confirmation_ready(event: KeyLevelEvent) -> bool:
    evidence = event.evidence
    factors = set(evidence.factors)
    if evidence.source_role is KeyLevelSourceRole.CME_OPTIONS_MODEL:
        receipt = evidence.qualification_receipt
        return (
            receipt.qualification_class is KeyLevelQualificationClass.FORMAL_STRUCTURE
            and receipt.publication_status is KeyLevelPublicationStatus.FINAL
            and receipt.calculation_method is KeyLevelCalculationMethod.BLACK76
            and receipt.previous_snapshot_id is not None
            and receipt.previous_snapshot_as_of is not None
            and len(factors.intersection(_MODEL_CONFIRMATION_FACTORS)) >= 2
        )
    if evidence.source_role is KeyLevelSourceRole.OFFICIAL_MARKET:
        return {
            KeyLevelEvidenceFactor.PRICE_STRUCTURE,
            KeyLevelEvidenceFactor.REPEATED_REACTION,
        }.issubset(factors) and _repeated_reaction_ready(event)
    return False


def _confirmation_rejection(evidence: KeyLevelEvidence) -> str:
    if evidence.source_role is KeyLevelSourceRole.CME_LARGE_OI:
        return "SINGLE_OI_CANNOT_CONFIRM"
    if evidence.source_role is KeyLevelSourceRole.VALIDATION_FALLBACK:
        return "VALIDATION_SOURCE_CANNOT_CONFIRM"
    if evidence.source_role in _PROPOSAL_ONLY_ROLES:
        return "PROPOSAL_SOURCE_CANNOT_CONFIRM"
    return "CONFIRMATION_FACTORS_INSUFFICIENT"


def _official_price_evidence(
    event: KeyLevelEvent,
    required_factors: set[KeyLevelEvidenceFactor],
    *,
    expected_rule: str,
) -> bool:
    evidence = event.evidence
    fact = evidence.price_fact
    if not (
        evidence.source_role is KeyLevelSourceRole.OFFICIAL_MARKET
        and required_factors.issubset(set(evidence.factors))
        and fact is not None
        and fact.window_complete
        and fact.rule_code == expected_rule
    ):
        return False
    if expected_rule == "price_structure":
        return True
    spec = event.spec
    lower = spec.reference_price if spec.reference_price is not None else spec.band_lower
    upper = spec.reference_price if spec.reference_price is not None else spec.band_upper
    if lower is None or upper is None:
        return False
    if expected_rule == "touch":
        return fact.low <= upper and fact.high >= lower
    holds_above = spec.comparator is KeyLevelComparator.ABOVE_OR_EQUAL
    holds_below = spec.comparator is KeyLevelComparator.BELOW_OR_EQUAL
    if expected_rule in {"hold", "reclaim"}:
        return (holds_above and all(close >= lower for close in fact.window_closes)) or (
            holds_below and all(close <= upper for close in fact.window_closes)
        )
    if expected_rule == "break" and len(fact.window_closes) >= 2:
        return (holds_above and all(close < lower for close in fact.window_closes)) or (
            holds_below and all(close > upper for close in fact.window_closes)
        )
    return False


def _repeated_reaction_ready(event: KeyLevelEvent) -> bool:
    fact = event.evidence.price_fact
    if fact is None or not fact.window_complete or fact.rule_code != "price_structure":
        return False
    spec = event.spec
    lower = spec.reference_price if spec.reference_price is not None else spec.band_lower
    upper = spec.reference_price if spec.reference_price is not None else spec.band_upper
    if lower is None or upper is None:
        return False
    anchor = spec.reference_price or (lower + upper) / 2
    tolerance = anchor * spec.rule_set.reaction_tolerance_bps / 10_000
    reaction_count = sum(1 for close in fact.window_closes if lower - tolerance <= close <= upper + tolerance)
    return reaction_count >= spec.rule_set.repeated_reaction_min_count


def _retirement_ready(previous: KeyLevelReadModel, event: KeyLevelEvent) -> bool:
    evidence = event.evidence
    receipt = evidence.qualification_receipt
    if (
        evidence.source_role is not KeyLevelSourceRole.SYSTEM_SCHEDULER
        or receipt.qualification_class is not KeyLevelQualificationClass.SYSTEM_AUTHORITY
        or event.retirement_rule is None
    ):
        return False
    required_factor = {
        KeyLevelRetirementRule.CONTRACT_EXPIRED: KeyLevelEvidenceFactor.CONTRACT_EXPIRY,
        KeyLevelRetirementRule.VALIDITY_EXPIRED: KeyLevelEvidenceFactor.VALIDITY_EXPIRED,
        KeyLevelRetirementRule.CONFIRMATION_TIMEOUT: KeyLevelEvidenceFactor.CONFIRMATION_TIMEOUT,
        KeyLevelRetirementRule.FAILURE_WINDOW_ELAPSED: (KeyLevelEvidenceFactor.FAILURE_WINDOW_ELAPSED),
    }[event.retirement_rule]
    if required_factor not in evidence.factors:
        return False
    if event.retirement_rule is KeyLevelRetirementRule.CONTRACT_EXPIRED:
        return (
            previous.spec.origin_source_role in {KeyLevelSourceRole.CME_OPTIONS_MODEL, KeyLevelSourceRole.CME_LARGE_OI}
            and previous.spec.origin_contract_id == receipt.contract_id
            and evidence.as_of >= previous.spec.expires_at
        )
    if event.retirement_rule is KeyLevelRetirementRule.VALIDITY_EXPIRED:
        return evidence.as_of >= previous.spec.expires_at
    if event.retirement_rule is KeyLevelRetirementRule.CONFIRMATION_TIMEOUT:
        return (
            previous.lifecycle in {KeyLevelLifecycle.CANDIDATE, KeyLevelLifecycle.CONFIRMED}
            and evidence.as_of >= previous.spec.expires_at
        )
    if event.retirement_rule is KeyLevelRetirementRule.FAILURE_WINDOW_ELAPSED:
        return (
            previous.lifecycle in {KeyLevelLifecycle.BROKEN, KeyLevelLifecycle.RECLAIMED}
            and (evidence.as_of - previous.as_of).total_seconds() >= previous.spec.rule_set.failure_window_seconds
        )
    return True


def _advance(
    previous: KeyLevelReadModel,
    event: KeyLevelEvent,
    *,
    lifecycle: KeyLevelLifecycle,
    action: KeyLevelTransitionAction,
    test_count: int,
    reason: str,
) -> KeyLevelLifecycleResult:
    state = _state(
        previous=previous,
        event=event,
        lifecycle=lifecycle,
        quality_status="accepted",
        test_count=test_count,
    )
    return _result(
        previous=previous,
        state=state,
        event=event,
        action=action,
        transition_allowed=True,
        reason=reason,
    )


def _state(
    *,
    previous: KeyLevelReadModel | None,
    event: KeyLevelEvent,
    lifecycle: KeyLevelLifecycle,
    quality_status: str,
    test_count: int,
) -> KeyLevelReadModel:
    source_refs: list[SourceReference] = list(event.evidence.source_refs)
    source_refs.append(
        SourceReference(
            source="key_level_event",
            reference=event.event_id,
            retrieved_at=event.evidence.as_of,
        )
    )
    previous_state_id = None
    if previous is not None:
        previous_state_id = previous.state_id
        source_refs.append(
            SourceReference(
                source="key_level_state",
                reference=previous.state_id,
                retrieved_at=previous.as_of,
            )
        )
    if lifecycle is KeyLevelLifecycle.CANDIDATE:
        authority_status = KeyLevelAuthorityStatus.CANDIDATE_ONLY
        activation_event = None
    elif lifecycle is KeyLevelLifecycle.CONFIRMED:
        authority_status = KeyLevelAuthorityStatus.FORMALLY_CONFIRMED
        activation_event = None
    elif lifecycle is KeyLevelLifecycle.ACTIVE:
        authority_status = KeyLevelAuthorityStatus.CANONICAL_XAUUSD_VALIDATED
        activation_event = event
    else:
        if previous is None:
            raise ValueError("post-activation lifecycle requires previous state lineage")
        authority_status = previous.authority_status
        activation_event = previous.activation_event
    if lifecycle in {KeyLevelLifecycle.CANDIDATE, KeyLevelLifecycle.CONFIRMED}:
        activation_event = None
    strategy_eligible = key_level_strategy_eligible(
        spec=event.spec,
        lifecycle=lifecycle,
        authority_status=authority_status,
        activation_event=activation_event,
        quality_status=quality_status,
        as_of=event.evidence.as_of,
    )
    return _build_key_level_read_model(
        {
            "spec": event.spec,
            "lifecycle": lifecycle,
            "authority_status": authority_status,
            "activation_event": activation_event,
            "strategy_eligible": strategy_eligible,
            "as_of": event.evidence.as_of,
            "quality_status": quality_status,
            "last_event_id": event.event_id,
            "test_count": test_count,
            "previous_state_id": previous_state_id,
            "source_refs": tuple(source_refs),
        }
    )


def _result(
    *,
    previous: KeyLevelReadModel | None,
    state: KeyLevelReadModel,
    event: KeyLevelEvent,
    action: KeyLevelTransitionAction,
    transition_allowed: bool,
    reason: str,
) -> KeyLevelLifecycleResult:
    decision = build_key_level_lifecycle_decision(
        {
            "from_state_id": previous.state_id if previous is not None else None,
            "to_state_id": state.state_id,
            "from_lifecycle": previous.lifecycle if previous is not None else None,
            "to_lifecycle": state.lifecycle,
            "action": action,
            "transition_allowed": transition_allowed,
            "advance": previous is None or previous.state_id != state.state_id,
            "from_strategy_eligible": (previous.strategy_eligible if previous is not None else False),
            "to_strategy_eligible": state.strategy_eligible,
            "event": event,
            "triggered_rule": _rule_for(action, event),
            "reasons": (reason,),
        }
    )
    return KeyLevelLifecycleResult(decision=decision, state=state)


def _preserve(
    previous: KeyLevelReadModel | None,
    event: KeyLevelEvent,
    *,
    reason: str,
    transition_allowed: bool = False,
    action: KeyLevelTransitionAction = KeyLevelTransitionAction.REJECT,
) -> KeyLevelLifecycleResult:
    decision = build_key_level_lifecycle_decision(
        {
            "from_state_id": previous.state_id if previous is not None else None,
            "to_state_id": previous.state_id if previous is not None else None,
            "from_lifecycle": previous.lifecycle if previous is not None else None,
            "to_lifecycle": previous.lifecycle if previous is not None else None,
            "action": action,
            "transition_allowed": transition_allowed,
            "advance": False,
            "from_strategy_eligible": (previous.strategy_eligible if previous is not None else False),
            "to_strategy_eligible": (previous.strategy_eligible if previous is not None else False),
            "event": event,
            "triggered_rule": _rule_for(action, event),
            "reasons": (reason,),
        }
    )
    return KeyLevelLifecycleResult(decision=decision, state=previous)


def _rule_for(
    action: KeyLevelTransitionAction,
    event: KeyLevelEvent,
) -> KeyLevelRuleCode:
    if action is KeyLevelTransitionAction.DISCOVER:
        return KeyLevelRuleCode.DISCOVER_PROPOSAL
    if action is KeyLevelTransitionAction.CONFIRM:
        return (
            KeyLevelRuleCode.CONFIRM_CME_TWO_SNAPSHOT
            if event.evidence.source_role is KeyLevelSourceRole.CME_OPTIONS_MODEL
            else KeyLevelRuleCode.CONFIRM_REPEATED_PRICE
        )
    if action is KeyLevelTransitionAction.ACTIVATE:
        return KeyLevelRuleCode.ACTIVATE_CANONICAL_CLOSE
    if action is KeyLevelTransitionAction.TEST:
        return KeyLevelRuleCode.TOUCH_CANONICAL_RANGE
    if action is KeyLevelTransitionAction.HOLD:
        return KeyLevelRuleCode.HOLD_CANONICAL_WINDOW
    if action is KeyLevelTransitionAction.BREAK:
        return KeyLevelRuleCode.BREAK_CANONICAL_WINDOW
    if action is KeyLevelTransitionAction.RECLAIM:
        return KeyLevelRuleCode.RECLAIM_CANONICAL_WINDOW
    if action is KeyLevelTransitionAction.RETIRE:
        return KeyLevelRuleCode.RETIRE_SYSTEM_RULE
    if action is KeyLevelTransitionAction.MAINTAIN:
        return (
            KeyLevelRuleCode.MAINTAIN_NO_OP
            if event.event_type is KeyLevelEventType.NO_OP
            else KeyLevelRuleCode.APPROACH_OBSERVE
        )
    return KeyLevelRuleCode.REJECT_FAIL_CLOSED
