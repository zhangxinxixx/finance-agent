from __future__ import annotations

from datetime import timedelta

import pytest

from apps.analysis.gold_policy.attribution_policy import attribute_gold_price
from apps.analysis.gold_policy.daily_close_loop import evaluate_gold_daily_close_loop
from apps.analysis.gold_policy.daily_close_schemas import DailyCloseLoopInput
from apps.analysis.gold_policy.key_level_policy import evaluate_key_level_lifecycle
from apps.analysis.gold_policy.key_level_schemas import build_key_level_lifecycle_decision
from apps.analysis.gold_policy.state_schemas import TransitionEvidence
from apps.analysis.gold_policy.state_transition_policy import ordinary_stage_distance
from apps.analysis.gold_policy.strategy_schemas import build_strategy_decision
from tests.analysis.test_gold_key_level_policy import _direct_state as _direct_level_state
from tests.analysis.test_gold_key_level_policy import _event as _level_event
from tests.analysis.test_gold_key_level_policy import _spec as _level_spec
from tests.analysis.test_gold_strategy_policy import _policy_input, _ref, _snapshot


def _evidence(
    as_of,
    *,
    delta_kind: str = "ordinary",
    categories: tuple[str, ...] | None = None,
    rule_code: str | None = None,
) -> TransitionEvidence:
    payload: dict[str, object] = {
        "evidence_id": f"evidence:daily-loop:{delta_kind}:{as_of.isoformat()}",
        "scope": "daily_close",
        "delta_kind": delta_kind,
        "as_of": as_of,
        "source_refs": (_ref(f"daily-loop-{delta_kind}", as_of),),
    }
    if delta_kind != "no_op":
        payload["evidence_categories"] = categories or ("macro",)
    if rule_code is not None:
        payload["rule_code"] = rule_code
    return TransitionEvidence.model_validate(payload)


def _bootstrap_result():
    current = _snapshot("feature_snapshot_v1_bearish_2025-01-21.json")
    previous = _snapshot("feature_snapshot_v1_bullish_2025-01-17.json")
    attribution = attribute_gold_price(current, previous)
    support = _policy_input(bias="bearish", feature=current, attribution=attribution)
    result = evaluate_gold_daily_close_loop(
        DailyCloseLoopInput(
            decision_as_of=support.decision_as_of,
            current_feature=current,
            previous_feature=previous,
            transition_evidence=_evidence(support.decision_as_of),
            options_regime=support.options_regime,
            event_risk=support.event_risk,
        )
    )
    return result, current


def _ordinary_result():
    previous_result, previous_feature = _bootstrap_result()
    current = _snapshot("feature_snapshot_v1_mixed_2025-01-24.json")
    attribution = attribute_gold_price(current, previous_feature)
    support = _policy_input(feature=current, attribution=attribution)
    result = evaluate_gold_daily_close_loop(
        DailyCloseLoopInput(
            decision_as_of=support.decision_as_of,
            current_feature=current,
            previous_feature=previous_feature,
            previous_policy_input=previous_result.strategy_policy_input,
            previous_state=previous_result.analysis_state,
            previous_transition=previous_result.transition_decision,
            previous_strategy=previous_result.candidate_strategy,
            transition_evidence=_evidence(support.decision_as_of),
            options_regime=support.options_regime,
            event_risk=support.event_risk,
        )
    )
    return result, current, previous_result


def _confirmed_support_break(as_of, *, reference_price: str = "4500"):
    spec = _level_spec(
        reference_price=reference_price,
        effective_from=as_of - timedelta(days=30),
        expires_at=as_of + timedelta(days=30),
        origin_key=f"fixture:{reference_price}",
    )
    holding = _direct_level_state(
        "holding",
        spec=spec,
        as_of=as_of - timedelta(days=1),
    )
    result = evaluate_key_level_lifecycle(
        holding,
        _level_event(
            "break_confirmed",
            spec=spec,
            source_role="official_market",
            factors=("official_close", "break_window"),
            as_of=as_of,
        ),
    )
    assert result.state is not None
    return result.state, result.decision


def test_accepted_bootstrap_builds_the_complete_formal_chain() -> None:
    result, _ = _bootstrap_result()

    assert result.canonical_action.value == "bootstrap"
    assert result.analysis_state is not None
    assert result.strategy_policy_input is not None
    assert result.candidate_strategy is not None
    assert result.consistency_decision.status.value == "consistent"
    assert result.selected_state_id == result.analysis_state.state_id
    assert result.selected_strategy_id == result.candidate_strategy.decision_id
    assert result.model_invocations == 0


def test_no_op_preserves_state_and_is_reproducible() -> None:
    previous_result, previous_feature = _bootstrap_result()
    current = _snapshot("feature_snapshot_v1_mixed_2025-01-24.json")
    attribution = attribute_gold_price(current, previous_feature)
    support = _policy_input(bias="bearish", feature=current, attribution=attribution)
    loop_input = DailyCloseLoopInput(
        decision_as_of=support.decision_as_of,
        current_feature=current,
        previous_feature=previous_feature,
        previous_policy_input=previous_result.strategy_policy_input,
        previous_state=previous_result.analysis_state,
        previous_transition=previous_result.transition_decision,
        previous_strategy=previous_result.candidate_strategy,
        transition_evidence=_evidence(support.decision_as_of, delta_kind="no_op"),
        options_regime=support.options_regime,
        event_risk=support.event_risk,
    )

    result = evaluate_gold_daily_close_loop(loop_input)
    expected = result.model_dump(mode="json")

    assert result.canonical_action.value == "maintain"
    assert result.analysis_state.state_id == previous_result.analysis_state.state_id
    assert result.transition_decision.advance is False
    assert result.model_invocations == 0
    assert all(evaluate_gold_daily_close_loop(loop_input).model_dump(mode="json") == expected for _ in range(100))


def test_ordinary_change_never_moves_more_than_one_stage() -> None:
    result, _, previous_result = _ordinary_result()

    assert result.consistency_decision.consistency_passed is True
    assert (
        ordinary_stage_distance(
            previous_result.analysis_state.stage,
            result.analysis_state.stage,
        )
        <= 1
    )
    assert result.canonical_action.value == "advance"


def test_typed_hard_invalidation_is_audited_and_selected() -> None:
    previous_result, previous_feature, _ = _ordinary_result()
    current = _snapshot("feature_snapshot_v1_event_flat_2025-01-29.json")
    attribution = attribute_gold_price(current, previous_feature)
    support = _policy_input(feature=current, attribution=attribution)
    broken_level, break_decision = _confirmed_support_break(support.decision_as_of)

    result = evaluate_gold_daily_close_loop(
        DailyCloseLoopInput(
            decision_as_of=support.decision_as_of,
            current_feature=current,
            previous_feature=previous_feature,
            previous_policy_input=previous_result.strategy_policy_input,
            previous_state=previous_result.analysis_state,
            previous_transition=previous_result.transition_decision,
            previous_strategy=previous_result.candidate_strategy,
            transition_evidence=_evidence(
                support.decision_as_of,
                delta_kind="hard_invalidation",
                categories=("price",),
                rule_code="CONFIRMED_SUPPORT_BREAK",
            ),
            options_regime=support.options_regime,
            event_risk=support.event_risk,
            key_levels=(broken_level,),
            key_level_decisions=(break_decision,),
            key_level_proof=(break_decision,),
        )
    )

    assert result.transition_decision.action.value == "invalidate"
    assert result.transition_decision.advance is True
    assert result.candidate_strategy.status.value == "INVALIDATED"
    assert result.consistency_decision.consistency_passed is True
    assert result.canonical_action.value == "advance"


def test_price_level_hard_invalidation_requires_canonical_break_proof() -> None:
    previous_result, previous_feature, _ = _ordinary_result()
    current = _snapshot("feature_snapshot_v1_event_flat_2025-01-29.json")
    support = _policy_input(
        feature=current,
        attribution=attribute_gold_price(current, previous_feature),
    )

    with pytest.raises(ValueError, match="canonical XAUUSD break proof"):
        DailyCloseLoopInput(
            decision_as_of=support.decision_as_of,
            current_feature=current,
            previous_feature=previous_feature,
            previous_policy_input=previous_result.strategy_policy_input,
            previous_state=previous_result.analysis_state,
            previous_transition=previous_result.transition_decision,
            previous_strategy=previous_result.candidate_strategy,
            transition_evidence=_evidence(
                support.decision_as_of,
                delta_kind="hard_invalidation",
                categories=("price",),
                rule_code="CONFIRMED_SUPPORT_BREAK",
            ),
            options_regime=support.options_regime,
            event_risk=support.event_risk,
        )


def test_price_level_hard_invalidation_rejects_cross_level_forged_proof() -> None:
    previous_result, previous_feature, _ = _ordinary_result()
    current = _snapshot("feature_snapshot_v1_event_flat_2025-01-29.json")
    support = _policy_input(
        feature=current,
        attribution=attribute_gold_price(current, previous_feature),
    )
    _, valid_decision = _confirmed_support_break(support.decision_as_of)
    unrelated_level, _ = _confirmed_support_break(
        support.decision_as_of,
        reference_price="4600",
    )
    forged = build_key_level_lifecycle_decision(
        valid_decision.model_copy(
            update={"to_state_id": unrelated_level.state_id}
        ).model_dump(exclude={"decision_hash"})
    )

    with pytest.raises(ValueError, match="canonical XAUUSD break proof"):
        DailyCloseLoopInput(
            decision_as_of=support.decision_as_of,
            current_feature=current,
            previous_feature=previous_feature,
            previous_policy_input=previous_result.strategy_policy_input,
            previous_state=previous_result.analysis_state,
            previous_transition=previous_result.transition_decision,
            previous_strategy=previous_result.candidate_strategy,
            transition_evidence=_evidence(
                support.decision_as_of,
                delta_kind="hard_invalidation",
                categories=("price",),
                rule_code="CONFIRMED_SUPPORT_BREAK",
            ),
            options_regime=support.options_regime,
            event_risk=support.event_risk,
            key_levels=(unrelated_level,),
            key_level_decisions=(forged,),
            key_level_proof=(forged,),
        )


def test_consistency_rejection_keeps_previous_canonical_selection() -> None:
    previous_result, previous_feature = _bootstrap_result()
    current = _snapshot("feature_snapshot_v1_mixed_2025-01-24.json")
    support = _policy_input(
        feature=current,
        attribution=attribute_gold_price(current, previous_feature),
    )
    forged_payload = previous_result.candidate_strategy.model_dump(exclude={"decision_hash", "decision_id"})
    forged_payload.update(
        {
            "status": "OBSERVE",
            "direction": "none",
            "reason_codes": ("FORGED_PREVIOUS_OUTPUT",),
            "no_trade_reason_code": None,
            "release_conditions": (),
            "review_triggers": (),
        }
    )
    forged_previous = build_strategy_decision(forged_payload)

    result = evaluate_gold_daily_close_loop(
        DailyCloseLoopInput(
            decision_as_of=support.decision_as_of,
            current_feature=current,
            previous_feature=previous_feature,
            previous_policy_input=previous_result.strategy_policy_input,
            previous_state=previous_result.analysis_state,
            previous_transition=previous_result.transition_decision,
            previous_strategy=forged_previous,
            transition_evidence=_evidence(
                support.decision_as_of,
                delta_kind="no_op",
            ),
            options_regime=support.options_regime,
            event_risk=support.event_risk,
        )
    )

    assert result.analysis_state is not None
    assert result.candidate_strategy is not None
    assert result.consistency_decision.consistency_passed is False
    assert result.canonical_action.value == "hold"
    assert result.selected_state_id == previous_result.analysis_state.state_id
    assert result.selected_strategy_id == forged_previous.decision_id


def test_blocked_day_keeps_state_and_emits_formal_no_trade() -> None:
    bootstrap, previous_feature = _bootstrap_result()
    blocked = _snapshot("feature_snapshot_v1_blocked_2025-01-22.json")
    blocked_support = _policy_input(
        bias="bearish",
        feature=blocked,
        attribution=attribute_gold_price(blocked, previous_feature),
    )

    result = evaluate_gold_daily_close_loop(
        DailyCloseLoopInput(
            decision_as_of=blocked_support.decision_as_of,
            current_feature=blocked,
            previous_feature=previous_feature,
            previous_policy_input=bootstrap.strategy_policy_input,
            previous_state=bootstrap.analysis_state,
            previous_transition=bootstrap.transition_decision,
            previous_strategy=bootstrap.candidate_strategy,
            transition_evidence=_evidence(blocked_support.decision_as_of),
            options_regime=blocked_support.options_regime,
            event_risk=blocked_support.event_risk,
        )
    )

    assert result.analysis_state.state_id == bootstrap.analysis_state.state_id
    assert result.transition_decision.advance is False
    assert result.candidate_strategy.status.value == "NO_TRADE"
    assert result.candidate_strategy.no_trade_reason_code.value == "DATA_QUALITY_BLOCKED"
    assert result.consistency_decision.status.value == "consistent"
    assert result.canonical_action.value == "maintain"


def test_unbootstrapped_blocked_day_holds_without_fabricating_state() -> None:
    blocked = _snapshot("feature_snapshot_v1_blocked_2025-01-22.json")
    previous = _snapshot("feature_snapshot_v1_bearish_2025-01-21.json")
    support = _policy_input(
        feature=blocked,
        attribution=attribute_gold_price(blocked, previous),
    )

    result = evaluate_gold_daily_close_loop(
        DailyCloseLoopInput(
            decision_as_of=support.decision_as_of,
            current_feature=blocked,
            previous_feature=previous,
            transition_evidence=_evidence(support.decision_as_of),
            options_regime=support.options_regime,
            event_risk=support.event_risk,
        )
    )

    assert result.canonical_action.value == "hold"
    assert result.analysis_state is None
    assert result.candidate_strategy is None
    assert result.consistency_decision is None
    assert result.reason_codes[0].value == "NO_CANONICAL_STATE_AVAILABLE"
