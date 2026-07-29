"""Pure orchestration for one deterministic XAUUSD daily-close decision."""

from __future__ import annotations

from apps.analysis.gold_policy.analysis_policy import evaluate_gold_analysis_policy
from apps.analysis.gold_policy.attribution_policy import attribute_gold_price
from apps.analysis.gold_policy.consistency_policy import evaluate_analysis_strategy_consistency
from apps.analysis.gold_policy.consistency_schemas import (
    AnalysisStrategyConsistencyInput,
    ConsistencyStatus,
)
from apps.analysis.gold_policy.daily_close_schemas import (
    CanonicalCommitAction,
    DailyCloseLoopInput,
    DailyCloseLoopReason,
    DailyCloseLoopResult,
    build_daily_close_loop_result,
)
from apps.analysis.gold_policy.schemas import SourceReference
from apps.analysis.gold_policy.state_transition_policy import (
    evaluate_analysis_state_transition,
)
from apps.analysis.gold_policy.strategy_policy import evaluate_gold_strategy_policy
from apps.analysis.gold_policy.strategy_schemas import StrategyPolicyInput


def evaluate_gold_daily_close_loop(loop_input: DailyCloseLoopInput) -> DailyCloseLoopResult:
    """Run the formal chain without I/O, prose inference, LLMs, or clocks."""

    analysis = evaluate_gold_analysis_policy(
        loop_input.current_feature,
        loop_input.previous_feature,
    )
    attribution = attribute_gold_price(
        loop_input.current_feature,
        loop_input.previous_feature,
    )
    transition_result = evaluate_analysis_state_transition(
        loop_input.previous_state,
        analysis,
        loop_input.transition_evidence,
        previous_transition=loop_input.previous_transition,
    )
    transition = transition_result.decision
    state = transition_result.state

    if state is None:
        return build_daily_close_loop_result(
            {
                **_base_payload(loop_input, analysis, attribution, transition),
                "analysis_state": None,
                "strategy_policy_input": None,
                "candidate_strategy": None,
                "consistency_decision": None,
                "canonical_action": CanonicalCommitAction.HOLD,
                "selected_state_id": None,
                "selected_strategy_id": None,
                "reason_codes": (DailyCloseLoopReason.NO_CANONICAL_STATE_AVAILABLE,),
                "source_refs": _source_refs(
                    loop_input,
                    analysis,
                    attribution,
                    transition,
                ),
            }
        )

    strategy_input = StrategyPolicyInput(
        decision_as_of=loop_input.decision_as_of,
        feature_snapshot=loop_input.current_feature,
        analysis_state=state,
        state_transition=transition,
        price_attribution=attribution,
        key_levels=loop_input.key_levels,
        key_level_decisions=loop_input.key_level_decisions,
        options_regime=loop_input.options_regime,
        event_risk=loop_input.event_risk,
    )
    candidate = evaluate_gold_strategy_policy(strategy_input)
    consistency = evaluate_analysis_strategy_consistency(
        AnalysisStrategyConsistencyInput(
            previous_policy_input=loop_input.previous_policy_input,
            previous_state=loop_input.previous_state,
            previous_transition=loop_input.previous_transition,
            previous_strategy=loop_input.previous_strategy,
            current_policy_input=strategy_input,
            candidate_strategy=candidate,
            key_level_proof=loop_input.key_level_proof,
        )
    )

    if consistency.status is ConsistencyStatus.CONSISTENT:
        action, reason = _selected_action(loop_input, transition.advance)
        selected_state_id = state.state_id
        selected_strategy_id = candidate.decision_id
    else:
        action = CanonicalCommitAction.HOLD
        reason = DailyCloseLoopReason.CONSISTENCY_GATE_REJECTED
        selected_state_id = loop_input.previous_state.state_id if loop_input.previous_state else None
        selected_strategy_id = loop_input.previous_strategy.decision_id if loop_input.previous_strategy else None

    return build_daily_close_loop_result(
        {
            **_base_payload(loop_input, analysis, attribution, transition),
            "analysis_state": state,
            "strategy_policy_input": strategy_input,
            "candidate_strategy": candidate,
            "consistency_decision": consistency,
            "canonical_action": action,
            "selected_state_id": selected_state_id,
            "selected_strategy_id": selected_strategy_id,
            "reason_codes": (reason,),
            "source_refs": _source_refs(
                loop_input,
                analysis,
                attribution,
                transition,
                state=state,
                candidate=candidate,
                consistency=consistency,
            ),
        }
    )


def _selected_action(loop_input: DailyCloseLoopInput, advance: bool):
    if loop_input.previous_state is None:
        return CanonicalCommitAction.BOOTSTRAP, DailyCloseLoopReason.BOOTSTRAP_SELECTED
    if advance:
        return (
            CanonicalCommitAction.ADVANCE,
            DailyCloseLoopReason.ADVANCING_DECISION_SELECTED,
        )
    return (
        CanonicalCommitAction.MAINTAIN,
        DailyCloseLoopReason.NON_ADVANCING_DECISION_SELECTED,
    )


def _base_payload(loop_input, analysis, attribution, transition):
    return {
        "decision_as_of": loop_input.decision_as_of,
        "current_feature_id": loop_input.current_feature.snapshot_id,
        "previous_feature_id": (loop_input.previous_feature.snapshot_id if loop_input.previous_feature else None),
        "previous_state_id": (loop_input.previous_state.state_id if loop_input.previous_state else None),
        "previous_strategy_id": (loop_input.previous_strategy.decision_id if loop_input.previous_strategy else None),
        "analysis_decision": analysis,
        "price_attribution": attribution,
        "transition_decision": transition,
    }


def _source_refs(
    loop_input: DailyCloseLoopInput,
    analysis,
    attribution,
    transition,
    *,
    state=None,
    candidate=None,
    consistency=None,
) -> tuple[SourceReference, ...]:
    refs = [
        *_feature_refs(loop_input.current_feature),
        *loop_input.transition_evidence.source_refs,
        *loop_input.options_regime.source_refs,
        *loop_input.event_risk.source_refs,
        *transition.evidence.source_refs,
        *attribution.source_refs,
        *(ref for driver in (*analysis.dominant_drivers, *analysis.counter_drivers) for ref in driver.source_refs),
        *(
            ref
            for driver in (
                *attribution.primary_drivers,
                *attribution.secondary_drivers,
                *attribution.counter_drivers,
            )
            for ref in driver.source_refs
        ),
    ]
    if loop_input.previous_feature is not None:
        refs.extend(_feature_refs(loop_input.previous_feature))
    if loop_input.previous_state is not None:
        refs.extend(loop_input.previous_state.source_refs)
    if state is not None:
        refs.extend(state.source_refs)
    if candidate is not None:
        refs.extend(candidate.source_refs)
    if consistency is not None:
        refs.extend(consistency.source_refs)
    refs.extend(ref for level in loop_input.key_levels for ref in level.source_refs)
    refs.extend(
        ref
        for decision in (*loop_input.key_level_decisions, *loop_input.key_level_proof)
        for ref in decision.event.evidence.source_refs
    )
    unique = {(ref.source, ref.reference, ref.retrieved_at): ref for ref in refs}
    return tuple(unique[key] for key in sorted(unique))


def _feature_refs(feature) -> tuple[SourceReference, ...]:
    observations = (
        feature.xauusd_spot,
        feature.gc_futures,
        feature.us02y,
        feature.us10y,
        feature.us30y,
        feature.t10yie,
        feature.real10y,
        feature.broad_dollar,
        feature.wti,
        feature.brent,
        feature.etf_flow,
        feature.cot,
        feature.cme_options_regime,
    )
    refs = [ref for observation in observations for ref in observation.source_refs]
    refs.extend(feature.official_events.source_refs)
    refs.extend(
        ref for event in feature.official_events.events for ref in (*event.source_refs, *event.reaction_source_refs)
    )
    return tuple(refs)
