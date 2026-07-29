from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from apps.analysis.gold_policy.key_level_schemas import (
    KeyLevelEvent,
    KeyLevelEventType,
    KeyLevelLifecycle,
    KeyLevelLifecycleDecision,
    KeyLevelReadModel,
    KeyLevelQualificationReceiptInput,
    KeyLevelTransitionAction,
    _build_key_level_read_model,
    _build_key_level_qualification_receipt,
    build_key_level_event,
    build_key_level_lifecycle_decision,
    build_key_level_spec,
)


AS_OF = datetime(2026, 7, 29, 21, 0, tzinfo=UTC)
_UNSET = object()


def _ref(source: str = "fixture", *, as_of: datetime = AS_OF) -> dict[str, object]:
    return {
        "source": source,
        "reference": f"artifact://{source}/{as_of.date().isoformat()}",
        "retrieved_at": as_of,
    }


def _spec(**overrides: object):
    payload: dict[str, object] = {
        "scope": "daily_close",
        "level_kind": "point",
        "role": "support",
        "comparator": "above_or_equal",
        "reference_price": "4500.00",
        "band_lower": None,
        "band_upper": None,
        "effective_from": AS_OF,
        "expires_at": AS_OF + timedelta(days=30),
        "origin_key": "jin10:article-1:4500",
        "origin_source_role": "jin10_supplemental",
        "origin_instrument": "XAUUSD_SPOT",
        "origin_contract_id": None,
    }
    payload.update(overrides)
    if "role" in overrides and "comparator" not in overrides:
        payload["comparator"] = {
            "support": "above_or_equal",
            "resistance": "below_or_equal",
            "trigger": "above_or_equal",
            "invalidation": "above_or_equal",
        }.get(str(overrides["role"]), "non_directional")
    return build_key_level_spec(payload)


def _evidence(
    *,
    source_role: str = "jin10_supplemental",
    factors: tuple[str, ...] = ("level_proposal",),
    as_of: datetime = AS_OF,
    quality: str = "accepted",
    freshness: str = "fresh",
    alignment: str = "unknown",
    refs: list[dict[str, object]] | None = None,
    receipt_overrides: dict[str, object] | None = None,
    scope: str = "daily_close",
    timeframe: str | None = None,
    subject_level_id: str | None = None,
) -> dict[str, object]:
    is_cme = source_role in {"cme_options_model", "cme_large_oi"}
    snapshot_ids = [f"snapshot:{source_role}:{as_of.isoformat()}"]
    if "oi_change" in factors:
        snapshot_ids.append(f"snapshot:{source_role}:previous")
    receipt_payload: dict[str, object] = {
        "source_role": source_role,
        "source_instrument": "GC_FUTURES" if is_cme else "XAUUSD_SPOT",
        "qualification_class": (
            "formal_structure"
            if source_role == "cme_options_model"
            else "canonical_market"
            if source_role == "official_market"
            else "system_authority"
            if source_role == "system_scheduler"
            else "proposal_only"
        ),
        "scope": scope,
        "subject_level_id": subject_level_id or _spec(scope=scope).level_id,
        "publication_status": "FINAL" if is_cme else "NOT_APPLICABLE",
        "calculation_method": (
            "black76"
            if source_role == "cme_options_model"
            else "oi_inventory"
            if source_role == "cme_large_oi"
            else "price_candle"
            if source_role == "official_market"
            else "system_rule"
            if source_role == "system_scheduler"
            else "none"
        ),
        "qualified_factors": factors,
        "qualified_snapshot_ids": tuple(snapshot_ids),
        "current_snapshot_id": snapshot_ids[0],
        "previous_snapshot_id": snapshot_ids[1] if len(snapshot_ids) > 1 else None,
        "current_snapshot_as_of": as_of,
        "previous_snapshot_as_of": as_of - timedelta(days=1) if len(snapshot_ids) > 1 else None,
        "contract_id": "GC:2026-08" if is_cme else None,
        "issued_at": as_of,
        "source_refs": tuple(_ref("input_snapshot", as_of=as_of) | {"reference": item} for item in snapshot_ids),
    }
    receipt_payload.update(receipt_overrides or {})
    receipt = _build_key_level_qualification_receipt(KeyLevelQualificationReceiptInput.model_validate(receipt_payload))
    price_rule = (
        "break"
        if "break_window" in factors
        else "reclaim"
        if "reclaim_window" in factors
        else "hold"
        if "hold_window" in factors
        else "touch"
        if "price_touch" in factors
        else "price_structure"
    )
    closes = ("4490", "4490") if price_rule == "break" else ("4510", "4510")
    if price_rule == "touch":
        closes = ("4500",)
    elif price_rule == "price_structure":
        closes = ("4500", "4500")
    return {
        "evidence_id": f"evidence:{source_role}:{as_of.isoformat()}",
        "qualification_receipt": receipt,
        "factors": factors,
        "timeframe": timeframe
        or (
            "contract"
            if is_cme
            else "system"
            if source_role == "system_scheduler"
            else "5m"
            if scope == "intraday"
            else "1w"
            if scope == "weekly_fundamental"
            else "1d"
        ),
        "window_start": as_of - timedelta(days=1),
        "window_end": as_of,
        "price_fact": (
            {
                "snapshot_id": snapshot_ids[0],
                "open": "4500",
                "high": "4512",
                "low": "4489",
                "close": closes[-1],
                "window_closes": closes,
                "window_start": as_of - timedelta(days=1),
                "window_end": as_of,
                "window_complete": True,
                "rule_code": price_rule,
            }
            if source_role == "official_market"
            else None
        ),
        "quality_status": quality,
        "freshness_status": freshness,
        "alignment_status": alignment,
        "as_of": as_of,
        "projection_method": "gc_basis_projection.v1" if is_cme and alignment == "aligned" else None,
        "basis_snapshot_id": "basis:2026-07-29" if is_cme and alignment == "aligned" else None,
        "source_refs": [
            *(refs or [_ref(source_role, as_of=as_of)]),
            {
                "source": "qualification_receipt",
                "reference": receipt.receipt_id,
                "retrieved_at": as_of,
            },
        ],
    }


def _event(
    event_type: str = "discover",
    *,
    spec=None,
    evidence: dict[str, object] | None = None,
):
    spec = spec or _spec()
    return build_key_level_event(
        {
            "event_type": event_type,
            "spec": spec,
            "evidence": evidence or _evidence(subject_level_id=spec.level_id, scope=spec.scope.value),
        }
    )


def _state(
    lifecycle: str,
    *,
    spec=None,
    event=None,
    quality: str = "accepted",
    strategy_eligible: bool | None = None,
    test_count: int = 0,
    previous_state_id: str | None = None,
    authority_status: str | None = None,
    activation_event: object | None = _UNSET,
):
    spec = spec or _spec()
    event = event or (
        _event(
            "activate",
            spec=spec,
            evidence=_evidence(
                source_role="official_market",
                factors=("official_close", "price_structure"),
                alignment="aligned",
                subject_level_id=spec.level_id,
                scope=spec.scope.value,
            ),
        )
        if lifecycle not in {"candidate", "confirmed"}
        else _event(spec=spec)
    )
    eligible = lifecycle in {"active", "holding"} and spec.role.value in {
        "support",
        "resistance",
        "trigger",
        "invalidation",
    }
    if authority_status is None:
        authority_status = {
            "candidate": "candidate_only",
            "confirmed": "formally_confirmed",
        }.get(lifecycle, "canonical_xauusd_validated")
    if activation_event is _UNSET and authority_status == "canonical_xauusd_validated":
        activation_event = event
    elif activation_event is _UNSET:
        activation_event = None
    refs = [
        _ref("state", as_of=event.evidence.as_of),
        {
            "source": "key_level_event",
            "reference": event.event_id,
            "retrieved_at": event.evidence.as_of,
        },
    ]
    if previous_state_id is not None:
        refs.append(
            {
                "source": "key_level_state",
                "reference": previous_state_id,
                "retrieved_at": event.evidence.as_of,
            }
        )
    return _build_key_level_read_model(
        {
            "spec": spec,
            "lifecycle": lifecycle,
            "authority_status": authority_status,
            "activation_event": activation_event,
            "strategy_eligible": eligible if strategy_eligible is None else strategy_eligible,
            "as_of": event.evidence.as_of,
            "quality_status": quality,
            "last_event_id": event.event_id,
            "test_count": test_count,
            "previous_state_id": previous_state_id,
            "source_refs": refs,
        }
    )


def test_point_spec_is_tick_normalized_content_addressed_and_stable() -> None:
    first = _spec(reference_price="4500.004")
    second = _spec(reference_price=Decimal("4500.00"))

    assert first == second
    assert first.reference_price == Decimal("4500.00")
    assert first.level_id.startswith("key_level.v1:")
    assert all(_spec(reference_price="4500.004") == first for _ in range(100))


def test_band_spec_and_identity_dimensions_are_explicit() -> None:
    band = _spec(
        level_kind="band",
        reference_price=None,
        band_lower="4498.001",
        band_upper="4502.009",
    )
    assert band.band_lower == Decimal("4498.00")
    assert band.band_upper == Decimal("4502.01")
    assert band.level_id != _spec().level_id
    assert _spec(origin_key="new-origin").level_id != _spec().level_id
    assert _spec(scope="intraday").level_id != _spec().level_id
    assert (
        _spec(role="trigger", comparator="above_or_equal").level_id
        != _spec(role="trigger", comparator="below_or_equal").level_id
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"level_kind": "point", "reference_price": None},
        {"level_kind": "point", "band_lower": "4499", "band_upper": "4501"},
        {"level_kind": "band", "reference_price": None, "band_lower": "4501", "band_upper": "4500"},
        {"expires_at": AS_OF},
        {"effective_from": datetime(2026, 7, 29, 21, 0)},
        {"role": "support", "comparator": "below_or_equal"},
        {"role": "trigger", "comparator": "non_directional"},
        {"rule_set": {"break_rule": "caller_defined"}},
        {"unexpected": True},
    ],
)
def test_spec_rejects_invalid_shape_time_and_extra_fields(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _spec(**changes)


def test_cme_evidence_preserves_instrument_and_requires_projection_when_aligned() -> None:
    event = _event(
        evidence=_evidence(
            source_role="cme_options_model",
            factors=("gex_wall", "oi_change"),
            alignment="aligned",
        )
    )
    assert event.evidence.source_instrument.value == "GC_FUTURES"
    assert event.evidence.projection_method == "gc_basis_projection.v1"

    invalid = _evidence(source_role="cme_options_model", alignment="aligned")
    invalid["projection_method"] = None
    with pytest.raises(ValidationError, match="projection"):
        _event(evidence=invalid)


def test_evidence_rejects_instrument_mix_future_refs_and_duplicate_factors() -> None:
    with pytest.raises(ValidationError, match="official"):
        _evidence(
            source_role="official_market",
            alignment="aligned",
            receipt_overrides={"source_instrument": "GC_FUTURES"},
        )

    future = _evidence(refs=[_ref(as_of=AS_OF + timedelta(seconds=1))])
    with pytest.raises(ValidationError, match="after as_of"):
        _event(evidence=future)

    with pytest.raises(ValidationError, match="unique"):
        _evidence(factors=("level_proposal", "level_proposal"))


def test_event_rejects_scope_mismatch_and_unqualified_factor_claims() -> None:
    intraday = _evidence(scope="intraday", timeframe="5m")
    with pytest.raises(ValidationError, match="scope must match"):
        _event(spec=_spec(scope="daily_close"), evidence=intraday)

    unqualified = _evidence(factors=("level_proposal",))
    unqualified["factors"] = ("official_close",)
    with pytest.raises(ValidationError, match="qualification receipt"):
        _event(evidence=unqualified)

    missing_previous = _evidence(
        source_role="cme_options_model",
        factors=("gex_wall", "oi_change"),
        alignment="aligned",
        receipt_overrides={
            "previous_snapshot_id": None,
            "previous_snapshot_as_of": None,
        },
    )
    with pytest.raises(ValidationError, match="current and previous"):
        _event("confirm", evidence=missing_previous)


def test_qualification_receipt_cannot_be_reused_for_another_level() -> None:
    qualified_spec = _spec(origin_key="qualified:4500")
    other_spec = _spec(origin_key="other:9999", reference_price="9999")
    evidence = _evidence(
        source_role="official_market",
        factors=("official_close", "price_structure"),
        alignment="aligned",
        subject_level_id=qualified_spec.level_id,
    )
    with pytest.raises(ValidationError, match="subject must match"):
        _event("activate", spec=other_spec, evidence=evidence)


def test_event_identity_normalizes_factor_and_source_ref_order_without_mutation() -> None:
    payload = {
        "event_type": "confirm",
        "spec": _spec(),
        "evidence": _evidence(
            source_role="cme_options_model",
            factors=("oi_change", "gex_wall"),
            alignment="aligned",
            refs=[_ref("z"), _ref("a")],
        ),
    }
    original = deepcopy(payload)
    first = build_key_level_event(payload)
    reversed_payload = deepcopy(payload)
    reversed_payload["evidence"]["factors"] = ("gex_wall", "oi_change")
    receipt_ref = next(ref for ref in payload["evidence"]["source_refs"] if ref["source"] == "qualification_receipt")
    reversed_payload["evidence"]["source_refs"] = [_ref("a"), receipt_ref, _ref("z")]
    second = build_key_level_event(reversed_payload)

    assert first.event_id == second.event_id
    assert payload == original


@pytest.mark.parametrize(
    ("lifecycle", "role", "quality", "eligible", "test_count"),
    [
        ("candidate", "support", "accepted", False, 0),
        ("confirmed", "support", "accepted", False, 0),
        ("active", "support", "accepted", True, 0),
        ("tested", "support", "accepted", False, 1),
        ("holding", "support", "accepted", True, 1),
        ("broken", "support", "accepted", False, 1),
        ("reclaimed", "support", "accepted", False, 1),
        ("retired", "support", "accepted", False, 1),
        ("active", "magnet_pin", "accepted", False, 0),
        ("active", "support", "observe", False, 0),
    ],
)
def test_strategy_eligibility_is_derived_not_caller_owned(
    lifecycle: str,
    role: str,
    quality: str,
    eligible: bool,
    test_count: int,
) -> None:
    spec = _spec(role=role)
    state = _state(
        lifecycle,
        spec=spec,
        quality=quality,
        strategy_eligible=eligible,
        test_count=test_count,
    )
    assert state.strategy_eligible is eligible

    with pytest.raises(ValidationError, match="derived"):
        _state(
            lifecycle,
            spec=spec,
            quality=quality,
            strategy_eligible=not eligible,
            test_count=test_count,
        )


def test_live_state_requires_canonical_activation_lineage() -> None:
    with pytest.raises(ValidationError, match="canonical XAUUSD activation lineage"):
        _state(
            "active",
            authority_status="formally_confirmed",
            activation_event=None,
            strategy_eligible=False,
        )

    fake_activation = _event(
        "discover",
        evidence=_evidence(source_role="jin10_supplemental"),
    )
    with pytest.raises(ValidationError, match="canonical XAUUSD activation lineage"):
        _state("active", activation_event=fake_activation, strategy_eligible=False)

    with pytest.raises(ValidationError, match="formal authority"):
        _state(
            "confirmed",
            authority_status="canonical_xauusd_validated",
            activation_event=_event(),
            strategy_eligible=False,
        )


def test_state_rejects_invalid_test_count_and_missing_previous_state_lineage() -> None:
    with pytest.raises(ValidationError, match="positive test_count"):
        _state("tested", test_count=0, strategy_eligible=False)
    with pytest.raises(ValidationError, match="test_count zero"):
        _state("active", test_count=1)
    with pytest.raises(ValidationError, match="previous key level state"):
        _build_key_level_read_model(
            {
                **_state("candidate").model_dump(exclude={"payload_hash", "state_id", "source_refs"}),
                "previous_state_id": "key_level_read_model.v1:" + "0" * 64,
                "source_refs": [_ref()],
            }
        )

    state = _state("candidate")
    with pytest.raises(ValidationError, match="last key level event"):
        _build_key_level_read_model(
            {
                **state.model_dump(exclude={"payload_hash", "state_id", "source_refs"}),
                "source_refs": [_ref()],
            }
        )


def test_state_and_event_are_frozen_and_reject_tampered_identity() -> None:
    event = _event()
    state = _state("candidate", event=event)
    with pytest.raises(ValidationError):
        state.test_count = 2  # type: ignore[misc]

    event_payload = event.model_dump(mode="python")
    event_payload["event_type"] = "touch"
    with pytest.raises(ValidationError, match="identity"):
        KeyLevelEvent.model_validate(event_payload)

    state_payload = state.model_dump(mode="python")
    state_payload["quality_status"] = "observe"
    with pytest.raises(ValidationError):
        KeyLevelReadModel.model_validate(state_payload)


def test_lifecycle_decision_is_content_addressed_and_enforces_no_op() -> None:
    previous = _state("candidate")
    event = _event("no_op", spec=previous.spec, evidence=_evidence(as_of=AS_OF + timedelta(days=1)))
    payload = {
        "from_state_id": previous.state_id,
        "to_state_id": previous.state_id,
        "from_lifecycle": previous.lifecycle,
        "to_lifecycle": previous.lifecycle,
        "action": "maintain",
        "transition_allowed": True,
        "advance": False,
        "from_strategy_eligible": False,
        "to_strategy_eligible": False,
        "event": event,
        "triggered_rule": "maintain_no_op.v1",
        "reasons": ("NO_MATERIAL_LEVEL_EVENT",),
    }
    decisions = [build_key_level_lifecycle_decision(payload) for _ in range(100)]
    assert all(decision == decisions[0] for decision in decisions)

    with pytest.raises(ValidationError, match="no_op"):
        build_key_level_lifecycle_decision({**payload, "action": "reject"})

    tampered = decisions[0].model_dump(mode="python")
    tampered["reasons"] = ("CHANGED",)
    with pytest.raises(ValidationError, match="hash"):
        KeyLevelLifecycleDecision.model_validate(tampered)


def test_closed_lifecycle_and_event_enums_match_pr6_contract() -> None:
    import apps.analysis.gold_policy as public_policy

    assert not hasattr(public_policy, "build_key_level_read_model")
    assert not hasattr(public_policy, "key_level_strategy_eligible")
    assert not hasattr(public_policy, "build_key_level_qualification_receipt")
    assert {item.value for item in KeyLevelLifecycle} == {
        "candidate",
        "confirmed",
        "active",
        "tested",
        "holding",
        "broken",
        "reclaimed",
        "retired",
    }
    assert {item.value for item in KeyLevelEventType} == {
        "discover",
        "confirm",
        "activate",
        "approach",
        "touch",
        "hold_confirmed",
        "break_confirmed",
        "reclaim_confirmed",
        "reclaim_hold_confirmed",
        "retire",
        "no_op",
    }
    assert KeyLevelTransitionAction.REJECT.value == "reject"
