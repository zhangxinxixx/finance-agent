from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from apps.analysis.gold_policy.attribution_policy import attribute_gold_price
from apps.analysis.gold_policy.key_level_controls import KeyLevelControlsBuilder
from apps.analysis.gold_policy.key_level_market_producer import (
    produce_gold_key_level_lifecycle_events,
    produce_gold_key_level_market_events,
)
from apps.analysis.gold_policy.key_level_policy import evaluate_key_level_lifecycle
from apps.analysis.gold_policy.key_level_schemas import (
    KeyLevelEvidenceFactor,
    KeyLevelEventType,
    KeyLevelLifecycle,
    _build_key_level_read_model,
)
from apps.analysis.gold_policy.runtime_controls import build_gold_daily_close_runtime_controls
from tests.analysis.test_gold_key_level_market_producer import CUTOFF, WINDOW_END, _rows
from tests.analysis.test_gold_key_level_policy import _direct_state, _spec
from tests.analysis.test_gold_runtime_hard_invalidation import _predecessor_case
from tests.analysis.test_gold_strategy_policy import _policy_input


def _state(
    lifecycle: str,
    *,
    role: str = "support",
    reference_price: str | None = "4500",
    as_of: datetime = WINDOW_END - timedelta(days=3),
    **spec_overrides: object,
):
    spec_payload: dict[str, object] = {
        "role": role,
        "reference_price": reference_price,
        "effective_from": as_of - timedelta(days=30),
        "expires_at": CUTOFF + timedelta(days=30),
        "origin_key": (
            f"lifecycle-producer:{role}:{lifecycle}:{reference_price}:{as_of.isoformat()}"
        ),
    }
    spec_payload.update(spec_overrides)
    spec = _spec(**spec_payload)
    return _direct_state(lifecycle, spec=spec, as_of=as_of)


def _band_state(
    lifecycle: str,
    *,
    role: str,
    as_of: datetime = WINDOW_END - timedelta(days=3),
    **spec_overrides: object,
):
    return _state(
        lifecycle,
        role=role,
        reference_price=None,
        as_of=as_of,
        level_kind="band",
        band_lower="4495",
        band_upper="4505",
        **spec_overrides,
    )


def _rows_with_closes(*closes: float, end: datetime = WINDOW_END):
    assert len(closes) == 2
    rows = _rows(end=end)
    for row, close in zip(rows, closes, strict=True):
        row.update(open=close, high=close + 5, low=close - 5, close=close)
    return rows


@pytest.mark.parametrize("role", ["support", "resistance"])
def test_candidate_confirms_from_canonical_repeated_d1_reaction(role: str) -> None:
    state = _state("candidate", role=role)
    rows = _rows_with_closes(4495.5, 4504.5)
    frozen = deepcopy(rows)

    production = produce_gold_key_level_lifecycle_events(
        previous_states=(state,),
        candidates=rows,
        decision_as_of=CUTOFF,
    )

    assert rows == frozen
    assert production.controls_input.previous_states == (state,)
    assert production.reason_codes == ("KEY_LEVEL_LIFECYCLE_EVENTS_PRODUCED",)
    assert len(production.controls_input.ordered_events) == 1
    event = production.controls_input.ordered_events[0]
    assert event.event_type is KeyLevelEventType.CONFIRM
    assert event.spec == state.spec
    assert event.evidence.factors == (
        KeyLevelEvidenceFactor.PRICE_STRUCTURE,
        KeyLevelEvidenceFactor.REPEATED_REACTION,
    )
    assert event.evidence.price_fact is not None
    assert event.evidence.price_fact.rule_code == "price_structure"
    assert event.evidence.window_start == WINDOW_END - timedelta(days=2)
    assert event.evidence.window_end == WINDOW_END
    assert event.evidence.as_of == CUTOFF
    assert event.evidence.projection_method is None
    assert event.evidence.basis_snapshot_id is None

    transition = evaluate_key_level_lifecycle(state, event)
    assert transition.state is not None
    assert transition.state.lifecycle is KeyLevelLifecycle.CONFIRMED
    assert transition.decision.action.value == "confirm"
    assert transition.decision.transition_allowed is True


@pytest.mark.parametrize(
    ("role", "close"),
    [("support", 4500.0), ("resistance", 4500.0)],
)
def test_confirmed_activates_only_from_two_legal_side_closes(role: str, close: float) -> None:
    state = _state("confirmed", role=role)

    production = produce_gold_key_level_lifecycle_events(
        previous_states=(state,),
        candidates=_rows_with_closes(close, close),
        decision_as_of=CUTOFF,
    )

    event = production.controls_input.ordered_events[0]
    assert event.event_type is KeyLevelEventType.ACTIVATE
    assert event.evidence.factors == (
        KeyLevelEvidenceFactor.OFFICIAL_CLOSE,
        KeyLevelEvidenceFactor.PRICE_STRUCTURE,
    )
    assert event.evidence.price_fact is not None
    assert event.evidence.price_fact.rule_code == "price_structure"
    assert event.event_type is not KeyLevelEventType.BREAK_CONFIRMED

    transition = evaluate_key_level_lifecycle(state, event)
    assert transition.state is not None
    assert transition.state.lifecycle is KeyLevelLifecycle.ACTIVE
    assert transition.state.activation_event == event
    assert transition.decision.action.value == "activate"


@pytest.mark.parametrize(
    ("role", "close"),
    [("support", 4499.99), ("resistance", 4500.01)],
)
def test_confirmed_illegal_activation_side_fails_closed(role: str, close: float) -> None:
    state = _state("confirmed", role=role)

    production = produce_gold_key_level_lifecycle_events(
        previous_states=(state,),
        candidates=_rows_with_closes(close, close),
        decision_as_of=CUTOFF,
    )

    assert production.controls_input.ordered_events == ()
    assert production.reason_codes == ("KEY_LEVEL_ACTIVATION_SIDE_NOT_CONFIRMED",)


@pytest.mark.parametrize(
    ("role", "boundary_close"),
    [("support", 4495.0), ("resistance", 4505.0)],
)
def test_band_activation_includes_directional_boundary(role: str, boundary_close: float) -> None:
    state = _band_state("confirmed", role=role)

    production = produce_gold_key_level_lifecycle_events(
        previous_states=(state,),
        candidates=_rows_with_closes(boundary_close, boundary_close),
        decision_as_of=CUTOFF,
    )

    assert production.controls_input.ordered_events[0].event_type is KeyLevelEventType.ACTIVATE


def test_band_reaction_tolerance_is_inclusive_and_count_is_not_invented() -> None:
    at_boundary = _band_state("candidate", role="support")
    accepted = produce_gold_key_level_lifecycle_events(
        previous_states=(at_boundary,),
        candidates=_rows_with_closes(4490.5, 4509.5),
        decision_as_of=CUTOFF,
    )
    assert accepted.controls_input.ordered_events[0].event_type is KeyLevelEventType.CONFIRM

    outside = produce_gold_key_level_lifecycle_events(
        previous_states=(at_boundary,),
        candidates=_rows_with_closes(4490.49, 4509.51),
        decision_as_of=CUTOFF,
    )
    assert outside.controls_input.ordered_events == ()
    assert outside.reason_codes == ("KEY_LEVEL_REPEATED_REACTION_NOT_CONFIRMED",)

    needs_three = _band_state(
        "candidate",
        role="support",
        rule_set={"repeated_reaction_min_count": 3},
    )
    insufficient = produce_gold_key_level_lifecycle_events(
        previous_states=(needs_three,),
        candidates=_rows_with_closes(4500.0, 4500.0),
        decision_as_of=CUTOFF,
    )
    assert insufficient.controls_input.ordered_events == ()
    assert insufficient.reason_codes == ("KEY_LEVEL_REPEATED_REACTION_NOT_CONFIRMED",)


def test_candidate_never_skips_directly_to_active() -> None:
    state = _state("candidate", role="support")
    production = produce_gold_key_level_lifecycle_events(
        previous_states=(state,),
        candidates=_rows_with_closes(4500.0, 4500.0),
        decision_as_of=CUTOFF,
    )

    assert len(production.controls_input.ordered_events) == 1
    event = production.controls_input.ordered_events[0]
    assert event.event_type is KeyLevelEventType.CONFIRM
    result = evaluate_key_level_lifecycle(state, event)
    assert result.state is not None
    assert result.state.lifecycle is KeyLevelLifecycle.CONFIRMED


def test_mixed_lifecycle_emits_at_most_one_transition_per_existing_level() -> None:
    candidate = _state("candidate", reference_price="4500")
    confirmed = _state("confirmed", role="resistance", reference_price="4510")
    live = _state("holding", reference_price="4510")

    production = produce_gold_key_level_lifecycle_events(
        previous_states=(live, confirmed, candidate),
        candidates=_rows_with_closes(4499.0, 4499.0),
        decision_as_of=CUTOFF,
    )

    assert production.controls_input.previous_states == tuple(
        sorted((live, confirmed, candidate), key=lambda item: item.spec.level_id)
    )
    assert len(production.controls_input.ordered_events) == 3
    assert {event.spec.level_id for event in production.controls_input.ordered_events} == {
        candidate.spec.level_id,
        confirmed.spec.level_id,
        live.spec.level_id,
    }
    assert {event.event_type for event in production.controls_input.ordered_events} == {
        KeyLevelEventType.CONFIRM,
        KeyLevelEventType.ACTIVATE,
        KeyLevelEventType.BREAK_CONFIRMED,
    }


def test_mixed_opposite_break_directions_reject_every_event() -> None:
    support = _state("holding", role="support", reference_price="4510")
    resistance = _state("active", role="resistance", reference_price="4490")
    candidate = _state("candidate", reference_price="4499")

    production = produce_gold_key_level_lifecycle_events(
        previous_states=(support, resistance, candidate),
        candidates=_rows_with_closes(4499.0, 4499.0),
        decision_as_of=CUTOFF,
    )

    assert production.controls_input.ordered_events == ()
    assert production.reason_codes == ("KEY_LEVEL_BREAK_DIRECTION_AMBIGUOUS",)


def test_live_only_result_and_legacy_break_identity_are_byte_identical() -> None:
    state = _state("holding", reference_price="4510")
    rows = _rows_with_closes(4499.0, 4499.0)

    legacy = produce_gold_key_level_market_events(
        previous_states=(state,), candidates=rows, decision_as_of=CUTOFF
    )
    lifecycle = produce_gold_key_level_lifecycle_events(
        previous_states=(state,), candidates=reversed(rows), decision_as_of=CUTOFF
    )

    assert lifecycle.model_dump_json() == legacy.model_dump_json()
    assert lifecycle.controls_input.ordered_events[0].event_id == (
        legacy.controls_input.ordered_events[0].event_id
    )


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("gc_origin", "KEY_LEVEL_STATE_ORIGIN_NOT_XAUUSD"),
        ("bad_lifecycle", "KEY_LEVEL_STATE_NOT_ACCEPTED_LIFECYCLE_HEAD"),
        ("bad_quality", "KEY_LEVEL_STATE_NOT_ACCEPTED_LIFECYCLE_HEAD"),
        ("unsupported_role", "KEY_LEVEL_STATE_NOT_SUPPORT_OR_RESISTANCE"),
    ],
)
def test_invalid_prior_lineage_role_or_quality_fails_closed(mutation: str, reason: str) -> None:
    if mutation == "gc_origin":
        state = _state(
            "candidate",
            origin_source_role="cme_options_model",
            origin_instrument="GC_FUTURES",
            origin_contract_id="GC:2026-12",
        )
    else:
        state = _state("candidate")
        if mutation == "bad_lifecycle":
            state = _state("retired")
        elif mutation == "bad_quality":
            payload = state.model_dump(mode="python", exclude={"payload_hash", "state_id"})
            payload["quality_status"] = "observe"
            state = _build_key_level_read_model(payload)
        else:
            state = _state("candidate", role="trigger")

    production = produce_gold_key_level_lifecycle_events(
        previous_states=(state,),
        candidates=_rows_with_closes(4500.0, 4500.0),
        decision_as_of=CUTOFF,
    )

    assert production.controls_input.ordered_events == ()
    assert reason in production.reason_codes


def test_complete_window_must_not_straddle_or_relabel_prior_state() -> None:
    window_start = WINDOW_END - timedelta(days=2)
    exact = _state("candidate", as_of=window_start)
    exact_result = produce_gold_key_level_lifecycle_events(
        previous_states=(exact,),
        candidates=_rows_with_closes(4500.0, 4500.0),
        decision_as_of=CUTOFF,
    )
    assert exact_result.controls_input.ordered_events[0].event_type is KeyLevelEventType.CONFIRM

    straddled = _state("candidate", as_of=window_start + timedelta(seconds=1))
    straddled_result = produce_gold_key_level_lifecycle_events(
        previous_states=(straddled,),
        candidates=_rows_with_closes(4500.0, 4500.0),
        decision_as_of=CUTOFF,
    )
    assert straddled_result.controls_input.ordered_events == ()
    assert straddled_result.reason_codes == ("D1_MARKET_WINDOW_NOT_FULLY_NEWER_THAN_STATE",)


@pytest.mark.parametrize("case", ["expired", "pending", "at_cutoff"])
def test_expired_pending_or_cutoff_time_prior_fails_closed(case: str) -> None:
    if case == "expired":
        state = _state("candidate", expires_at=CUTOFF)
        reason = "KEY_LEVEL_STATE_EXPIRED_OR_NOT_EFFECTIVE"
    elif case == "pending":
        state = _state(
            "candidate",
            effective_from=CUTOFF + timedelta(hours=1),
            expires_at=CUTOFF + timedelta(days=30),
        )
        reason = "KEY_LEVEL_STATE_EXPIRED_OR_NOT_EFFECTIVE"
    else:
        state = _state("candidate", as_of=CUTOFF)
        reason = "KEY_LEVEL_STATE_AFTER_DECISION_CUTOFF"

    production = produce_gold_key_level_lifecycle_events(
        previous_states=(state,),
        candidates=_rows_with_closes(4500.0, 4500.0),
        decision_as_of=CUTOFF,
    )

    assert production.controls_input.previous_states == (state,)
    assert production.controls_input.ordered_events == ()
    assert production.reason_codes == (reason,)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("asset", "GC", "D1_MARKET_ASSET_NOT_CANONICAL_XAUUSD"),
        ("timeframe", "5m", "D1_MARKET_TIMEFRAME_INVALID"),
        ("raw_path", "", "D1_MARKET_RAW_LINEAGE_MISSING"),
    ],
)
def test_shared_market_validation_rejects_noncanonical_rows(
    field: str,
    value: str,
    reason: str,
) -> None:
    rows = _rows_with_closes(4500.0, 4500.0)
    rows[0][field] = value

    production = produce_gold_key_level_lifecycle_events(
        previous_states=(_state("candidate"),),
        candidates=rows,
        decision_as_of=CUTOFF,
    )

    assert production.controls_input.ordered_events == ()
    assert reason in production.reason_codes


@pytest.mark.parametrize("lifecycle", ["candidate", "confirmed"])
def test_actual_controls_and_runtime_keep_typed_transition_proof(lifecycle: str) -> None:
    predecessor, previous, current = _predecessor_case("v1")
    policy_input = _policy_input(feature=current, attribution=attribute_gold_price(current, previous))
    end = current.as_of
    state = _state(
        lifecycle,
        reference_price="4500",
        as_of=end - timedelta(days=3),
        effective_from=end - timedelta(days=30),
        expires_at=policy_input.decision_as_of + timedelta(days=30),
        origin_key=f"runtime-roundtrip:{lifecycle}",
    )
    rows = _rows_with_closes(4500.0, 4500.0, end=end)

    production = produce_gold_key_level_lifecycle_events(
        previous_states=(state,),
        candidates=rows,
        decision_as_of=policy_input.decision_as_of,
    )
    direct = KeyLevelControlsBuilder().build(production.controls_input)
    runtime = build_gold_daily_close_runtime_controls(
        current_feature=current,
        previous_feature=previous,
        previous_transition=predecessor.transition_decision,
        decision_as_of=policy_input.decision_as_of,
        options_regime_snapshot=policy_input.options_regime,
        key_level_controls_input=production.controls_input,
    )

    expected_action = "confirm" if lifecycle == "candidate" else "activate"
    assert direct.key_level_decisions[0].action.value == expected_action
    assert direct.key_level_decisions[0].transition_allowed is True
    assert runtime.key_level_decisions == direct.key_level_decisions
    assert runtime.key_level_proof == direct.key_level_proof
    assert runtime.key_levels == direct.key_levels
