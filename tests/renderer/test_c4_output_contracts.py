from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from apps.analysis.agents import AgentBias, AgentOutput
from apps.analysis.strategy.schemas import StrategyCardOutput
from apps.renderer.contracts import FinalReportOutput, ReportSection
from tests.fixtures.c4_agent_outputs import coordinator_output_payload

_CREATED_AT = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)


def _coordinator_output() -> AgentOutput:
    return AgentOutput.model_validate(coordinator_output_payload(created_at=_CREATED_AT))


def _final_report_payload() -> dict:
    return {
        "version": "1.0",
        "asset": "XAUUSD",
        "trade_date": "2026-05-14",
        "run_id": "run-c4-contract",
        "snapshot_id": "XAUUSD:2026-05-14:analysis",
        "input_snapshot_ids": {
            "analysis_snapshot": "XAUUSD:2026-05-14:analysis",
            "coordinator": "XAUUSD:2026-05-14:analysis",
        },
        "source_refs": [],
        "coordinator_output": _coordinator_output(),
        "sections": [
            {
                "title": "Coordinator summary",
                "body": "Bullish but limited by missing technical/news/positioning inputs.",
                "source_refs": [],
            }
        ],
        "risk_disclosures": ["Research output only; not investment advice or trade execution."],
        "created_at": _CREATED_AT,
    }


def _strategy_card_payload() -> dict:
    return {
        "version": "1.0",
        "asset": "XAUUSD",
        "trade_date": "2026-05-14",
        "run_id": "run-c4-contract",
        "bias": "bullish",
        "confidence": 0.61,
        "scenario_summary": "Macro and options are aligned, with confidence capped by missing inputs.",
        "key_levels_from_options": ["Call wall near 2450", "Put support near 2350"],
        "risk_points": ["Technical, news, and positioning inputs are unavailable."],
        "invalid_conditions": ["Invalidate if analysis snapshot lineage changes."],
        "watchlist": ["DGS10", "CME option walls"],
        "source_refs": [],
        "input_snapshot_ids": {
            "analysis_snapshot": "XAUUSD:2026-05-14:analysis",
            "coordinator": "XAUUSD:2026-05-14:analysis",
        },
        "created_at": _CREATED_AT,
        "is_trade_instruction": False,
    }


def test_final_report_contract_accepts_required_fields_and_serializes_to_json():
    report = FinalReportOutput.model_validate(_final_report_payload())

    assert report.version == "1.0"
    assert report.asset == "XAUUSD"
    assert report.trade_date == "2026-05-14"
    assert report.run_id == "run-c4-contract"
    assert report.snapshot_id == "XAUUSD:2026-05-14:analysis"
    assert report.input_snapshot_ids["analysis_snapshot"] == "XAUUSD:2026-05-14:analysis"
    assert report.input_snapshot_ids["coordinator"] == "XAUUSD:2026-05-14:analysis"
    assert report.source_refs == []
    assert report.coordinator_output.agent_name == "coordinator_agent"
    assert report.sections == [
        ReportSection(
            title="Coordinator summary",
            body="Bullish but limited by missing technical/news/positioning inputs.",
            source_refs=[],
        )
    ]
    assert report.risk_disclosures == ["Research output only; not investment advice or trade execution."]
    assert report.model_dump(mode="json")["coordinator_output"]["status"] == "partial"


def test_strategy_card_contract_is_explicitly_not_trade_instruction():
    card = StrategyCardOutput.model_validate(_strategy_card_payload())

    assert card.bias is AgentBias.BULLISH
    assert card.confidence == 0.61
    assert card.source_refs == []
    assert card.input_snapshot_ids["analysis_snapshot"] == "XAUUSD:2026-05-14:analysis"
    assert card.input_snapshot_ids["coordinator"] == "XAUUSD:2026-05-14:analysis"
    assert card.is_trade_instruction is False
    assert card.model_dump(mode="json")["is_trade_instruction"] is False


@pytest.mark.parametrize(
    ("model_factory", "payload_factory", "field"),
    [
        (FinalReportOutput, _final_report_payload, "version"),
        (FinalReportOutput, _final_report_payload, "source_refs"),
        (FinalReportOutput, _final_report_payload, "input_snapshot_ids"),
        (FinalReportOutput, _final_report_payload, "coordinator_output"),
        (StrategyCardOutput, _strategy_card_payload, "version"),
        (StrategyCardOutput, _strategy_card_payload, "source_refs"),
        (StrategyCardOutput, _strategy_card_payload, "input_snapshot_ids"),
        (StrategyCardOutput, _strategy_card_payload, "is_trade_instruction"),
    ],
)
def test_output_contracts_validate_required_fields(model_factory, payload_factory, field: str):
    payload = payload_factory()
    payload.pop(field)

    with pytest.raises(ValidationError, match=field):
        model_factory.model_validate(payload)


@pytest.mark.parametrize("model_factory,payload_factory", [(FinalReportOutput, _final_report_payload), (StrategyCardOutput, _strategy_card_payload)])
def test_input_snapshot_ids_must_include_analysis_snapshot_and_coordinator_lineage(model_factory, payload_factory):
    payload = payload_factory()
    payload["input_snapshot_ids"] = {"analysis_snapshot": "XAUUSD:2026-05-14:analysis"}

    with pytest.raises(ValidationError, match="coordinator"):
        model_factory.model_validate(payload)


def test_strategy_card_rejects_trade_instruction_true():
    payload = _strategy_card_payload()
    payload["is_trade_instruction"] = True

    with pytest.raises(ValidationError, match="is_trade_instruction"):
        StrategyCardOutput.model_validate(payload)


def test_strategy_card_rejects_unknown_bias():
    payload = _strategy_card_payload()
    payload["bias"] = "execute_long"

    with pytest.raises(ValidationError, match="bias"):
        StrategyCardOutput.model_validate(payload)
