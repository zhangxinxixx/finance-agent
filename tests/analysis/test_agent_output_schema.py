from __future__ import annotations

import json
from datetime import datetime

import pytest
from pydantic import ValidationError

from apps.analysis.agents import AcceptedStateConclusion, AgentBias, AgentOutput, AgentStatus


def _valid_payload() -> dict:
    return {
        "version": "1.0",
        "agent_name": "macro_pseudo_agent",
        "module": "macro",
        "snapshot_id": "XAUUSD:2026-05-14:test-run",
        "input_snapshot_ids": {"analysis_snapshot": "XAUUSD:2026-05-14:test-run"},
        "bias": "neutral",
        "confidence": 0.5,
        "key_findings": ["real yields are stable"],
        "risk_points": ["CPI release may invalidate the setup"],
        "watchlist": ["DGS10", "T10YIE"],
        "invalid_conditions": ["analysis snapshot is stale"],
        "summary": "Macro backdrop is neutral.",
        "source_refs": [],
        "status": "success",
        "created_at": "2026-05-14T10:00:00+00:00",
    }


def test_agent_output_accepts_required_schema_and_serializes_to_json():
    output = AgentOutput.model_validate(_valid_payload())

    assert output.version == "1.0"
    assert output.agent_name == "macro_pseudo_agent"
    assert output.module == "macro"
    assert output.snapshot_id == "XAUUSD:2026-05-14:test-run"
    assert output.input_snapshot_ids == {"analysis_snapshot": "XAUUSD:2026-05-14:test-run"}
    assert output.bias is AgentBias.NEUTRAL
    assert output.confidence == 0.5
    assert output.key_findings == ["real yields are stable"]
    assert output.risk_points == ["CPI release may invalidate the setup"]
    assert output.watchlist == ["DGS10", "T10YIE"]
    assert output.invalid_conditions == ["analysis snapshot is stale"]
    assert output.invalidation_conditions == ["analysis snapshot is stale"]
    assert output.summary == "Macro backdrop is neutral."
    assert output.source_refs == []
    assert output.evidence_items == []
    assert output.status is AgentStatus.SUCCESS
    assert isinstance(output.created_at, datetime)

    encoded = output.model_dump(mode="json")
    assert encoded["bias"] == "neutral"
    assert encoded["status"] == "success"
    assert encoded["source_refs"] == []
    assert encoded["evidence_items"] == []
    json.dumps(encoded, ensure_ascii=False)


def test_agent_output_keeps_legacy_payload_without_typed_conclusion_readable():
    output = AgentOutput.model_validate(_valid_payload())

    assert output.accepted_state_conclusion is None


@pytest.mark.parametrize(
    ("direction", "state_bias", "direction_tilt"),
    [
        (AgentBias.MIXED, "mixed_bullish", "bullish"),
        (AgentBias.NEUTRAL, "neutral_bearish", "bearish"),
        (AgentBias.BULLISH, "strong_bullish", None),
    ],
)
def test_agent_output_accepts_coarse_direction_with_known_fine_state_bias(
    direction: AgentBias,
    state_bias: str,
    direction_tilt: str | None,
):
    payload = _valid_payload()
    payload["bias"] = direction.value
    payload["accepted_state_conclusion"] = AcceptedStateConclusion(
        direction=direction,
        direction_tilt=direction_tilt,
        state_bias=state_bias,
        market_stage="direction_decision",
        core_thesis="Typed state semantics.",
        dominant_drivers=[],
    ).model_dump(mode="json")

    output = AgentOutput.model_validate(payload)

    assert output.accepted_state_conclusion is not None
    assert output.accepted_state_conclusion.state_bias == state_bias


def test_accepted_state_conclusion_rejects_unknown_or_contradictory_bias():
    with pytest.raises(ValidationError, match="outside the accepted state vocabulary"):
        AcceptedStateConclusion(
            direction=AgentBias.MIXED,
            state_bias="future_unknown_bias",
            market_stage="direction_decision",
            core_thesis="Unknown semantics.",
        )
    payload = _valid_payload()
    payload["accepted_state_conclusion"] = {
        "direction": "bullish",
        "state_bias": "strong_bullish",
        "market_stage": "direction_decision",
        "core_thesis": "Contradicts output bias.",
    }
    with pytest.raises(ValidationError, match="contradicts AgentOutput.bias"):
        AgentOutput.model_validate(payload)


def test_agent_output_projects_new_invalidation_contract_to_legacy_field():
    payload = _valid_payload()
    payload["invalid_conditions"] = []
    payload["invalidation_conditions"] = ["Invalidate if real yields reverse."]
    payload["active_blockers"] = ["canonical candle is unavailable"]
    payload["data_gaps"] = [
        {"code": "missing_xauusd_price", "message": "Canonical XAUUSD price is missing.", "severity": "p0"}
    ]
    payload["review_triggers"] = ["macro_options_conflict"]

    output = AgentOutput.model_validate(payload)

    assert output.invalid_conditions == ["Invalidate if real yields reverse."]
    assert output.invalidation_conditions == output.invalid_conditions
    assert output.active_blockers == ["canonical candle is unavailable"]
    assert output.data_gaps[0].code == "missing_xauusd_price"
    assert output.review_triggers == ["macro_options_conflict"]


def test_agent_output_accepts_structured_evidence_items():
    payload = _valid_payload()
    payload["evidence_items"] = [
        {
            "factor": "option_wall",
            "direction": "bullish",
            "strength": 0.7,
            "confidence": 0.82,
            "freshness": 1.0,
            "source_tier": "exchange",
            "invalidation_hint": "Top wall migrates.",
        }
    ]

    output = AgentOutput.model_validate(payload)

    assert output.evidence_items[0]["factor"] == "option_wall"
    assert output.evidence_items[0]["source_tier"] == "exchange"


@pytest.mark.parametrize("confidence", [0.0, 1.0])
def test_agent_output_accepts_confidence_boundaries(confidence: float):
    payload = _valid_payload()
    payload["confidence"] = confidence

    output = AgentOutput.model_validate(payload)

    assert output.confidence == confidence


@pytest.mark.parametrize(
    ("status", "bias"),
    [
        ("unavailable", "unavailable"),
        ("failed", "unavailable"),
    ],
)
def test_agent_output_allows_unavailable_or_failed_without_normal_conclusions(status: str, bias: str):
    payload = _valid_payload()
    payload.update(
        {
            "bias": bias,
            "confidence": 0.0,
            "key_findings": [],
            "risk_points": [],
            "watchlist": [],
            "invalid_conditions": ["analysis snapshot is missing"],
            "summary": "",
            "source_refs": [],
            "status": status,
        }
    )

    output = AgentOutput.model_validate(payload)

    assert output.status.value == status
    assert output.bias is AgentBias.UNAVAILABLE
    assert output.key_findings == []
    assert output.summary == ""


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_agent_output_rejects_confidence_outside_zero_to_one(confidence: float):
    payload = _valid_payload()
    payload["confidence"] = confidence

    with pytest.raises(ValidationError, match="confidence"):
        AgentOutput.model_validate(payload)


@pytest.mark.parametrize(
    "field,value",
    [
        ("bias", "sideways"),
        ("status", "done"),
    ],
)
def test_agent_output_rejects_unknown_enums(field: str, value: str):
    payload = _valid_payload()
    payload[field] = value

    with pytest.raises(ValidationError, match=field):
        AgentOutput.model_validate(payload)


@pytest.mark.parametrize("field", ["snapshot_id", "input_snapshot_ids", "source_refs"])
def test_agent_output_requires_snapshot_ids_and_source_refs(field: str):
    payload = _valid_payload()
    payload.pop(field)

    with pytest.raises(ValidationError, match=field):
        AgentOutput.model_validate(payload)


def test_agent_output_requires_input_snapshot_ids_to_be_dict():
    payload = _valid_payload()
    payload["input_snapshot_ids"] = ["XAUUSD:2026-05-14:test-run"]

    with pytest.raises(ValidationError, match="input_snapshot_ids"):
        AgentOutput.model_validate(payload)


def test_agent_output_exposes_expected_enums():
    assert [item.value for item in AgentBias] == ["bullish", "bearish", "neutral", "mixed", "unavailable"]
    assert [item.value for item in AgentStatus] == ["success", "partial", "unavailable", "failed"]
