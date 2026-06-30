from __future__ import annotations

from datetime import datetime, timezone

from apps.analysis.agents.schemas import AgentBias, AgentOutput, AgentStatus
from apps.analysis.confidence import ConfidenceKernel, compute_confidence_kernel

_CREATED_AT = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)


def _agent_output(*, module: str, bias: AgentBias, confidence: float) -> AgentOutput:
    return AgentOutput(
        version="1.0",
        agent_name=f"{module}_agent",
        module=module,
        snapshot_id=f"{module}:2026-05-14",
        input_snapshot_ids={module: f"{module}:2026-05-14"},
        bias=bias,
        confidence=confidence,
        key_findings=[f"{module} finding"],
        risk_points=[],
        watchlist=[],
        invalid_conditions=[],
        summary=f"{module} summary",
        source_refs=[{"source": module, "source_ref": f"{module}:2026-05-14"}],
        status=AgentStatus.SUCCESS,
        created_at=_CREATED_AT,
    )


def test_confidence_kernel_is_deterministic_for_same_inputs() -> None:
    market_state = {
        "snapshot_id": "XAUUSD:2026-05-14",
        "macro": {"status": "available"},
        "options": {"status": "available"},
        "technical": {"status": "available"},
    }
    evidence_items = [
        {"source_type": "official", "status": "confirmed", "bias": "bullish"},
        {"source_type": "structured", "status": "confirmed", "bias": "bullish"},
    ]
    agent_outputs = [
        _agent_output(module="macro", bias=AgentBias.BULLISH, confidence=0.78),
        _agent_output(module="options", bias=AgentBias.BULLISH, confidence=0.74),
    ]

    first = compute_confidence_kernel(
        market_state=market_state,
        evidence_items=evidence_items,
        agent_outputs=agent_outputs,
    )
    second = compute_confidence_kernel(
        market_state=market_state,
        evidence_items=evidence_items,
        agent_outputs=agent_outputs,
    )

    assert isinstance(first, ConfidenceKernel)
    assert first == second
    assert first.overall > 0.65
    assert first.caps == []


def test_confidence_kernel_caps_macro_options_directional_conflict() -> None:
    kernel = compute_confidence_kernel(
        market_state={
            "snapshot_id": "XAUUSD:2026-05-14",
            "macro": {"status": "available"},
            "options": {"status": "available"},
            "technical": {"status": "available"},
        },
        evidence_items=[
            {"source_type": "official", "status": "confirmed", "bias": "bullish"},
            {"source_type": "structured", "status": "confirmed", "bias": "bearish"},
        ],
        agent_outputs=[
            _agent_output(module="macro", bias=AgentBias.BULLISH, confidence=0.86),
            _agent_output(module="options", bias=AgentBias.BEARISH, confidence=0.84),
        ],
    )

    assert kernel.overall <= 0.55
    assert "macro_options_conflict" in kernel.caps
    assert kernel.cross_source_confidence < 0.65
    assert any("macro/options" in reason for reason in kernel.reasons)


def test_confidence_kernel_caps_missing_technical_data() -> None:
    kernel = compute_confidence_kernel(
        market_state={
            "snapshot_id": "XAUUSD:2026-05-14",
            "macro": {"status": "available"},
            "options": {"status": "available"},
            "technical": {"status": "unavailable", "reason": "input_not_available"},
        },
        evidence_items=[
            {"source_type": "official", "status": "confirmed", "bias": "bullish"},
            {"source_type": "structured", "status": "confirmed", "bias": "bullish"},
        ],
        agent_outputs=[
            _agent_output(module="macro", bias=AgentBias.BULLISH, confidence=0.84),
            _agent_output(module="options", bias=AgentBias.BULLISH, confidence=0.82),
        ],
    )

    assert kernel.data_confidence < 1.0
    assert kernel.overall <= 0.65
    assert "technical_unavailable" in kernel.caps
    assert any("technical" in reason for reason in kernel.reasons)
