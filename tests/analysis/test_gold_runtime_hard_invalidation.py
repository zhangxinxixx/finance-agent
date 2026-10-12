from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from pathlib import Path

import pytest

from apps.analysis.gold_policy.attribution_policy import attribute_gold_price
from apps.analysis.gold_policy.daily_close_loop import evaluate_gold_daily_close_loop
from apps.analysis.gold_policy.daily_close_runtime import execute_gold_daily_close_runtime
from apps.analysis.gold_policy.daily_close_schemas import DailyCloseLoopInput
from apps.analysis.gold_policy.daily_close_store import (
    load_gold_daily_close_head,
    persist_gold_daily_close_run,
    verify_gold_daily_close_bundle,
)
from apps.analysis.gold_policy.feature_snapshot import build_feature_snapshot
from apps.analysis.gold_policy.key_level_controls import KeyLevelControlsInput
from apps.analysis.gold_policy.key_level_schemas import build_key_level_event
from apps.analysis.gold_policy.runtime_controls import build_gold_daily_close_runtime_controls
from apps.analysis.gold_policy.state_schemas import (
    StateTransitionPolicyDecisionV2,
    TransitionEvidence,
    build_state_transition_policy_decision,
    build_state_transition_policy_decision_v2,
)
from tests.analysis.test_gold_daily_close_loop import _evidence, _ordinary_result, _v2_snapshot
from tests.analysis.test_gold_daily_close_store import _bootstrap_pair
from tests.analysis.test_gold_key_level_policy import _direct_state, _event, _spec
from tests.analysis.test_gold_strategy_policy import _policy_input, _snapshot


def _predecessor_case(version: str = "v1"):
    if version == "v1":
        result, previous, _ = _ordinary_result()
        current = _snapshot("feature_snapshot_v1_event_flat_2025-01-29.json")
        return result, previous, current

    prior = _v2_snapshot(_snapshot("feature_snapshot_v1_bearish_2025-01-21.json"))
    previous = _v2_snapshot(_snapshot("feature_snapshot_v1_mixed_2025-01-24.json"))
    support = _policy_input(
        feature=previous,
        attribution=attribute_gold_price(previous, prior),
    )
    loop_input = DailyCloseLoopInput(
        decision_as_of=support.decision_as_of,
        current_feature=previous,
        previous_feature=prior,
        transition_evidence=_evidence(support.decision_as_of),
        options_regime=support.options_regime,
        event_risk=support.event_risk,
    )
    result = evaluate_gold_daily_close_loop(loop_input)
    current = _v2_snapshot(_snapshot("feature_snapshot_v1_event_flat_2025-01-29.json"))
    return result, previous, current


def _same_session_case(version: str):
    predecessor, previous, _ = _predecessor_case(version)
    feature_as_of = predecessor.transition_decision.evidence.as_of
    assert previous.as_of < feature_as_of
    payload = previous.model_dump(
        mode="json",
        exclude={
            "data_quality",
            "payload_hash",
            "snapshot_id",
            "real10y_estimated",
            "real10y_basis_bp",
            "real10y_alignment",
            "real10y_reason_codes",
            "real10y_quality",
        },
    )
    payload["as_of"] = feature_as_of.isoformat()
    payload["xauusd_spot"]["as_of"] = feature_as_of.isoformat()
    payload["xauusd_spot"]["value"] += 10
    current = build_feature_snapshot(payload)
    support = _policy_input(
        feature=current,
        attribution=attribute_gold_price(current, previous),
    )
    assert previous.as_of < current.as_of < support.decision_as_of
    return predecessor, previous, current, support


def _transition_with_evidence_as_of(transition, as_of):
    evidence_payload = transition.evidence.model_dump(mode="python")
    evidence_payload.update(
        evidence_id=f"{transition.evidence.evidence_id}:revised:{as_of.isoformat()}",
        as_of=as_of,
    )
    evidence = TransitionEvidence.model_validate(evidence_payload)
    payload = transition.model_dump(mode="python", exclude={"decision_hash"})
    payload["evidence"] = evidence
    if isinstance(transition, StateTransitionPolicyDecisionV2):
        return build_state_transition_policy_decision_v2(payload)
    return build_state_transition_policy_decision(payload)


def _break_input(
    as_of,
    *,
    role: str = "support",
    reference_price: str | None = None,
    event_as_of=None,
    freshness: str = "fresh",
    source_role: str = "official_market",
    expires_at=None,
    single_close: bool = False,
    incomplete_window: bool = False,
):
    price = reference_price or ("4500" if role != "resistance" else "4480")
    spec = _spec(
        role=role,
        reference_price=price,
        effective_from=as_of - timedelta(days=30),
        expires_at=expires_at or as_of + timedelta(days=30),
        origin_key=f"hard-invalidation:{role}:{price}",
    )
    holding = _direct_state("holding", spec=spec, as_of=as_of - timedelta(days=1))
    factors = ("official_close", "break_window") if source_role == "official_market" else ("gex_wall", "oi_change")
    event = _event(
        "break_confirmed",
        spec=spec,
        source_role=source_role,
        factors=factors,
        as_of=event_as_of or as_of,
        freshness=freshness,
        alignment="aligned",
    )
    if single_close or incomplete_window:
        payload = event.model_dump(mode="json", exclude={"event_hash", "event_id"})
        if single_close:
            payload["evidence"]["price_fact"]["window_closes"] = [
                payload["evidence"]["price_fact"]["window_closes"][-1]
            ]
        if incomplete_window:
            payload["evidence"]["price_fact"]["window_complete"] = False
        event = build_key_level_event(payload)
    return holding, event


def _build_case(
    *,
    version: str = "v1",
    lifecycle_input: KeyLevelControlsInput | None = None,
    previous_feature_marker: object = ...,
    previous_transition_marker: object = ...,
    current_override=None,
):
    previous_result, previous, current = _predecessor_case(version)
    current = current_override or current
    support = _policy_input(
        feature=current,
        attribution=attribute_gold_price(current, previous),
    )
    if lifecycle_input is None:
        holding, event = _break_input(support.decision_as_of)
        lifecycle_input = KeyLevelControlsInput(
            decision_as_of=support.decision_as_of,
            scope="daily_close",
            previous_states=(holding,),
            ordered_events=(event,),
        )
    previous_feature = previous if previous_feature_marker is ... else previous_feature_marker
    previous_transition = (
        previous_result.transition_decision if previous_transition_marker is ... else previous_transition_marker
    )
    controls = build_gold_daily_close_runtime_controls(
        current_feature=current,
        previous_feature=previous_feature,
        previous_transition=previous_transition,
        decision_as_of=support.decision_as_of,
        options_regime_snapshot=support.options_regime,
        key_level_controls_input=lifecycle_input,
    )
    return controls, previous_result, previous, current, support, lifecycle_input


@pytest.mark.parametrize(
    ("version", "role", "expected_rule"),
    [
        ("v1", "support", "CONFIRMED_SUPPORT_BREAK"),
        ("v1", "resistance", "CONFIRMED_RESISTANCE_BREAK"),
        ("v2", "support", "CONFIRMED_SUPPORT_BREAK"),
        ("v2", "resistance", "CONFIRMED_RESISTANCE_BREAK"),
    ],
)
def test_formal_recomputed_break_promotes_and_invalidates_loop(
    version: str,
    role: str,
    expected_rule: str,
) -> None:
    predecessor, previous, current = _predecessor_case(version)
    support = _policy_input(feature=current, attribution=attribute_gold_price(current, previous))
    holding, event = _break_input(support.decision_as_of, role=role)
    lifecycle = KeyLevelControlsInput(
        decision_as_of=support.decision_as_of,
        scope="daily_close",
        previous_states=(holding,),
        ordered_events=(event,),
    )
    original = deepcopy(lifecycle.model_dump(mode="json"))

    controls = build_gold_daily_close_runtime_controls(
        current_feature=current,
        previous_feature=previous,
        previous_transition=predecessor.transition_decision,
        decision_as_of=support.decision_as_of,
        options_regime_snapshot=support.options_regime,
        key_level_controls_input=lifecycle,
    )
    repeated = build_gold_daily_close_runtime_controls(
        current_feature=current,
        previous_feature=previous,
        previous_transition=predecessor.transition_decision,
        decision_as_of=support.decision_as_of,
        options_regime_snapshot=support.options_regime,
        key_level_controls_input=lifecycle,
    )

    assert controls == repeated
    assert lifecycle.model_dump(mode="json") == original
    assert controls.transition_evidence.delta_kind.value == "hard_invalidation"
    assert controls.transition_evidence.rule_code.value == expected_rule
    assert controls.transition_evidence.predecessor_evidence_id == (
        predecessor.transition_decision.evidence.evidence_id
    )
    references = {(ref.source, ref.reference) for ref in controls.transition_evidence.source_refs}
    assert ("input_snapshot", current.snapshot_id) in references
    assert ("input_snapshot", previous.snapshot_id) in references
    assert ("state_transition_decision", predecessor.transition_decision.decision_hash) in references
    assert ("transition_evidence", predecessor.transition_decision.evidence.evidence_id) in references
    assert ("analysis_state", predecessor.transition_decision.to_state_id) in references
    assert any(source == "key_level_activation_event" for source, _ in references)
    assert any(source == "key_level_decision" for source, _ in references)
    assert any(source == "key_level_state" for source, _ in references)
    assert any(source == "qualification_receipt" for source, _ in references)

    loop_input = DailyCloseLoopInput(
        decision_as_of=support.decision_as_of,
        current_feature=current,
        previous_feature=previous,
        previous_policy_input=predecessor.strategy_policy_input,
        previous_state=predecessor.analysis_state,
        previous_transition=predecessor.transition_decision,
        previous_strategy=predecessor.candidate_strategy,
        transition_evidence=controls.transition_evidence,
        options_regime=controls.options_regime,
        event_risk=controls.event_risk,
        key_levels=controls.key_levels,
        key_level_decisions=controls.key_level_decisions,
        key_level_proof=controls.key_level_proof,
    )
    result = evaluate_gold_daily_close_loop(loop_input)
    assert result.transition_decision.action.value == "invalidate"
    assert result.candidate_strategy.status.value == "INVALIDATED"


@pytest.mark.parametrize("missing", ["feature", "transition", "target_state"])
def test_missing_predecessor_never_promotes(missing: str) -> None:
    predecessor, previous, current = _predecessor_case()
    support = _policy_input(feature=current, attribution=attribute_gold_price(current, previous))
    holding, event = _break_input(support.decision_as_of)
    lifecycle = KeyLevelControlsInput(
        decision_as_of=support.decision_as_of,
        scope="daily_close",
        previous_states=(holding,),
        ordered_events=(event,),
    )
    previous_feature = None if missing == "feature" else previous
    transition = None if missing == "transition" else predecessor.transition_decision
    if missing == "target_state":
        transition = transition.model_copy(update={"to_state_id": None})

    controls = build_gold_daily_close_runtime_controls(
        current_feature=current,
        previous_feature=previous_feature,
        previous_transition=transition,
        decision_as_of=support.decision_as_of,
        options_regime_snapshot=support.options_regime,
        key_level_controls_input=lifecycle,
    )

    assert controls.transition_evidence.delta_kind.value != "hard_invalidation"
    assert "HARD_INVALIDATION_PREDECESSOR_MISSING" in controls.reason_codes


@pytest.mark.parametrize(
    "case",
    [
        "stale",
        "single_close",
        "incomplete_window",
        "expired",
        "old_broken",
        "replayed",
        "gc",
        "llm",
        "non_support_resistance",
        "wrong_decision_time",
    ],
)
def test_nonqualifying_lifecycle_inputs_preserve_default_evidence(case: str) -> None:
    predecessor, previous, current = _predecessor_case()
    support = _policy_input(feature=current, attribution=attribute_gold_price(current, previous))
    as_of = support.decision_as_of
    if case == "old_broken":
        spec = _spec(
            role="support",
            effective_from=as_of - timedelta(days=30),
            expires_at=as_of + timedelta(days=30),
            origin_key="hard-invalidation:old-broken",
        )
        lifecycle = KeyLevelControlsInput(
            decision_as_of=as_of,
            scope="daily_close",
            previous_states=(_direct_state("broken", spec=spec, as_of=as_of - timedelta(days=1)),),
        )
    else:
        holding, event = _break_input(
            as_of,
            role="trigger" if case == "non_support_resistance" else "support",
            freshness="stale" if case == "stale" else "fresh",
            source_role=(
                "cme_options_model" if case == "gc" else "llm_extracted" if case == "llm" else "official_market"
            ),
            expires_at=as_of if case == "expired" else None,
            event_as_of=(
                as_of - timedelta(days=2)
                if case == "replayed"
                else as_of - timedelta(minutes=1)
                if case == "wrong_decision_time"
                else None
            ),
            single_close=case == "single_close",
            incomplete_window=case == "incomplete_window",
        )
        lifecycle = KeyLevelControlsInput(
            decision_as_of=as_of,
            scope="daily_close",
            previous_states=(holding,),
            ordered_events=(event,),
        )

    controls = build_gold_daily_close_runtime_controls(
        current_feature=current,
        previous_feature=previous,
        previous_transition=predecessor.transition_decision,
        decision_as_of=as_of,
        options_regime_snapshot=support.options_regime,
        key_level_controls_input=lifecycle,
    )

    assert controls.transition_evidence.delta_kind.value != "hard_invalidation"
    assert (
        controls.transition_evidence.rule_code is None
        or not controls.transition_evidence.rule_code.value.startswith("CONFIRMED_")
    )


def test_conflicting_break_rules_are_explicitly_ambiguous() -> None:
    predecessor, previous, current = _predecessor_case()
    support = _policy_input(feature=current, attribution=attribute_gold_price(current, previous))
    pairs = (
        _break_input(support.decision_as_of, role="support"),
        _break_input(support.decision_as_of, role="resistance"),
    )
    lifecycle = KeyLevelControlsInput(
        decision_as_of=support.decision_as_of,
        scope="daily_close",
        previous_states=tuple(pair[0] for pair in pairs),
        ordered_events=tuple(sorted((pair[1] for pair in pairs), key=lambda item: item.event_id)),
    )

    controls = build_gold_daily_close_runtime_controls(
        current_feature=current,
        previous_feature=previous,
        previous_transition=predecessor.transition_decision,
        decision_as_of=support.decision_as_of,
        options_regime_snapshot=support.options_regime,
        key_level_controls_input=lifecycle,
    )

    assert controls.transition_evidence.delta_kind.value != "hard_invalidation"
    assert "HARD_INVALIDATION_BREAK_RULE_AMBIGUOUS" in controls.reason_codes


def test_wrong_scope_is_rejected_before_runtime_promotion() -> None:
    predecessor, previous, current = _predecessor_case()
    support = _policy_input(feature=current, attribution=attribute_gold_price(current, previous))
    spec = _spec(
        role="support",
        scope="intraday",
        effective_from=support.decision_as_of - timedelta(days=30),
        expires_at=support.decision_as_of + timedelta(days=30),
        origin_key="hard-invalidation:wrong-scope",
    )
    holding = _direct_state("holding", spec=spec, as_of=support.decision_as_of - timedelta(days=1))
    event = _event(
        "break_confirmed",
        spec=spec,
        source_role="official_market",
        factors=("official_close", "break_window"),
        as_of=support.decision_as_of,
    )
    lifecycle = KeyLevelControlsInput(
        decision_as_of=support.decision_as_of,
        scope="intraday",
        previous_states=(holding,),
        ordered_events=(event,),
    )

    with pytest.raises(ValueError, match="must use daily_close scope"):
        build_gold_daily_close_runtime_controls(
            current_feature=current,
            previous_feature=previous,
            previous_transition=predecessor.transition_decision,
            decision_as_of=support.decision_as_of,
            options_regime_snapshot=support.options_regime,
            key_level_controls_input=lifecycle,
        )


def test_cross_version_predecessor_does_not_promote() -> None:
    v1_predecessor, _, _ = _predecessor_case("v1")
    _, previous, current = _predecessor_case("v2")
    support = _policy_input(feature=current, attribution=attribute_gold_price(current, previous))
    holding, event = _break_input(support.decision_as_of)

    controls = build_gold_daily_close_runtime_controls(
        current_feature=current,
        previous_feature=previous,
        previous_transition=v1_predecessor.transition_decision,
        decision_as_of=support.decision_as_of,
        options_regime_snapshot=support.options_regime,
        key_level_controls_input=KeyLevelControlsInput(
            decision_as_of=support.decision_as_of,
            scope="daily_close",
            previous_states=(holding,),
            ordered_events=(event,),
        ),
    )

    assert controls.transition_evidence.delta_kind.value != "hard_invalidation"
    assert "HARD_INVALIDATION_PREDECESSOR_INCONSISTENT" in controls.reason_codes


@pytest.mark.parametrize("version", ["v1", "v2"])
@pytest.mark.parametrize(
    ("predecessor_time", "expected_hard_invalidation"),
    [
        ("at_feature", True),
        ("between_feature_and_decision", True),
        ("at_decision", False),
        ("after_decision", False),
    ],
)
def test_same_session_predecessor_uses_strict_decision_cutoff(
    version: str,
    predecessor_time: str,
    expected_hard_invalidation: bool,
) -> None:
    predecessor, previous, current, support = _same_session_case(version)
    evidence_as_of = {
        "at_feature": current.as_of,
        "between_feature_and_decision": current.as_of + timedelta(minutes=1),
        "at_decision": support.decision_as_of,
        "after_decision": support.decision_as_of + timedelta(seconds=1),
    }[predecessor_time]
    transition = _transition_with_evidence_as_of(
        predecessor.transition_decision,
        evidence_as_of,
    )
    holding, event = _break_input(support.decision_as_of)

    controls = build_gold_daily_close_runtime_controls(
        current_feature=current,
        previous_feature=previous,
        previous_transition=transition,
        decision_as_of=support.decision_as_of,
        options_regime_snapshot=support.options_regime,
        key_level_controls_input=KeyLevelControlsInput(
            decision_as_of=support.decision_as_of,
            scope="daily_close",
            previous_states=(holding,),
            ordered_events=(event,),
        ),
    )

    is_hard_invalidation = controls.transition_evidence.delta_kind.value == "hard_invalidation"
    assert is_hard_invalidation is expected_hard_invalidation
    if expected_hard_invalidation:
        assert controls.transition_evidence.predecessor_evidence_id == transition.evidence.evidence_id
        refs = {(ref.source, ref.reference) for ref in controls.transition_evidence.source_refs}
        assert ("state_transition_decision", transition.decision_hash) in refs
        assert ("transition_evidence", transition.evidence.evidence_id) in refs
    else:
        assert "HARD_INVALIDATION_PREDECESSOR_INCONSISTENT" in controls.reason_codes


def test_multiple_same_rule_proofs_aggregate_stably() -> None:
    predecessor, previous, current = _predecessor_case()
    support = _policy_input(feature=current, attribution=attribute_gold_price(current, previous))
    pairs = (
        _break_input(support.decision_as_of, role="support", reference_price="4500"),
        _break_input(support.decision_as_of, role="support", reference_price="4510"),
    )
    lifecycle = KeyLevelControlsInput(
        decision_as_of=support.decision_as_of,
        scope="daily_close",
        previous_states=tuple(reversed(tuple(pair[0] for pair in pairs))),
        ordered_events=tuple(sorted((pair[1] for pair in pairs), key=lambda item: item.event_id)),
    )
    reordered = lifecycle.model_copy(update={"previous_states": tuple(pair[0] for pair in pairs)})

    controls, *_ = _build_case(lifecycle_input=lifecycle)
    repeated, *_ = _build_case(lifecycle_input=reordered)

    assert controls == repeated
    assert controls.transition_evidence.rule_code.value == "CONFIRMED_SUPPORT_BREAK"
    decision_refs = [ref for ref in controls.transition_evidence.source_refs if ref.source == "key_level_decision"]
    assert len(decision_refs) == 2


def test_future_current_feature_reference_is_not_filtered_into_acceptance() -> None:
    predecessor, previous, current = _predecessor_case()
    support = _policy_input(feature=current, attribution=attribute_gold_price(current, previous))
    payload = current.model_dump(mode="json", exclude={"data_quality", "payload_hash", "snapshot_id"})
    payload["xauusd_spot"]["source_refs"][0]["retrieved_at"] = (
        support.decision_as_of + timedelta(seconds=1)
    ).isoformat()
    future_current = build_feature_snapshot(payload)
    future_support = _policy_input(
        feature=future_current,
        attribution=attribute_gold_price(future_current, previous),
    )
    holding, event = _break_input(future_support.decision_as_of)
    lifecycle = KeyLevelControlsInput(
        decision_as_of=future_support.decision_as_of,
        scope="daily_close",
        previous_states=(holding,),
        ordered_events=(event,),
    )

    controls = build_gold_daily_close_runtime_controls(
        current_feature=future_current,
        previous_feature=previous,
        previous_transition=predecessor.transition_decision,
        decision_as_of=future_support.decision_as_of,
        options_regime_snapshot=future_support.options_regime,
        key_level_controls_input=lifecycle,
    )

    assert controls.transition_evidence.delta_kind.value != "hard_invalidation"
    assert "HARD_INVALIDATION_BREAK_PROOF_INVALID" in controls.reason_codes


def test_future_predecessor_reference_is_not_filtered_into_acceptance() -> None:
    predecessor, previous, current = _predecessor_case()
    support = _policy_input(feature=current, attribution=attribute_gold_price(current, previous))
    payload = previous.model_dump(mode="json", exclude={"data_quality", "payload_hash", "snapshot_id"})
    payload["xauusd_spot"]["source_refs"][0]["retrieved_at"] = (
        support.decision_as_of + timedelta(seconds=1)
    ).isoformat()
    future_previous = build_feature_snapshot(payload)
    holding, event = _break_input(support.decision_as_of)

    controls = build_gold_daily_close_runtime_controls(
        current_feature=current,
        previous_feature=future_previous,
        previous_transition=predecessor.transition_decision,
        decision_as_of=support.decision_as_of,
        options_regime_snapshot=support.options_regime,
        key_level_controls_input=KeyLevelControlsInput(
            decision_as_of=support.decision_as_of,
            scope="daily_close",
            previous_states=(holding,),
            ordered_events=(event,),
        ),
    )

    assert controls.transition_evidence.delta_kind.value != "hard_invalidation"
    assert "HARD_INVALIDATION_FUTURE_OR_INVALID_SOURCE_REF" in controls.reason_codes


def test_hard_invalidation_bundle_persists_and_full_verifier_reloads(tmp_path: Path) -> None:
    bootstrap_input, bootstrap_result = _bootstrap_pair()
    persist_gold_daily_close_run(
        storage_root=tmp_path,
        run_id="hard-invalidation-bootstrap",
        loop_input=bootstrap_input,
        result=bootstrap_result,
    )
    head = load_gold_daily_close_head(storage_root=tmp_path)
    assert head.status == "found" and head.head is not None
    current = _snapshot("feature_snapshot_v1_mixed_2025-01-24.json")
    support = _policy_input(
        feature=current,
        attribution=attribute_gold_price(current, head.head.feature_snapshot),
    )
    holding, event = _break_input(support.decision_as_of)
    controls = build_gold_daily_close_runtime_controls(
        current_feature=current,
        previous_feature=head.head.feature_snapshot,
        previous_transition=head.head.transition_decision,
        decision_as_of=support.decision_as_of,
        options_regime_snapshot=support.options_regime,
        key_level_controls_input=KeyLevelControlsInput(
            decision_as_of=support.decision_as_of,
            scope="daily_close",
            previous_states=(holding,),
            ordered_events=(event,),
        ),
    )

    execution = execute_gold_daily_close_runtime(
        storage_root=tmp_path,
        run_id="hard-invalidation-current",
        current_feature=current,
        controls=controls,
    )
    verified = verify_gold_daily_close_bundle(
        storage_root=tmp_path,
        bundle_path=execution.write_result.bundle_path,
    )

    assert execution.result.transition_decision.action.value == "invalidate"
    assert execution.result.candidate_strategy.status.value == "INVALIDATED"
    assert verified.status == "valid"
    assert verified.current_feature_id == current.snapshot_id
