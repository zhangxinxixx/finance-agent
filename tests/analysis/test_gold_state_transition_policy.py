from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.analysis.gold_policy.analysis_policy import GoldAnalysisDecision
from apps.analysis.gold_policy.state_schemas import (
    AnalysisStage,
    EvidenceDeltaKind,
    EvidenceScope,
    PendingRule,
    TransitionAction,
    TransitionEvidence,
    build_analysis_state,
)
from apps.analysis.gold_policy.state_transition_policy import (
    evaluate_analysis_state_transition,
    ordinary_stage_distance,
)


AS_OF = datetime(2026, 7, 29, 21, 0, tzinfo=UTC)
GOLDEN_CASES = (
    Path(__file__).parents[1] / "fixtures" / "gold_state" / "v1_transition_cases.json"
)


def _ref(source: str, as_of: datetime = AS_OF) -> dict[str, object]:
    return {
        "source": source,
        "reference": f"artifact://{source}/{as_of.date().isoformat()}",
        "retrieved_at": as_of,
    }


def _analysis(
    direction: str,
    *,
    quality: str = "accepted",
    confidence: float = 0.7,
) -> GoldAnalysisDecision:
    stage = {
        "bullish": "upside_pressure",
        "bearish": "downside_pressure",
        "neutral": "range",
        "mixed": "direction_decision",
        "unavailable": "unavailable",
    }[direction]
    tilt = direction if direction in {"bullish", "bearish"} else "none"
    return GoldAnalysisDecision(
        current_snapshot_id="feature_snapshot.v1:current",
        previous_snapshot_id="feature_snapshot.v1:previous",
        direction=direction,
        direction_tilt=tilt,
        macro_regime=f"test_{direction}",
        market_stage_candidate=stage,
        dominant_drivers=(),
        counter_drivers=(),
        conflicts=(),
        confidence=confidence,
        quality_status=quality,
    )


def _evidence(
    day: int,
    *,
    kind: str = "ordinary",
    scope: str = "daily_close",
    categories: tuple[str, ...] = ("macro",),
    rule_code: str | None = None,
    evidence_id: str | None = None,
    predecessor_evidence_id: str | None = None,
) -> TransitionEvidence:
    as_of = AS_OF + timedelta(days=day)
    return TransitionEvidence.model_validate(
        {
            "evidence_id": evidence_id or f"evidence:{kind}:{day}",
            "scope": scope,
            "delta_kind": kind,
            "as_of": as_of,
            "source_refs": [_ref(f"evidence_{day}", as_of)],
            "evidence_categories": categories,
            "predecessor_evidence_id": predecessor_evidence_id,
            "rule_code": rule_code,
        }
    )


def _state(
    stage: str,
    bias: str,
    *,
    scope: str = "daily_close",
    confidence: float = 0.75,
):
    return build_analysis_state(
        {
            "stage": stage,
            "directional_bias": bias,
            "pending_transition": None,
            "scope": scope,
            "as_of": AS_OF,
            "confidence": confidence,
            "quality_status": "accepted",
            "source_refs": [_ref("previous_state")],
        }
    )


@pytest.mark.parametrize(
    ("direction", "stage", "bias"),
    [
        ("bullish", AnalysisStage.PRESSURE, "bullish"),
        ("bearish", AnalysisStage.PRESSURE, "bearish"),
        ("neutral", AnalysisStage.RANGE, "neutral"),
        ("mixed", AnalysisStage.DIRECTION_DECISION, "mixed"),
    ],
)
def test_bootstrap_is_conservative_and_never_creates_a_trend(
    direction: str,
    stage: AnalysisStage,
    bias: str,
) -> None:
    result = evaluate_analysis_state_transition(
        None,
        _analysis(direction),
        _evidence(1),
    )

    assert result.state is not None
    assert result.state.stage is stage
    assert result.state.directional_bias == bias
    assert result.decision.advance is True
    assert result.decision.from_state_id is None
    assert result.state.stage is not AnalysisStage.TREND_CONFIRMED


@pytest.mark.parametrize(
    ("quality", "direction"),
    [("blocked", "unavailable"), ("observe", "bullish")],
)
def test_unaccepted_bootstrap_does_not_fabricate_canonical_state(
    quality: str,
    direction: str,
) -> None:
    result = evaluate_analysis_state_transition(
        None,
        _analysis(direction, quality=quality, confidence=0.0),
        _evidence(1),
    )

    assert result.state is None
    assert result.decision.advance is False
    assert result.decision.transition_allowed is False
    assert result.decision.to_stage is None


def test_no_op_short_circuits_candidate_and_preserves_exact_state() -> None:
    previous = _state("trend_confirmed", "bullish")
    result = evaluate_analysis_state_transition(
        previous,
        _analysis("neutral"),
        _evidence(1, kind="no_op", categories=()),
    )

    assert result.state is previous
    assert result.decision.action is TransitionAction.MAINTAIN
    assert result.decision.advance is False
    assert result.decision.to_state_id == previous.state_id


@pytest.mark.parametrize(
    ("quality", "direction"),
    [("blocked", "unavailable"), ("observe", "bearish")],
)
def test_blocked_and_observe_preserve_existing_canonical_state(
    quality: str,
    direction: str,
) -> None:
    previous = _state("pressure", "bullish")
    result = evaluate_analysis_state_transition(
        previous,
        _analysis(direction, quality=quality, confidence=0.0),
        _evidence(1),
    )

    assert result.state is previous
    assert result.decision.action is TransitionAction.PENDING
    assert result.decision.transition_allowed is False
    assert result.decision.advance is False


def test_blocked_no_op_is_non_advancing_and_contract_valid() -> None:
    previous = _state("pressure", "bullish")
    result = evaluate_analysis_state_transition(
        previous,
        _analysis("unavailable", quality="blocked", confidence=0.0),
        _evidence(1, kind="no_op", categories=()),
    )

    assert result.state is previous
    assert result.decision.action is TransitionAction.MAINTAIN
    assert result.decision.transition_allowed is False
    assert result.decision.advance is False


def test_scope_heads_are_independent() -> None:
    previous = _state("pressure", "bullish", scope="weekly_fundamental")
    result = evaluate_analysis_state_transition(
        previous,
        _analysis("bullish"),
        _evidence(1, scope="daily_close"),
    )

    assert result.state is previous
    assert result.decision.advance is False
    assert result.decision.reasons == ("SCOPE_HEAD_MISMATCH",)


def test_inconsistent_analysis_candidate_fails_closed() -> None:
    previous = _state("pressure", "bullish")
    inconsistent = _analysis("bullish").model_copy(
        update={"market_stage_candidate": "range"}
    )
    result = evaluate_analysis_state_transition(
        previous,
        inconsistent,
        _evidence(1),
    )

    assert result.state is previous
    assert result.decision.transition_allowed is False
    assert result.decision.advance is False
    assert result.decision.reasons == ("ANALYSIS_STAGE_CANDIDATE_MISMATCH",)


def test_ordinary_support_moves_exactly_one_business_edge() -> None:
    previous = _state("pressure", "bullish")
    result = evaluate_analysis_state_transition(
        previous,
        _analysis("bullish"),
        _evidence(1),
    )

    assert result.state is not None
    assert result.state.stage is AnalysisStage.WEAK_REPAIR
    assert result.state.directional_bias == "bullish"
    assert result.decision.action is TransitionAction.STRENGTHEN
    assert ordinary_stage_distance(previous.stage, result.state.stage) == 1


def test_single_opposite_observation_is_pending_and_second_only_weakens_one_edge() -> None:
    previous = _state("pressure", "bullish")
    first = evaluate_analysis_state_transition(
        previous,
        _analysis("bearish"),
        _evidence(1),
    )

    assert first.state is not None
    assert first.state.stage is AnalysisStage.PRESSURE
    assert first.state.directional_bias == "bullish"
    assert first.state.pending_transition is not None
    assert first.state.pending_transition.rule is PendingRule.OPPOSITE_BIAS
    assert first.decision.action is TransitionAction.PENDING
    assert first.decision.advance is True
    assert first.decision.stage_changed is False

    second = evaluate_analysis_state_transition(
        first.state,
        _analysis("bearish"),
        _evidence(2, predecessor_evidence_id="evidence:ordinary:1"),
        previous_transition=first.decision,
    )
    assert second.state is not None
    assert second.state.stage is AnalysisStage.WEAK_REPAIR
    assert second.state.directional_bias == "bullish"
    assert second.state.pending_transition is None
    assert second.decision.action is TransitionAction.WEAKEN
    assert ordinary_stage_distance(first.state.stage, second.state.stage) == 1


def test_duplicate_pending_evidence_is_idempotent() -> None:
    previous = _state("pressure", "bullish")
    evidence = _evidence(1, evidence_id="same-evidence")
    first = evaluate_analysis_state_transition(
        previous,
        _analysis("bearish"),
        evidence,
    )
    assert first.state is not None

    duplicate = evaluate_analysis_state_transition(
        first.state,
        _analysis("bearish"),
        evidence,
        previous_transition=first.decision,
    )
    assert duplicate.state is first.state
    assert duplicate.decision.advance is False
    assert duplicate.decision.reasons == ("DUPLICATE_EVIDENCE_ALREADY_APPLIED",)


def test_expired_pending_evidence_restarts_confirmation_streak() -> None:
    previous = _state("pressure", "bullish")
    first = evaluate_analysis_state_transition(
        previous,
        _analysis("bearish"),
        _evidence(1),
    )
    assert first.state is not None

    expired = evaluate_analysis_state_transition(
        first.state,
        _analysis("bearish"),
        _evidence(6, predecessor_evidence_id="evidence:ordinary:1"),
        previous_transition=first.decision,
    )
    assert expired.state is not None
    assert expired.state.stage is AnalysisStage.PRESSURE
    assert expired.state.directional_bias == "bullish"
    assert expired.state.pending_transition is not None
    assert expired.state.pending_transition.count == 1
    assert expired.state.pending_transition.first_seen_at == AS_OF + timedelta(days=6)


def test_pending_cannot_complete_without_latest_transition_head() -> None:
    previous = _state("pressure", "bullish")
    first = evaluate_analysis_state_transition(
        previous,
        _analysis("bearish"),
        _evidence(1),
    )
    assert first.state is not None

    missing_head = evaluate_analysis_state_transition(
        first.state,
        _analysis("bearish"),
        _evidence(2, predecessor_evidence_id="evidence:ordinary:1"),
    )
    assert missing_head.state is not None
    assert missing_head.state.stage is AnalysisStage.PRESSURE
    assert missing_head.state.directional_bias == "bullish"
    assert missing_head.state.pending_transition is not None
    assert missing_head.state.pending_transition.count == 1
    assert missing_head.decision.action is TransitionAction.PENDING


def test_mixed_is_preserved_instead_of_collapsed_to_neutral() -> None:
    previous = _state("pressure", "bullish")
    first = evaluate_analysis_state_transition(previous, _analysis("mixed"), _evidence(1))
    assert first.state is not None
    second = evaluate_analysis_state_transition(
        first.state,
        _analysis("mixed"),
        _evidence(2, predecessor_evidence_id="evidence:ordinary:1"),
        previous_transition=first.decision,
    )

    assert second.state is not None
    assert second.state.directional_bias == "mixed"
    assert second.state.stage in {AnalysisStage.RANGE, AnalysisStage.DIRECTION_DECISION}
    assert second.state.directional_bias != "neutral"


def test_trend_entry_requires_two_consecutive_multi_category_confirmations() -> None:
    previous = _state("reversal_watch", "bullish")
    first = evaluate_analysis_state_transition(
        previous,
        _analysis("bullish"),
        _evidence(1, categories=("price", "macro")),
    )

    assert first.state is not None
    assert first.state.stage is AnalysisStage.REVERSAL_WATCH
    assert first.state.pending_transition is not None
    assert first.state.pending_transition.rule is PendingRule.TREND_ENTRY
    assert first.decision.action is TransitionAction.PENDING

    second = evaluate_analysis_state_transition(
        first.state,
        _analysis("bullish"),
        _evidence(
            2,
            categories=("price", "macro"),
            predecessor_evidence_id="evidence:ordinary:1",
        ),
        previous_transition=first.decision,
    )
    assert second.state is not None
    assert second.state.stage is AnalysisStage.TREND_CONFIRMED
    assert second.state.pending_transition is None
    assert second.decision.action is TransitionAction.STRENGTHEN


def test_one_category_cannot_enter_trend() -> None:
    previous = _state("reversal_watch", "bullish")
    result = evaluate_analysis_state_transition(
        previous,
        _analysis("bullish"),
        _evidence(1, categories=("price",)),
    )

    assert result.state is previous
    assert result.decision.advance is False
    assert result.decision.reasons == ("TREND_ENTRY_EVIDENCE_INSUFFICIENT",)


def test_trend_exit_requires_two_counter_observations_and_keeps_old_bias() -> None:
    previous = _state("trend_confirmed", "bullish")
    first = evaluate_analysis_state_transition(
        previous,
        _analysis("bearish"),
        _evidence(1, categories=("price", "macro")),
    )
    assert first.state is not None
    assert first.state.stage is AnalysisStage.TREND_CONFIRMED
    assert first.state.directional_bias == "bullish"
    assert first.state.pending_transition is not None
    assert first.state.pending_transition.rule is PendingRule.TREND_EXIT

    second = evaluate_analysis_state_transition(
        first.state,
        _analysis("bearish"),
        _evidence(
            2,
            categories=("price",),
            predecessor_evidence_id="evidence:ordinary:1",
        ),
        previous_transition=first.decision,
    )
    assert second.state is not None
    assert second.state.stage is AnalysisStage.REVERSAL_WATCH
    assert second.state.directional_bias == "bullish"
    assert second.decision.action is TransitionAction.WEAKEN


def test_trend_exit_threshold_is_lower_than_trend_entry_threshold() -> None:
    previous = _state("trend_confirmed", "bullish")
    first = evaluate_analysis_state_transition(
        previous,
        _analysis("neutral"),
        _evidence(1, categories=("price",)),
    )
    assert first.state is not None
    second = evaluate_analysis_state_transition(
        first.state,
        _analysis("neutral"),
        _evidence(
            2,
            categories=("price",),
            predecessor_evidence_id="evidence:ordinary:1",
        ),
        previous_transition=first.decision,
    )

    assert second.state is not None
    assert second.state.stage is AnalysisStage.REVERSAL_WATCH
    assert second.state.directional_bias == "bullish"


def test_same_timestamp_with_different_id_cannot_complete_confirmation() -> None:
    previous = _state("pressure", "bullish")
    first = evaluate_analysis_state_transition(
        previous,
        _analysis("bearish"),
        _evidence(1, evidence_id="first"),
    )
    assert first.state is not None

    same_time = evaluate_analysis_state_transition(
        first.state,
        _analysis("bearish"),
        _evidence(
            1,
            evidence_id="second",
            predecessor_evidence_id="first",
        ),
        previous_transition=first.decision,
    )
    assert same_time.state is first.state
    assert same_time.decision.advance is False
    assert same_time.decision.reasons == ("EVIDENCE_AS_OF_NOT_STRICTLY_NEW",)


def test_blocked_evaluation_interrupts_pending_confirmation_chain() -> None:
    previous = _state("pressure", "bullish")
    first = evaluate_analysis_state_transition(
        previous,
        _analysis("bearish"),
        _evidence(1, evidence_id="accepted-1"),
    )
    assert first.state is not None

    blocked = evaluate_analysis_state_transition(
        first.state,
        _analysis("unavailable", quality="blocked", confidence=0.0),
        _evidence(
            2,
            evidence_id="blocked-2",
            predecessor_evidence_id="accepted-1",
        ),
        previous_transition=first.decision,
    )
    assert blocked.state is first.state

    resumed = evaluate_analysis_state_transition(
        blocked.state,
        _analysis("bearish"),
        _evidence(
            3,
            evidence_id="accepted-3",
            predecessor_evidence_id="accepted-1",
        ),
        previous_transition=blocked.decision,
    )
    assert resumed.state is not None
    assert resumed.state.stage is AnalysisStage.PRESSURE
    assert resumed.state.directional_bias == "bullish"
    assert resumed.state.pending_transition is not None
    assert resumed.state.pending_transition.count == 1
    assert resumed.state.pending_transition.last_evidence_id == "accepted-3"


def test_blocked_quality_gate_precedes_duplicate_detection() -> None:
    previous = _state("pressure", "bullish")
    evidence = _evidence(1, evidence_id="accepted-1")
    first = evaluate_analysis_state_transition(
        previous,
        _analysis("bearish"),
        evidence,
    )
    assert first.state is not None

    blocked = evaluate_analysis_state_transition(
        first.state,
        _analysis("unavailable", quality="blocked", confidence=0.0),
        evidence,
        previous_transition=first.decision,
    )
    assert blocked.state is first.state
    assert blocked.decision.transition_allowed is False
    assert blocked.decision.reasons == ("ANALYSIS_DECISION_BLOCKED",)


def test_major_confirmation_accelerates_but_cannot_create_a_new_trend() -> None:
    previous = _state("pressure", "bullish")
    result = evaluate_analysis_state_transition(
        previous,
        _analysis("bullish"),
        _evidence(
            1,
            kind="major_confirmation",
            categories=("price", "official_event"),
            rule_code="OFFICIAL_EVENT_REACTION_CONFIRMED",
        ),
    )

    assert result.state is not None
    assert result.state.stage is AnalysisStage.REVERSAL_WATCH
    assert result.state.stage is not AnalysisStage.TREND_CONFIRMED


def test_major_confirmation_can_complete_an_existing_trend_entry_streak() -> None:
    previous = _state("reversal_watch", "bullish")
    first = evaluate_analysis_state_transition(
        previous,
        _analysis("bullish"),
        _evidence(1, categories=("price", "macro")),
    )
    assert first.state is not None

    completed = evaluate_analysis_state_transition(
        first.state,
        _analysis("bullish"),
        _evidence(
            2,
            kind="major_confirmation",
            categories=("price", "official_event"),
            rule_code="OFFICIAL_EVENT_REACTION_CONFIRMED",
            predecessor_evidence_id="evidence:ordinary:1",
        ),
        previous_transition=first.decision,
    )
    assert completed.state is not None
    assert completed.state.stage is AnalysisStage.TREND_CONFIRMED
    assert completed.state.directional_bias == "bullish"


def test_opposite_major_confirmation_invalidates_only_the_old_bias() -> None:
    previous = _state("trend_confirmed", "bullish")
    result = evaluate_analysis_state_transition(
        previous,
        _analysis("bearish"),
        _evidence(
            1,
            kind="major_confirmation",
            categories=("price", "macro"),
            rule_code="MAJOR_MACRO_REACTION_CONFIRMED",
        ),
    )

    assert result.state is not None
    assert result.decision.action is TransitionAction.INVALIDATE
    assert result.state.stage is AnalysisStage.DIRECTION_DECISION
    assert result.state.directional_bias == "mixed"
    assert result.state.pending_transition is not None
    assert result.state.pending_transition.direction == "bearish"


def test_hard_invalidation_can_cross_edges_but_never_confirms_opposite_trend() -> None:
    previous = _state("trend_confirmed", "bullish")
    result = evaluate_analysis_state_transition(
        previous,
        _analysis("bearish"),
        _evidence(
            1,
            kind="hard_invalidation",
            categories=("price",),
            rule_code="CONFIRMED_SUPPORT_BREAK",
        ),
    )

    assert result.state is not None
    assert result.decision.action is TransitionAction.INVALIDATE
    assert result.state.stage is AnalysisStage.DIRECTION_DECISION
    assert result.state.directional_bias == "mixed"
    assert not (
        result.state.stage is AnalysisStage.TREND_CONFIRMED
        and result.state.directional_bias == "bearish"
    )


def test_same_input_is_reproducible_100_times_and_inputs_are_immutable() -> None:
    previous = _state("pressure", "bullish")
    analysis = _analysis("bearish")
    evidence = _evidence(1)
    previous_dump = deepcopy(previous.model_dump(mode="python"))
    analysis_dump = deepcopy(analysis.model_dump(mode="python"))
    evidence_dump = deepcopy(evidence.model_dump(mode="python"))

    results = [
        evaluate_analysis_state_transition(previous, analysis, evidence)
        for _ in range(100)
    ]

    assert all(result == results[0] for result in results)
    assert previous.model_dump(mode="python") == previous_dump
    assert analysis.model_dump(mode="python") == analysis_dump
    assert evidence.model_dump(mode="python") == evidence_dump


@pytest.mark.parametrize(
    ("stage", "bias"),
    [
        ("pressure", "bullish"),
        ("range", "neutral"),
        ("direction_decision", "mixed"),
        ("weak_repair", "bullish"),
        ("reversal_watch", "bullish"),
        ("trend_confirmed", "bullish"),
    ],
)
@pytest.mark.parametrize("direction", ["bullish", "bearish", "neutral", "mixed"])
def test_every_ordinary_branch_stays_within_one_business_edge(
    stage: str,
    bias: str,
    direction: str,
) -> None:
    previous = _state(stage, bias)
    result = evaluate_analysis_state_transition(
        previous,
        _analysis(direction),
        _evidence(1, categories=("price", "macro")),
    )

    assert result.state is not None
    assert ordinary_stage_distance(previous.stage, result.state.stage) <= 1


def test_state_lineage_references_previous_state_without_copying_all_history() -> None:
    first = _state("pressure", "bullish")
    second = evaluate_analysis_state_transition(
        first,
        _analysis("bullish"),
        _evidence(1),
    )
    assert second.state is not None
    third = evaluate_analysis_state_transition(
        second.state,
        _analysis("bullish"),
        _evidence(2),
    )
    assert third.state is not None

    assert len(second.state.source_refs) == 2
    assert len(third.state.source_refs) == 2
    assert any(ref.reference == second.state.state_id for ref in third.state.source_refs)


def test_evidence_cannot_predate_previous_state() -> None:
    previous = _state("pressure", "bullish")
    evidence = _evidence(-1)
    with pytest.raises(ValueError, match="predate"):
        evaluate_analysis_state_transition(previous, _analysis("bullish"), evidence)


def test_graph_uses_semantic_adjacency_not_enum_order() -> None:
    assert ordinary_stage_distance(AnalysisStage.PRESSURE, AnalysisStage.WEAK_REPAIR) == 1
    assert ordinary_stage_distance(AnalysisStage.RANGE, AnalysisStage.DIRECTION_DECISION) == 1
    assert ordinary_stage_distance(AnalysisStage.PRESSURE, AnalysisStage.TREND_CONFIRMED) == 3


def test_major_confirmation_contract_requires_two_evidence_categories() -> None:
    with pytest.raises(ValueError, match="price plus"):
        _evidence(
            1,
            kind="major_confirmation",
            categories=("official_event",),
            rule_code="OFFICIAL_EVENT_REACTION_CONFIRMED",
        )


def test_hard_invalidation_kind_is_explicit() -> None:
    evidence = _evidence(
        1,
        kind="hard_invalidation",
        categories=("price",),
        rule_code="CONFIRMED_SUPPORT_BREAK",
    )
    assert evidence.delta_kind is EvidenceDeltaKind.HARD_INVALIDATION
    assert evidence.scope is EvidenceScope.DAILY_CLOSE


def test_v1_golden_transition_cases() -> None:
    cases = json.loads(GOLDEN_CASES.read_text(encoding="utf-8"))
    assert len(cases) == 5

    for case in cases:
        previous_payload = case["previous"]
        previous = (
            None
            if previous_payload is None
            else _state(previous_payload["stage"], previous_payload["bias"])
        )
        analysis_payload = case["analysis"]
        confidence = 0.0 if analysis_payload["quality"] == "blocked" else 0.7
        evidence_payload = case["evidence"]
        result = evaluate_analysis_state_transition(
            previous,
            _analysis(
                analysis_payload["direction"],
                quality=analysis_payload["quality"],
                confidence=confidence,
            ),
            _evidence(
                1,
                kind=evidence_payload["kind"],
                categories=tuple(evidence_payload["categories"]),
                rule_code=evidence_payload.get("rule_code"),
            ),
        )
        expected = case["expected"]
        assert result.state is not None, case["case_id"]
        assert result.decision.action.value == expected["action"], case["case_id"]
        assert result.decision.advance is expected["advance"], case["case_id"]
        assert result.state.stage.value == expected["stage"], case["case_id"]
        assert result.state.directional_bias == expected["bias"], case["case_id"]
