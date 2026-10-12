"""Pure builders for authoritative Gold daily-close runtime controls."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel

from apps.analysis.gold_policy.analysis_policy import evaluate_gold_analysis_policy
from apps.analysis.gold_policy.attribution_policy import attribute_gold_price
from apps.analysis.gold_policy.daily_close_runtime import GoldDailyCloseRuntimeControls
from apps.analysis.gold_policy.feature_snapshot import feature_snapshot_integrity_valid
from apps.analysis.gold_policy.key_level_controls import (
    KeyLevelControls,
    KeyLevelControlsBuilder,
    KeyLevelControlsInput,
)
from apps.analysis.gold_policy.key_level_schemas import (
    KeyLevelAuthorityStatus,
    KeyLevelEventType,
    KeyLevelLifecycle,
    KeyLevelLifecycleDecision,
    KeyLevelReadModel,
    KeyLevelRole,
    KeyLevelRuleCode,
    KeyLevelSourceInstrument,
    KeyLevelSourceRole,
    KeyLevelTransitionAction,
)
from apps.analysis.gold_policy.readiness_policy import _event_readiness
from apps.analysis.gold_policy.schemas import (
    FeatureSnapshotContract,
    FeatureSnapshotV2,
    OfficialEventSnapshot,
    SourceReference,
)
from apps.analysis.gold_policy.state_schemas import (
    EvidenceCategory,
    EvidenceDeltaKind,
    HardInvalidationRule,
    MajorConfirmationRule,
    StateTransitionPolicyDecision,
    StateTransitionPolicyDecisionV2,
    TransitionEvidence,
    canonical_state_transition_decision_json,
    canonical_state_transition_decision_v2_json,
)
from apps.analysis.gold_policy.strategy_schemas import (
    StrategyOptionsRegimeContract,
    build_strategy_event_risk,
    build_strategy_options_regime,
)


def build_gold_daily_close_runtime_controls(
    *,
    current_feature: FeatureSnapshotContract,
    previous_feature: FeatureSnapshotContract | None,
    decision_as_of: datetime,
    previous_transition: (StateTransitionPolicyDecision | StateTransitionPolicyDecisionV2 | None) = None,
    options_regime_snapshot: StrategyOptionsRegimeContract | None = None,
    key_level_controls_input: KeyLevelControlsInput | None = None,
) -> GoldDailyCloseRuntimeControls:
    """Build fail-closed controls from typed inputs without I/O or prose."""

    decision_time = _aware_utc(decision_as_of)
    if current_feature.as_of > decision_time:
        raise ValueError("current feature cannot be after runtime decision_as_of")
    if current_feature.as_of.date() != decision_time.date():
        raise ValueError("current feature and runtime controls must share a UTC session date")

    analysis = evaluate_gold_analysis_policy(current_feature, previous_feature)
    attribution = attribute_gold_price(current_feature, previous_feature)
    ordinary_evidence = _transition_evidence(
        current=current_feature,
        analysis=analysis,
        attribution=attribution,
        decision_as_of=decision_time,
        previous_transition=previous_transition,
    )
    options = options_regime_snapshot or _options_regime(current_feature, decision_time)
    if options.source_snapshot_id != current_feature.snapshot_id:
        raise ValueError("options regime must bind the current feature snapshot")
    if options.as_of != decision_time:
        raise ValueError("options regime must align to runtime decision_as_of")
    event_risk = _event_risk(current_feature, decision_time)
    if key_level_controls_input is None:
        key_level_controls = KeyLevelControlsBuilder().build(
            KeyLevelControlsInput(
                decision_as_of=decision_time,
                scope="daily_close",
            )
        )
        reasons = ["KEY_LEVEL_CONTROLS_EMPTY_NO_FORMAL_LIFECYCLE_INPUT"]
    else:
        if key_level_controls_input.decision_as_of != decision_time:
            raise ValueError("key-level controls must align to runtime decision_as_of")
        if key_level_controls_input.scope.value != "daily_close":
            raise ValueError("key-level controls must use daily_close scope")
        key_level_controls = KeyLevelControlsBuilder().build(key_level_controls_input)
        reasons = list(key_level_controls.reason_codes)
    hard_evidence, hard_reason = _hard_invalidation_evidence(
        current=current_feature,
        previous=previous_feature,
        previous_transition=previous_transition,
        decision_as_of=decision_time,
        controls=key_level_controls,
    )
    evidence = hard_evidence or ordinary_evidence
    if hard_reason is not None:
        reasons.append(hard_reason)
    if options.regime.value == "unavailable":
        reasons.append("OPTIONS_REGIME_UNAVAILABLE")
    formal_reason_codes = getattr(options, "reason_codes", ())
    reasons.extend(str(code) for code in formal_reason_codes)
    if event_risk.risk_status.value == "unavailable":
        reasons.append("EVENT_RISK_UNAVAILABLE")
    return GoldDailyCloseRuntimeControls(
        decision_as_of=decision_time,
        transition_evidence=evidence,
        options_regime=options,
        event_risk=event_risk,
        key_levels=key_level_controls.key_levels,
        key_level_decisions=key_level_controls.key_level_decisions,
        key_level_proof=key_level_controls.key_level_proof,
        reason_codes=tuple(dict.fromkeys(reasons)),
    )


def _hard_invalidation_evidence(
    *,
    current: FeatureSnapshotContract,
    previous: FeatureSnapshotContract | None,
    previous_transition: StateTransitionPolicyDecision | StateTransitionPolicyDecisionV2 | None,
    decision_as_of: datetime,
    controls: KeyLevelControls,
) -> tuple[TransitionEvidence | None, str | None]:
    """Promote only a freshly recomputed, fully linked canonical break proof."""

    target_roles = {KeyLevelRole.SUPPORT, KeyLevelRole.RESISTANCE}
    states = {state.state_id: state for state in controls.key_levels}
    structural_candidates = tuple(
        (decision, states.get(decision.to_state_id))
        for decision in controls.key_level_proof
        if decision.action is KeyLevelTransitionAction.BREAK
        and decision.transition_allowed
        and decision.advance
        and decision.triggered_rule is KeyLevelRuleCode.BREAK_CANONICAL_WINDOW
        and decision.to_lifecycle is KeyLevelLifecycle.BROKEN
        and decision.event.event_type is KeyLevelEventType.BREAK_CONFIRMED
        and decision.event.spec.role in target_roles
    )
    if not structural_candidates:
        return None, None

    predecessor_reason = _hard_invalidation_predecessor_reason(
        current=current,
        previous=previous,
        previous_transition=previous_transition,
        decision_as_of=decision_as_of,
    )
    if predecessor_reason is not None:
        return None, predecessor_reason
    assert previous is not None
    assert previous_transition is not None

    candidates: list[tuple[HardInvalidationRule, KeyLevelLifecycleDecision, KeyLevelReadModel]] = []
    for decision, state in structural_candidates:
        if state is None or not _valid_break_candidate(
            current=current,
            decision=decision,
            state=state,
            decision_as_of=decision_as_of,
            previous_transition=previous_transition,
        ):
            return None, "HARD_INVALIDATION_BREAK_PROOF_INVALID"
        rule = {
            KeyLevelRole.SUPPORT: HardInvalidationRule.CONFIRMED_SUPPORT_BREAK,
            KeyLevelRole.RESISTANCE: HardInvalidationRule.CONFIRMED_RESISTANCE_BREAK,
        }[decision.event.spec.role]
        candidates.append((rule, decision, state))

    rules = {rule for rule, _, _ in candidates}
    if len(rules) != 1:
        return None, "HARD_INVALIDATION_BREAK_RULE_AMBIGUOUS"

    ordered = tuple(sorted(candidates, key=lambda item: item[1].decision_hash))
    refs = _hard_invalidation_source_refs(
        current=current,
        previous=previous,
        previous_transition=previous_transition,
        candidates=ordered,
    )
    if not _refs_are_complete_at(refs, decision_as_of):
        return None, "HARD_INVALIDATION_FUTURE_OR_INVALID_SOURCE_REF"
    source_refs = _refs(decision_as_of, *refs)
    rule = ordered[0][0]
    identity_payload = {
        "current_feature_id": current.snapshot_id,
        "previous_feature_id": previous.snapshot_id,
        "previous_transition_decision_hash": previous_transition.decision_hash,
        "previous_transition_to_state_id": previous_transition.to_state_id,
        "predecessor_evidence_id": previous_transition.evidence.evidence_id,
        "decision_as_of": decision_as_of.isoformat(),
        "rule_code": rule.value,
        "proofs": [
            {
                "decision_hash": decision.decision_hash,
                "from_state_id": decision.from_state_id,
                "to_state_id": decision.to_state_id,
                "event_id": decision.event.event_id,
                "event_evidence_id": decision.event.evidence.evidence_id,
                "qualification_receipt_id": decision.event.evidence.qualification_receipt.receipt_id,
                "level_id": decision.event.spec.level_id,
                "broken_state_id": state.state_id,
                "activation_event_id": state.activation_event.event_id if state.activation_event is not None else None,
            }
            for _, decision, state in ordered
        ],
        "source_refs": [ref.model_dump(mode="json") for ref in source_refs],
    }
    digest = hashlib.sha256(json.dumps(identity_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return (
        TransitionEvidence(
            evidence_id=f"gold_transition_evidence.v1:{digest}",
            scope="daily_close",
            delta_kind=EvidenceDeltaKind.HARD_INVALIDATION,
            as_of=decision_as_of,
            source_refs=source_refs,
            evidence_categories=(EvidenceCategory.PRICE,),
            predecessor_evidence_id=previous_transition.evidence.evidence_id,
            rule_code=rule,
        ),
        None,
    )


def _hard_invalidation_predecessor_reason(
    *,
    current: FeatureSnapshotContract,
    previous: FeatureSnapshotContract | None,
    previous_transition: StateTransitionPolicyDecision | StateTransitionPolicyDecisionV2 | None,
    decision_as_of: datetime,
) -> str | None:
    if previous is None or previous_transition is None or previous_transition.to_state_id is None:
        return "HARD_INVALIDATION_PREDECESSOR_MISSING"
    current_is_v2 = isinstance(current, FeatureSnapshotV2)
    bound_feature_ids = {
        ref.reference
        for ref in previous_transition.evidence.source_refs
        if ref.source == "input_snapshot" and ref.reference.startswith("feature_snapshot.v")
    }
    if (
        isinstance(previous, FeatureSnapshotV2) != current_is_v2
        or isinstance(previous_transition, StateTransitionPolicyDecisionV2) != current_is_v2
        or not feature_snapshot_integrity_valid(previous)
        or not _transition_integrity_valid(previous_transition)
        or (bound_feature_ids and previous.snapshot_id not in bound_feature_ids)
        or previous.scope != "daily_close"
        or previous.as_of >= current.as_of
        or previous_transition.evidence.scope.value != "daily_close"
        or previous_transition.evidence.as_of.date() != previous.as_of.date()
        or previous_transition.evidence.as_of < previous.as_of
        or previous_transition.evidence.as_of >= decision_as_of
        or not previous_transition.to_state_id.startswith(
            "analysis_state.v2:" if current_is_v2 else "analysis_state.v1:"
        )
    ):
        return "HARD_INVALIDATION_PREDECESSOR_INCONSISTENT"
    predecessor_refs = tuple(_all_source_references(previous)) + tuple(_all_source_references(previous_transition))
    if not _refs_are_complete_at(predecessor_refs, decision_as_of):
        return "HARD_INVALIDATION_FUTURE_OR_INVALID_SOURCE_REF"
    return None


def _transition_integrity_valid(
    transition: StateTransitionPolicyDecision | StateTransitionPolicyDecisionV2,
) -> bool:
    canonical = (
        canonical_state_transition_decision_v2_json(transition)
        if isinstance(transition, StateTransitionPolicyDecisionV2)
        else canonical_state_transition_decision_json(transition)
    )
    return hashlib.sha256(canonical.encode()).hexdigest() == transition.decision_hash


def _valid_break_candidate(
    *,
    current: FeatureSnapshotContract,
    decision: KeyLevelLifecycleDecision,
    state: KeyLevelReadModel,
    decision_as_of: datetime,
    previous_transition: StateTransitionPolicyDecision | StateTransitionPolicyDecisionV2,
) -> bool:
    event = decision.event
    evidence = event.evidence
    receipt = evidence.qualification_receipt
    fact = evidence.price_fact
    activation = state.activation_event
    spot = current.xauusd_spot
    if (
        not feature_snapshot_integrity_valid(current)
        or state.state_id != decision.to_state_id
        or state.lifecycle is not KeyLevelLifecycle.BROKEN
        or state.authority_status is not KeyLevelAuthorityStatus.CANONICAL_XAUUSD_VALIDATED
        or state.quality_status != "accepted"
        or state.spec != event.spec
        or state.last_event_id != event.event_id
        or state.as_of != decision_as_of
        or evidence.as_of != decision_as_of
        or not timedelta(0) <= decision_as_of - evidence.window_end < timedelta(days=1)
        or evidence.window_end <= previous_transition.evidence.as_of
        or event.spec.scope.value != "daily_close"
        or evidence.scope.value != "daily_close"
        or evidence.source_role is not KeyLevelSourceRole.OFFICIAL_MARKET
        or evidence.source_instrument is not KeyLevelSourceInstrument.XAUUSD_SPOT
        or evidence.quality_status != "accepted"
        or evidence.freshness_status != "fresh"
        or evidence.alignment_status != "aligned"
        or receipt.qualification_class.value != "canonical_market"
        or fact is None
        or not fact.window_complete
        or fact.rule_code != "break"
        or len(fact.window_closes) < 2
        or not event.spec.effective_from <= decision_as_of < event.spec.expires_at
        or activation is None
        or activation.event_type is not KeyLevelEventType.ACTIVATE
        or activation.spec != event.spec
        or activation.evidence.source_role is not KeyLevelSourceRole.OFFICIAL_MARKET
        or activation.evidence.source_instrument is not KeyLevelSourceInstrument.XAUUSD_SPOT
        or activation.evidence.quality_status != "accepted"
        or activation.evidence.freshness_status != "fresh"
        or activation.evidence.alignment_status != "aligned"
        or activation.evidence.as_of > decision_as_of
        or spot.series_id != "XAUUSD_SPOT"
        or spot.market_role != "spot"
        or spot.value is None
        or spot.quality_status != "accepted"
        or spot.freshness_status != "fresh"
        or spot.alignment_status != "aligned"
        or spot.as_of > decision_as_of
    ):
        return False
    relevant = (
        tuple(_all_source_references(current))
        + tuple(_all_source_references(decision))
        + tuple(_all_source_references(state))
    )
    return _refs_are_complete_at(relevant, decision_as_of)


def _hard_invalidation_source_refs(
    *,
    current: FeatureSnapshotContract,
    previous: FeatureSnapshotContract,
    previous_transition: StateTransitionPolicyDecision | StateTransitionPolicyDecisionV2,
    candidates: tuple[tuple[HardInvalidationRule, KeyLevelLifecycleDecision, KeyLevelReadModel], ...],
) -> tuple[SourceReference, ...]:
    refs: list[SourceReference] = [
        SourceReference(source="input_snapshot", reference=current.snapshot_id, retrieved_at=current.as_of),
        SourceReference(source="input_snapshot", reference=previous.snapshot_id, retrieved_at=previous.as_of),
        SourceReference(
            source="state_transition_decision",
            reference=previous_transition.decision_hash,
            retrieved_at=previous_transition.evidence.as_of,
        ),
        SourceReference(
            source="transition_evidence",
            reference=previous_transition.evidence.evidence_id,
            retrieved_at=previous_transition.evidence.as_of,
        ),
        SourceReference(
            source="analysis_state",
            reference=previous_transition.to_state_id or "missing",
            retrieved_at=previous_transition.evidence.as_of,
        ),
        *current.xauusd_spot.source_refs,
        *previous_transition.evidence.source_refs,
    ]
    for _, decision, state in candidates:
        event = decision.event
        activation = state.activation_event
        refs.extend(_all_source_references(decision))
        refs.extend(_all_source_references(state))
        refs.extend(
            (
                SourceReference(
                    source="key_level_decision",
                    reference=decision.decision_hash,
                    retrieved_at=event.evidence.as_of,
                ),
                SourceReference(
                    source="key_level_state",
                    reference=state.state_id,
                    retrieved_at=state.as_of,
                ),
                SourceReference(
                    source="key_level_event",
                    reference=event.event_id,
                    retrieved_at=event.evidence.as_of,
                ),
                SourceReference(
                    source="qualification_receipt",
                    reference=event.evidence.qualification_receipt.receipt_id,
                    retrieved_at=event.evidence.qualification_receipt.issued_at,
                ),
            )
        )
        if activation is not None:
            refs.extend(
                (
                    SourceReference(
                        source="key_level_activation_event",
                        reference=activation.event_id,
                        retrieved_at=activation.evidence.as_of,
                    ),
                    SourceReference(
                        source="qualification_receipt",
                        reference=activation.evidence.qualification_receipt.receipt_id,
                        retrieved_at=activation.evidence.qualification_receipt.issued_at,
                    ),
                )
            )
    return tuple(refs)


def _all_source_references(value: object) -> tuple[SourceReference, ...]:
    if isinstance(value, SourceReference):
        return (value,)
    if isinstance(value, BaseModel):
        return tuple(
            ref for field_name in type(value).model_fields for ref in _all_source_references(getattr(value, field_name))
        )
    if isinstance(value, dict):
        return tuple(ref for item in value.values() for ref in _all_source_references(item))
    if isinstance(value, (tuple, list)):
        return tuple(ref for item in value for ref in _all_source_references(item))
    return ()


def _refs_are_complete_at(refs: tuple[SourceReference, ...], as_of: datetime) -> bool:
    return bool(refs) and all(
        ref.retrieved_at.tzinfo is not None
        and ref.retrieved_at.utcoffset() is not None
        and ref.retrieved_at.astimezone(UTC) <= as_of
        for ref in refs
    )


def _transition_evidence(
    *,
    current: FeatureSnapshotContract,
    analysis: object,
    attribution: object,
    decision_as_of: datetime,
    previous_transition: (StateTransitionPolicyDecision | StateTransitionPolicyDecisionV2 | None),
) -> TransitionEvidence:
    analysis_drivers = (*analysis.dominant_drivers, *analysis.counter_drivers)  # type: ignore[attr-defined]
    categories: set[EvidenceCategory] = set()
    if analysis_drivers:
        categories.add(EvidenceCategory.MACRO)
    if attribution.price_move in {"up", "down"}:  # type: ignore[attr-defined]
        categories.add(EvidenceCategory.PRICE)

    rule_code = None
    if attribution.attribution_status == "confirmed_event":  # type: ignore[attr-defined]
        delta_kind = EvidenceDeltaKind.MAJOR_CONFIRMATION
        categories = {EvidenceCategory.PRICE, EvidenceCategory.OFFICIAL_EVENT}
        rule_code = MajorConfirmationRule.OFFICIAL_EVENT_REACTION_CONFIRMED
    elif (
        attribution.attribution_status == "cross_asset_consistent"  # type: ignore[attr-defined]
        and EvidenceCategory.MACRO in categories
        and EvidenceCategory.PRICE in categories
    ):
        delta_kind = EvidenceDeltaKind.MAJOR_CONFIRMATION
        rule_code = MajorConfirmationRule.MAJOR_MACRO_REACTION_CONFIRMED
    elif categories:
        delta_kind = EvidenceDeltaKind.ORDINARY
    else:
        delta_kind = EvidenceDeltaKind.NO_OP

    refs = _refs(
        decision_as_of,
        *(ref for driver in analysis_drivers for ref in driver.source_refs),
        *attribution.source_refs,  # type: ignore[attr-defined]
        *current.xauusd_spot.source_refs,
    )
    predecessor_evidence_id = (
        previous_transition.evidence.evidence_id
        if previous_transition is not None and delta_kind is not EvidenceDeltaKind.NO_OP
        else None
    )
    identity_payload = {
        "current_feature_id": current.snapshot_id,
        "analysis_policy_version": analysis.policy_version,  # type: ignore[attr-defined]
        "attribution_policy_version": attribution.policy_version,  # type: ignore[attr-defined]
        "delta_kind": delta_kind.value,
        "categories": sorted(item.value for item in categories),
        "rule_code": rule_code.value if rule_code is not None else None,
        "predecessor_evidence_id": predecessor_evidence_id,
    }
    digest = hashlib.sha256(json.dumps(identity_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return TransitionEvidence(
        evidence_id=f"gold_transition_evidence.v1:{digest}",
        scope="daily_close",
        delta_kind=delta_kind,
        as_of=decision_as_of,
        source_refs=refs,
        evidence_categories=tuple(sorted(categories, key=lambda item: item.value)),
        predecessor_evidence_id=predecessor_evidence_id,
        rule_code=rule_code,
    )


def _options_regime(current: FeatureSnapshotContract, decision_as_of: datetime):
    observation = current.cme_options_regime
    if observation.value is None or observation.quality_status == "blocked":
        regime = "unavailable"
        directional_bias = "unavailable"
    elif observation.value < 0:
        regime = "stress"
        directional_bias = "neutral"
    elif observation.value == 0:
        regime = "pinning"
        directional_bias = "neutral"
    else:
        regime = "normal"
        directional_bias = "neutral"
    return build_strategy_options_regime(
        {
            "source_snapshot_id": current.snapshot_id,
            "as_of": decision_as_of,
            "regime": regime,
            "directional_bias": directional_bias,
            "freshness_status": observation.freshness_status,
            "quality_status": observation.quality_status,
            "alignment_status": observation.alignment_status,
            "source_refs": _refs(decision_as_of, *observation.source_refs),
        }
    )


def _event_risk(current: FeatureSnapshotContract, decision_as_of: datetime):
    events = current.official_events
    # The feature snapshot is the authority boundary for this control.  A
    # later runtime decision timestamp must not make a post-snapshot event or
    # lineage reference appear eligible.
    readiness_cutoff = current.as_of if isinstance(current, FeatureSnapshotV2) else decision_as_of
    event_readiness, _ = _event_readiness(events, readiness_cutoff)
    if _has_future_event_observation(events, readiness_cutoff):
        event_readiness = "blocked"
    snapshot_is_accepted = (
        events.freshness_status == "fresh"
        and events.quality_status == "accepted"
        and events.alignment_status == "aligned"
    )
    if event_readiness == "blocked":
        risk_status = "unavailable"
        quality_status = "blocked"
        active_ids: tuple[str, ...] = ()
    elif not snapshot_is_accepted:
        risk_status = "unavailable"
        quality_status = "observe"
        active_ids = ()
    else:
        active_ids = tuple(
            sorted(
                event.event_id
                for event in events.events
                if event.occurred_at <= readiness_cutoff and event.reaction_status != "confirmed"
            )
        )
        risk_status = "watch" if active_ids else "clear"
        quality_status = "accepted"
    source_refs = _event_risk_source_refs(
        current=current,
        events=events,
        cutoff=readiness_cutoff,
    )
    return build_strategy_event_risk(
        {
            "as_of": decision_as_of,
            "risk_status": risk_status,
            "active_event_ids": active_ids,
            "quality_status": quality_status,
            "source_refs": source_refs,
        }
    )


def _event_risk_source_refs(
    *,
    current: FeatureSnapshotContract,
    events: OfficialEventSnapshot,
    cutoff: datetime,
) -> tuple[SourceReference, ...]:
    """Return eligible event lineage, with an explicit rejected-input passport."""

    typed_event_refs = tuple(
        ref
        for event in events.events
        for ref in (*event.source_refs, *event.reaction_source_refs)
    )
    eligible_refs = _refs_at_or_before(cutoff, *events.source_refs, *typed_event_refs)
    if eligible_refs:
        return eligible_refs
    # This reference records which feature snapshot supplied the rejected
    # event input.  It is not an official event reference and does not mean
    # that the official calendar was empty.
    return (
        SourceReference(
            source="input_snapshot",
            reference=current.snapshot_id,
            retrieved_at=current.as_of,
        ),
    )


def _refs_at_or_before(as_of: datetime, *refs: SourceReference) -> tuple[SourceReference, ...]:
    eligible = tuple(
        ref
        for ref in refs
        if ref.retrieved_at.tzinfo is not None
        and ref.retrieved_at.utcoffset() is not None
        and ref.retrieved_at.astimezone(UTC) <= as_of
    )
    return _refs(as_of, *eligible) if eligible else ()


def _has_future_event_observation(events: OfficialEventSnapshot, cutoff: datetime) -> bool:
    return events.as_of > cutoff or any(
        event.occurred_at > cutoff
        or (
            event.reaction_window_end is not None
            and event.reaction_window_end > cutoff
        )
        for event in events.events
    )


def _refs(as_of: datetime, *refs: SourceReference) -> tuple[SourceReference, ...]:
    unique = {(ref.source, ref.reference, ref.retrieved_at): ref for ref in refs if ref.retrieved_at <= as_of}
    if not unique:
        raise ValueError("runtime controls require an upstream typed source reference")
    return tuple(unique[key] for key in sorted(unique))


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("runtime decision_as_of must be timezone-aware")
    return value.astimezone(UTC)
