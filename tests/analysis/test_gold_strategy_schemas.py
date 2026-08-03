from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from apps.analysis.gold_policy.attribution_policy import attribute_gold_price
from apps.analysis.gold_policy.feature_snapshot import build_feature_snapshot
from apps.analysis.gold_policy.strategy_schemas import (
    StrategyDecision,
    StrategyDecisionInput,
    build_strategy_decision,
    build_strategy_event_risk,
    build_strategy_options_regime,
)
from tests.analysis.test_gold_strategy_policy import _policy_input, _snapshot


AS_OF = datetime(2025, 1, 17, 21, 5, tzinfo=UTC)


def _v2_feature():
    fixture_path = Path(__file__).parents[1] / "fixtures" / "gold_policy" / "real10y_v2_cases.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    payload = json.loads(json.dumps(fixture["base_payload"]))
    return build_feature_snapshot(payload)


def test_strategy_input_schema_carries_v2_feature_without_version_conversion() -> None:
    feature = _v2_feature()
    legacy = _snapshot()
    strategy_input = _policy_input(
        feature=feature,
        attribution=attribute_gold_price(legacy, legacy),
    )

    assert strategy_input.feature_snapshot == feature
    assert strategy_input.feature_snapshot.schema_version == "feature_snapshot.v2"
    assert strategy_input.feature_snapshot.snapshot_id.startswith("feature_snapshot.v2:")


def _ref(name: str = "fixture") -> dict[str, object]:
    return {
        "source": name,
        "reference": f"artifact://{name}",
        "retrieved_at": AS_OF,
    }


def _decision_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "decision_as_of": AS_OF,
        "analysis_state_id": f"analysis_state.v1:{'a' * 64}",
        "transition_decision_hash": "b" * 64,
        "feature_snapshot_id": "feature_snapshot.v1:current",
        "attribution_snapshot_ids": ("feature_snapshot.v1:previous", "feature_snapshot.v1:current"),
        "options_snapshot_id": "feature_snapshot.v1:current",
        "event_risk_snapshot_id": "event-risk:clear",
        "status": "NO_TRADE",
        "direction": "none",
        "stage": "pressure",
        "reason_codes": ("DATA_QUALITY_BLOCKED",),
        "no_trade_reason_code": "DATA_QUALITY_BLOCKED",
        "release_conditions": ("DATA_QUALITY_READY",),
        "review_triggers": ("ON_DATA_QUALITY_CHANGE",),
        "source_refs": (_ref(),),
    }
    payload.update(overrides)
    return payload


def _triggered_payload() -> dict[str, object]:
    trigger_state_id = f"key_level_read_model.v1:{'c' * 64}"
    invalidation_state_id = f"key_level_read_model.v1:{'e' * 64}"
    trigger_level_id = f"key_level.v1:{'d' * 64}"
    invalidation_level_id = f"key_level.v1:{'f' * 64}"
    return _decision_payload(
        status="LONG_RESEARCH_TRIGGERED",
        direction="long",
        no_trade_reason_code=None,
        release_conditions=(),
        review_triggers=(),
        reason_codes=("RESEARCH_TRIGGER_REQUIREMENTS_SATISFIED",),
        level_refs=(
            {
                "level_id": trigger_level_id,
                "state_id": trigger_state_id,
                "role": "trigger",
                "comparator": "above_or_equal",
                "lifecycle": "holding",
                "authority_status": "canonical_xauusd_validated",
                "quality_status": "accepted",
                "effective_from": AS_OF - timedelta(days=1),
                "expires_at": AS_OF + timedelta(days=1),
                "strategy_eligible_at_decision": True,
            },
            {
                "level_id": invalidation_level_id,
                "state_id": invalidation_state_id,
                "role": "invalidation",
                "comparator": "above_or_equal",
                "lifecycle": "active",
                "authority_status": "canonical_xauusd_validated",
                "quality_status": "accepted",
                "effective_from": AS_OF - timedelta(days=1),
                "expires_at": AS_OF + timedelta(days=1),
                "strategy_eligible_at_decision": True,
            },
        ),
        key_level_state_ids=(trigger_state_id, invalidation_state_id),
        trigger_level_ids=(trigger_level_id,),
        invalidation_level_ids=(invalidation_level_id,),
    )


def test_decision_is_content_addressed_immutable_and_order_normalized() -> None:
    first = build_strategy_decision(
        _decision_payload(
            reason_codes=("DATA_QUALITY_BLOCKED", "DETAIL"),
            review_triggers=("ON_NEXT_DAILY_CLOSE", "ON_DATA_QUALITY_CHANGE"),
            source_refs=(_ref("z"), _ref("a")),
        )
    )
    second = build_strategy_decision(
        _decision_payload(
            reason_codes=("DATA_QUALITY_BLOCKED", "DETAIL"),
            review_triggers=("ON_NEXT_DAILY_CLOSE", "ON_DATA_QUALITY_CHANGE"),
            source_refs=(_ref("a"), _ref("z")),
        )
    )

    assert first == second
    assert first.decision_id == f"strategy_decision.v1:{first.decision_hash}"
    reversed_refs = StrategyDecision.model_validate(
        {
            **first.model_dump(exclude={"source_refs"}),
            "source_refs": tuple(reversed(first.source_refs)),
        }
    )
    assert reversed_refs.decision_id == first.decision_id
    with pytest.raises(ValidationError):
        StrategyDecision.model_validate({**first.model_dump(), "decision_hash": "0" * 64})


@pytest.mark.parametrize(
    "changes",
    [
        {"direction": "long"},
        {"no_trade_reason_code": None},
        {"release_conditions": ()},
        {"review_triggers": ()},
        {"unexpected": True},
    ],
)
def test_no_trade_contract_requires_complete_closed_remediation(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        StrategyDecisionInput.model_validate({**_decision_payload(), **changes})


def test_triggered_decision_requires_level_lineage_and_is_never_an_order() -> None:
    trigger_level_id = f"key_level.v1:{'d' * 64}"
    decision = build_strategy_decision(_triggered_payload())

    assert decision.is_trade_instruction is False
    assert decision.trigger_level_ids == (trigger_level_id,)


def test_triggered_contract_rejects_missing_invalidation_lineage() -> None:
    payload = _triggered_payload()
    with pytest.raises(ValidationError):
        StrategyDecisionInput.model_validate(
            {
                **payload,
                "level_refs": payload["level_refs"][:1],
                "key_level_state_ids": payload["key_level_state_ids"][:1],
                "invalidation_level_ids": (),
            }
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("comparator", "below_or_equal"),
        ("lifecycle", "candidate"),
        ("authority_status", "candidate_only"),
        ("quality_status", "observe"),
        ("strategy_eligible_at_decision", False),
    ],
)
def test_triggered_contract_rejects_unqualified_trigger_lineage(field: str, value: object) -> None:
    payload = _triggered_payload()
    refs = [dict(ref) for ref in payload["level_refs"]]
    refs[0][field] = value
    with pytest.raises(ValidationError):
        StrategyDecisionInput.model_validate({**payload, "level_refs": refs})


def test_same_formal_level_cannot_be_both_trigger_and_invalidation() -> None:
    payload = _triggered_payload()
    refs = [dict(ref) for ref in payload["level_refs"]]
    refs[1]["level_id"] = refs[0]["level_id"]
    with pytest.raises(ValidationError):
        StrategyDecisionInput.model_validate(
            {
                **payload,
                "level_refs": refs,
                "invalidation_level_ids": payload["trigger_level_ids"],
            }
        )


def test_event_blackout_and_unavailable_options_have_strict_semantics() -> None:
    blackout = build_strategy_event_risk(
        {
            "as_of": AS_OF,
            "risk_status": "blackout",
            "active_event_ids": ("FOMC",),
            "window_start": AS_OF - timedelta(minutes=5),
            "window_end": AS_OF + timedelta(minutes=25),
            "next_review_at": AS_OF + timedelta(minutes=25),
            "quality_status": "accepted",
            "source_refs": (_ref("event-calendar"),),
        }
    )
    assert blackout.window_end > blackout.as_of
    with pytest.raises(ValidationError):
        type(blackout).model_validate(
            {
                **blackout.model_dump(),
                "risk_status": "watch",
            }
        )

    with pytest.raises(ValidationError):
        build_strategy_event_risk(
            {
                **blackout.model_dump(),
                "active_event_ids": (),
            }
        )
    with pytest.raises(ValidationError):
        build_strategy_options_regime(
            {
                "source_snapshot_id": "feature:1",
                "as_of": AS_OF,
                "regime": "unavailable",
                "directional_bias": "bullish",
                "freshness_status": "missing",
                "quality_status": "observe",
                "alignment_status": "unknown",
                "source_refs": (_ref("options"),),
            }
        )


def test_options_identity_is_content_addressed_and_order_independent() -> None:
    first = build_strategy_options_regime(
        {
            "source_snapshot_id": "feature:1",
            "as_of": AS_OF,
            "regime": "normal",
            "directional_bias": "neutral",
            "freshness_status": "fresh",
            "quality_status": "accepted",
            "alignment_status": "aligned",
            "source_refs": (_ref("z"), _ref("a")),
        }
    )
    second = build_strategy_options_regime(
        {
            **first.model_dump(exclude={"payload_hash", "snapshot_id", "source_refs"}),
            "source_refs": (_ref("a"), _ref("z")),
        }
    )

    assert first == second


def test_future_source_reference_is_rejected_by_formal_context() -> None:
    with pytest.raises(ValidationError):
        build_strategy_event_risk(
            {
                "as_of": AS_OF,
                "risk_status": "clear",
                "quality_status": "accepted",
                "source_refs": (
                    {
                        **_ref("future"),
                        "retrieved_at": AS_OF + timedelta(seconds=1),
                    },
                ),
            }
        )
