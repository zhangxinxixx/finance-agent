"""Pure deterministic policy for the formal daily XAUUSD StrategyDecision."""

from __future__ import annotations

from datetime import datetime

from apps.analysis.gold_policy.key_level_schemas import (
    KeyLevelAuthorityStatus,
    KeyLevelComparator,
    KeyLevelEventType,
    KeyLevelLifecycle,
    KeyLevelRole,
    KeyLevelTransitionAction,
    key_level_strategy_eligible_at,
)
from apps.analysis.gold_policy.schemas import SourceReference
from apps.analysis.gold_policy.state_schemas import AnalysisStage, TransitionAction
from apps.analysis.gold_policy.strategy_schemas import (
    EventRiskStatus,
    NoTradeReasonCode,
    OptionsRegime,
    ReleaseConditionCode,
    ReviewTriggerCode,
    StrategyDecision,
    StrategyDirection,
    StrategyPolicyInput,
    StrategyStatus,
    build_strategy_decision,
)


_STAGE_DIRECTION_COMPATIBILITY = {
    "bullish": {
        AnalysisStage.WEAK_REPAIR,
        AnalysisStage.REVERSAL_WATCH,
        AnalysisStage.TREND_CONFIRMED,
    },
    "bearish": {
        AnalysisStage.PRESSURE,
        AnalysisStage.WEAK_REPAIR,
        AnalysisStage.REVERSAL_WATCH,
        AnalysisStage.TREND_CONFIRMED,
    },
    "neutral": {AnalysisStage.RANGE},
    "mixed": {AnalysisStage.DIRECTION_DECISION},
}

_TRIGGER_STAGES = {AnalysisStage.REVERSAL_WATCH, AnalysisStage.TREND_CONFIRMED}

_NO_TRADE_REMEDIATION = {
    NoTradeReasonCode.INPUT_LINEAGE_INVALID: (
        (ReleaseConditionCode.INPUT_LINEAGE_RECONCILED,),
        (ReviewTriggerCode.ON_INPUT_REBUILT,),
    ),
    NoTradeReasonCode.INPUT_SCOPE_MISMATCH: (
        (ReleaseConditionCode.INPUT_SCOPE_RECONCILED,),
        (ReviewTriggerCode.ON_INPUT_REBUILT,),
    ),
    NoTradeReasonCode.INPUT_TIME_INVALID: (
        (ReleaseConditionCode.INPUT_TIME_RECONCILED,),
        (ReviewTriggerCode.ON_INPUT_REBUILT,),
    ),
    NoTradeReasonCode.DATA_QUALITY_BLOCKED: (
        (ReleaseConditionCode.DATA_QUALITY_READY,),
        (ReviewTriggerCode.ON_DATA_QUALITY_CHANGE, ReviewTriggerCode.ON_NEXT_DAILY_CLOSE),
    ),
    NoTradeReasonCode.ANALYSIS_STATE_NOT_ACCEPTED: (
        (ReleaseConditionCode.CANONICAL_STATE_ACCEPTED,),
        (ReviewTriggerCode.ON_CANONICAL_STATE_CHANGE, ReviewTriggerCode.ON_NEXT_DAILY_CLOSE),
    ),
    NoTradeReasonCode.ANALYSIS_STATE_UNAVAILABLE: (
        (ReleaseConditionCode.DIRECTION_AUTHORITY_AVAILABLE,),
        (ReviewTriggerCode.ON_CANONICAL_STATE_CHANGE, ReviewTriggerCode.ON_NEXT_DAILY_CLOSE),
    ),
    NoTradeReasonCode.EVENT_RISK_UNAVAILABLE: (
        (ReleaseConditionCode.EVENT_RISK_CONFIRMED_SAFE,),
        (ReviewTriggerCode.ON_EVENT_RISK_UPDATE,),
    ),
    NoTradeReasonCode.MAJOR_EVENT_BLACKOUT: (
        (ReleaseConditionCode.EVENT_WINDOW_CLOSED,),
        (ReviewTriggerCode.ON_EVENT_WINDOW_CLOSE, ReviewTriggerCode.ON_EVENT_RISK_UPDATE),
    ),
    NoTradeReasonCode.INVALIDATION_NOT_CANONICAL: (
        (ReleaseConditionCode.CANONICAL_INVALIDATION_CONFIRMED,),
        (ReviewTriggerCode.ON_CANONICAL_STATE_CHANGE, ReviewTriggerCode.ON_INPUT_REBUILT),
    ),
}


def evaluate_gold_strategy_policy(policy_input: StrategyPolicyInput) -> StrategyDecision:
    """Return a content-addressed decision without consulting prose, LLMs, or clocks."""

    diagnostics = _input_diagnostics(policy_input)
    for reason in (
        NoTradeReasonCode.INPUT_LINEAGE_INVALID,
        NoTradeReasonCode.INPUT_SCOPE_MISMATCH,
        NoTradeReasonCode.INPUT_TIME_INVALID,
    ):
        if reason.value in diagnostics:
            return _no_trade(policy_input, reason, diagnostics)

    if policy_input.feature_snapshot.data_quality.analysis_readiness == "blocked":
        return _no_trade(
            policy_input,
            NoTradeReasonCode.DATA_QUALITY_BLOCKED,
            (*diagnostics, "FEATURE_SNAPSHOT_ANALYSIS_BLOCKED"),
        )
    if policy_input.analysis_state.quality_status != "accepted":
        return _no_trade(
            policy_input,
            NoTradeReasonCode.ANALYSIS_STATE_NOT_ACCEPTED,
            (*diagnostics, "CANONICAL_STATE_NOT_ACCEPTED"),
        )
    if policy_input.analysis_state.directional_bias == "unavailable":
        return _no_trade(
            policy_input,
            NoTradeReasonCode.ANALYSIS_STATE_UNAVAILABLE,
            (*diagnostics, "CANONICAL_DIRECTION_UNAVAILABLE"),
        )
    if (
        policy_input.event_risk.risk_status is EventRiskStatus.UNAVAILABLE
        or policy_input.event_risk.quality_status != "accepted"
    ):
        return _no_trade(
            policy_input,
            NoTradeReasonCode.EVENT_RISK_UNAVAILABLE,
            (*diagnostics, "EVENT_RISK_NOT_VERIFIABLE"),
        )
    if policy_input.event_risk.risk_status is EventRiskStatus.BLACKOUT:
        return _no_trade(
            policy_input,
            NoTradeReasonCode.MAJOR_EVENT_BLACKOUT,
            (*diagnostics, "MAJOR_EVENT_WINDOW_ACTIVE"),
        )

    eligible_levels = tuple(
        level
        for level in policy_input.key_levels
        if key_level_strategy_eligible_at(
            level,
            decision_as_of=policy_input.decision_as_of,
            current_quality_status=level.quality_status,
        )
    )
    invalidation_level_ids = tuple(
        level.spec.level_id for level in eligible_levels if level.spec.role is KeyLevelRole.INVALIDATION
    )

    if policy_input.state_transition.action is TransitionAction.INVALIDATE and not (
        policy_input.state_transition.transition_allowed and policy_input.state_transition.advance
    ):
        return _no_trade(
            policy_input,
            NoTradeReasonCode.INVALIDATION_NOT_CANONICAL,
            (*diagnostics, "INVALIDATION_DID_NOT_ADVANCE_CANONICAL_STATE"),
        )
    broken_invalidation_levels = _broken_invalidation_levels(policy_input)
    if policy_input.state_transition.action is TransitionAction.INVALIDATE or broken_invalidation_levels:
        return _decision(
            policy_input,
            status=StrategyStatus.INVALIDATED,
            direction=StrategyDirection.NONE,
            reason_codes=(*diagnostics, "FORMAL_INVALIDATION_CONFIRMED"),
            eligible_levels=(*eligible_levels, *broken_invalidation_levels),
            invalidation_level_ids=tuple(
                dict.fromkeys(
                    (
                        *invalidation_level_ids,
                        *(level.spec.level_id for level in broken_invalidation_levels),
                    )
                )
            ),
        )

    bias = policy_input.analysis_state.directional_bias
    stage = policy_input.analysis_state.stage
    if bias in {"neutral", "mixed"}:
        return _decision(
            policy_input,
            status=StrategyStatus.OBSERVE,
            direction=StrategyDirection.NONE,
            reason_codes=(*diagnostics, f"CANONICAL_DIRECTION_{bias.upper()}"),
            eligible_levels=eligible_levels,
            invalidation_level_ids=invalidation_level_ids,
        )
    if bias == "bullish" and stage is AnalysisStage.PRESSURE:
        return _decision(
            policy_input,
            status=StrategyStatus.OBSERVE,
            direction=StrategyDirection.NONE,
            reason_codes=(*diagnostics, "DAILY_PRESSURE_NO_LONG_CHASE"),
            eligible_levels=eligible_levels,
            invalidation_level_ids=invalidation_level_ids,
        )
    if stage not in _STAGE_DIRECTION_COMPATIBILITY.get(bias, set()):
        return _decision(
            policy_input,
            status=StrategyStatus.OBSERVE,
            direction=StrategyDirection.NONE,
            reason_codes=(*diagnostics, "STATE_DIRECTION_STAGE_INCOMPATIBLE"),
            eligible_levels=eligible_levels,
            invalidation_level_ids=invalidation_level_ids,
        )

    direction = StrategyDirection.LONG if bias == "bullish" else StrategyDirection.SHORT
    watch_status = StrategyStatus.LONG_WATCH if direction is StrategyDirection.LONG else StrategyStatus.SHORT_WATCH
    trigger_status = (
        StrategyStatus.LONG_RESEARCH_TRIGGERED
        if direction is StrategyDirection.LONG
        else StrategyStatus.SHORT_RESEARCH_TRIGGERED
    )
    trigger_levels = tuple(
        level
        for level in eligible_levels
        if _is_directional_trigger(level, direction=direction)
        and _has_verified_hold_decision(policy_input, level.state_id)
    )

    watch_reasons = list(diagnostics)
    if policy_input.state_transition.action is TransitionAction.PENDING:
        watch_reasons.append("STATE_TRANSITION_PENDING")
    if policy_input.feature_snapshot.data_quality.analysis_readiness != "ready":
        watch_reasons.append("DATA_QUALITY_OBSERVE_ONLY")
    if policy_input.event_risk.risk_status is EventRiskStatus.WATCH:
        watch_reasons.append("EVENT_RISK_WATCH")
    if stage not in _TRIGGER_STAGES:
        watch_reasons.append("STAGE_WATCH_ONLY")
    if not trigger_levels:
        watch_reasons.append("VERIFIED_TRIGGER_EVENT_MISSING")
    if not invalidation_level_ids:
        watch_reasons.append("FORMAL_INVALIDATION_LEVEL_MISSING")
    if not _attribution_supports_direction(policy_input, direction=direction):
        watch_reasons.append("ATTRIBUTION_NOT_DIRECTIONALLY_CONFIRMED")
    if not _options_support_direction(policy_input, direction=direction):
        watch_reasons.append("OPTIONS_REGIME_NOT_DIRECTIONALLY_CONFIRMED")

    if watch_reasons or policy_input.state_transition.action is TransitionAction.PENDING:
        return _decision(
            policy_input,
            status=watch_status,
            direction=direction,
            reason_codes=tuple(watch_reasons) or ("DIRECTIONAL_WATCH",),
            eligible_levels=eligible_levels,
            invalidation_level_ids=invalidation_level_ids,
        )

    return _decision(
        policy_input,
        status=trigger_status,
        direction=direction,
        reason_codes=("RESEARCH_TRIGGER_REQUIREMENTS_SATISFIED",),
        eligible_levels=eligible_levels,
        trigger_level_ids=tuple(level.spec.level_id for level in trigger_levels),
        invalidation_level_ids=invalidation_level_ids,
    )


def _input_diagnostics(policy_input: StrategyPolicyInput) -> tuple[str, ...]:
    diagnostics: list[str] = []
    state = policy_input.analysis_state
    transition = policy_input.state_transition
    feature = policy_input.feature_snapshot

    if (
        transition.to_state_id != state.state_id
        or transition.to_stage is not state.stage
        or policy_input.price_attribution.current_snapshot_id != feature.snapshot_id
        or policy_input.options_regime.source_snapshot_id != feature.snapshot_id
    ):
        diagnostics.append(NoTradeReasonCode.INPUT_LINEAGE_INVALID.value)
    if (
        state.scope.value != policy_input.scope.value
        or transition.evidence.scope is not state.scope
        or feature.scope != policy_input.scope.value
        or any(level.spec.scope is not state.scope for level in policy_input.key_levels)
    ):
        diagnostics.append(NoTradeReasonCode.INPUT_SCOPE_MISMATCH.value)

    source_refs = _all_source_refs(policy_input_ref=policy_input)
    timestamps = (
        feature.as_of,
        state.as_of,
        transition.evidence.as_of,
        policy_input.options_regime.as_of,
        policy_input.event_risk.as_of,
        *(level.as_of for level in policy_input.key_levels),
        *(item.event.evidence.as_of for item in policy_input.key_level_decisions),
        *(ref.retrieved_at for ref in source_refs),
    )
    if any(timestamp > policy_input.decision_as_of for timestamp in timestamps):
        diagnostics.append(NoTradeReasonCode.INPUT_TIME_INVALID.value)
    if (
        policy_input.options_regime.as_of != policy_input.decision_as_of
        or policy_input.event_risk.as_of != policy_input.decision_as_of
    ):
        diagnostics.append(NoTradeReasonCode.INPUT_TIME_INVALID.value)
    for driver in (
        *policy_input.price_attribution.primary_drivers,
        *policy_input.price_attribution.secondary_drivers,
        *policy_input.price_attribution.counter_drivers,
    ):
        try:
            current_as_of = datetime.fromisoformat(driver.current_as_of)
            previous_as_of = datetime.fromisoformat(driver.previous_as_of) if driver.previous_as_of else None
        except ValueError:
            diagnostics.append(NoTradeReasonCode.INPUT_TIME_INVALID.value)
            break
        if current_as_of.tzinfo is None or (previous_as_of is not None and previous_as_of.tzinfo is None):
            diagnostics.append(NoTradeReasonCode.INPUT_TIME_INVALID.value)
            break
        if current_as_of > policy_input.decision_as_of or (
            previous_as_of is not None and previous_as_of > policy_input.decision_as_of
        ):
            diagnostics.append(NoTradeReasonCode.INPUT_TIME_INVALID.value)
            break

    level_by_state_id = {level.state_id: level for level in policy_input.key_levels}
    for item in policy_input.key_level_decisions:
        level = level_by_state_id.get(item.to_state_id or "")
        if level is None or item.event.spec.level_id != level.spec.level_id:
            diagnostics.append(NoTradeReasonCode.INPUT_LINEAGE_INVALID.value)
            break
    return tuple(dict.fromkeys(diagnostics))


def _broken_invalidation_levels(policy_input: StrategyPolicyInput):
    return tuple(
        level
        for level in policy_input.key_levels
        if level.spec.role is KeyLevelRole.INVALIDATION
        and level.lifecycle is KeyLevelLifecycle.BROKEN
        and level.authority_status is KeyLevelAuthorityStatus.CANONICAL_XAUUSD_VALIDATED
        and level.quality_status == "accepted"
        and level.as_of <= policy_input.decision_as_of < level.spec.expires_at
    )


def _is_directional_trigger(level, *, direction: StrategyDirection) -> bool:
    expected = (
        KeyLevelComparator.ABOVE_OR_EQUAL if direction is StrategyDirection.LONG else KeyLevelComparator.BELOW_OR_EQUAL
    )
    return (
        level.spec.role is KeyLevelRole.TRIGGER
        and level.lifecycle is KeyLevelLifecycle.HOLDING
        and level.spec.comparator is expected
    )


def _has_verified_hold_decision(policy_input: StrategyPolicyInput, state_id: str) -> bool:
    return any(
        item.to_state_id == state_id
        and item.to_lifecycle is KeyLevelLifecycle.HOLDING
        and item.action is KeyLevelTransitionAction.HOLD
        and item.event.event_type in {KeyLevelEventType.HOLD_CONFIRMED, KeyLevelEventType.RECLAIM_HOLD_CONFIRMED}
        and item.transition_allowed
        and item.advance
        for item in policy_input.key_level_decisions
    )


def _attribution_supports_direction(policy_input: StrategyPolicyInput, *, direction: StrategyDirection) -> bool:
    attribution = policy_input.price_attribution
    expected_move = "up" if direction is StrategyDirection.LONG else "down"
    expected_driver = "supports_up" if direction is StrategyDirection.LONG else "supports_down"
    return (
        attribution.price_move == expected_move
        and attribution.attribution_status in {"confirmed_event", "cross_asset_consistent"}
        and attribution.explained_ratio >= 0.5
        and bool(attribution.primary_drivers)
        and all(driver.direction == expected_driver for driver in attribution.primary_drivers)
    )


def _options_support_direction(policy_input: StrategyPolicyInput, *, direction: StrategyDirection) -> bool:
    options = policy_input.options_regime
    expected_bias = "bullish" if direction is StrategyDirection.LONG else "bearish"
    return (
        options.quality_status == "accepted"
        and options.freshness_status == "fresh"
        and options.alignment_status == "aligned"
        and options.regime is OptionsRegime.NORMAL
        and options.directional_bias in {expected_bias, "neutral"}
    )


def _no_trade(
    policy_input: StrategyPolicyInput,
    reason: NoTradeReasonCode,
    diagnostics: tuple[str, ...],
) -> StrategyDecision:
    release_conditions, review_triggers = _NO_TRADE_REMEDIATION[reason]
    return _decision(
        policy_input,
        status=StrategyStatus.NO_TRADE,
        direction=StrategyDirection.NONE,
        reason_codes=(reason.value, *diagnostics),
        no_trade_reason_code=reason,
        release_conditions=release_conditions,
        review_triggers=review_triggers,
    )


def _decision(
    policy_input: StrategyPolicyInput,
    *,
    status: StrategyStatus,
    direction: StrategyDirection,
    reason_codes: tuple[str, ...],
    eligible_levels=(),
    trigger_level_ids: tuple[str, ...] = (),
    invalidation_level_ids: tuple[str, ...] = (),
    no_trade_reason_code: NoTradeReasonCode | None = None,
    release_conditions: tuple[ReleaseConditionCode, ...] = (),
    review_triggers: tuple[ReviewTriggerCode, ...] = (),
) -> StrategyDecision:
    refs = _all_source_refs(policy_input_ref=policy_input)
    return build_strategy_decision(
        {
            "decision_as_of": policy_input.decision_as_of,
            "analysis_state_id": policy_input.analysis_state.state_id,
            "transition_decision_hash": policy_input.state_transition.decision_hash,
            "feature_snapshot_id": policy_input.feature_snapshot.snapshot_id,
            "attribution_snapshot_ids": (
                policy_input.price_attribution.previous_snapshot_id,
                policy_input.price_attribution.current_snapshot_id,
            ),
            "options_snapshot_id": policy_input.options_regime.snapshot_id,
            "event_risk_snapshot_id": policy_input.event_risk.snapshot_id,
            "level_refs": tuple(
                {
                    "level_id": level.spec.level_id,
                    "state_id": level.state_id,
                    "role": level.spec.role,
                    "comparator": level.spec.comparator,
                    "lifecycle": level.lifecycle,
                    "authority_status": level.authority_status,
                    "quality_status": level.quality_status,
                    "effective_from": level.spec.effective_from,
                    "expires_at": level.spec.expires_at,
                    "strategy_eligible_at_decision": key_level_strategy_eligible_at(
                        level,
                        decision_as_of=policy_input.decision_as_of,
                        current_quality_status=level.quality_status,
                    ),
                }
                for level in eligible_levels
            ),
            "key_level_state_ids": tuple(level.state_id for level in eligible_levels),
            "trigger_level_ids": trigger_level_ids,
            "invalidation_level_ids": invalidation_level_ids,
            "status": status,
            "direction": direction,
            "stage": policy_input.analysis_state.stage,
            "reason_codes": tuple(dict.fromkeys(reason_codes)),
            "no_trade_reason_code": no_trade_reason_code,
            "release_conditions": release_conditions,
            "review_triggers": review_triggers,
            "source_refs": refs,
        }
    )


def _all_source_refs(*, policy_input_ref: StrategyPolicyInput) -> tuple[SourceReference, ...]:
    feature = policy_input_ref.feature_snapshot
    refs = (
        *policy_input_ref.analysis_state.source_refs,
        *policy_input_ref.state_transition.evidence.source_refs,
        *policy_input_ref.price_attribution.source_refs,
        *policy_input_ref.options_regime.source_refs,
        *policy_input_ref.event_risk.source_refs,
        *feature.xauusd_spot.source_refs,
        *feature.cme_options_regime.source_refs,
        *feature.official_events.source_refs,
        *(ref for level in policy_input_ref.key_levels for ref in level.source_refs),
        *(ref for item in policy_input_ref.key_level_decisions for ref in item.event.evidence.source_refs),
    )
    unique = {(ref.source, ref.reference, ref.retrieved_at): ref for ref in refs}
    return tuple(unique[key] for key in sorted(unique))
