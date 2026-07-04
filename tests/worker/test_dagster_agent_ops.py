from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

from dagster import build_op_context

from apps.analysis.agents.schemas import AgentBias, AgentOutput, AgentStatus
from dagster_finance.ops.agents import strategy_card_op

_CREATED_AT = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)


def _snapshot() -> dict[str, object]:
    return {
        "snapshot_id": "XAUUSD:2026-05-14:analysis",
        "run_id": "run-card-test",
        "input_snapshot_ids": {
            "analysis_snapshot": "XAUUSD:2026-05-14:analysis",
            "macro": "macro:2026-05-14",
            "options": "cme-options:2026-05-14",
        },
        "metadata": {
            "symbol": "XAUUSD",
            "as_of": "2026-05-14",
            "unavailable_modules": [],
        },
        "source_refs": [{"source": "analysis_snapshot", "snapshot_id": "XAUUSD:2026-05-14:analysis"}],
    }


def _agent_output(*, module: str, agent_name: str) -> AgentOutput:
    return AgentOutput(
        version="1.0",
        agent_name=agent_name,
        module=module,
        snapshot_id=f"{module}:2026-05-14",
        input_snapshot_ids={module: f"{module}:2026-05-14"},
        bias=AgentBias.BULLISH,
        confidence=0.70,
        key_findings=["Options prior finding: Call wall near 2450"],
        risk_points=[f"{module} risk point"],
        watchlist=["DXY"],
        invalid_conditions=[f"{module} invalid condition"],
        summary=f"{module} summary",
        source_refs=[{"source": module, "snapshot_id": f"{module}:2026-05-14"}],
        status=AgentStatus.SUCCESS,
        created_at=_CREATED_AT,
    )


def test_strategy_card_op_coerces_dagster_dict_payloads() -> None:
    coordinator_output = _agent_output(module="coordinator", agent_name="coordinator_agent")
    risk_output = _agent_output(module="risk", agent_name="risk_agent")

    with patch("apps.output.final_report.write_strategy_card", return_value={"ok": True}) as write_mock:
        result = strategy_card_op(
            build_op_context(resources={"db_session": object()}),
            snapshot=_snapshot(),
            coordinator_output=coordinator_output.model_dump(mode="json"),
            risk_output=risk_output.model_dump(mode="json"),
        )

    assert result == {"ok": True}
    card = write_mock.call_args.kwargs["card"]
    assert card.bias == AgentBias.BULLISH
    assert card.confidence == 0.70
    assert any("Call wall near 2450" in level for level in card.key_levels_from_options)
