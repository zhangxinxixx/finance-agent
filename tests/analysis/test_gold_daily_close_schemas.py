from __future__ import annotations

import pytest
from pydantic import ValidationError

from apps.analysis.gold_policy.daily_close_schemas import (
    DailyCloseLoopInput,
    DailyCloseLoopResultInput,
)
from tests.analysis.test_gold_daily_close_loop import _bootstrap_result, _evidence
from tests.analysis.test_gold_strategy_policy import _policy_input, _snapshot


def test_loop_result_is_content_addressed_and_immutable() -> None:
    result, _ = _bootstrap_result()

    assert result.result_id.endswith(result.result_hash)
    with pytest.raises(ValidationError):
        type(result).model_validate({**result.model_dump(), "result_hash": "0" * 64})

    reversed_refs = result.model_dump()
    reversed_refs["source_refs"] = tuple(reversed(reversed_refs["source_refs"]))
    assert type(result).model_validate(reversed_refs).model_dump() == result.model_dump()


def test_partial_predecessor_bundle_is_rejected() -> None:
    current = _snapshot("feature_snapshot_v1_bearish_2025-01-21.json")
    previous = _snapshot("feature_snapshot_v1_bullish_2025-01-17.json")
    support = _policy_input(feature=current)
    bootstrap, _ = _bootstrap_result()

    with pytest.raises(ValidationError):
        DailyCloseLoopInput(
            decision_as_of=support.decision_as_of,
            current_feature=current,
            previous_feature=previous,
            previous_state=bootstrap.analysis_state,
            transition_evidence=_evidence(support.decision_as_of),
            options_regime=support.options_regime,
            event_risk=support.event_risk,
        )


def test_result_rejects_canonical_action_that_conflicts_with_transition() -> None:
    result, _ = _bootstrap_result()
    payload = result.model_dump(exclude={"result_hash", "result_id"})
    payload["canonical_action"] = "maintain"

    with pytest.raises(ValidationError, match="canonical action must match"):
        DailyCloseLoopResultInput.model_validate(payload)


def test_result_rejects_cross_product_feature_lineage() -> None:
    result, _ = _bootstrap_result()
    payload = result.model_dump(exclude={"result_hash", "result_id"})
    payload["current_feature_id"] = result.previous_feature_id

    with pytest.raises(ValidationError, match="analysis decision must bind"):
        DailyCloseLoopResultInput.model_validate(payload)


def test_predecessor_bundle_requires_its_exact_feature_snapshot() -> None:
    bootstrap, previous_feature = _bootstrap_result()
    current = _snapshot("feature_snapshot_v1_mixed_2025-01-24.json")
    wrong_previous = _snapshot("feature_snapshot_v1_bullish_2025-01-17.json")
    support = _policy_input(feature=current)

    with pytest.raises(ValidationError, match="previous feature must bind"):
        DailyCloseLoopInput(
            decision_as_of=support.decision_as_of,
            current_feature=current,
            previous_feature=wrong_previous,
            previous_policy_input=bootstrap.strategy_policy_input,
            previous_state=bootstrap.analysis_state,
            previous_transition=bootstrap.transition_decision,
            previous_strategy=bootstrap.candidate_strategy,
            transition_evidence=_evidence(support.decision_as_of),
            options_regime=support.options_regime,
            event_risk=support.event_risk,
        )

    assert previous_feature.snapshot_id == bootstrap.strategy_policy_input.feature_snapshot.snapshot_id


def test_loop_rejects_cross_session_feature_and_decision_inputs() -> None:
    current = _snapshot("feature_snapshot_v1_bearish_2025-01-21.json")
    previous = _snapshot("feature_snapshot_v1_bullish_2025-01-17.json")
    future = _snapshot("feature_snapshot_v1_mixed_2025-01-24.json")
    future_support = _policy_input(
        feature=future,
        options_source_snapshot_id=current.snapshot_id,
    )

    with pytest.raises(ValidationError, match="decision daily-close session"):
        DailyCloseLoopInput(
            decision_as_of=future_support.decision_as_of,
            current_feature=current,
            previous_feature=previous,
            transition_evidence=_evidence(future_support.decision_as_of),
            options_regime=future_support.options_regime,
            event_risk=future_support.event_risk,
        )
