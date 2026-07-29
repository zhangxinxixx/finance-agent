from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from pathlib import Path

from apps.analysis.gold_policy.attribution_policy import attribute_gold_price
from apps.analysis.gold_policy.daily_close_delivery import build_gold_daily_close_delivery
from apps.analysis.gold_policy.daily_close_loop import evaluate_gold_daily_close_loop
from apps.analysis.gold_policy.daily_close_schemas import DailyCloseLoopInput
from apps.analysis.gold_policy.key_level_policy import evaluate_key_level_lifecycle
from apps.worker.composite_analysis_pipeline import _build_gold_daily_close_summary
from tests.analysis.test_gold_daily_close_loop import _bootstrap_result, _evidence
from tests.analysis.test_gold_daily_close_store import _bootstrap_pair
from tests.analysis.test_gold_key_level_policy import _event as _level_event
from tests.analysis.test_gold_key_level_policy import _spec as _level_spec
from tests.analysis.test_gold_strategy_policy import _policy_input, _snapshot


def test_delivery_projects_only_formal_selected_artifacts() -> None:
    loop_input, result = _bootstrap_pair()

    delivery = build_gold_daily_close_delivery(loop_input, result)

    assert delivery.final_report.authority_result_id == result.result_id
    assert delivery.final_report.selected_state_id == result.selected_state_id
    assert delivery.final_report.selected_strategy_id == result.selected_strategy_id
    assert delivery.final_report.language_generation == "not_invoked"
    assert delivery.context_bundle.transition_decision_hash == result.transition_decision.decision_hash
    assert delivery.token_trace.model_invocations == 0
    assert delivery.strategy_diff.candidate_selected is True


def test_no_op_delivery_records_zero_token_skip_and_stable_selection() -> None:
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

    delivery = build_gold_daily_close_delivery(loop_input, result)

    assert delivery.token_trace.skip_reason == "no_material_change"
    assert delivery.token_trace.input_tokens == delivery.token_trace.output_tokens == 0
    assert delivery.strategy_diff.selected_strategy_id == result.selected_strategy_id
    assert delivery.strategy_diff.canonical_action.value == "maintain"


def test_hold_delivery_separates_selected_authority_from_candidate_projection() -> None:
    previous_result, previous_feature = _bootstrap_result()
    current = _snapshot("feature_snapshot_v1_mixed_2025-01-24.json")
    support = _policy_input(
        feature=current,
        attribution=attribute_gold_price(current, previous_feature),
    )
    spec = _level_spec(
        effective_from=support.decision_as_of - timedelta(days=1),
        expires_at=support.decision_as_of + timedelta(days=30),
    )
    unmatched = evaluate_key_level_lifecycle(
        None,
        _level_event(
            "discover",
            spec=spec,
            source_role="jin10_supplemental",
            factors=("level_proposal",),
            as_of=support.decision_as_of,
        ),
    ).decision
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
        key_level_decisions=(unmatched,),
    )
    result = evaluate_gold_daily_close_loop(loop_input)

    delivery = build_gold_daily_close_delivery(loop_input, result)

    assert result.canonical_action.value == "hold"
    assert delivery.strategy_diff.candidate_selected is False
    assert delivery.strategy_diff.selected_status == previous_result.candidate_strategy.status.value
    assert delivery.final_report.direction == previous_result.analysis_state.directional_bias
    assert delivery.final_report.candidate_direction == result.analysis_decision.direction
    assert delivery.final_report.transition_action == "hold"
    assert (
        delivery.final_report.candidate_transition_action
        == result.transition_decision.action.value
    )
    assert delivery.final_report.selected_strategy_id == previous_result.candidate_strategy.decision_id

    summary = _build_gold_daily_close_summary(
        execution=SimpleNamespace(
            loop_input=loop_input,
            result=result,
            write_result=SimpleNamespace(bundle_path=Path("/tmp/store/daily_close")),
        ),
        storage_root=Path("/tmp/store"),
    )
    assert summary["daily_close_strategy_status"] == delivery.strategy_diff.selected_status
    assert (
        summary["daily_close_candidate_strategy_status"]
        == delivery.strategy_diff.candidate_status
    )
