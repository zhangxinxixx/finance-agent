from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from apps.analysis.gold_policy.consistency_policy import evaluate_analysis_strategy_consistency
from apps.analysis.gold_policy.consistency_schemas import AnalysisStrategyConsistencyInput
from apps.analysis.gold_policy.key_level_market_producer import produce_gold_key_level_lifecycle_events
from apps.analysis.gold_policy.key_level_policy import evaluate_key_level_lifecycle
from apps.analysis.gold_policy.key_level_schemas import (
    KeyLevelEvent,
    KeyLevelQualificationReceiptInput,
    KeyLevelReadModel,
    _build_key_level_qualification_receipt,
    build_key_level_event,
)
from apps.analysis.gold_policy.state_schemas import (
    TransitionEvidence,
    build_analysis_state_v2,
    build_state_transition_policy_decision_v2,
)
from apps.analysis.gold_policy.strategy_policy import evaluate_gold_strategy_policy
from tests.analysis.test_gold_consistency_policy import _advanced_input, _later_input
from tests.analysis.test_gold_strategy_policy import _direct_state, _event, _policy_input, _ref, _spec
from tests.analysis.test_gold_strategy_v2_policy import _v2_input


def _confirmed_level(policy_input, *, role: str = "support", age: timedelta = timedelta(days=3)):
    comparator = "above_or_equal" if role == "support" else "below_or_equal"
    level_as_of = policy_input.decision_as_of - age
    spec = _spec(
        role=role,
        comparator=comparator,
        reference_price="4500",
        effective_from=level_as_of - timedelta(days=1),
        expires_at=policy_input.decision_as_of + timedelta(days=30),
    )
    return _direct_state("confirmed", spec=spec, as_of=level_as_of)


def _producer_rows(*, window_end: datetime, close: float = 4500.0) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for offset in (1, 0):
        close_time = window_end - timedelta(days=offset)
        rows.append(
            {
                "asset": "XAUUSD",
                "timeframe": "1d",
                "open_time": (close_time - timedelta(days=1)).isoformat(),
                "close_time": close_time.isoformat(),
                "open": close,
                "high": close + 5,
                "low": close - 5,
                "close": close,
                "source": "fixture_xauusd_primary_1d",
                "raw_path": f"fixtures/activation-lineage/{close_time.date()}.json",
                "source_ref": {
                    "provider_symbol": "XAUUSD",
                    "instrument_type": "otc_spot_quote_proxy",
                    "source_role": "market_primary",
                    "quality_status": "accepted",
                    "reference": f"fixture://activation-lineage/{close_time.date()}",
                    "retrieved_at": close_time.isoformat(),
                    "sha256": f"{offset + 1:064x}",
                },
            }
        )
    return tuple(rows)


def _producer_activation_event(
    confirmed: KeyLevelReadModel,
    *,
    decision_as_of: datetime,
) -> KeyLevelEvent:
    production = produce_gold_key_level_lifecycle_events(
        previous_states=(confirmed,),
        candidates=_producer_rows(window_end=decision_as_of),
        decision_as_of=decision_as_of,
    )
    assert production.reason_codes == ("KEY_LEVEL_LIFECYCLE_EVENTS_PRODUCED",)
    assert len(production.controls_input.ordered_events) == 1
    return production.controls_input.ordered_events[0]


def _retime_activation_event(
    event: KeyLevelEvent,
    *,
    window_start: datetime,
    window_end: datetime,
    receipt_current_as_of: datetime | None = None,
    receipt_previous_as_of: datetime | None = None,
) -> KeyLevelEvent:
    evidence = event.evidence.model_dump(mode="python")
    fact = event.evidence.price_fact
    assert fact is not None
    evidence["window_start"] = window_start
    evidence["window_end"] = window_end
    evidence["price_fact"] = {
        **fact.model_dump(mode="python"),
        "window_start": window_start,
        "window_end": window_end,
    }

    receipt_payload = event.evidence.qualification_receipt.model_dump(
        mode="python",
        exclude={"receipt_hash", "receipt_id"},
    )
    receipt_payload["current_snapshot_as_of"] = receipt_current_as_of or window_end
    receipt_payload["previous_snapshot_as_of"] = receipt_previous_as_of or window_end - timedelta(days=1)
    receipt = _build_key_level_qualification_receipt(KeyLevelQualificationReceiptInput.model_validate(receipt_payload))
    evidence["qualification_receipt"] = receipt
    evidence["source_refs"] = tuple(
        {
            **ref.model_dump(mode="python"),
            "reference": receipt.receipt_id,
        }
        if ref.source == "qualification_receipt"
        else ref
        for ref in event.evidence.source_refs
    )
    return build_key_level_event(
        {
            **event.model_dump(mode="python", exclude={"event_hash", "event_id"}),
            "evidence": evidence,
        }
    )


def _v2_current(previous_input, *, key_levels, key_level_decisions, state_advance: bool):
    current = _later_input(previous_input)
    as_of = current.decision_as_of
    if state_advance:
        previous_state = previous_input.analysis_state
        state = build_analysis_state_v2(
            {
                **previous_state.model_dump(exclude={"payload_hash", "state_id", "as_of", "source_refs"}),
                "as_of": as_of,
                "source_refs": (_ref("activation-state-v2", as_of),),
            }
        )
        evidence = TransitionEvidence.model_validate(
            {
                "evidence_id": "evidence:activation-state-advance-v2",
                "scope": "daily_close",
                "delta_kind": "ordinary",
                "as_of": as_of,
                "source_refs": (_ref("activation-state-advance-v2", as_of),),
                "evidence_categories": ("structure",),
            }
        )
        transition = build_state_transition_policy_decision_v2(
            {
                "from_state_id": previous_state.state_id,
                "to_state_id": state.state_id,
                "action": "strengthen",
                "transition_allowed": True,
                "advance": True,
                "from_direction": previous_state.direction,
                "to_direction": state.direction,
                "from_direction_tilt": previous_state.direction_tilt,
                "to_direction_tilt": state.direction_tilt,
                "from_market_regime": previous_state.market_regime,
                "to_market_regime": state.market_regime,
                "from_trend_maturity": previous_state.trend_maturity,
                "to_trend_maturity": state.trend_maturity,
                "changed_dimensions": (),
                "evidence": evidence,
                "reasons": ("CANONICAL_STATE_REFRESHED",),
            }
        )
        current = current.model_copy(update={"analysis_state": state, "state_transition": transition})
    return current.model_copy(update={"key_levels": key_levels, "key_level_decisions": key_level_decisions})


def _gate(
    *,
    version: str = "v1",
    role: str = "support",
    state_advance: bool = False,
    previous_levels=None,
    event_mutator=None,
    event_override=None,
    confirmed_override=None,
):
    if version == "v1":
        base = _policy_input(bias="bullish", stage="weak_repair")
    else:
        base = _v2_input(
            direction="bullish",
            tilt="none",
            regime="repair",
            maturity="forming",
        )
    confirmed = confirmed_override or _confirmed_level(base, role=role)
    previous_levels = tuple(previous_levels) if previous_levels is not None else (confirmed,)
    previous_input = base.model_copy(update={"key_levels": previous_levels})
    previous_strategy = evaluate_gold_strategy_policy(previous_input)

    current_shell = (
        _advanced_input(previous_input) if version == "v1" and state_advance else _later_input(previous_input)
    )
    event = event_override or _producer_activation_event(
        confirmed,
        decision_as_of=current_shell.decision_as_of,
    )
    if event_mutator is not None:
        event = event_mutator(event)
    activated = evaluate_key_level_lifecycle(confirmed, event)
    assert activated.state is not None

    if version == "v1":
        current_input = current_shell.model_copy(
            update={
                "key_levels": (activated.state,),
                "key_level_decisions": (activated.decision,),
            }
        )
    else:
        current_input = _v2_current(
            previous_input,
            key_levels=(activated.state,),
            key_level_decisions=(activated.decision,),
            state_advance=state_advance,
        )
    candidate = evaluate_gold_strategy_policy(current_input)
    gate_input = AnalysisStrategyConsistencyInput(
        previous_policy_input=previous_input,
        previous_state=previous_input.analysis_state,
        previous_transition=previous_input.state_transition,
        previous_strategy=previous_strategy,
        current_policy_input=current_input,
        candidate_strategy=candidate,
    )
    return gate_input, confirmed, activated


@pytest.mark.parametrize("version", ["v1", "v2"])
@pytest.mark.parametrize("role", ["support", "resistance"])
@pytest.mark.parametrize("state_advance", [False, True])
def test_exact_confirmed_activation_replay_is_accepted(
    version: str,
    role: str,
    state_advance: bool,
) -> None:
    gate_input, confirmed, activated = _gate(
        version=version,
        role=role,
        state_advance=state_advance,
    )

    result = evaluate_analysis_strategy_consistency(gate_input)

    assert gate_input.previous_strategy.level_refs == ()
    assert confirmed.lifecycle.value == "confirmed"
    assert activated.state is not None and activated.state.lifecycle.value == "active"
    assert result.status.value == "consistent"
    assert result.change_kind.value == ("state_advance" if state_advance else "readiness_changed")


def test_missing_or_orphan_activation_proof_remains_unverifiable() -> None:
    gate_input, _, _ = _gate()
    without_proof_input = gate_input.current_policy_input.model_copy(update={"key_level_decisions": ()})
    missing = evaluate_analysis_strategy_consistency(
        gate_input.model_copy(
            update={
                "current_policy_input": without_proof_input,
                "candidate_strategy": evaluate_gold_strategy_policy(without_proof_input),
            }
        )
    )

    other_gate, _, other_activation = _gate(role="resistance")
    orphan = evaluate_analysis_strategy_consistency(
        gate_input.model_copy(
            update={
                "current_policy_input": without_proof_input,
                "candidate_strategy": evaluate_gold_strategy_policy(without_proof_input),
                "key_level_proof": (other_activation.decision,),
            }
        )
    )

    assert missing.status.value == orphan.status.value == "unverifiable"
    assert missing.reason_codes[0].value == orphan.reason_codes[0].value == "UNSUPPORTED_READINESS_CHANGE"
    assert other_gate.current_policy_input.key_levels[0].spec.role.value == "resistance"


def test_new_level_preserves_existing_from_none_discovery_chain() -> None:
    previous_input = _policy_input(bias="bullish", stage="weak_repair")
    previous_strategy = evaluate_gold_strategy_policy(previous_input)
    current_shell = _later_input(previous_input)
    spec = _spec(
        role="support",
        comparator="above_or_equal",
        reference_price="4500",
        effective_from=previous_input.decision_as_of - timedelta(days=1),
        expires_at=previous_input.decision_as_of + timedelta(days=30),
    )
    discovered = evaluate_key_level_lifecycle(
        None,
        _event(
            "discover",
            spec=spec,
            source_role="jin10_supplemental",
            factors=("level_proposal",),
            as_of=previous_input.decision_as_of + timedelta(minutes=1),
        ),
    )
    assert discovered.state is not None
    confirmed = evaluate_key_level_lifecycle(
        discovered.state,
        _event(
            "confirm",
            spec=spec,
            source_role="cme_options_model",
            factors=("gex_wall", "oi_change"),
            as_of=previous_input.decision_as_of + timedelta(minutes=2),
        ),
    )
    assert confirmed.state is not None
    activated = evaluate_key_level_lifecycle(
        confirmed.state,
        _event(
            "activate",
            spec=spec,
            source_role="official_market",
            factors=("official_close", "price_structure"),
            as_of=current_shell.decision_as_of,
        ),
    )
    assert activated.state is not None
    current_input = current_shell.model_copy(
        update={
            "key_levels": (activated.state,),
            "key_level_decisions": (activated.decision,),
        }
    )
    gate_input = AnalysisStrategyConsistencyInput(
        previous_policy_input=previous_input,
        previous_state=previous_input.analysis_state,
        previous_transition=previous_input.state_transition,
        previous_strategy=previous_strategy,
        current_policy_input=current_input,
        candidate_strategy=evaluate_gold_strategy_policy(current_input),
        key_level_proof=(discovered.decision, confirmed.decision),
    )

    result = evaluate_analysis_strategy_consistency(gate_input)

    assert result.status.value == "consistent"
    assert result.change_kind.value == "readiness_changed"


@pytest.mark.parametrize("prior_kind", ["wrong_confirmed", "candidate", "ambiguous"])
def test_mismatched_or_ambiguous_prior_state_cannot_supplement_strategy_ref(prior_kind: str) -> None:
    gate_input, confirmed, activated = _gate()
    if prior_kind == "wrong_confirmed":
        prior_levels = (
            _direct_state(
                "confirmed",
                spec=confirmed.spec,
                as_of=confirmed.as_of + timedelta(hours=1),
            ),
        )
    elif prior_kind == "candidate":
        prior_levels = (_direct_state("candidate", spec=confirmed.spec, as_of=confirmed.as_of),)
    else:
        prior_levels = (
            confirmed,
            _direct_state(
                "confirmed",
                spec=confirmed.spec,
                as_of=confirmed.as_of + timedelta(hours=1),
            ),
        )
    previous_input = gate_input.previous_policy_input.model_copy(update={"key_levels": prior_levels})
    changed = gate_input.model_copy(
        update={
            "previous_policy_input": previous_input,
            "previous_strategy": evaluate_gold_strategy_policy(previous_input),
            "key_level_proof": (activated.decision,),
        }
    )

    result = evaluate_analysis_strategy_consistency(changed)

    assert result.status.value == "unverifiable"
    assert result.reason_codes[0].value == "UNSUPPORTED_READINESS_CHANGE"


def _bad_support_geometry(event):
    payload = event.model_dump(mode="python", exclude={"event_hash", "event_id"})
    evidence = payload["evidence"]
    evidence["price_fact"] = {
        **evidence["price_fact"],
        "low": "4489",
        "close": "4490",
        "window_closes": ("4490", "4490"),
    }
    return build_key_level_event(payload)


def test_replayed_activation_rejects_bad_geometry() -> None:
    gate_input, _, activated = _gate(event_mutator=_bad_support_geometry)

    result = evaluate_analysis_strategy_consistency(gate_input)

    assert activated.decision.action.value == "activate"
    assert result.status.value == "unverifiable"
    assert result.reason_codes[0].value == "UNSUPPORTED_READINESS_CHANGE"


def test_replayed_activation_requires_window_after_confirmed_state() -> None:
    base = _policy_input(bias="bullish", stage="weak_repair")
    recent = _confirmed_level(base, age=timedelta(hours=12))
    event_source = _direct_state(
        "confirmed",
        spec=recent.spec,
        as_of=base.decision_as_of - timedelta(days=3),
    )
    activation_event = _producer_activation_event(
        event_source,
        decision_as_of=_later_input(base).decision_as_of,
    )
    gate_input, _, activated = _gate(
        confirmed_override=recent,
        event_override=activation_event,
    )

    result = evaluate_analysis_strategy_consistency(gate_input)

    assert activated.decision.event.evidence.window_start < recent.as_of
    assert result.status.value == "unverifiable"
    assert result.reason_codes[0].value == "UNSUPPORTED_READINESS_CHANGE"


@pytest.mark.parametrize("role", ["support", "resistance"])
@pytest.mark.parametrize(
    ("age", "expected_status"),
    [
        (timedelta(0), "consistent"),
        (timedelta(days=1) - timedelta(seconds=1), "consistent"),
        (timedelta(days=1), "unverifiable"),
    ],
)
def test_activation_uses_actual_decision_to_window_end_boundary(
    role: str,
    age: timedelta,
    expected_status: str,
) -> None:
    def retime(event: KeyLevelEvent) -> KeyLevelEvent:
        window_end = event.evidence.as_of - age
        return _retime_activation_event(
            event,
            window_start=window_end - timedelta(days=2),
            window_end=window_end,
        )

    gate_input, _, activated = _gate(role=role, event_mutator=retime)

    result = evaluate_analysis_strategy_consistency(gate_input)

    assert activated.decision.transition_allowed is True
    assert activated.decision.event.evidence.freshness_status == "fresh"
    assert result.status.value == expected_status
    if expected_status == "unverifiable":
        assert result.reason_codes[0].value == "UNSUPPORTED_READINESS_CHANGE"


@pytest.mark.parametrize("role", ["support", "resistance"])
@pytest.mark.parametrize("duration", [timedelta(hours=12), timedelta(days=2, seconds=1)])
def test_activation_rejects_non_exact_two_d1_window(role: str, duration: timedelta) -> None:
    def retime(event: KeyLevelEvent) -> KeyLevelEvent:
        return _retime_activation_event(
            event,
            window_start=event.evidence.window_end - duration,
            window_end=event.evidence.window_end,
        )

    gate_input, _, activated = _gate(role=role, event_mutator=retime)

    result = evaluate_analysis_strategy_consistency(gate_input)

    assert activated.decision.transition_allowed is True
    assert result.status.value == "unverifiable"
    assert result.reason_codes[0].value == "UNSUPPORTED_READINESS_CHANGE"


@pytest.mark.parametrize("role", ["support", "resistance"])
@pytest.mark.parametrize("mismatch", ["current", "previous"])
def test_activation_rejects_receipt_window_timestamp_mismatch(role: str, mismatch: str) -> None:
    def retime(event: KeyLevelEvent) -> KeyLevelEvent:
        window_end = event.evidence.window_end
        current_as_of = window_end - timedelta(minutes=1) if mismatch == "current" else window_end
        previous_as_of = current_as_of - timedelta(days=1)
        if mismatch == "previous":
            previous_as_of -= timedelta(minutes=1)
        return _retime_activation_event(
            event,
            window_start=event.evidence.window_start,
            window_end=window_end,
            receipt_current_as_of=current_as_of,
            receipt_previous_as_of=previous_as_of,
        )

    gate_input, _, activated = _gate(role=role, event_mutator=retime)

    result = evaluate_analysis_strategy_consistency(gate_input)

    assert activated.decision.transition_allowed is True
    assert result.status.value == "unverifiable"
    assert result.reason_codes[0].value == "UNSUPPORTED_READINESS_CHANGE"
