from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from apps.analysis.gold_policy.state_schemas import (
    AnalysisStage,
    AnalysisState,
    EvidenceCategory,
    EvidenceDeltaKind,
    EvidenceScope,
    HardInvalidationRule,
    MajorConfirmationRule,
    PendingRule,
    StateTransitionPolicyDecision,
    TransitionAction,
    TransitionEvidence,
    build_analysis_state,
    build_state_transition_policy_decision,
    canonical_analysis_state_json,
    canonical_state_transition_decision_json,
)


AS_OF = datetime(2026, 7, 29, 21, 0, tzinfo=UTC)


def _ref(
    source: str = "gold_analysis_policy",
    *,
    retrieved_at: datetime = AS_OF,
) -> dict[str, object]:
    return {
        "source": source,
        "reference": f"artifact://{source}/2026-07-29",
        "retrieved_at": retrieved_at,
    }


def _state_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "analysis_state.v1",
        "asset": "XAUUSD",
        "stage": "range",
        "directional_bias": "neutral",
        "pending_transition": None,
        "scope": "daily_close",
        "as_of": AS_OF,
        "confidence": 0.62,
        "quality_status": "accepted",
        "source_refs": [_ref()],
    }
    payload.update(overrides)
    return payload


def _decision_payload(
    from_state: AnalysisState,
    to_state: AnalysisState,
    **overrides: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "from_state_id": from_state.state_id,
        "to_state_id": to_state.state_id,
        "from_stage": from_state.stage,
        "to_stage": to_state.stage,
        "action": "strengthen",
        "transition_allowed": True,
        "advance": True,
        "stage_changed": from_state.stage != to_state.stage,
        "evidence": {
            "evidence_id": "gold_analysis_decision.v1:2026-07-30",
            "scope": "daily_close",
            "delta_kind": "ordinary",
            "as_of": AS_OF + timedelta(days=1),
            "source_refs": [
                _ref("gold_analysis_decision", retrieved_at=AS_OF + timedelta(days=1))
            ],
            "evidence_categories": ["macro"],
        },
        "reasons": ["REAL_YIELD_FALL_CONFIRMED"],
        "policy_version": "analysis_state_transition_policy.v1",
    }
    payload.update(overrides)
    return payload


def test_enums_are_closed_to_the_issue_95_values() -> None:
    assert {item.value for item in AnalysisStage} == {
        "pressure",
        "range",
        "direction_decision",
        "weak_repair",
        "reversal_watch",
        "trend_confirmed",
    }
    assert {item.value for item in TransitionAction} == {
        "strengthen",
        "maintain",
        "weaken",
        "invalidate",
        "pending",
    }
    assert {item.value for item in EvidenceScope} == {
        "intraday",
        "daily_close",
        "weekly_fundamental",
    }
    assert {item.value for item in EvidenceDeltaKind} == {
        "no_op",
        "ordinary",
        "hard_invalidation",
        "major_confirmation",
    }
    assert {item.value for item in EvidenceCategory} == {
        "macro",
        "price",
        "structure",
        "official_event",
    }
    assert {item.value for item in PendingRule} == {
        "opposite_bias",
        "new_bias",
        "trend_entry",
        "trend_exit",
        "conflict",
    }
    assert {item.value for item in HardInvalidationRule} == {
        "CONFIRMED_SUPPORT_BREAK",
        "CONFIRMED_RESISTANCE_BREAK",
        "MAJOR_MACRO_STATE_INVALIDATED",
    }
    assert {item.value for item in MajorConfirmationRule} == {
        "OFFICIAL_EVENT_REACTION_CONFIRMED",
        "MAJOR_MACRO_REACTION_CONFIRMED",
        "PRICE_STRUCTURE_MACRO_CONFIRMED",
    }


def test_analysis_state_is_content_addressed_stable_and_does_not_mutate_input() -> None:
    payload = _state_payload(
        source_refs=[_ref("z_source"), _ref("a_source")],
    )
    original = deepcopy(payload)

    states = [build_analysis_state(payload) for _ in range(100)]
    expected = states[0]

    assert all(state == expected for state in states)
    assert payload == original
    assert expected.schema_version == "analysis_state.v1"
    assert expected.asset == "XAUUSD"
    assert [ref.source for ref in expected.source_refs] == ["a_source", "z_source"]
    assert expected.payload_hash == hashlib.sha256(
        canonical_analysis_state_json(expected).encode()
    ).hexdigest()
    assert expected.state_id == f"analysis_state.v1:{expected.payload_hash}"


def test_equivalent_timezone_and_reference_order_have_one_state_identity() -> None:
    first = build_analysis_state(
        _state_payload(source_refs=[_ref("b"), _ref("a")])
    )
    equivalent_as_of = AS_OF.astimezone(timezone(timedelta(hours=8)))
    second = build_analysis_state(
        _state_payload(
            as_of=equivalent_as_of,
            source_refs=[
                _ref("a", retrieved_at=equivalent_as_of),
                _ref("b", retrieved_at=equivalent_as_of),
            ],
        )
    )

    assert first.state_id == second.state_id


@pytest.mark.parametrize(
    "changes",
    [
        {"as_of": datetime(2026, 7, 29, 21, 0)},
        {"source_refs": [_ref(retrieved_at=AS_OF + timedelta(seconds=1))]},
        {"source_refs": [_ref(), _ref()]},
        {
            "quality_status": "blocked",
            "directional_bias": "bearish",
            "confidence": 0.0,
        },
        {
            "quality_status": "blocked",
            "directional_bias": "unavailable",
            "confidence": 0.1,
        },
        {
            "pending_transition": {
                "rule": "opposite_bias",
                "direction": "bearish",
                "count": 1,
                "first_seen_at": AS_OF + timedelta(seconds=1),
                "last_seen_at": AS_OF + timedelta(seconds=1),
                "last_evidence_id": "future",
                "source_refs": [
                    _ref(retrieved_at=AS_OF + timedelta(seconds=1))
                ],
            }
        },
        {"quality_status": "accepted", "directional_bias": "unavailable"},
    ],
)
def test_analysis_state_rejects_invalid_time_lineage_and_semantics(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        build_analysis_state(_state_payload(**changes))


def test_analysis_state_is_frozen_extra_forbidden_and_rejects_tampered_identity() -> None:
    with pytest.raises(ValidationError):
        build_analysis_state(_state_payload(unexpected=True))

    state = build_analysis_state(_state_payload())
    with pytest.raises(ValidationError):
        state.confidence = 0.9  # type: ignore[misc]

    tampered = state.model_dump(mode="python")
    tampered["confidence"] = 0.9
    with pytest.raises(ValidationError, match="identity"):
        AnalysisState.model_validate(tampered)


@pytest.mark.parametrize(
    "changes",
    [
        {"stage": "trend_confirmed", "directional_bias": "neutral"},
        {
            "stage": "pressure",
            "directional_bias": "bullish",
            "pending_transition": {
                "rule": "trend_entry",
                "direction": "bullish",
                "count": 1,
                "first_seen_at": AS_OF,
                "last_seen_at": AS_OF,
                "last_evidence_id": "evidence-1",
                "source_refs": [_ref()],
            },
        },
        {
            "directional_bias": "bullish",
            "pending_transition": {
                "rule": "opposite_bias",
                "direction": "bullish",
                "count": 1,
                "first_seen_at": AS_OF,
                "last_seen_at": AS_OF,
                "last_evidence_id": "evidence-1",
                "source_refs": [_ref()],
            },
        },
        {
            "directional_bias": "bullish",
            "pending_transition": {
                "rule": "new_bias",
                "direction": "bearish",
                "count": 1,
                "first_seen_at": AS_OF,
                "last_seen_at": AS_OF,
                "last_evidence_id": "evidence-1",
                "source_refs": [_ref()],
            },
        },
    ],
)
def test_analysis_state_rejects_impossible_stage_bias_pending_combinations(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        build_analysis_state(_state_payload(**changes))


def test_hard_and_major_rules_are_whitelisted_and_category_bound() -> None:
    base = {
        "evidence_id": "evidence:privileged",
        "scope": "daily_close",
        "as_of": AS_OF,
        "source_refs": [_ref()],
    }
    with pytest.raises(ValidationError, match="CALLER_DEFINED_HARD_RULE"):
        TransitionEvidence.model_validate(
            {
                **base,
                "delta_kind": "hard_invalidation",
                "evidence_categories": ["price"],
                "rule_code": "CALLER_DEFINED_HARD_RULE",
            }
        )

    with pytest.raises(ValidationError, match="official event confirmation"):
        TransitionEvidence.model_validate(
            {
                **base,
                "delta_kind": "major_confirmation",
                "evidence_categories": ["price", "macro"],
                "rule_code": "OFFICIAL_EVENT_REACTION_CONFIRMED",
            }
        )

    with pytest.raises(ValidationError, match="weekly head"):
        TransitionEvidence.model_validate(
            {
                **base,
                "scope": "weekly_fundamental",
                "delta_kind": "major_confirmation",
                "evidence_categories": ["price", "official_event"],
                "rule_code": "OFFICIAL_EVENT_REACTION_CONFIRMED",
            }
        )


def test_transition_decision_is_content_addressed_stable_and_non_mutating() -> None:
    previous = build_analysis_state(_state_payload())
    current = build_analysis_state(
        _state_payload(
            stage="direction_decision",
            directional_bias="mixed",
            quality_status="observe",
            as_of=AS_OF + timedelta(days=1),
            source_refs=[_ref(retrieved_at=AS_OF + timedelta(days=1))],
        )
    )
    payload = _decision_payload(previous, current)
    original = deepcopy(payload)

    decisions = [build_state_transition_policy_decision(payload) for _ in range(100)]
    expected = decisions[0]

    assert all(decision == expected for decision in decisions)
    assert payload == original
    assert expected.decision_hash == hashlib.sha256(
        canonical_state_transition_decision_json(expected).encode()
    ).hexdigest()
    assert json.loads(canonical_state_transition_decision_json(expected))[
        "policy_version"
    ] == "analysis_state_transition_policy.v1"


def test_no_op_requires_non_advancing_maintain() -> None:
    state = build_analysis_state(_state_payload())
    payload = _decision_payload(
        state,
        state,
        action="maintain",
        transition_allowed=True,
        advance=False,
        stage_changed=False,
        evidence={
            "evidence_id": "evidence_delta:no-op",
            "scope": "daily_close",
            "delta_kind": "no_op",
            "as_of": AS_OF,
            "source_refs": [_ref()],
            "evidence_categories": [],
        },
        reasons=["NO_MATERIAL_EVIDENCE_DELTA"],
    )
    decision = build_state_transition_policy_decision(payload)
    assert decision.action is TransitionAction.MAINTAIN
    assert decision.advance is False

    with pytest.raises(ValidationError, match="no_op"):
        build_state_transition_policy_decision(
            {**payload, "action": "strengthen"}
        )


def test_hard_invalidation_requires_invalidate_action() -> None:
    previous = build_analysis_state(_state_payload())
    current = build_analysis_state(
        _state_payload(
            stage="reversal_watch",
            directional_bias="bearish",
            as_of=AS_OF + timedelta(days=1),
            source_refs=[_ref(retrieved_at=AS_OF + timedelta(days=1))],
        )
    )
    payload = _decision_payload(
        previous,
        current,
        action="invalidate",
        evidence={
            "evidence_id": "evidence_delta:hard-invalidation",
            "scope": "daily_close",
            "delta_kind": "hard_invalidation",
            "as_of": AS_OF + timedelta(days=1),
            "source_refs": [
                _ref("hard_invalidation", retrieved_at=AS_OF + timedelta(days=1))
            ],
            "evidence_categories": ["price"],
            "rule_code": "CONFIRMED_SUPPORT_BREAK",
        },
        reasons=["CORE_THESIS_INVALIDATED"],
    )
    assert build_state_transition_policy_decision(payload).action is TransitionAction.INVALIDATE

    with pytest.raises(ValidationError, match="hard_invalidation"):
        build_state_transition_policy_decision({**payload, "action": "weaken"})


@pytest.mark.parametrize(
    "changes",
    [
        {"advance": False},
        {"transition_allowed": False},
        {"stage_changed": False},
        {"action": "maintain"},
        {"action": "pending"},
        {"reasons": ["", "VALID"]},
        {"reasons": ["DUPLICATE", "DUPLICATE"]},
        {"extra": "forbidden"},
    ],
)
def test_transition_decision_rejects_inconsistent_or_extra_fields(
    changes: dict[str, object],
) -> None:
    previous = build_analysis_state(_state_payload())
    current = build_analysis_state(
        _state_payload(
            stage="direction_decision",
            directional_bias="mixed",
            quality_status="observe",
            as_of=AS_OF + timedelta(days=1),
            source_refs=[_ref(retrieved_at=AS_OF + timedelta(days=1))],
        )
    )
    with pytest.raises(ValidationError):
        build_state_transition_policy_decision(
            _decision_payload(previous, current, **changes)
        )


def test_transition_decision_rejects_naive_or_future_evidence_and_tampered_hash() -> None:
    state = build_analysis_state(_state_payload())
    no_op = _decision_payload(
        state,
        state,
        action="maintain",
        transition_allowed=True,
        advance=False,
        stage_changed=False,
        evidence={
            "evidence_id": "evidence_delta:no-op",
            "scope": "daily_close",
            "delta_kind": "no_op",
            "as_of": AS_OF,
            "source_refs": [_ref()],
            "evidence_categories": [],
        },
    )
    naive = deepcopy(no_op)
    naive["evidence"]["as_of"] = datetime(2026, 7, 29, 21, 0)  # type: ignore[index]
    with pytest.raises(ValidationError):
        build_state_transition_policy_decision(naive)

    future_ref = deepcopy(no_op)
    future_ref["evidence"]["source_refs"][0]["retrieved_at"] = AS_OF + timedelta(seconds=1)  # type: ignore[index]
    with pytest.raises(ValidationError):
        build_state_transition_policy_decision(future_ref)

    decision = build_state_transition_policy_decision(no_op)
    tampered = decision.model_dump(mode="python")
    tampered["reasons"] = ("CHANGED",)
    with pytest.raises(ValidationError, match="hash"):
        StateTransitionPolicyDecision.model_validate(tampered)
