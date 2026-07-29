from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from apps.analysis.gold_policy.consistency_policy import evaluate_analysis_strategy_consistency
from apps.analysis.gold_policy.consistency_schemas import AnalysisStrategyConsistencyInput
from apps.analysis.gold_policy.key_level_policy import evaluate_key_level_lifecycle
from apps.analysis.gold_policy.state_schemas import (
    TransitionEvidence,
    build_analysis_state,
    build_state_transition_policy_decision,
)
from apps.analysis.gold_policy.strategy_policy import evaluate_gold_strategy_policy
from apps.analysis.gold_policy.strategy_schemas import (
    StrategyDecisionInput,
    build_strategy_decision,
    build_strategy_event_risk,
    build_strategy_options_regime,
)
from tests.analysis.test_gold_strategy_policy import (
    _direct_state,
    _event,
    _policy_input,
    _ref,
    _spec,
)


GOLDEN_CASES = Path(__file__).parents[1] / "fixtures" / "gold_consistency" / "v1_gate_cases.json"


def _bootstrap_input():
    base = _policy_input(bias="bullish", stage="weak_repair")
    state = base.analysis_state
    evidence = TransitionEvidence.model_validate(
        {
            "evidence_id": "evidence:bootstrap",
            "scope": "daily_close",
            "delta_kind": "ordinary",
            "as_of": base.decision_as_of,
            "source_refs": (_ref("bootstrap", base.decision_as_of),),
            "evidence_categories": ("macro",),
        }
    )
    transition = build_state_transition_policy_decision(
        {
            "from_state_id": None,
            "to_state_id": state.state_id,
            "from_stage": None,
            "to_stage": state.stage,
            "action": "strengthen",
            "transition_allowed": True,
            "advance": True,
            "stage_changed": True,
            "evidence": evidence,
            "reasons": ("BOOTSTRAP_CANONICAL_STATE",),
        }
    )
    return base.model_copy(update={"state_transition": transition})


def _later_input(base, *, event_status: str = "clear"):
    as_of = base.decision_as_of + timedelta(minutes=5)
    options = build_strategy_options_regime(
        {
            **base.options_regime.model_dump(exclude={"payload_hash", "snapshot_id", "as_of", "source_refs"}),
            "as_of": as_of,
            "source_refs": (_ref("later-options", as_of),),
        }
    )
    event_payload: dict[str, object] = {
        "as_of": as_of,
        "risk_status": event_status,
        "quality_status": "accepted",
        "source_refs": (_ref("later-event", as_of),),
    }
    if event_status == "blackout":
        event_payload.update(
            {
                "active_event_ids": ("FOMC",),
                "window_start": as_of - timedelta(minutes=1),
                "window_end": as_of + timedelta(minutes=30),
                "next_review_at": as_of + timedelta(minutes=30),
            }
        )
    return base.model_copy(
        update={
            "decision_as_of": as_of,
            "options_regime": options,
            "event_risk": build_strategy_event_risk(event_payload),
        }
    )


def _advanced_input(base, *, key_levels=None):
    current = _later_input(base)
    state = build_analysis_state(
        {
            **base.analysis_state.model_dump(exclude={"payload_hash", "state_id", "as_of", "source_refs"}),
            "as_of": current.decision_as_of,
            "source_refs": (_ref("advanced-state", current.decision_as_of),),
        }
    )
    evidence = TransitionEvidence.model_validate(
        {
            "evidence_id": "evidence:state-advance",
            "scope": "daily_close",
            "delta_kind": "ordinary",
            "as_of": current.decision_as_of,
            "source_refs": (_ref("state-advance", current.decision_as_of),),
            "evidence_categories": ("macro",),
        }
    )
    transition = build_state_transition_policy_decision(
        {
            "from_state_id": base.analysis_state.state_id,
            "to_state_id": state.state_id,
            "from_stage": base.analysis_state.stage,
            "to_stage": state.stage,
            "action": "strengthen",
            "transition_allowed": True,
            "advance": True,
            "stage_changed": False,
            "evidence": evidence,
            "reasons": ("CANONICAL_STATE_REFRESHED",),
        }
    )
    updates = {"analysis_state": state, "state_transition": transition}
    if key_levels is not None:
        updates["key_levels"] = key_levels
    return current.model_copy(update=updates)


def _watch_trigger_gate_input() -> AnalysisStrategyConsistencyInput:
    previous_input = _policy_input(bias="bullish", stage="trend_confirmed")
    base_as_of = previous_input.decision_as_of
    common = {
        "comparator": "above_or_equal",
        "reference_price": "4500",
        "effective_from": base_as_of - timedelta(days=1),
        "expires_at": base_as_of + timedelta(days=30),
    }
    trigger_spec = _spec(role="trigger", **common)
    active = _direct_state("active", spec=trigger_spec, as_of=base_as_of)
    invalidation = _direct_state(
        "active",
        spec=_spec(role="invalidation", **common),
        as_of=base_as_of,
    )
    previous_input = previous_input.model_copy(update={"key_levels": (active, invalidation)})
    previous = evaluate_gold_strategy_policy(previous_input)
    touched = evaluate_key_level_lifecycle(
        active,
        _event(
            "touch",
            spec=trigger_spec,
            source_role="official_market",
            factors=("price_touch",),
            as_of=base_as_of + timedelta(minutes=1),
        ),
    )
    assert touched.state is not None
    held = evaluate_key_level_lifecycle(
        touched.state,
        _event(
            "hold_confirmed",
            spec=trigger_spec,
            source_role="official_market",
            factors=("official_close", "hold_window"),
            as_of=base_as_of + timedelta(minutes=2),
        ),
    )
    assert held.state is not None
    current_input = _later_input(previous_input).model_copy(
        update={
            "key_levels": (held.state, invalidation),
            "key_level_decisions": (held.decision,),
        }
    )
    return AnalysisStrategyConsistencyInput(
        previous_policy_input=previous_input,
        previous_state=previous_input.analysis_state,
        previous_transition=previous_input.state_transition,
        previous_strategy=previous,
        current_policy_input=current_input,
        candidate_strategy=evaluate_gold_strategy_policy(current_input),
        key_level_proof=(touched.decision, held.decision),
    )


def _invalidation_gate_input() -> AnalysisStrategyConsistencyInput:
    previous_input = _policy_input(bias="bearish", stage="trend_confirmed")
    base_as_of = previous_input.decision_as_of
    spec = _spec(
        role="invalidation",
        comparator="below_or_equal",
        reference_price="4480",
        effective_from=base_as_of - timedelta(days=1),
        expires_at=base_as_of + timedelta(days=30),
    )
    active = _direct_state("active", spec=spec, as_of=base_as_of)
    previous_input = previous_input.model_copy(update={"key_levels": (active,)})
    previous = evaluate_gold_strategy_policy(previous_input)
    broken = evaluate_key_level_lifecycle(
        active,
        _event(
            "break_confirmed",
            spec=spec,
            source_role="official_market",
            factors=("official_close", "break_window"),
            as_of=base_as_of + timedelta(minutes=1),
        ),
    )
    assert broken.state is not None
    current_input = _later_input(previous_input).model_copy(
        update={
            "key_levels": (broken.state,),
            "key_level_decisions": (broken.decision,),
        }
    )
    return AnalysisStrategyConsistencyInput(
        previous_policy_input=previous_input,
        previous_state=previous_input.analysis_state,
        previous_transition=previous_input.state_transition,
        previous_strategy=previous,
        current_policy_input=current_input,
        candidate_strategy=evaluate_gold_strategy_policy(current_input),
    )


def _direct_flip_gate_input() -> AnalysisStrategyConsistencyInput:
    previous_input = _policy_input(bias="bullish", stage="weak_repair")
    previous = evaluate_gold_strategy_policy(previous_input)
    current_input = _later_input(_policy_input(bias="bearish", stage="weak_repair"))
    current_state = build_analysis_state(
        {
            **current_input.analysis_state.model_dump(exclude={"payload_hash", "state_id", "as_of", "source_refs"}),
            "as_of": current_input.decision_as_of,
            "source_refs": (_ref("current-state", current_input.decision_as_of),),
        }
    )
    evidence = TransitionEvidence.model_validate(
        {
            "evidence_id": "evidence:direct-flip",
            "scope": "daily_close",
            "delta_kind": "ordinary",
            "as_of": current_input.decision_as_of,
            "source_refs": (_ref("direct-flip", current_input.decision_as_of),),
            "evidence_categories": ("macro",),
        }
    )
    transition = build_state_transition_policy_decision(
        {
            "from_state_id": previous_input.analysis_state.state_id,
            "to_state_id": current_state.state_id,
            "from_stage": previous_input.analysis_state.stage,
            "to_stage": current_state.stage,
            "action": "weaken",
            "transition_allowed": True,
            "advance": True,
            "stage_changed": False,
            "evidence": evidence,
            "reasons": ("DIRECTION_CHANGED_AFTER_HYSTERESIS",),
        }
    )
    current_input = current_input.model_copy(update={"analysis_state": current_state, "state_transition": transition})
    return AnalysisStrategyConsistencyInput(
        previous_policy_input=previous_input,
        previous_state=previous_input.analysis_state,
        previous_transition=previous_input.state_transition,
        previous_strategy=previous,
        current_policy_input=current_input,
        candidate_strategy=evaluate_gold_strategy_policy(current_input),
    )


@pytest.mark.parametrize("case", json.loads(GOLDEN_CASES.read_text()), ids=lambda case: case["case_id"])
def test_golden_consistency_gate_cases(case: dict[str, str]) -> None:
    scenario = case["scenario"]
    if scenario == "bootstrap":
        current_input = _bootstrap_input()
        gate_input = AnalysisStrategyConsistencyInput(
            current_policy_input=current_input,
            candidate_strategy=evaluate_gold_strategy_policy(current_input),
        )
    elif scenario == "missing_predecessor":
        current_input = _policy_input(bias="bullish", stage="weak_repair")
        gate_input = AnalysisStrategyConsistencyInput(
            current_policy_input=current_input,
            candidate_strategy=evaluate_gold_strategy_policy(current_input),
        )
    elif scenario in {"unchanged", "event_blackout"}:
        previous_input = _policy_input(bias="bullish", stage="trend_confirmed")
        previous = evaluate_gold_strategy_policy(previous_input)
        current_input = (
            previous_input if scenario == "unchanged" else _later_input(previous_input, event_status="blackout")
        )
        gate_input = AnalysisStrategyConsistencyInput(
            previous_policy_input=previous_input,
            previous_state=previous_input.analysis_state,
            previous_transition=previous_input.state_transition,
            previous_strategy=previous,
            current_policy_input=current_input,
            candidate_strategy=evaluate_gold_strategy_policy(current_input),
        )
    elif scenario == "mixed_observe":
        previous_input = _policy_input(bias="mixed", stage="direction_decision")
        previous = evaluate_gold_strategy_policy(previous_input)
        gate_input = AnalysisStrategyConsistencyInput(
            previous_policy_input=previous_input,
            previous_state=previous_input.analysis_state,
            previous_transition=previous_input.state_transition,
            previous_strategy=previous,
            current_policy_input=previous_input,
            candidate_strategy=previous,
        )
    elif scenario == "state_advance":
        previous_input = _policy_input(bias="bullish", stage="weak_repair")
        previous = evaluate_gold_strategy_policy(previous_input)
        current_input = _advanced_input(previous_input)
        gate_input = AnalysisStrategyConsistencyInput(
            previous_policy_input=previous_input,
            previous_state=previous_input.analysis_state,
            previous_transition=previous_input.state_transition,
            previous_strategy=previous,
            current_policy_input=current_input,
            candidate_strategy=evaluate_gold_strategy_policy(current_input),
        )
    elif scenario == "risk_release":
        previous_input = _policy_input(bias="bullish", stage="trend_confirmed", event_risk="blackout")
        previous = evaluate_gold_strategy_policy(previous_input)
        current_input = _later_input(previous_input)
        gate_input = AnalysisStrategyConsistencyInput(
            previous_policy_input=previous_input,
            previous_state=previous_input.analysis_state,
            previous_transition=previous_input.state_transition,
            previous_strategy=previous,
            current_policy_input=current_input,
            candidate_strategy=evaluate_gold_strategy_policy(current_input),
        )
    elif scenario == "candidate_mismatch":
        current_input = _policy_input(bias="bullish", stage="weak_repair")
        expected = evaluate_gold_strategy_policy(current_input)
        payload = expected.model_dump(exclude={"decision_hash", "decision_id"})
        payload["reason_codes"] = (*expected.reason_codes, "CALLER_INVENTED_REASON")
        gate_input = AnalysisStrategyConsistencyInput(
            previous_policy_input=current_input,
            previous_state=current_input.analysis_state,
            previous_transition=current_input.state_transition,
            previous_strategy=expected,
            current_policy_input=current_input,
            candidate_strategy=build_strategy_decision(payload),
        )
    elif scenario == "watch_trigger":
        gate_input = _watch_trigger_gate_input()
    elif scenario == "invalidation":
        gate_input = _invalidation_gate_input()
    elif scenario == "direct_flip":
        gate_input = _direct_flip_gate_input()
    else:
        raise AssertionError(f"unknown golden consistency scenario: {scenario}")

    result = evaluate_analysis_strategy_consistency(gate_input)

    assert result.status.value == case["expected_status"]
    assert result.change_kind.value == case["expected_change_kind"]
    assert result.reason_codes[0].value == case["expected_reason"]
    if expected_strategy_status := case.get("expected_strategy_status"):
        assert gate_input.candidate_strategy.status.value == expected_strategy_status


def test_missing_predecessor_for_non_bootstrap_is_unverifiable() -> None:
    current_input = _policy_input(bias="bullish", stage="weak_repair")
    result = evaluate_analysis_strategy_consistency(
        AnalysisStrategyConsistencyInput(
            current_policy_input=current_input,
            candidate_strategy=evaluate_gold_strategy_policy(current_input),
        )
    )

    assert result.status.value == "unverifiable"
    assert result.reason_codes[0].value == "PREVIOUS_LINEAGE_MISSING"
    assert result.consistency_passed is False


def test_partial_predecessor_is_reported_without_crashing_gate_output() -> None:
    current_input = _policy_input(bias="bullish", stage="weak_repair")
    candidate = evaluate_gold_strategy_policy(current_input)

    result = evaluate_analysis_strategy_consistency(
        AnalysisStrategyConsistencyInput(
            previous_policy_input=current_input,
            previous_state=current_input.analysis_state,
            previous_strategy=None,
            current_policy_input=current_input,
            candidate_strategy=candidate,
        )
    )

    assert result.status.value == "unverifiable"
    assert result.previous_state_id == current_input.analysis_state.state_id
    assert result.previous_strategy_id is None


def test_previous_strategy_must_bind_the_supplied_previous_transition() -> None:
    current_input = _policy_input(bias="bullish", stage="weak_repair")
    previous = evaluate_gold_strategy_policy(current_input)
    alternate_transition = build_state_transition_policy_decision(
        {
            **current_input.state_transition.model_dump(exclude={"decision_hash", "reasons"}),
            "reasons": ("ALTERNATE_PREDECESSOR_PROOF",),
        }
    )
    alternate_previous_input = current_input.model_copy(update={"state_transition": alternate_transition})

    result = evaluate_analysis_strategy_consistency(
        AnalysisStrategyConsistencyInput(
            previous_policy_input=alternate_previous_input,
            previous_state=current_input.analysis_state,
            previous_transition=alternate_transition,
            previous_strategy=previous,
            current_policy_input=current_input,
            candidate_strategy=previous,
        )
    )

    assert result.status.value == "blocked"
    assert result.reason_codes[0].value == "PREVIOUS_STRATEGY_TRANSITION_MISMATCH"


def test_previous_strategy_must_equal_recomputed_previous_policy_output() -> None:
    previous_input = _policy_input(bias="bullish", stage="trend_confirmed")
    formal_previous = evaluate_gold_strategy_policy(previous_input)
    forged_previous = build_strategy_decision(
        {
            **formal_previous.model_dump(
                exclude={
                    "decision_hash",
                    "decision_id",
                    "status",
                    "direction",
                    "no_trade_reason_code",
                    "reason_codes",
                    "release_conditions",
                    "review_triggers",
                }
            ),
            "status": "NO_TRADE",
            "direction": "none",
            "no_trade_reason_code": "MAJOR_EVENT_BLACKOUT",
            "reason_codes": ("MAJOR_EVENT_BLACKOUT",),
            "release_conditions": ("EVENT_WINDOW_CLOSED",),
            "review_triggers": ("ON_EVENT_WINDOW_CLOSE",),
        }
    )
    current_input = _later_input(previous_input)
    candidate = evaluate_gold_strategy_policy(current_input)

    result = evaluate_analysis_strategy_consistency(
        AnalysisStrategyConsistencyInput(
            previous_policy_input=previous_input,
            previous_state=previous_input.analysis_state,
            previous_transition=previous_input.state_transition,
            previous_strategy=forged_previous,
            current_policy_input=current_input,
            candidate_strategy=candidate,
        )
    )

    assert result.status.value == "blocked"
    assert result.reason_codes[0].value == "PREVIOUS_POLICY_OUTPUT_MISMATCH"


def test_current_strategy_cannot_move_backwards_before_previous_strategy() -> None:
    current_input = _policy_input(bias="bullish", stage="weak_repair")
    previous_input = _later_input(current_input)
    previous = evaluate_gold_strategy_policy(previous_input)
    candidate = evaluate_gold_strategy_policy(current_input)

    result = evaluate_analysis_strategy_consistency(
        AnalysisStrategyConsistencyInput(
            previous_policy_input=previous_input,
            previous_state=previous_input.analysis_state,
            previous_transition=previous_input.state_transition,
            previous_strategy=previous,
            current_policy_input=current_input,
            candidate_strategy=candidate,
        )
    )

    assert result.status.value == "blocked"
    assert result.reason_codes[0].value == "TIME_ORDER_INVALID"


def test_advancing_transition_cannot_use_evidence_after_target_state() -> None:
    previous_input = _policy_input(bias="bullish", stage="weak_repair")
    previous = evaluate_gold_strategy_policy(previous_input)
    current_input = _later_input(previous_input)
    state_as_of = previous_input.decision_as_of + timedelta(minutes=3)
    evidence_as_of = previous_input.decision_as_of + timedelta(minutes=4)
    current_state = build_analysis_state(
        {
            **previous_input.analysis_state.model_dump(exclude={"payload_hash", "state_id", "as_of", "source_refs"}),
            "as_of": state_as_of,
            "source_refs": (_ref("past-target-state", state_as_of),),
        }
    )
    future_evidence = TransitionEvidence.model_validate(
        {
            "evidence_id": "evidence:after-target-state",
            "scope": "daily_close",
            "delta_kind": "ordinary",
            "as_of": evidence_as_of,
            "source_refs": (_ref("after-target-state", evidence_as_of),),
            "evidence_categories": ("macro",),
        }
    )
    transition = build_state_transition_policy_decision(
        {
            "from_state_id": previous_input.analysis_state.state_id,
            "to_state_id": current_state.state_id,
            "from_stage": previous_input.analysis_state.stage,
            "to_stage": current_state.stage,
            "action": "strengthen",
            "transition_allowed": True,
            "advance": True,
            "stage_changed": False,
            "evidence": future_evidence,
            "reasons": ("FUTURE_EVIDENCE_ATTACK",),
        }
    )
    current_input = current_input.model_copy(update={"analysis_state": current_state, "state_transition": transition})
    candidate = evaluate_gold_strategy_policy(current_input)

    result = evaluate_analysis_strategy_consistency(
        AnalysisStrategyConsistencyInput(
            previous_policy_input=previous_input,
            previous_state=previous_input.analysis_state,
            previous_transition=previous_input.state_transition,
            previous_strategy=previous,
            current_policy_input=current_input,
            candidate_strategy=candidate,
        )
    )

    assert candidate.no_trade_reason_code is None
    assert result.status.value == "blocked"
    assert result.reason_codes[0].value == "TIME_ORDER_INVALID"


def test_later_no_op_evidence_can_preserve_an_older_canonical_state() -> None:
    previous_input = _policy_input(bias="bullish", stage="weak_repair")
    previous = evaluate_gold_strategy_policy(previous_input)
    current_input = _later_input(previous_input)
    current_evidence = TransitionEvidence.model_validate(
        {
            "evidence_id": "evidence:later-no-op",
            "scope": "daily_close",
            "delta_kind": "no_op",
            "as_of": current_input.decision_as_of,
            "source_refs": (_ref("later-no-op", current_input.decision_as_of),),
        }
    )
    current_transition = build_state_transition_policy_decision(
        {
            "from_state_id": previous_input.analysis_state.state_id,
            "to_state_id": previous_input.analysis_state.state_id,
            "from_stage": previous_input.analysis_state.stage,
            "to_stage": previous_input.analysis_state.stage,
            "action": "maintain",
            "transition_allowed": True,
            "advance": False,
            "stage_changed": False,
            "evidence": current_evidence,
            "reasons": ("NO_MATERIAL_CHANGE",),
        }
    )
    current_input = current_input.model_copy(update={"state_transition": current_transition})
    candidate = evaluate_gold_strategy_policy(current_input)

    result = evaluate_analysis_strategy_consistency(
        AnalysisStrategyConsistencyInput(
            previous_policy_input=previous_input,
            previous_state=previous_input.analysis_state,
            previous_transition=previous_input.state_transition,
            previous_strategy=previous,
            current_policy_input=current_input,
            candidate_strategy=candidate,
        )
    )

    assert current_transition.evidence.as_of > current_input.analysis_state.as_of
    assert result.status.value == "consistent"
    assert result.change_kind.value == "stable_refresh"


def test_state_advance_cannot_replace_triggered_levels_without_proof() -> None:
    previous_input = _policy_input(bias="bullish", stage="trend_confirmed")
    base_as_of = previous_input.decision_as_of
    common = {
        "comparator": "above_or_equal",
        "effective_from": base_as_of - timedelta(days=1),
        "expires_at": base_as_of + timedelta(days=30),
    }

    def triggered_levels(trigger_price: str, invalidation_price: str, start_at):
        trigger_spec = _spec(role="trigger", reference_price=trigger_price, **common)
        active = _direct_state("active", spec=trigger_spec, as_of=start_at)
        touched = evaluate_key_level_lifecycle(
            active,
            _event(
                "touch",
                spec=trigger_spec,
                source_role="official_market",
                factors=("price_touch",),
                as_of=start_at + timedelta(minutes=1),
            ),
        )
        assert touched.state is not None
        held = evaluate_key_level_lifecycle(
            touched.state,
            _event(
                "hold_confirmed",
                spec=trigger_spec,
                source_role="official_market",
                factors=("official_close", "hold_window"),
                as_of=start_at + timedelta(minutes=2),
            ),
        )
        assert held.state is not None
        invalidation = _direct_state(
            "active",
            spec=_spec(
                role="invalidation",
                reference_price=invalidation_price,
                **common,
            ),
            as_of=start_at,
        )
        return (held.state, invalidation), (held.decision,)

    previous_levels, previous_level_decisions = triggered_levels("4500", "4480", base_as_of - timedelta(minutes=3))
    previous_input = previous_input.model_copy(
        update={
            "key_levels": previous_levels,
            "key_level_decisions": previous_level_decisions,
        }
    )
    previous = evaluate_gold_strategy_policy(previous_input)
    replacement_levels, replacement_decisions = triggered_levels("4505", "4490", base_as_of + timedelta(minutes=2))
    current_input = _advanced_input(previous_input, key_levels=replacement_levels).model_copy(
        update={"key_level_decisions": replacement_decisions}
    )
    candidate = evaluate_gold_strategy_policy(current_input)

    result = evaluate_analysis_strategy_consistency(
        AnalysisStrategyConsistencyInput(
            previous_policy_input=previous_input,
            previous_state=previous_input.analysis_state,
            previous_transition=previous_input.state_transition,
            previous_strategy=previous,
            current_policy_input=current_input,
            candidate_strategy=candidate,
        )
    )

    assert previous.status.value == candidate.status.value == "LONG_RESEARCH_TRIGGERED"
    assert result.status.value == "unverifiable"
    assert result.reason_codes[0].value == "UNSUPPORTED_READINESS_CHANGE"


def test_same_status_level_refresh_requires_lifecycle_proof() -> None:
    previous_input = _policy_input(bias="bullish", stage="trend_confirmed")
    previous = evaluate_gold_strategy_policy(previous_input)
    base_as_of = previous_input.decision_as_of
    added_level = _direct_state(
        "active",
        spec=_spec(
            role="trigger",
            comparator="above_or_equal",
            reference_price="4500",
            effective_from=base_as_of - timedelta(days=1),
            expires_at=base_as_of + timedelta(days=30),
        ),
        as_of=base_as_of + timedelta(minutes=1),
    )
    current_input = _later_input(previous_input).model_copy(update={"key_levels": (added_level,)})
    candidate = evaluate_gold_strategy_policy(current_input)

    result = evaluate_analysis_strategy_consistency(
        AnalysisStrategyConsistencyInput(
            previous_policy_input=previous_input,
            previous_state=previous_input.analysis_state,
            previous_transition=previous_input.state_transition,
            previous_strategy=previous,
            current_policy_input=current_input,
            candidate_strategy=candidate,
        )
    )

    assert previous.status.value == candidate.status.value == "LONG_WATCH"
    assert result.status.value == "unverifiable"
    assert result.reason_codes[0].value == "UNSUPPORTED_READINESS_CHANGE"


def test_same_state_watch_to_trigger_requires_continuous_level_proof() -> None:
    gate_input = _watch_trigger_gate_input()

    result = evaluate_analysis_strategy_consistency(gate_input)
    without_chain = evaluate_analysis_strategy_consistency(gate_input.model_copy(update={"key_level_proof": ()}))

    assert gate_input.previous_strategy.status.value == "LONG_WATCH"
    assert gate_input.candidate_strategy.status.value == "LONG_RESEARCH_TRIGGERED"
    assert result.status.value == "consistent"
    assert result.change_kind.value == "readiness_changed"
    assert without_chain.status.value == "unverifiable"


def test_existing_holding_level_is_continuous_proof_for_later_trigger() -> None:
    previous_input = _policy_input(bias="bullish", stage="trend_confirmed", event_risk="watch")
    base_as_of = previous_input.decision_as_of
    common = {
        "comparator": "above_or_equal",
        "reference_price": "4500",
        "effective_from": base_as_of - timedelta(days=1),
        "expires_at": base_as_of + timedelta(days=30),
    }
    trigger_spec = _spec(role="trigger", **common)
    active = _direct_state("active", spec=trigger_spec, as_of=base_as_of - timedelta(minutes=3))
    touched = evaluate_key_level_lifecycle(
        active,
        _event(
            "touch",
            spec=trigger_spec,
            source_role="official_market",
            factors=("price_touch",),
            as_of=base_as_of - timedelta(minutes=2),
        ),
    )
    assert touched.state is not None
    held = evaluate_key_level_lifecycle(
        touched.state,
        _event(
            "hold_confirmed",
            spec=trigger_spec,
            source_role="official_market",
            factors=("official_close", "hold_window"),
            as_of=base_as_of - timedelta(minutes=1),
        ),
    )
    assert held.state is not None
    invalidation = _direct_state(
        "active",
        spec=_spec(role="invalidation", **common),
        as_of=base_as_of - timedelta(minutes=3),
    )
    previous_input = previous_input.model_copy(
        update={
            "key_levels": (held.state, invalidation),
            "key_level_decisions": (held.decision,),
        }
    )
    previous = evaluate_gold_strategy_policy(previous_input)
    current_input = _later_input(previous_input)
    candidate = evaluate_gold_strategy_policy(current_input)

    result = evaluate_analysis_strategy_consistency(
        AnalysisStrategyConsistencyInput(
            previous_policy_input=previous_input,
            previous_state=previous_input.analysis_state,
            previous_transition=previous_input.state_transition,
            previous_strategy=previous,
            current_policy_input=current_input,
            candidate_strategy=candidate,
        )
    )

    assert previous.status.value == "LONG_WATCH"
    assert candidate.status.value == "LONG_RESEARCH_TRIGGERED"
    assert result.status.value == "consistent"


def test_every_selected_trigger_requires_its_own_continuous_proof() -> None:
    previous_input = _policy_input(bias="bullish", stage="trend_confirmed")
    base_as_of = previous_input.decision_as_of
    common = {
        "comparator": "above_or_equal",
        "effective_from": base_as_of - timedelta(days=1),
        "expires_at": base_as_of + timedelta(days=30),
    }
    trigger_specs = (
        _spec(role="trigger", reference_price="4500", **common),
        _spec(role="trigger", reference_price="4510", **common),
    )
    active_triggers = tuple(_direct_state("active", spec=spec, as_of=base_as_of) for spec in trigger_specs)
    invalidation = _direct_state(
        "active",
        spec=_spec(role="invalidation", reference_price="4480", **common),
        as_of=base_as_of,
    )
    previous_input = previous_input.model_copy(update={"key_levels": (*active_triggers, invalidation)})
    previous = evaluate_gold_strategy_policy(previous_input)
    touch_decisions = []
    hold_decisions = []
    held_states = []
    for index, (active, spec) in enumerate(zip(active_triggers, trigger_specs, strict=True)):
        touched = evaluate_key_level_lifecycle(
            active,
            _event(
                "touch",
                spec=spec,
                source_role="official_market",
                factors=("price_touch",),
                as_of=base_as_of + timedelta(minutes=1, seconds=index),
            ),
        )
        assert touched.state is not None
        held = evaluate_key_level_lifecycle(
            touched.state,
            _event(
                "hold_confirmed",
                spec=spec,
                source_role="official_market",
                factors=("official_close", "hold_window"),
                as_of=base_as_of + timedelta(minutes=2, seconds=index),
            ),
        )
        assert held.state is not None
        touch_decisions.append(touched.decision)
        hold_decisions.append(held.decision)
        held_states.append(held.state)
    current_input = _later_input(previous_input).model_copy(
        update={
            "key_levels": (*held_states, invalidation),
            "key_level_decisions": tuple(hold_decisions),
        }
    )
    candidate = evaluate_gold_strategy_policy(current_input)
    incomplete = evaluate_analysis_strategy_consistency(
        AnalysisStrategyConsistencyInput(
            previous_policy_input=previous_input,
            previous_state=previous_input.analysis_state,
            previous_transition=previous_input.state_transition,
            previous_strategy=previous,
            current_policy_input=current_input,
            candidate_strategy=candidate,
            key_level_proof=(touch_decisions[0],),
        )
    )
    complete = evaluate_analysis_strategy_consistency(
        AnalysisStrategyConsistencyInput(
            previous_policy_input=previous_input,
            previous_state=previous_input.analysis_state,
            previous_transition=previous_input.state_transition,
            previous_strategy=previous,
            current_policy_input=current_input,
            candidate_strategy=candidate,
            key_level_proof=tuple(touch_decisions),
        )
    )

    assert candidate.status.value == "LONG_RESEARCH_TRIGGERED"
    assert incomplete.status.value == "unverifiable"
    assert complete.status.value == "consistent"


def test_same_state_invalidation_requires_break_lifecycle_proof() -> None:
    gate_input = _invalidation_gate_input()

    result = evaluate_analysis_strategy_consistency(gate_input)
    no_proof_input = gate_input.current_policy_input.model_copy(update={"key_level_decisions": ()})
    no_proof_candidate = evaluate_gold_strategy_policy(no_proof_input)
    without_proof = evaluate_analysis_strategy_consistency(
        gate_input.model_copy(
            update={
                "current_policy_input": no_proof_input,
                "candidate_strategy": no_proof_candidate,
            }
        )
    )

    assert gate_input.candidate_strategy.status.value == "INVALIDATED"
    assert result.status.value == "consistent"
    assert result.change_kind.value == "invalidated"
    assert without_proof.status.value == "unverifiable"


def test_no_trade_reason_must_be_present_in_closed_reason_list() -> None:
    current_input = _later_input(
        _policy_input(bias="bullish", stage="trend_confirmed"),
        event_status="blackout",
    )
    decision = evaluate_gold_strategy_policy(current_input)
    payload = decision.model_dump(exclude={"decision_hash", "decision_id"})
    payload["reason_codes"] = ("DIFFERENT_REASON",)

    with pytest.raises(ValidationError):
        StrategyDecisionInput.model_validate(payload)


def test_same_input_gate_is_reproducible_100_times() -> None:
    current_input = _bootstrap_input()
    candidate = evaluate_gold_strategy_policy(current_input)
    gate_input = AnalysisStrategyConsistencyInput(
        current_policy_input=current_input,
        candidate_strategy=candidate,
    )
    expected = evaluate_analysis_strategy_consistency(gate_input).model_dump(mode="json")

    assert all(
        evaluate_analysis_strategy_consistency(gate_input).model_dump(mode="json") == expected for _ in range(100)
    )


def test_previous_policy_hash_is_stable_when_key_levels_are_reordered() -> None:
    previous_input = _policy_input(bias="bullish", stage="trend_confirmed")
    as_of = previous_input.decision_as_of
    levels = (
        _direct_state(
            "active",
            spec=_spec(
                role="trigger",
                comparator="above_or_equal",
                reference_price="4500",
                effective_from=as_of - timedelta(days=1),
                expires_at=as_of + timedelta(days=30),
            ),
            as_of=as_of,
        ),
        _direct_state(
            "active",
            spec=_spec(
                role="invalidation",
                comparator="above_or_equal",
                reference_price="4480",
                effective_from=as_of - timedelta(days=1),
                expires_at=as_of + timedelta(days=30),
            ),
            as_of=as_of,
        ),
    )
    previous_input = previous_input.model_copy(update={"key_levels": levels})
    reordered_input = previous_input.model_copy(update={"key_levels": tuple(reversed(levels))})
    previous = evaluate_gold_strategy_policy(previous_input)
    assert evaluate_gold_strategy_policy(reordered_input).decision_id == previous.decision_id

    def gate(policy_input):
        return evaluate_analysis_strategy_consistency(
            AnalysisStrategyConsistencyInput(
                previous_policy_input=policy_input,
                previous_state=previous_input.analysis_state,
                previous_transition=previous_input.state_transition,
                previous_strategy=previous,
                current_policy_input=previous_input,
                candidate_strategy=previous,
            )
        )

    original = gate(previous_input)
    reordered = gate(reordered_input)

    assert original.previous_policy_input_hash == reordered.previous_policy_input_hash
    assert original.proof_hash == reordered.proof_hash
    assert original.decision_id == reordered.decision_id
