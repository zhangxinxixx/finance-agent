from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from apps.analysis.gold_policy.analysis_policy import GoldAnalysisDecision
from apps.analysis.gold_policy.state_schemas import (
    StateTransitionPolicyDecisionV2,
    TransitionEvidence,
    build_analysis_state_v2,
)
from apps.analysis.gold_policy.state_transition_policy import evaluate_analysis_state_transition_v2


AS_OF = datetime(2026, 8, 2, 21, tzinfo=UTC)


def _analysis(direction: str, *, tilt: str = "none") -> GoldAnalysisDecision:
    return GoldAnalysisDecision(
        current_snapshot_id="a",
        previous_snapshot_id="b",
        direction=direction,
        direction_tilt=tilt,
        macro_regime="x",
        market_stage_candidate={
            "bullish": "upside_pressure",
            "bearish": "downside_pressure",
            "neutral": "range",
            "mixed": "direction_decision",
            "unavailable": "unavailable",
        }[direction],
        dominant_drivers=(),
        counter_drivers=(),
        conflicts=(),
        confidence=0.7,
        quality_status="accepted",
    )


def _evidence(
    day: int,
    kind: str = "ordinary",
    *,
    predecessor: str | None = None,
    rule_code: str | None = None,
) -> TransitionEvidence:
    when = AS_OF + timedelta(days=day)
    categories = [] if kind == "no_op" else ["macro"]
    if kind == "major_confirmation":
        categories.append("price")
    return TransitionEvidence.model_validate(
        {
            "evidence_id": f"e-{day}",
            "scope": "daily_close",
            "delta_kind": kind,
            "as_of": when,
            "source_refs": [
                {
                    "source": "fixture",
                    "reference": f"fixture://{day}",
                    "retrieved_at": when,
                }
            ],
            "evidence_categories": categories,
            "predecessor_evidence_id": predecessor,
            "rule_code": rule_code,
        }
    )


def _previous():
    return build_analysis_state_v2(
        {
            "direction": "bullish",
            "direction_tilt": "none",
            "market_regime": "pressure",
            "trend_maturity": "forming",
            "scope": "daily_close",
            "as_of": AS_OF,
            "confidence": 0.7,
            "quality_status": "accepted",
            "source_refs": [{"source": "fixture", "reference": "fixture://head", "retrieved_at": AS_OF}],
        }
    )


def test_ordinary_changes_at_most_one_dimension_and_reversal_requires_pending() -> None:
    first = evaluate_analysis_state_transition_v2(_previous(), _analysis("bearish"), _evidence(1))
    assert first.state is not None and first.state.direction == "bullish"
    assert first.state.pending_transition is not None
    assert first.decision.changed_dimensions == ()
    second = evaluate_analysis_state_transition_v2(
        first.state,
        _analysis("bearish"),
        _evidence(2, predecessor="e-1"),
        previous_transition=first.decision,
    )
    assert second.state is not None and second.state.direction == "bearish"
    assert second.decision.changed_dimensions == ("direction",)


def test_no_op_is_non_advancing_maintain() -> None:
    result = evaluate_analysis_state_transition_v2(_previous(), _analysis("bullish"), _evidence(1, "no_op"))
    assert result.decision.advance is False
    assert result.state is not None


def test_mixed_direction_tilt_survives_consecutive_daily_closes() -> None:
    previous = build_analysis_state_v2(
        {
            "direction": "mixed",
            "direction_tilt": "bullish",
            "market_regime": "direction_decision",
            "trend_maturity": "watching",
            "scope": "daily_close",
            "as_of": AS_OF,
            "confidence": 0.6,
            "quality_status": "accepted",
            "source_refs": [
                {
                    "source": "fixture",
                    "reference": "fixture://mixed-head",
                    "retrieved_at": AS_OF,
                }
            ],
        }
    )
    first = evaluate_analysis_state_transition_v2(
        previous,
        _analysis("mixed", tilt="bullish"),
        _evidence(1, "no_op"),
    )
    second = evaluate_analysis_state_transition_v2(
        first.state,
        _analysis("mixed", tilt="bullish"),
        _evidence(2, "no_op"),
        previous_transition=first.decision,
    )

    assert first.state == second.state == previous
    assert second.state.direction_tilt == "bullish"


def test_ordinary_progresses_exactly_one_regime_or_maturity_dimension() -> None:
    repair = evaluate_analysis_state_transition_v2(_previous(), _analysis("bullish"), _evidence(1))
    assert repair.state is not None
    assert repair.state.market_regime == "repair"
    assert repair.decision.changed_dimensions == ("market_regime",)

    watching = evaluate_analysis_state_transition_v2(repair.state, _analysis("bullish"), _evidence(2))
    assert watching.state is not None
    assert watching.state.trend_maturity == "watching"
    assert watching.decision.changed_dimensions == ("trend_maturity",)

    forged = repair.decision.model_dump(mode="python")
    forged["changed_dimensions"] = ()
    with pytest.raises(ValidationError):
        StateTransitionPolicyDecisionV2.model_validate(forged)


def test_hard_invalidation_and_major_confirmation_use_typed_paths() -> None:
    invalidated = evaluate_analysis_state_transition_v2(
        _previous(),
        _analysis("bullish"),
        _evidence(
            1,
            "hard_invalidation",
            rule_code="MAJOR_MACRO_STATE_INVALIDATED",
        ),
    )
    assert invalidated.state is not None
    assert invalidated.state.trend_maturity == "invalidated"
    assert invalidated.decision.action.value == "invalidate"

    confirmed = evaluate_analysis_state_transition_v2(
        _previous(),
        _analysis("bullish"),
        _evidence(
            1,
            "major_confirmation",
            rule_code="MAJOR_MACRO_REACTION_CONFIRMED",
        ),
    )
    assert confirmed.state is not None
    assert (confirmed.state.market_regime, confirmed.state.trend_maturity) == (
        "trend",
        "confirmed",
    )
    assert confirmed.decision.changed_dimensions == (
        "market_regime",
        "trend_maturity",
    )
