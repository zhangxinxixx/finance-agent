from datetime import UTC, datetime, timedelta

import pytest

from apps.analysis.gold_policy.key_level_controls import (
    KeyLevelControls,
    KeyLevelControlsBuilder,
    KeyLevelControlsInput,
)
from apps.analysis.gold_policy.key_level_schemas import (
    KeyLevelQualificationReceiptInput,
    _build_key_level_qualification_receipt,
    build_key_level_event,
    build_key_level_spec,
)


AS_OF = datetime(2026, 8, 1, tzinfo=UTC)


def _source_ref(source: str, as_of: datetime) -> dict[str, object]:
    return {"source": source, "reference": f"fixture://{source}/{as_of.isoformat()}", "retrieved_at": as_of}


def _spec(*, origin_key: str = "fixture:4500"):
    return build_key_level_spec(
        {
            "scope": "daily_close",
            "level_kind": "point",
            "role": "support",
            "comparator": "above_or_equal",
            "reference_price": "4500.00",
            "effective_from": AS_OF,
            "expires_at": AS_OF + timedelta(days=30),
            "origin_key": origin_key,
            "origin_source_role": "jin10_supplemental",
            "origin_instrument": "XAUUSD_SPOT",
            "origin_contract_id": None,
        }
    )


def _event(*, spec, as_of: datetime, event_type: str = "discover"):
    source_role = "jin10_supplemental"
    factors = ("level_proposal",)
    snapshot_id = f"snapshot:{as_of.isoformat()}"
    receipt = _build_key_level_qualification_receipt(
        KeyLevelQualificationReceiptInput.model_validate(
            {
                "source_role": source_role,
                "source_instrument": "XAUUSD_SPOT",
                "qualification_class": "proposal_only",
                "scope": spec.scope,
                "subject_level_id": spec.level_id,
                "publication_status": "NOT_APPLICABLE",
                "calculation_method": "none",
                "qualified_factors": factors,
                "qualified_snapshot_ids": (snapshot_id,),
                "current_snapshot_id": snapshot_id,
                "current_snapshot_as_of": as_of,
                "issued_at": as_of,
                "source_refs": ({"source": "input_snapshot", "reference": snapshot_id, "retrieved_at": as_of},),
            }
        )
    )
    return build_key_level_event(
        {
            "event_type": event_type,
            "spec": spec,
            "evidence": {
                "evidence_id": f"evidence:{event_type}:{spec.level_id}:{as_of.isoformat()}",
                "qualification_receipt": receipt,
                "factors": factors,
                "timeframe": "1d",
                "window_start": as_of - timedelta(hours=1),
                "window_end": as_of,
                "quality_status": "accepted",
                "freshness_status": "fresh",
                "alignment_status": "unknown",
                "as_of": as_of,
                "source_refs": (
                    _source_ref(source_role, as_of),
                    {"source": "qualification_receipt", "reference": receipt.receipt_id, "retrieved_at": as_of},
                ),
            },
        }
    )


def test_builder_returns_deterministic_state_decisions_and_exact_proof() -> None:
    first, second = _spec(origin_key="fixture:one"), _spec(origin_key="fixture:two")
    events = (_event(spec=first, as_of=AS_OF), _event(spec=second, as_of=AS_OF + timedelta(minutes=1)))

    controls = KeyLevelControlsBuilder().build(
        KeyLevelControlsInput(decision_as_of=AS_OF + timedelta(minutes=1), scope="daily_close", ordered_events=events)
    )

    assert tuple(state.spec.level_id for state in controls.key_levels) == tuple(
        sorted((first.level_id, second.level_id))
    )
    assert controls.key_level_proof == controls.key_level_decisions
    assert controls.reason_codes == ("PROPOSAL_ONLY_SOURCE",)
    assert controls == KeyLevelControlsBuilder().build(
        KeyLevelControlsInput(decision_as_of=AS_OF + timedelta(minutes=1), scope="daily_close", ordered_events=events)
    )


def test_builder_empty_input_is_explicit() -> None:
    controls = KeyLevelControlsBuilder().build(KeyLevelControlsInput(decision_as_of=AS_OF, scope="daily_close"))
    assert controls.key_levels == controls.key_level_decisions == controls.key_level_proof == ()
    assert controls.reason_codes == ("NO_KEY_LEVEL_INPUT",)


def test_builder_rejects_future_scope_duplicate_and_unordered_lifecycle_input() -> None:
    spec = _spec()
    future = _event(spec=spec, as_of=AS_OF + timedelta(minutes=1))
    with pytest.raises(ValueError, match="cannot be after"):
        KeyLevelControlsInput(decision_as_of=AS_OF, scope="daily_close", ordered_events=(future,))

    candidate = (
        KeyLevelControlsBuilder()
        .build(
            KeyLevelControlsInput(
                decision_as_of=AS_OF, scope="daily_close", ordered_events=(_event(spec=spec, as_of=AS_OF),)
            )
        )
        .key_levels[0]
    )
    with pytest.raises(ValueError, match="duplicate levels"):
        KeyLevelControlsInput(decision_as_of=AS_OF, scope="daily_close", previous_states=(candidate, candidate))

    later = _event(spec=_spec(origin_key="fixture:later"), as_of=AS_OF + timedelta(minutes=2))
    earlier = _event(spec=_spec(origin_key="fixture:earlier"), as_of=AS_OF + timedelta(minutes=1))
    with pytest.raises(ValueError, match="must be ordered"):
        KeyLevelControlsInput(decision_as_of=later.evidence.as_of, scope="daily_close", ordered_events=(later, earlier))


def test_controls_reject_inconsistent_proof() -> None:
    event = _event(spec=_spec(), as_of=AS_OF)
    decision = (
        KeyLevelControlsBuilder()
        .build(KeyLevelControlsInput(decision_as_of=AS_OF, scope="daily_close", ordered_events=(event,)))
        .key_level_decisions[0]
    )
    with pytest.raises(ValueError, match="proof must exactly match"):
        KeyLevelControls(key_level_decisions=(decision,), key_level_proof=())


def test_builder_carries_formal_trigger_confirmation_and_invalidation_lifecycles() -> None:
    from tests.analysis.test_gold_key_level_policy import (
        AS_OF as POLICY_AS_OF,
        _event as policy_event,
        _spec as policy_spec,
    )

    trigger = policy_spec(
        role="trigger",
        comparator="above_or_equal",
        origin_key="formal:trigger:4550",
    )
    invalidation = policy_spec(
        role="invalidation",
        comparator="above_or_equal",
        origin_key="formal:invalidation:4450",
    )

    def lifecycle(spec):
        return (
            policy_event(
                "discover",
                spec=spec,
                source_role="jin10_supplemental",
                factors=("level_proposal",),
                as_of=POLICY_AS_OF,
            ),
            policy_event(
                "confirm",
                spec=spec,
                source_role="cme_options_model",
                factors=("gex_wall", "oi_change"),
                as_of=POLICY_AS_OF + timedelta(days=1),
            ),
            policy_event(
                "activate",
                spec=spec,
                source_role="official_market",
                factors=("official_close", "price_structure"),
                as_of=POLICY_AS_OF + timedelta(days=2),
            ),
            policy_event(
                "touch",
                spec=spec,
                source_role="official_market",
                factors=("price_touch",),
                as_of=POLICY_AS_OF + timedelta(days=3),
            ),
            policy_event(
                "hold_confirmed",
                spec=spec,
                source_role="official_market",
                factors=("official_close", "hold_window"),
                as_of=POLICY_AS_OF + timedelta(days=4),
            ),
        )

    events = tuple(
        sorted(
            (*lifecycle(trigger), *lifecycle(invalidation)),
            key=lambda event: (event.evidence.as_of, event.event_id),
        )
    )
    controls = KeyLevelControlsBuilder().build(
        KeyLevelControlsInput(
            decision_as_of=POLICY_AS_OF + timedelta(days=4),
            scope="daily_close",
            ordered_events=events,
        )
    )

    assert {level.spec.role.value for level in controls.key_levels} == {
        "trigger",
        "invalidation",
    }
    assert all(level.lifecycle.value == "holding" for level in controls.key_levels), [
        (level.spec.role.value, level.lifecycle.value) for level in controls.key_levels
    ]
    assert len(controls.key_level_decisions) == 10
    assert controls.key_level_proof == controls.key_level_decisions
