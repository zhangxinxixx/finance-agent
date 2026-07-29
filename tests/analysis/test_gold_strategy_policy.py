from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from apps.analysis.gold_policy.attribution_policy import attribute_gold_price
from apps.analysis.gold_policy.feature_snapshot import build_feature_snapshot
from apps.analysis.gold_policy.key_level_policy import evaluate_key_level_lifecycle
from apps.analysis.gold_policy.state_schemas import (
    TransitionEvidence,
    build_analysis_state,
    build_state_transition_policy_decision,
)
from apps.analysis.gold_policy.strategy_policy import evaluate_gold_strategy_policy
from apps.analysis.gold_policy.strategy_schemas import (
    StrategyPolicyInput,
    build_strategy_event_risk,
    build_strategy_options_regime,
)
from tests.analysis.test_gold_key_level_policy import _direct_state, _event, _spec


FIXTURES = Path(__file__).parents[1] / "fixtures" / "gold_policy"
GOLDEN_CASES = Path(__file__).parents[1] / "fixtures" / "gold_strategy" / "v1_decision_cases.json"


def _snapshot(name: str = "feature_snapshot_v1_bullish_2025-01-17.json"):
    return build_feature_snapshot(json.loads((FIXTURES / name).read_text()))


def _current(direction: str = "bullish"):
    previous = _snapshot()
    payload = previous.model_dump(
        mode="json",
        exclude={"data_quality", "payload_hash", "snapshot_id"},
    )
    changes = (
        {
            "xauusd_spot": 2712.0,
            "real10y": 2.05,
            "broad_dollar": 120.6,
            "t10yie": 2.40,
        }
        if direction != "bearish"
        else {
            "xauusd_spot": 2694.0,
            "real10y": 2.22,
            "broad_dollar": 121.4,
            "t10yie": 2.29,
        }
    )
    for field_name, value in changes.items():
        payload[field_name]["value"] = value
    return build_feature_snapshot(payload), previous


def _ref(name: str, as_of) -> dict[str, object]:
    return {
        "source": name,
        "reference": f"artifact://{name}/{as_of.isoformat()}",
        "retrieved_at": as_of,
    }


def _policy_input(
    *,
    bias: str = "bullish",
    stage: str = "pressure",
    quality: str = "accepted",
    event_risk: str = "clear",
    feature=None,
    attribution=None,
    options_source_snapshot_id: str | None = None,
) -> StrategyPolicyInput:
    if feature is None:
        feature, previous = _current("bearish" if bias == "bearish" else "bullish")
    else:
        previous = _snapshot()
    attribution = attribution or attribute_gold_price(feature, previous)
    decision_as_of = feature.as_of + timedelta(minutes=5)
    state_bias = "unavailable" if quality == "blocked" else bias
    state = build_analysis_state(
        {
            "stage": stage,
            "directional_bias": state_bias,
            "scope": "daily_close",
            "as_of": decision_as_of,
            "confidence": 0.0 if quality == "blocked" else 0.75,
            "quality_status": quality,
            "source_refs": (_ref("canonical-state", decision_as_of),),
        }
    )
    evidence = TransitionEvidence.model_validate(
        {
            "evidence_id": "evidence:no-op",
            "scope": "daily_close",
            "delta_kind": "no_op",
            "as_of": decision_as_of,
            "source_refs": (_ref("state-transition", decision_as_of),),
        }
    )
    transition = build_state_transition_policy_decision(
        {
            "from_state_id": state.state_id,
            "to_state_id": state.state_id,
            "from_stage": state.stage,
            "to_stage": state.stage,
            "action": "maintain",
            "transition_allowed": True,
            "advance": False,
            "stage_changed": False,
            "evidence": evidence,
            "reasons": ("NO_MATERIAL_CHANGE",),
        }
    )
    event_payload: dict[str, object] = {
        "as_of": decision_as_of,
        "risk_status": event_risk,
        "quality_status": "accepted" if event_risk != "unavailable" else "observe",
        "source_refs": (_ref("event-calendar", decision_as_of),),
    }
    if event_risk == "blackout":
        event_payload.update(
            {
                "active_event_ids": ("FOMC",),
                "window_start": decision_as_of - timedelta(minutes=5),
                "window_end": decision_as_of + timedelta(minutes=25),
                "next_review_at": decision_as_of + timedelta(minutes=25),
            }
        )
    return StrategyPolicyInput(
        decision_as_of=decision_as_of,
        feature_snapshot=feature,
        analysis_state=state,
        state_transition=transition,
        price_attribution=attribution,
        options_regime=build_strategy_options_regime(
            {
                "source_snapshot_id": options_source_snapshot_id or feature.snapshot_id,
                "as_of": decision_as_of,
                "regime": "normal",
                "directional_bias": (bias if bias in {"bullish", "bearish"} else "neutral"),
                "freshness_status": "fresh",
                "quality_status": "accepted",
                "alignment_status": "aligned",
                "source_refs": (_ref("options-regime", decision_as_of),),
            }
        ),
        event_risk=build_strategy_event_risk(event_payload),
    )


@pytest.mark.parametrize("case", json.loads(GOLDEN_CASES.read_text()), ids=lambda case: case["case_id"])
def test_golden_decision_cases(case: dict[str, str]) -> None:
    decision = evaluate_gold_strategy_policy(
        _policy_input(
            bias=case["bias"],
            stage=case["stage"],
            event_risk=case.get("event_risk", "clear"),
        )
    )

    assert decision.status.value == case["expected_status"]
    assert decision.direction.value == case["expected_direction"]
    if "expected_reason" in case:
        assert decision.no_trade_reason_code.value == case["expected_reason"]


def test_blocked_feature_data_is_no_trade_with_release_and_review() -> None:
    blocked = _snapshot("feature_snapshot_v1_blocked_2025-01-22.json")
    decision = evaluate_gold_strategy_policy(
        _policy_input(
            feature=blocked,
            attribution=attribute_gold_price(blocked, _snapshot()),
        )
    )

    assert decision.status.value == "NO_TRADE"
    assert decision.no_trade_reason_code.value == "DATA_QUALITY_BLOCKED"
    assert decision.release_conditions
    assert decision.review_triggers


@pytest.mark.parametrize("quality", ["observe", "blocked"])
def test_unaccepted_analysis_state_never_creates_directional_strategy(quality: str) -> None:
    decision = evaluate_gold_strategy_policy(_policy_input(quality=quality))

    assert decision.status.value == "NO_TRADE"
    assert decision.direction.value == "none"
    assert decision.no_trade_reason_code.value == "ANALYSIS_STATE_NOT_ACCEPTED"


def test_cross_product_lineage_mismatch_fails_closed() -> None:
    decision = evaluate_gold_strategy_policy(_policy_input(options_source_snapshot_id="feature_snapshot.v1:other"))

    assert decision.status.value == "NO_TRADE"
    assert decision.no_trade_reason_code.value == "INPUT_LINEAGE_INVALID"


def test_event_risk_unavailable_fails_closed() -> None:
    decision = evaluate_gold_strategy_policy(_policy_input(event_risk="unavailable"))

    assert decision.status.value == "NO_TRADE"
    assert decision.no_trade_reason_code.value == "EVENT_RISK_UNAVAILABLE"


def test_stale_event_risk_cannot_authorize_a_directional_strategy() -> None:
    base = _policy_input(bias="bullish", stage="trend_confirmed")
    stale_as_of = base.decision_as_of - timedelta(minutes=1)
    stale_event = build_strategy_event_risk(
        {
            "as_of": stale_as_of,
            "risk_status": "clear",
            "quality_status": "accepted",
            "source_refs": (_ref("stale-event-calendar", stale_as_of),),
        }
    )

    decision = evaluate_gold_strategy_policy(base.model_copy(update={"event_risk": stale_event}))

    assert decision.status.value == "NO_TRADE"
    assert decision.no_trade_reason_code.value == "INPUT_TIME_INVALID"


def test_unapproved_invalidation_cannot_flip_strategy_state() -> None:
    base = _policy_input(bias="bullish", stage="trend_confirmed")
    evidence = TransitionEvidence.model_validate(
        {
            "evidence_id": "evidence:unapproved-invalidation",
            "scope": "daily_close",
            "delta_kind": "ordinary",
            "as_of": base.decision_as_of,
            "source_refs": (_ref("unapproved-invalidation", base.decision_as_of),),
            "evidence_categories": ("price",),
        }
    )
    transition = build_state_transition_policy_decision(
        {
            "from_state_id": base.analysis_state.state_id,
            "to_state_id": base.analysis_state.state_id,
            "from_stage": base.analysis_state.stage,
            "to_stage": base.analysis_state.stage,
            "action": "invalidate",
            "transition_allowed": False,
            "advance": False,
            "stage_changed": False,
            "evidence": evidence,
            "reasons": ("INVALIDATION_NOT_CONFIRMED",),
        }
    )

    decision = evaluate_gold_strategy_policy(base.model_copy(update={"state_transition": transition}))

    assert decision.status.value == "NO_TRADE"
    assert decision.no_trade_reason_code.value == "INVALIDATION_NOT_CANONICAL"


def test_broken_invalidation_preserves_the_causal_level_lineage() -> None:
    base = _policy_input(bias="bearish", stage="trend_confirmed")
    broken = _direct_state(
        "broken",
        spec=_spec(
            role="invalidation",
            comparator="below_or_equal",
            effective_from=base.decision_as_of - timedelta(days=1),
            expires_at=base.decision_as_of + timedelta(days=30),
        ),
        as_of=base.decision_as_of,
    )

    decision = evaluate_gold_strategy_policy(base.model_copy(update={"key_levels": (broken,)}))

    assert decision.status.value == "INVALIDATED"
    assert decision.invalidation_level_ids == (broken.spec.level_id,)
    assert decision.key_level_state_ids == (broken.state_id,)
    assert decision.level_refs[0].lifecycle.value == "broken"
    assert decision.level_refs[0].strategy_eligible_at_decision is False


def test_no_formal_trigger_event_can_never_emit_research_triggered() -> None:
    decision = evaluate_gold_strategy_policy(_policy_input(bias="bullish", stage="trend_confirmed"))

    assert decision.status.value == "LONG_WATCH"
    assert "VERIFIED_TRIGGER_EVENT_MISSING" in decision.reason_codes
    assert not decision.trigger_level_ids


@pytest.mark.parametrize(
    ("bias", "comparator", "reference_price", "expected"),
    [
        ("bullish", "above_or_equal", "4500", "LONG_RESEARCH_TRIGGERED"),
        ("bearish", "below_or_equal", "4510", "SHORT_RESEARCH_TRIGGERED"),
    ],
)
def test_research_trigger_requires_verified_hold_and_invalidation_lineage(
    bias: str,
    comparator: str,
    reference_price: str,
    expected: str,
) -> None:
    base = _policy_input(bias=bias, stage="trend_confirmed")
    level_as_of = base.decision_as_of - timedelta(minutes=3)
    common_spec = {
        "comparator": comparator,
        "reference_price": reference_price,
        "effective_from": level_as_of - timedelta(days=1),
        "expires_at": level_as_of + timedelta(days=30),
    }
    trigger_spec = _spec(role="trigger", **common_spec)
    active = _direct_state("active", spec=trigger_spec, as_of=level_as_of)
    tested = evaluate_key_level_lifecycle(
        active,
        _event(
            "touch",
            spec=trigger_spec,
            source_role="official_market",
            factors=("price_touch",),
            as_of=level_as_of + timedelta(minutes=1),
        ),
    )
    assert tested.state is not None
    held = evaluate_key_level_lifecycle(
        tested.state,
        _event(
            "hold_confirmed",
            spec=trigger_spec,
            source_role="official_market",
            factors=("official_close", "hold_window"),
            as_of=level_as_of + timedelta(minutes=2),
        ),
    )
    assert held.state is not None
    invalidation = _direct_state(
        "active",
        spec=_spec(role="invalidation", **common_spec),
        as_of=level_as_of,
    )
    policy_input = base.model_copy(
        update={
            "key_levels": (held.state, invalidation),
            "key_level_decisions": (held.decision,),
        }
    )

    decision = evaluate_gold_strategy_policy(policy_input)

    assert decision.status.value == expected
    assert decision.trigger_level_ids == (trigger_spec.level_id,)
    assert decision.invalidation_level_ids == (invalidation.spec.level_id,)


def test_same_input_is_exactly_reproducible_100_times() -> None:
    policy_input = _policy_input(bias="bearish", stage="reversal_watch")
    expected = evaluate_gold_strategy_policy(policy_input).model_dump(mode="json")

    assert all(evaluate_gold_strategy_policy(policy_input).model_dump(mode="json") == expected for _ in range(100))
