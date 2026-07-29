from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.analysis.gold_policy.key_level_policy import evaluate_key_level_lifecycle
from apps.analysis.gold_policy.key_level_schemas import (
    KeyLevelLifecycle,
    KeyLevelQualificationReceiptInput,
    _build_key_level_qualification_receipt,
    _build_key_level_read_model,
    build_key_level_event,
    build_key_level_spec,
    key_level_strategy_eligible_at,
)


AS_OF = datetime(2026, 7, 29, 21, 0, tzinfo=UTC)
FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "gold_key_levels" / "v1_lifecycle_sequences.json"


def _ref(source: str, as_of: datetime) -> dict[str, object]:
    return {
        "source": source,
        "reference": f"artifact://{source}/{as_of.isoformat()}",
        "retrieved_at": as_of,
    }


def _spec(**overrides: object):
    payload: dict[str, object] = {
        "scope": "daily_close",
        "level_kind": "point",
        "role": "support",
        "comparator": "above_or_equal",
        "reference_price": "4500.00",
        "effective_from": AS_OF,
        "expires_at": AS_OF + timedelta(days=30),
        "origin_key": "fixture:4500",
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
    source_role: str,
    factors: tuple[str, ...],
    *,
    as_of: datetime,
    quality: str = "accepted",
    freshness: str = "fresh",
    alignment: str | None = None,
    scope: str = "daily_close",
    publication_status: str | None = None,
    calculation_method: str | None = None,
    contract_id: str | None = None,
    subject_level_id: str | None = None,
) -> dict[str, object]:
    is_cme = source_role in {"cme_options_model", "cme_large_oi"}
    if alignment is None:
        alignment = (
            "aligned" if source_role in {"official_market", "cme_options_model", "system_scheduler"} else "unknown"
        )
    snapshot_ids = [f"snapshot:{source_role}:{as_of.isoformat()}"]
    if "oi_change" in factors:
        snapshot_ids.append(f"snapshot:{source_role}:previous")
    qualification_class = (
        "formal_structure"
        if source_role == "cme_options_model"
        else "canonical_market"
        if source_role == "official_market"
        else "system_authority"
        if source_role == "system_scheduler"
        else "proposal_only"
    )
    publication_status = publication_status or ("FINAL" if is_cme else "NOT_APPLICABLE")
    calculation_method = calculation_method or (
        "black76"
        if source_role == "cme_options_model"
        else "oi_inventory"
        if source_role == "cme_large_oi"
        else "price_candle"
        if source_role == "official_market"
        else "system_rule"
        if source_role == "system_scheduler"
        else "none"
    )
    receipt = _build_key_level_qualification_receipt(
        KeyLevelQualificationReceiptInput.model_validate(
            {
                "source_role": source_role,
                "source_instrument": "GC_FUTURES" if is_cme else "XAUUSD_SPOT",
                "qualification_class": qualification_class,
                "scope": scope,
                "subject_level_id": subject_level_id or _spec(scope=scope).level_id,
                "publication_status": publication_status,
                "calculation_method": calculation_method,
                "qualified_factors": factors,
                "qualified_snapshot_ids": tuple(snapshot_ids),
                "current_snapshot_id": snapshot_ids[0],
                "previous_snapshot_id": snapshot_ids[1] if len(snapshot_ids) > 1 else None,
                "current_snapshot_as_of": as_of,
                "previous_snapshot_as_of": as_of - timedelta(days=1) if len(snapshot_ids) > 1 else None,
                "contract_id": contract_id or ("GC:2026-08" if is_cme else None),
                "issued_at": as_of,
                "source_refs": tuple(
                    {
                        "source": "input_snapshot",
                        "reference": snapshot_id,
                        "retrieved_at": as_of,
                    }
                    for snapshot_id in snapshot_ids
                ),
            }
        )
    )
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
        "evidence_id": f"evidence:{source_role}:{as_of.isoformat()}:{'-'.join(factors)}",
        "qualification_receipt": receipt,
        "factors": factors,
        "timeframe": (
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
        "source_refs": (
            _ref(source_role, as_of),
            {
                "source": "qualification_receipt",
                "reference": receipt.receipt_id,
                "retrieved_at": as_of,
            },
        ),
    }


def _event(
    event_type: str,
    *,
    spec,
    source_role: str,
    factors: tuple[str, ...],
    as_of: datetime,
    retirement_rule: str | None = None,
    **evidence_overrides: object,
):
    evidence_overrides.setdefault("scope", spec.scope.value)
    evidence_overrides.setdefault("subject_level_id", spec.level_id)
    return build_key_level_event(
        {
            "event_type": event_type,
            "spec": spec,
            "evidence": _evidence(
                source_role,
                factors,
                as_of=as_of,
                **evidence_overrides,
            ),
            "retirement_rule": retirement_rule,
        }
    )


def _direct_state(
    lifecycle: str,
    *,
    spec=None,
    as_of: datetime = AS_OF,
    role: str = "support",
    test_count: int | None = None,
):
    spec = spec or _spec(role=role)
    if lifecycle == "candidate":
        authority_status = "candidate_only"
        last_event = _event(
            "discover",
            spec=spec,
            source_role="jin10_supplemental",
            factors=("level_proposal",),
            as_of=as_of,
        )
        activation_event = None
    elif lifecycle == "confirmed":
        authority_status = "formally_confirmed"
        last_event = _event(
            "confirm",
            spec=spec,
            source_role="cme_options_model",
            factors=("gex_wall", "oi_change"),
            as_of=as_of,
        )
        activation_event = None
    else:
        authority_status = "canonical_xauusd_validated"
        activation_event = _event(
            "activate",
            spec=spec,
            source_role="official_market",
            factors=("official_close", "price_structure"),
            as_of=as_of,
        )
        last_event = activation_event
    if test_count is None:
        test_count = 1 if lifecycle in {"tested", "holding", "broken", "reclaimed", "retired"} else 0
    strategy_eligible = lifecycle in {"active", "holding"} and role in {
        "support",
        "resistance",
        "trigger",
        "invalidation",
    }
    return _build_key_level_read_model(
        {
            "spec": spec,
            "lifecycle": lifecycle,
            "authority_status": authority_status,
            "activation_event": activation_event,
            "strategy_eligible": strategy_eligible,
            "as_of": as_of,
            "quality_status": "accepted",
            "last_event_id": last_event.event_id,
            "test_count": test_count,
            "source_refs": (
                _ref("state-fixture", as_of),
                {
                    "source": "key_level_event",
                    "reference": last_event.event_id,
                    "retrieved_at": as_of,
                },
            ),
        }
    )


@pytest.mark.parametrize(
    ("source_role", "factors", "reason"),
    [
        ("jin10_supplemental", ("level_proposal",), "PROPOSAL_ONLY_SOURCE"),
        ("llm_extracted", ("level_proposal",), "LLM_LEVEL_CANDIDATE_ONLY"),
        ("cme_large_oi", ("open_interest",), "SINGLE_OI_OBSERVATION"),
    ],
)
def test_unconfirmed_sources_can_only_bootstrap_candidate(
    source_role: str,
    factors: tuple[str, ...],
    reason: str,
) -> None:
    spec = _spec()
    event = _event(
        "discover",
        spec=spec,
        source_role=source_role,
        factors=factors,
        as_of=AS_OF,
    )

    result = evaluate_key_level_lifecycle(None, event)

    assert result.state is not None
    assert result.state.lifecycle is KeyLevelLifecycle.CANDIDATE
    assert result.state.authority_status.value == "candidate_only"
    assert result.state.strategy_eligible is False
    assert result.decision.reasons == (reason,)


@pytest.mark.parametrize(
    ("quality", "freshness"),
    [("blocked", "fresh"), ("accepted", "missing")],
)
def test_blocked_or_missing_discovery_does_not_create_state(
    quality: str,
    freshness: str,
) -> None:
    spec = _spec()
    event = _event(
        "discover",
        spec=spec,
        source_role="jin10_supplemental",
        factors=("level_proposal",),
        as_of=AS_OF,
        quality=quality,
        freshness=freshness,
    )

    result = evaluate_key_level_lifecycle(None, event)

    assert result.state is None
    assert result.decision.advance is False
    assert result.decision.reasons == ("INITIAL_LEVEL_EVIDENCE_BLOCKED",)


def test_non_discover_cannot_bootstrap_state() -> None:
    spec = _spec()
    event = _event(
        "confirm",
        spec=spec,
        source_role="cme_options_model",
        factors=("gex_wall", "oi_change"),
        as_of=AS_OF,
    )
    result = evaluate_key_level_lifecycle(None, event)
    assert result.state is None
    assert result.decision.reasons == ("INITIAL_EVENT_MUST_DISCOVER",)


@pytest.mark.parametrize(
    ("source_role", "factors", "reason"),
    [
        ("jin10_supplemental", ("level_proposal",), "PROPOSAL_SOURCE_CANNOT_CONFIRM"),
        ("llm_extracted", ("level_proposal",), "PROPOSAL_SOURCE_CANNOT_CONFIRM"),
        ("cme_large_oi", ("open_interest",), "SINGLE_OI_CANNOT_CONFIRM"),
        ("validation_fallback", ("price_structure",), "VALIDATION_SOURCE_CANNOT_CONFIRM"),
        ("cme_options_model", ("gex_wall",), "CONFIRMATION_FACTORS_INSUFFICIENT"),
    ],
)
def test_candidate_confirmation_fails_closed(
    source_role: str,
    factors: tuple[str, ...],
    reason: str,
) -> None:
    previous = _direct_state("candidate")
    event = _event(
        "confirm",
        spec=previous.spec,
        source_role=source_role,
        factors=factors,
        as_of=AS_OF + timedelta(days=1),
        alignment="aligned",
    )
    result = evaluate_key_level_lifecycle(previous, event)
    assert result.state == previous
    assert result.decision.reasons == (reason,)
    assert result.decision.advance is False


@pytest.mark.parametrize(
    ("source_role", "factors"),
    [
        ("cme_options_model", ("gex_wall", "oi_change")),
        ("official_market", ("price_structure", "repeated_reaction")),
    ],
)
def test_candidate_can_be_formally_confirmed_by_frozen_rules(
    source_role: str,
    factors: tuple[str, ...],
) -> None:
    previous = _direct_state("candidate")
    event = _event(
        "confirm",
        spec=previous.spec,
        source_role=source_role,
        factors=factors,
        as_of=AS_OF + timedelta(days=1),
    )
    result = evaluate_key_level_lifecycle(previous, event)
    assert result.state is not None
    assert result.state.lifecycle.value == "confirmed"
    assert result.state.authority_status.value == "formally_confirmed"
    assert result.state.activation_event is None
    assert result.state.strategy_eligible is False
    assert result.decision.triggered_rule.value.startswith("confirm_")


@pytest.mark.parametrize(
    ("publication_status", "calculation_method"),
    [("PRELIM", "black76"), ("FINAL", "proxy")],
)
def test_prelim_or_proxy_cme_model_cannot_formally_confirm(
    publication_status: str,
    calculation_method: str,
) -> None:
    previous = _direct_state("candidate")
    event = _event(
        "confirm",
        spec=previous.spec,
        source_role="cme_options_model",
        factors=("gex_wall", "oi_change"),
        as_of=AS_OF + timedelta(days=1),
        publication_status=publication_status,
        calculation_method=calculation_method,
    )
    result = evaluate_key_level_lifecycle(previous, event)
    assert result.state == previous
    assert result.decision.reasons == ("CONFIRMATION_FACTORS_INSUFFICIENT",)


def test_cme_confirmation_always_requires_ordered_previous_snapshot() -> None:
    previous = _direct_state("candidate")
    event = _event(
        "confirm",
        spec=previous.spec,
        source_role="cme_options_model",
        factors=("gex_wall", "volume"),
        as_of=AS_OF + timedelta(days=1),
    )
    result = evaluate_key_level_lifecycle(previous, event)
    assert result.state == previous
    assert result.decision.reasons == ("CONFIRMATION_FACTORS_INSUFFICIENT",)


def test_official_repeated_reaction_must_be_near_the_subject_level() -> None:
    previous = _direct_state("candidate")
    far = _evidence(
        "official_market",
        ("price_structure", "repeated_reaction"),
        as_of=AS_OF + timedelta(days=1),
        subject_level_id=previous.spec.level_id,
    )
    far["price_fact"] = {
        **far["price_fact"],
        "open": "5000",
        "high": "5010",
        "low": "4990",
        "close": "5000",
        "window_closes": ("5000", "5000"),
    }
    event = build_key_level_event({"event_type": "confirm", "spec": previous.spec, "evidence": far})
    result = evaluate_key_level_lifecycle(previous, event)
    assert result.state == previous
    assert result.decision.reasons == ("CONFIRMATION_FACTORS_INSUFFICIENT",)


def test_confirmed_level_requires_canonical_xauusd_activation() -> None:
    previous = _direct_state("confirmed")
    untrusted = _event(
        "activate",
        spec=previous.spec,
        source_role="cme_options_model",
        factors=("gex_wall", "oi_change"),
        as_of=AS_OF + timedelta(days=1),
    )
    rejected = evaluate_key_level_lifecycle(previous, untrusted)
    assert rejected.state == previous
    assert rejected.decision.reasons == ("ACTIVATION_REQUIRES_CANONICAL_XAUUSD",)

    canonical = _event(
        "activate",
        spec=previous.spec,
        source_role="official_market",
        factors=("official_close", "price_structure"),
        as_of=AS_OF + timedelta(days=2),
    )
    activated = evaluate_key_level_lifecycle(previous, canonical)
    assert activated.state is not None
    assert activated.state.lifecycle.value == "active"
    assert activated.state.authority_status.value == "canonical_xauusd_validated"
    assert activated.state.activation_event == canonical
    assert activated.state.strategy_eligible is True


def test_activation_window_and_role_gate_are_enforced() -> None:
    spec = _spec(effective_from=AS_OF + timedelta(days=5))
    previous = _direct_state("confirmed", spec=spec)
    early = _event(
        "activate",
        spec=spec,
        source_role="official_market",
        factors=("official_close", "price_structure"),
        as_of=AS_OF + timedelta(days=1),
    )
    assert evaluate_key_level_lifecycle(previous, early).decision.reasons == ("ACTIVATION_WINDOW_PENDING",)

    magnet_previous = _direct_state("confirmed", spec=_spec(role="magnet_pin"))
    activation = _event(
        "activate",
        spec=magnet_previous.spec,
        source_role="official_market",
        factors=("official_close", "price_structure"),
        as_of=AS_OF + timedelta(days=1),
    )
    result = evaluate_key_level_lifecycle(magnet_previous, activation)
    assert result.state is not None
    assert result.state.lifecycle.value == "active"
    assert result.state.strategy_eligible is False


def test_approach_touch_hold_sequence_controls_strategy_eligibility() -> None:
    active = _direct_state("active")
    approach = _event(
        "approach",
        spec=active.spec,
        source_role="official_market",
        factors=("price_touch",),
        as_of=AS_OF + timedelta(hours=1),
    )
    approached = evaluate_key_level_lifecycle(active, approach)
    assert approached.state == active
    assert approached.decision.reasons == ("LEVEL_APPROACH_ONLY",)

    touch = _event(
        "touch",
        spec=active.spec,
        source_role="official_market",
        factors=("price_touch",),
        as_of=AS_OF + timedelta(hours=2),
    )
    tested = evaluate_key_level_lifecycle(active, touch)
    assert tested.state is not None
    assert tested.state.lifecycle.value == "tested"
    assert tested.state.test_count == 1
    assert tested.state.strategy_eligible is False

    hold = _event(
        "hold_confirmed",
        spec=active.spec,
        source_role="official_market",
        factors=("official_close", "hold_window"),
        as_of=AS_OF + timedelta(hours=3),
    )
    holding = evaluate_key_level_lifecycle(tested.state, hold)
    assert holding.state is not None
    assert holding.state.lifecycle.value == "holding"
    assert holding.state.strategy_eligible is True
    assert holding.state.activation_event == active.activation_event


def test_break_reclaim_and_reclaim_hold_require_canonical_windows() -> None:
    holding = _direct_state("holding")
    weak_break = _event(
        "break_confirmed",
        spec=holding.spec,
        source_role="official_market",
        factors=("price_touch",),
        as_of=AS_OF + timedelta(hours=1),
    )
    pending = evaluate_key_level_lifecycle(holding, weak_break)
    assert pending.state == holding
    assert pending.decision.reasons == ("BREAK_CONFIRMATION_PENDING",)

    hard_break = _event(
        "break_confirmed",
        spec=holding.spec,
        source_role="official_market",
        factors=("official_close", "break_window"),
        as_of=AS_OF + timedelta(hours=2),
    )
    broken = evaluate_key_level_lifecycle(holding, hard_break)
    assert broken.state is not None
    assert broken.state.lifecycle.value == "broken"
    assert broken.state.strategy_eligible is False

    reclaim = _event(
        "reclaim_confirmed",
        spec=holding.spec,
        source_role="official_market",
        factors=("official_close", "reclaim_window"),
        as_of=AS_OF + timedelta(hours=3),
    )
    reclaimed = evaluate_key_level_lifecycle(broken.state, reclaim)
    assert reclaimed.state is not None
    assert reclaimed.state.lifecycle.value == "reclaimed"
    assert reclaimed.state.strategy_eligible is False

    reclaim_hold = _event(
        "reclaim_hold_confirmed",
        spec=holding.spec,
        source_role="official_market",
        factors=("official_close", "hold_window"),
        as_of=AS_OF + timedelta(hours=4),
    )
    restored = evaluate_key_level_lifecycle(reclaimed.state, reclaim_hold)
    assert restored.state is not None
    assert restored.state.lifecycle.value == "holding"
    assert restored.state.strategy_eligible is True


def test_price_events_are_derived_from_structured_window_not_factor_labels() -> None:
    active = _direct_state("active")
    missed_touch = _evidence(
        "official_market",
        ("price_touch",),
        as_of=AS_OF + timedelta(hours=1),
        subject_level_id=active.spec.level_id,
    )
    missed_touch["price_fact"] = {
        **missed_touch["price_fact"],
        "open": "4600",
        "high": "4610",
        "low": "4590",
        "close": "4600",
        "window_closes": ("4600",),
    }
    touch_event = build_key_level_event({"event_type": "touch", "spec": active.spec, "evidence": missed_touch})
    assert evaluate_key_level_lifecycle(active, touch_event).state == active

    incomplete_break = _evidence(
        "official_market",
        ("official_close", "break_window"),
        as_of=AS_OF + timedelta(hours=2),
        subject_level_id=active.spec.level_id,
    )
    incomplete_break["price_fact"] = {
        **incomplete_break["price_fact"],
        "window_closes": ("4490",),
    }
    break_event = build_key_level_event(
        {"event_type": "break_confirmed", "spec": active.spec, "evidence": incomplete_break}
    )
    assert evaluate_key_level_lifecycle(active, break_event).state == active


def test_trigger_comparator_controls_which_side_is_a_break() -> None:
    trigger_below = _spec(role="trigger", comparator="below_or_equal")
    active = _direct_state("active", spec=trigger_below)
    below_closes = _event(
        "break_confirmed",
        spec=trigger_below,
        source_role="official_market",
        factors=("official_close", "break_window"),
        as_of=AS_OF + timedelta(hours=1),
    )
    result = evaluate_key_level_lifecycle(active, below_closes)
    assert result.state == active
    assert result.decision.reasons == ("BREAK_CONFIRMATION_PENDING",)


def test_wrong_lifecycle_edges_are_rejected_without_state_change() -> None:
    candidate = _direct_state("candidate")
    activate = _event(
        "activate",
        spec=candidate.spec,
        source_role="official_market",
        factors=("official_close", "price_structure"),
        as_of=AS_OF + timedelta(hours=1),
    )
    assert evaluate_key_level_lifecycle(candidate, activate).decision.reasons == ("ACTIVATION_REQUIRES_CONFIRMED",)

    active = _direct_state("active")
    hold = _event(
        "hold_confirmed",
        spec=active.spec,
        source_role="official_market",
        factors=("official_close", "hold_window"),
        as_of=AS_OF + timedelta(hours=1),
    )
    assert evaluate_key_level_lifecycle(active, hold).decision.reasons == ("HOLD_REQUIRES_TESTED_LEVEL",)

    broken = _direct_state("broken")
    touch = _event(
        "touch",
        spec=broken.spec,
        source_role="official_market",
        factors=("price_touch",),
        as_of=AS_OF + timedelta(hours=1),
    )
    assert evaluate_key_level_lifecycle(broken, touch).decision.reasons == ("TOUCH_REQUIRES_ACTIVE_LEVEL",)


def test_explicit_retirement_is_authorized_and_retired_is_terminal() -> None:
    spec = _spec(expires_at=AS_OF + timedelta(days=1))
    active = _direct_state("active", spec=spec)
    unauthorized = _event(
        "retire",
        spec=spec,
        source_role="manual_observation",
        factors=("validity_expired",),
        as_of=AS_OF + timedelta(days=1),
        retirement_rule="validity_expired",
    )
    assert evaluate_key_level_lifecycle(active, unauthorized).state == active

    retire = _event(
        "retire",
        spec=spec,
        source_role="system_scheduler",
        factors=("validity_expired",),
        as_of=AS_OF + timedelta(days=1),
        retirement_rule="validity_expired",
    )
    retired = evaluate_key_level_lifecycle(active, retire)
    assert retired.state is not None
    assert retired.state.lifecycle.value == "retired"
    assert retired.state.strategy_eligible is False
    assert retired.state.activation_event == active.activation_event

    later = _event(
        "activate",
        spec=spec,
        source_role="official_market",
        factors=("official_close", "price_structure"),
        as_of=AS_OF + timedelta(days=2),
    )
    terminal = evaluate_key_level_lifecycle(retired.state, later)
    assert terminal.state == retired.state
    assert terminal.decision.reasons == ("RETIRED_LEVEL_IMMUTABLE",)


def test_expiry_uses_system_cutoff_and_current_time_eligibility() -> None:
    spec = _spec(expires_at=AS_OF + timedelta(days=1))
    active = _direct_state("active", spec=spec)
    stale = _event(
        "touch",
        spec=spec,
        source_role="jin10_supplemental",
        factors=("level_proposal",),
        as_of=AS_OF + timedelta(days=1),
        freshness="stale",
    )
    result = evaluate_key_level_lifecycle(active, stale)
    assert result.state == active
    assert result.decision.reasons == ("LEVEL_EVIDENCE_NOT_READY",)
    assert (
        key_level_strategy_eligible_at(
            active,
            decision_as_of=AS_OF - timedelta(seconds=1),
            current_quality_status="accepted",
        )
        is False
    )
    assert (
        key_level_strategy_eligible_at(
            active,
            decision_as_of=AS_OF,
            current_quality_status="observe",
        )
        is False
    )
    assert (
        key_level_strategy_eligible_at(
            active,
            decision_as_of=AS_OF + timedelta(days=1),
            current_quality_status="accepted",
        )
        is False
    )

    expiry = _event(
        "retire",
        spec=spec,
        source_role="system_scheduler",
        factors=("validity_expired",),
        as_of=AS_OF + timedelta(days=1),
        retirement_rule="validity_expired",
    )
    retired = evaluate_key_level_lifecycle(active, expiry)
    assert retired.state is not None
    assert retired.state.lifecycle.value == "retired"
    assert retired.decision.reasons == ("LEVEL_RETIRED:validity_expired",)


def test_contract_expiry_must_match_cme_origin_contract() -> None:
    spec = _spec(
        expires_at=AS_OF + timedelta(days=1),
        origin_source_role="cme_options_model",
        origin_instrument="GC_FUTURES",
        origin_contract_id="GC:2026-08",
    )
    active = _direct_state("active", spec=spec)
    mismatch = _event(
        "retire",
        spec=spec,
        source_role="system_scheduler",
        factors=("contract_expiry",),
        as_of=AS_OF + timedelta(days=1),
        retirement_rule="contract_expired",
        contract_id="GC:2026-09",
    )
    assert evaluate_key_level_lifecycle(active, mismatch).state == active

    matched = _event(
        "retire",
        spec=spec,
        source_role="system_scheduler",
        factors=("contract_expiry",),
        as_of=AS_OF + timedelta(days=1),
        retirement_rule="contract_expired",
        contract_id="GC:2026-08",
    )
    result = evaluate_key_level_lifecycle(active, matched)
    assert result.state is not None
    assert result.state.lifecycle.value == "retired"


def test_failure_window_cannot_retire_immediately() -> None:
    broken = _direct_state("broken")
    early = _event(
        "retire",
        spec=broken.spec,
        source_role="system_scheduler",
        factors=("failure_window_elapsed",),
        as_of=AS_OF + timedelta(seconds=1),
        retirement_rule="failure_window_elapsed",
    )
    assert evaluate_key_level_lifecycle(broken, early).state == broken

    mature = _event(
        "retire",
        spec=broken.spec,
        source_role="system_scheduler",
        factors=("failure_window_elapsed",),
        as_of=AS_OF + timedelta(days=1),
        retirement_rule="failure_window_elapsed",
    )
    result = evaluate_key_level_lifecycle(broken, mature)
    assert result.state is not None
    assert result.state.lifecycle.value == "retired"


@pytest.mark.parametrize(
    "evidence_overrides",
    [
        {"quality": "blocked"},
        {"freshness": "stale"},
        {"alignment": "misaligned"},
    ],
)
def test_unready_evidence_cannot_advance_live_lifecycle(
    evidence_overrides: dict[str, object],
) -> None:
    active = _direct_state("active")
    event = _event(
        "touch",
        spec=active.spec,
        source_role="official_market",
        factors=("price_touch",),
        as_of=AS_OF + timedelta(hours=1),
        **evidence_overrides,
    )
    result = evaluate_key_level_lifecycle(active, event)
    assert result.state == active
    assert result.decision.reasons == ("LEVEL_EVIDENCE_NOT_READY",)


def test_duplicate_same_time_and_level_identity_guards_are_fail_closed() -> None:
    active = _direct_state("active")
    duplicate = evaluate_key_level_lifecycle(
        active,
        build_key_level_event(
            {
                "event_type": "activate",
                "spec": active.spec,
                "evidence": _evidence(
                    "official_market",
                    ("official_close", "price_structure"),
                    as_of=AS_OF,
                ),
            }
        ),
    )
    assert duplicate.state == active
    assert duplicate.decision.reasons == ("DUPLICATE_LEVEL_EVENT",)

    same_time = _event(
        "touch",
        spec=active.spec,
        source_role="official_market",
        factors=("price_touch",),
        as_of=AS_OF,
    )
    conflict = evaluate_key_level_lifecycle(active, same_time)
    assert conflict.state == active
    assert conflict.decision.reasons == ("CONFLICTING_SAME_TIME_EVENT",)

    other_spec = _spec(origin_key="different-origin")
    mismatch = _event(
        "touch",
        spec=other_spec,
        source_role="official_market",
        factors=("price_touch",),
        as_of=AS_OF + timedelta(hours=1),
    )
    rejected = evaluate_key_level_lifecycle(active, mismatch)
    assert rejected.state == active
    assert rejected.decision.reasons == ("LEVEL_IDENTITY_MISMATCH",)


def test_historical_event_replay_is_rejected_without_worker_exception() -> None:
    spec = _spec()
    discover = _event(
        "discover",
        spec=spec,
        source_role="jin10_supplemental",
        factors=("level_proposal",),
        as_of=AS_OF,
    )
    candidate = evaluate_key_level_lifecycle(None, discover).state
    assert candidate is not None
    confirm = _event(
        "confirm",
        spec=spec,
        source_role="cme_options_model",
        factors=("gex_wall", "oi_change"),
        as_of=AS_OF + timedelta(days=1),
    )
    confirmed = evaluate_key_level_lifecycle(candidate, confirm).state
    assert confirmed is not None

    replayed = evaluate_key_level_lifecycle(confirmed, discover)
    assert replayed.state == confirmed
    assert replayed.decision.reasons == ("STALE_OR_REPLAYED_LEVEL_EVENT",)


def test_no_op_is_idempotent_and_does_not_create_initial_state() -> None:
    spec = _spec()
    event = _event(
        "no_op",
        spec=spec,
        source_role="manual_observation",
        factors=("level_proposal",),
        as_of=AS_OF,
    )
    initial = evaluate_key_level_lifecycle(None, event)
    assert initial.state is None
    assert initial.decision.reasons == ("INITIAL_NO_OP_HAS_NO_LEVEL",)

    active = _direct_state("active")
    later = _event(
        "no_op",
        spec=active.spec,
        source_role="manual_observation",
        factors=("level_proposal",),
        as_of=AS_OF + timedelta(hours=1),
    )
    maintained = evaluate_key_level_lifecycle(active, later)
    assert maintained.state == active
    assert maintained.decision.transition_allowed is True
    assert maintained.decision.advance is False


def test_policy_is_100_run_deterministic_and_does_not_mutate_inputs() -> None:
    previous = _direct_state("candidate")
    event = _event(
        "confirm",
        spec=previous.spec,
        source_role="cme_options_model",
        factors=("gex_wall", "oi_change"),
        as_of=AS_OF + timedelta(days=1),
    )
    previous_payload = deepcopy(previous.model_dump(mode="python"))
    event_payload = deepcopy(event.model_dump(mode="python"))
    results = [evaluate_key_level_lifecycle(previous, event) for _ in range(100)]
    assert all(result == results[0] for result in results)
    assert previous.model_dump(mode="python") == previous_payload
    assert event.model_dump(mode="python") == event_payload


def test_five_golden_lifecycle_sequences() -> None:
    cases = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert len(cases) == 5
    for case in cases:
        spec = _spec(origin_key=f"golden:{case['case_id']}")
        state = _direct_state(case["start_lifecycle"], spec=spec) if case.get("start_lifecycle") else None
        for index, item in enumerate(case["events"], start=1):
            event = _event(
                item["type"],
                spec=spec,
                source_role=item["source_role"],
                factors=tuple(item["factors"]),
                as_of=AS_OF + timedelta(days=item.get("day_offset", 0), hours=index),
                retirement_rule=item.get("retirement_rule"),
            )
            state = evaluate_key_level_lifecycle(state, event).state
        assert state is not None, case["case_id"]
        assert state.lifecycle.value == case["expected_lifecycle"], case["case_id"]
        assert state.strategy_eligible is case["strategy_eligible"], case["case_id"]
