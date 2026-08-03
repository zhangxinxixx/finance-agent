from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

from apps.analysis.gold_policy.attribution_policy import attribute_gold_price
from apps.analysis.gold_policy.daily_close_loop import evaluate_gold_daily_close_loop
from apps.analysis.gold_policy.daily_close_schemas import DailyCloseLoopInput
from apps.analysis.gold_policy.report_context import (
    GoldReportContext,
    build_gold_report_context,
    build_gold_report_context_v1,
)
from tests.analysis.test_gold_daily_close_loop import _evidence, _v2_snapshot
from tests.analysis.test_gold_daily_close_store import (
    _bootstrap_pair,
    _bootstrap_v2_pair,
)
from tests.analysis.test_gold_strategy_policy import _policy_input, _snapshot


def _v2_pair_with_missing_confirmatory_and_options():
    previous_v1 = _snapshot("feature_snapshot_v1_bullish_2025-01-17.json")
    previous = _v2_snapshot(
        previous_v1,
        real10y_direct={"value": previous_v1.us10y.value - previous_v1.t10yie.value},
    )
    current_v1 = _snapshot("feature_snapshot_v1_bearish_2025-01-21.json")
    current = _v2_snapshot(
        current_v1,
        real10y_direct={"value": current_v1.us10y.value - current_v1.t10yie.value},
        cot={
            "value": None,
            "freshness_status": "missing",
            "quality_status": "blocked",
            "alignment_status": "unknown",
        },
        cme_options_regime={
            "value": None,
            "freshness_status": "missing",
            "quality_status": "blocked",
            "alignment_status": "unknown",
        },
    )
    support = _policy_input(
        bias="bearish",
        feature=current,
        attribution=attribute_gold_price(current, previous),
    )
    loop_input = DailyCloseLoopInput(
        decision_as_of=support.decision_as_of,
        current_feature=current,
        previous_feature=previous,
        transition_evidence=_evidence(support.decision_as_of),
        options_regime=support.options_regime,
        event_risk=support.event_risk,
    )
    return loop_input, evaluate_gold_daily_close_loop(loop_input)


def _event_blackout_pair():
    previous = _snapshot("feature_snapshot_v1_mixed_2025-01-24.json")
    current = _snapshot("feature_snapshot_v1_event_flat_2025-01-29.json")
    support = _policy_input(
        feature=current,
        event_risk="blackout",
        attribution=attribute_gold_price(current, previous),
    )
    loop_input = DailyCloseLoopInput(
        decision_as_of=support.decision_as_of,
        current_feature=current,
        previous_feature=previous,
        transition_evidence=_evidence(support.decision_as_of),
        options_regime=support.options_regime,
        event_risk=support.event_risk,
    )
    return loop_input, evaluate_gold_daily_close_loop(loop_input)


def test_v2_context_binds_complete_typed_projection() -> None:
    loop_input, result = _bootstrap_v2_pair()

    context = build_gold_report_context(loop_input, result, run_id="run-v2-complete")

    assert context.schema_version == "gold_report_context.v1.1"
    assert context.context_id.startswith("gold_report_context.v1.1:")
    assert context.asset == "XAUUSD"
    assert context.trade_date == result.decision_as_of.date()
    assert context.session == "daily_close"
    assert context.run_id == "run-v2-complete"
    assert context.snapshot_id == loop_input.current_feature.snapshot_id
    assert context.input_snapshot_ids.current_feature == loop_input.current_feature.snapshot_id
    assert context.input_snapshot_ids.previous_feature == loop_input.previous_feature.snapshot_id
    assert context.input_snapshot_ids.options == loop_input.options_regime.snapshot_id
    assert context.input_snapshot_ids.event_risk == loop_input.event_risk.snapshot_id
    assert context.transition_action == result.transition_decision.action
    assert context.transition_reasons == tuple(sorted(result.transition_decision.reasons))
    assert context.strategy_reason_codes == tuple(sorted(result.candidate_strategy.reason_codes))
    assert context.strategy_release_conditions == tuple(result.candidate_strategy.release_conditions)
    assert context.strategy_review_triggers == tuple(result.candidate_strategy.review_triggers)
    assert context.strategy_invalidation_level_ids == tuple(sorted(result.candidate_strategy.invalidation_level_ids))
    assert context.consistency_decision == result.consistency_decision
    assert context.analysis_decision == result.analysis_decision
    assert context.candidate_state == result.analysis_state
    assert context.selected_state == result.analysis_state
    assert context.candidate_strategy == result.candidate_strategy
    assert context.selected_strategy == result.candidate_strategy
    assert all(not hasattr(ref, "path") for ref in context.artifact_refs)
    assert {(ref.artifact_type, ref.identity) for ref in context.artifact_refs} >= {
        ("authority_result", result.result_id),
        ("analysis_decision", result.analysis_decision.decision_id),
        ("price_attribution", result.price_attribution.attribution_id),
        ("transition_decision", result.transition_decision.decision_hash),
        ("consistency_decision", result.consistency_decision.decision_id),
    }


def test_v2_readiness_is_bound_field_by_field_without_inference() -> None:
    loop_input, result = _v2_pair_with_missing_confirmatory_and_options()
    quality = loop_input.current_feature.data_quality

    context = build_gold_report_context(loop_input, result, run_id="run-v2-readiness")

    assert context.readiness_projection == "feature_snapshot_v2_bound"
    assert context.readiness_policy_version == quality.readiness_policy_version
    assert context.analysis_readiness == quality.analysis_readiness
    assert context.strategy_readiness == quality.strategy_readiness
    assert context.options_readiness == quality.options_readiness
    assert context.event_attribution_readiness == quality.event_attribution_readiness
    assert context.missing_required_inputs == quality.missing_required_inputs
    assert context.missing_confirmatory_inputs == quality.missing_confirmatory_inputs
    assert context.prohibited_outputs == quality.prohibited_outputs
    assert context.readiness_reason_codes == quality.reason_codes
    assert tuple(item.model_dump() for item in context.unresolved_items) == (
        {"kind": "missing_confirmatory_input", "code": "COT"},
        {"kind": "prohibited_output", "code": "OPTIONS_CONFIRMATION"},
        {"kind": "prohibited_output", "code": "TRIGGERED_STRATEGY"},
    )


def test_v1_readiness_mapping_is_explicit_and_conservative() -> None:
    loop_input, result = _bootstrap_pair()

    context = build_gold_report_context(loop_input, result, run_id="run-v1")

    assert context.readiness_projection == "feature_snapshot_v1_conservative"
    assert context.analysis_readiness == loop_input.current_feature.data_quality.analysis_readiness
    assert context.strategy_readiness == "observe"
    assert context.options_readiness == "observe"
    assert context.event_attribution_readiness == "observe"
    assert context.missing_required_inputs == ()
    assert context.missing_confirmatory_inputs == ()
    assert context.prohibited_outputs == (
        "CONFIRMED_EVENT_ATTRIBUTION",
        "OPTIONS_CONFIRMATION",
        "TRIGGERED_STRATEGY",
    )
    assert "LEGACY_FEATURE_SNAPSHOT_V1_CONSERVATIVE_PROJECTION" in (context.readiness_reason_codes)
    assert "LEGACY_MISSING_INPUT_CLASSIFICATION_UNAVAILABLE" in (context.readiness_reason_codes)


def test_frozen_v1_builder_keeps_the_historical_payload_shape_and_identity() -> None:
    loop_input, result = _bootstrap_pair()

    context = build_gold_report_context_v1(loop_input, result)
    payload = context.model_dump(mode="json")

    assert context.schema_version == "gold_report_context.v1"
    assert context.context_id.startswith("gold_report_context.v1:")
    assert "run_id" not in payload
    assert "artifact_refs" not in payload
    assert "major_events" not in payload
    assert set(payload) == {
        "schema_version",
        "authority_result_id",
        "current_feature_id",
        "previous_feature_id",
        "decision_as_of",
        "analysis_decision",
        "price_attribution",
        "candidate_state",
        "selected_state",
        "transition_decision",
        "candidate_strategy",
        "selected_strategy",
        "key_levels",
        "key_level_decisions",
        "analysis_readiness",
        "source_refs",
        "language_generation",
        "payload_hash",
        "context_id",
    }


@pytest.mark.parametrize("run_id", ("", "../escape", "a/b", " spaced", "a" * 129))
def test_run_id_is_required_and_fail_closed(run_id: str) -> None:
    loop_input, result = _bootstrap_pair()

    with pytest.raises(ValueError, match="run_id"):
        build_gold_report_context(loop_input, result, run_id=run_id)

    assert inspect.signature(build_gold_report_context).parameters["run_id"].default is inspect.Parameter.empty
    assert inspect.signature(build_gold_report_context).parameters["run_id"].kind is inspect.Parameter.KEYWORD_ONLY


def test_identity_tamper_fails_closed_at_the_builder_boundary() -> None:
    loop_input, result = _bootstrap_v2_pair()
    tampered_result = result.model_copy(update={"result_hash": "0" * 64})
    tampered_feature = loop_input.current_feature.model_copy(update={"snapshot_id": f"feature_snapshot.v2:{'0' * 64}"})
    tampered_input = loop_input.model_copy(update={"current_feature": tampered_feature})

    with pytest.raises(ValidationError, match="identity"):
        build_gold_report_context(loop_input, tampered_result, run_id="run-tampered")
    with pytest.raises(ValueError, match="bind|identity"):
        build_gold_report_context(tampered_input, result, run_id="run-tampered")

    context = build_gold_report_context(loop_input, result, run_id="run-original")
    tampered_context = context.model_copy(update={"run_id": "run-other"})
    with pytest.raises(ValidationError, match="context identity"):
        GoldReportContext.model_validate(tampered_context.model_dump(mode="python"))


def test_major_events_and_unresolved_items_have_no_synthetic_facts() -> None:
    loop_input, result = _event_blackout_pair()

    context = build_gold_report_context(loop_input, result, run_id="run-event")

    assert context.major_events == loop_input.current_feature.official_events.events
    assert tuple(event.event_id for event in context.major_events) == ("fed-2025-01-29",)
    assert "FOMC" not in {event.event_id for event in context.major_events}
    assert context.strategy_reason_codes == (
        "MAJOR_EVENT_BLACKOUT",
        "MAJOR_EVENT_WINDOW_ACTIVE",
    )
    assert context.strategy_release_conditions == ("EVENT_WINDOW_CLOSED",)
    assert context.strategy_review_triggers == (
        "ON_EVENT_RISK_UPDATE",
        "ON_EVENT_WINDOW_CLOSE",
    )
    assert tuple(item.model_dump() for item in context.unresolved_items) == (
        {"kind": "prohibited_output", "code": "CONFIRMED_EVENT_ATTRIBUTION"},
        {"kind": "prohibited_output", "code": "OPTIONS_CONFIRMATION"},
        {"kind": "prohibited_output", "code": "TRIGGERED_STRATEGY"},
        {"kind": "release_condition", "code": "EVENT_WINDOW_CLOSED"},
        {"kind": "review_trigger", "code": "ON_EVENT_RISK_UPDATE"},
        {"kind": "review_trigger", "code": "ON_EVENT_WINDOW_CLOSE"},
        {"kind": "strategy_reason", "code": "MAJOR_EVENT_BLACKOUT"},
        {"kind": "strategy_reason", "code": "MAJOR_EVENT_WINDOW_ACTIVE"},
    )
