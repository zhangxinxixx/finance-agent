from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from apps.analysis.gold_policy.consistency_schemas import (
    AnalysisStrategyConsistencyDecision,
    build_analysis_strategy_consistency_decision,
)


AS_OF = datetime(2025, 1, 17, 21, 5, tzinfo=UTC)


def _payload(**overrides: object) -> dict[str, object]:
    candidate_id = f"strategy_decision.v1:{'a' * 64}"
    payload: dict[str, object] = {
        "previous_state_id": None,
        "current_state_id": f"analysis_state.v1:{'b' * 64}",
        "previous_strategy_id": None,
        "candidate_strategy_id": candidate_id,
        "transition_decision_hash": "c" * 64,
        "proof_hash": "d" * 64,
        "status": "consistent",
        "change_kind": "bootstrap",
        "consistency_passed": True,
        "selected_strategy_decision_id": candidate_id,
        "reason_codes": ("BOOTSTRAP_ACCEPTED",),
        "source_refs": (
            {
                "source": "fixture",
                "reference": "artifact://consistency",
                "retrieved_at": AS_OF,
            },
        ),
    }
    payload.update(overrides)
    return payload


def test_consistency_decision_is_content_addressed_and_immutable() -> None:
    decision = build_analysis_strategy_consistency_decision(_payload())

    assert decision.decision_id.endswith(decision.decision_hash)
    with pytest.raises(ValidationError):
        AnalysisStrategyConsistencyDecision.model_validate({**decision.model_dump(), "proof_hash": "0" * 64})


@pytest.mark.parametrize(
    "changes",
    [
        {"consistency_passed": False},
        {"selected_strategy_decision_id": None},
        {"change_kind": "rejected"},
        {"change_kind": "state_advance"},
        {"previous_state_id": f"analysis_state.v1:{'e' * 64}"},
        {
            "previous_state_id": f"analysis_state.v1:{'e' * 64}",
            "previous_policy_input_hash": "2" * 64,
            "previous_transition_decision_hash": "f" * 64,
            "previous_strategy_id": f"strategy_decision.v1:{'1' * 64}",
        },
        {"previous_state_id": "analysis_state.v1:not-a-hash"},
        {"previous_strategy_id": "strategy_decision.v1:not-a-hash"},
        {"unexpected": True},
    ],
)
def test_consistent_result_requires_complete_paired_selection(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        build_analysis_strategy_consistency_decision({**_payload(), **changes})


def test_blocked_result_cannot_publish_candidate() -> None:
    decision = build_analysis_strategy_consistency_decision(
        _payload(
            status="blocked",
            change_kind="rejected",
            consistency_passed=False,
            selected_strategy_decision_id=None,
            reason_codes=("CURRENT_POLICY_OUTPUT_MISMATCH",),
        )
    )

    assert decision.consistency_passed is False
    assert decision.selected_strategy_decision_id is None
