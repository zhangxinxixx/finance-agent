from __future__ import annotations

import pytest
from pydantic import ValidationError

from apps.analysis.gold_policy.attribution_policy import attribute_gold_price
from apps.analysis.gold_policy.state_schemas import (
    TransitionEvidence,
    build_analysis_state_v2,
    build_state_transition_policy_decision_v2,
)
from apps.analysis.gold_policy.strategy_policy import evaluate_gold_strategy_policy
from apps.analysis.gold_policy.strategy_schemas import (
    StrategyDecisionV2Input,
    StrategyPolicyInputV2,
    StrategyStatus,
)
from tests.analysis.test_gold_strategy_policy import (
    _policy_input,
    _ref,
    _triggerable_policy_input,
)
from tests.analysis.test_gold_analysis_v2_contract import _pair


def _v2_input(
    *,
    direction: str,
    tilt: str,
    regime: str,
    maturity: str,
    quality: str = "accepted",
    with_levels: bool = False,
):
    current, previous = _pair(
        {
            "deltas": {
                "real10y_estimated": "-0.06",
                "broad_dollar": "-0.40",
                "xauusd_spot": "12",
            }
        }
    )
    base = _policy_input(
        bias="bullish",
        feature=current,
        attribution=attribute_gold_price(current, previous),
    )
    if with_levels:
        levels = _triggerable_policy_input(bias="bullish")
        base = base.model_copy(
            update={
                "key_levels": levels.key_levels,
                "key_level_decisions": levels.key_level_decisions,
            }
        )
    as_of = base.decision_as_of
    state = build_analysis_state_v2(
        {
            "direction": direction,
            "direction_tilt": tilt,
            "market_regime": regime,
            "trend_maturity": maturity,
            "scope": "daily_close",
            "as_of": as_of,
            "confidence": 0.0 if quality == "blocked" else 0.75,
            "quality_status": quality,
            "source_refs": (_ref("state-v2", as_of),),
        }
    )
    evidence = TransitionEvidence.model_validate(
        {
            "evidence_id": "evidence:v2-noop",
            "scope": "daily_close",
            "delta_kind": "no_op",
            "as_of": as_of,
            "source_refs": (_ref("transition-v2", as_of),),
        }
    )
    transition = build_state_transition_policy_decision_v2(
        {
            "from_state_id": state.state_id,
            "to_state_id": state.state_id,
            "action": "maintain",
            "transition_allowed": True,
            "advance": False,
            "from_direction": state.direction,
            "to_direction": state.direction,
            "from_direction_tilt": state.direction_tilt,
            "to_direction_tilt": state.direction_tilt,
            "from_market_regime": state.market_regime,
            "to_market_regime": state.market_regime,
            "from_trend_maturity": state.trend_maturity,
            "to_trend_maturity": state.trend_maturity,
            "changed_dimensions": (),
            "evidence": evidence,
            "reasons": ("NO_MATERIAL_CHANGE",),
        }
    )
    return StrategyPolicyInputV2(
        decision_as_of=as_of,
        feature_snapshot=base.feature_snapshot,
        analysis_state=state,
        state_transition=transition,
        price_attribution=base.price_attribution,
        key_levels=base.key_levels,
        key_level_decisions=base.key_level_decisions,
        options_regime=base.options_regime,
        event_risk=base.event_risk,
    )


def test_v2_direction_regime_maturity_gates_are_explicit() -> None:
    pressure = evaluate_gold_strategy_policy(
        _v2_input(direction="bullish", tilt="none", regime="pressure", maturity="forming")
    )
    repair = evaluate_gold_strategy_policy(
        _v2_input(direction="bullish", tilt="none", regime="repair", maturity="watching")
    )
    confirmed = evaluate_gold_strategy_policy(
        _v2_input(direction="bullish", tilt="none", regime="trend", maturity="confirmed")
    )

    assert pressure.status is StrategyStatus.OBSERVE
    assert repair.status is StrategyStatus.LONG_WATCH
    assert confirmed.status is StrategyStatus.LONG_WATCH  # formal trigger checks remain required
    assert confirmed.analysis_state_id.startswith("analysis_state.v2:")
    assert (confirmed.state_direction, confirmed.market_regime, confirmed.trend_maturity) == (
        "bullish",
        "trend",
        "confirmed",
    )


def test_v2_mixed_tilt_and_blocked_state_fail_closed() -> None:
    mixed = evaluate_gold_strategy_policy(
        _v2_input(direction="mixed", tilt="bullish", regime="repair", maturity="watching")
    )
    blocked = evaluate_gold_strategy_policy(
        _v2_input(direction="unavailable", tilt="none", regime="range", maturity="forming", quality="blocked")
    )

    assert mixed.status is StrategyStatus.OBSERVE
    assert mixed.direction.value == "none"
    assert mixed.direction_tilt == "bullish"
    assert blocked.status is StrategyStatus.NO_TRADE


def test_v2_identity_is_stable_and_derived_identity_rejects_injection() -> None:
    policy_input = _v2_input(direction="bullish", tilt="none", regime="repair", maturity="watching")
    first = evaluate_gold_strategy_policy(policy_input)
    second = evaluate_gold_strategy_policy(policy_input)

    assert first.decision_id == second.decision_id
    with pytest.raises(ValidationError):
        type(first).model_validate({**first.model_dump(mode="python"), "decision_hash": "0" * 64})


def test_v2_input_rejects_scope_mismatch() -> None:
    base = _v2_input(direction="bullish", tilt="none", regime="repair", maturity="watching")
    with pytest.raises(ValidationError):
        StrategyPolicyInputV2(**{**base.model_dump(), "scope": "weekly_fundamental"})


def test_v2_input_rejects_v1_feature_and_attribution_contracts() -> None:
    base = _v2_input(
        direction="bullish",
        tilt="none",
        regime="repair",
        maturity="watching",
    )
    legacy = _policy_input(bias="bullish")
    payload = base.model_dump(mode="python")

    with pytest.raises(ValidationError):
        StrategyPolicyInputV2.model_validate({**payload, "feature_snapshot": legacy.feature_snapshot})
    with pytest.raises(ValidationError):
        StrategyPolicyInputV2.model_validate({**payload, "price_attribution": legacy.price_attribution})


def test_v2_canonical_invalidation_requires_legal_advancing_transition() -> None:
    base = _v2_input(direction="bullish", tilt="none", regime="trend", maturity="confirmed")
    evidence = TransitionEvidence.model_validate(
        {
            "evidence_id": "evidence:v2-invalidation",
            "scope": "daily_close",
            "delta_kind": "hard_invalidation",
            "as_of": base.decision_as_of,
            "source_refs": (_ref("v2-invalidation", base.decision_as_of),),
            "evidence_categories": ("macro",),
            "rule_code": "MAJOR_MACRO_STATE_INVALIDATED",
        }
    )
    illegal = build_state_transition_policy_decision_v2(
        {
            "from_state_id": base.analysis_state.state_id,
            "to_state_id": base.analysis_state.state_id,
            "action": "invalidate",
            "transition_allowed": False,
            "advance": False,
            "from_direction": base.analysis_state.direction,
            "to_direction": base.analysis_state.direction,
            "from_direction_tilt": base.analysis_state.direction_tilt,
            "to_direction_tilt": base.analysis_state.direction_tilt,
            "from_market_regime": base.analysis_state.market_regime,
            "to_market_regime": base.analysis_state.market_regime,
            "from_trend_maturity": base.analysis_state.trend_maturity,
            "to_trend_maturity": base.analysis_state.trend_maturity,
            "changed_dimensions": (),
            "evidence": evidence,
            "reasons": ("INVALIDATION_REJECTED",),
        }
    )
    assert (
        evaluate_gold_strategy_policy(base.model_copy(update={"state_transition": illegal})).status
        is StrategyStatus.NO_TRADE
    )

    invalidated_state = build_analysis_state_v2(
        {
            **base.analysis_state.model_dump(mode="python", exclude={"payload_hash", "state_id"}),
            "trend_maturity": "invalidated",
        }
    )
    legal = build_state_transition_policy_decision_v2(
        {
            "from_state_id": base.analysis_state.state_id,
            "to_state_id": invalidated_state.state_id,
            "action": "invalidate",
            "transition_allowed": True,
            "advance": True,
            "from_direction": base.analysis_state.direction,
            "to_direction": invalidated_state.direction,
            "from_direction_tilt": base.analysis_state.direction_tilt,
            "to_direction_tilt": invalidated_state.direction_tilt,
            "from_market_regime": base.analysis_state.market_regime,
            "to_market_regime": invalidated_state.market_regime,
            "from_trend_maturity": base.analysis_state.trend_maturity,
            "to_trend_maturity": invalidated_state.trend_maturity,
            "changed_dimensions": ("trend_maturity",),
            "evidence": evidence,
            "reasons": ("INVALIDATION_CONFIRMED",),
        }
    )
    result = evaluate_gold_strategy_policy(
        base.model_copy(update={"analysis_state": invalidated_state, "state_transition": legal})
    )
    assert result.status is StrategyStatus.INVALIDATED


def test_v2_confirmed_trend_never_triggers_without_formal_level_lineage() -> None:
    result = evaluate_gold_strategy_policy(
        _v2_input(direction="bullish", tilt="none", regime="trend", maturity="confirmed")
    )

    assert result.status is StrategyStatus.LONG_WATCH
    assert result.trigger_level_ids == ()
    assert "V2_CONFIRMED_TREND_TRIGGER_CHECKS_PENDING" in result.reason_codes


def test_v2_confirmed_trend_requires_strict_formal_level_lineage() -> None:
    result = evaluate_gold_strategy_policy(
        _v2_input(
            direction="bullish",
            tilt="none",
            regime="trend",
            maturity="confirmed",
            with_levels=True,
        )
    )
    assert result.status is StrategyStatus.LONG_RESEARCH_TRIGGERED

    payload = result.model_dump(
        mode="python",
        exclude={"decision_hash", "decision_id"},
    )
    trigger_index = next(index for index, ref in enumerate(payload["level_refs"]) if ref["role"].value == "trigger")
    for field, value in (
        ("comparator", "below_or_equal"),
        ("authority_status", "candidate_only"),
        ("quality_status", "observe"),
        ("strategy_eligible_at_decision", False),
    ):
        changed = {**payload, "level_refs": [dict(ref) for ref in payload["level_refs"]]}
        changed["level_refs"][trigger_index][field] = value
        with pytest.raises(ValidationError):
            StrategyDecisionV2Input.model_validate(changed)
