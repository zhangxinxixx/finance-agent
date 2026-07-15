from __future__ import annotations

import copy
from datetime import datetime, timezone

from apps.analysis.agents import AgentBias, AgentOutput, AgentStatus
from apps.analysis.agents.risk import analyze_risk


_CREATED_AT = datetime(2026, 5, 14, 10, 0, tzinfo=timezone.utc)


def _snapshot() -> dict:
    return {
        "snapshot_id": "XAUUSD:2026-05-14:analysis",
        "input_snapshot_ids": {
            "analysis_snapshot": "XAUUSD:2026-05-14:analysis",
            "macro": "macro:2026-05-14",
            "options": "cme-options:2026-05-14",
        },
        "metadata": {
            "symbol": "XAUUSD",
            "as_of": "2026-05-14",
            "unavailable_modules": ["news", "technical"],
        },
        "source_refs": [{"source": "analysis_snapshot", "snapshot_id": "XAUUSD:2026-05-14:analysis"}],
    }


def _agent_output(
    *,
    agent_name: str,
    module: str,
    bias: AgentBias,
    confidence: float,
    status: AgentStatus = AgentStatus.SUCCESS,
) -> AgentOutput:
    return AgentOutput(
        version="1.0",
        agent_name=agent_name,
        module=module,
        snapshot_id="XAUUSD:2026-05-14:analysis",
        input_snapshot_ids={"analysis_snapshot": "XAUUSD:2026-05-14:analysis", module: f"{module}:2026-05-14"},
        bias=bias,
        confidence=confidence,
        key_findings=[f"{module} finding"],
        risk_points=[f"{module} risk"],
        watchlist=[f"{module} watch"],
        invalid_conditions=[],
        summary=f"{module} summary",
        source_refs=[{"source": module, "ref": f"{module}:2026-05-14"}],
        status=status,
        created_at=_CREATED_AT,
    )


def test_macro_options_conflict_records_risk_note_and_mixed_bias():
    output = analyze_risk(
        _snapshot(),
        macro_output=_agent_output(
            agent_name="macro_liquidity_agent",
            module="macro",
            bias=AgentBias.BULLISH,
            confidence=0.72,
        ),
        options_output=_agent_output(
            agent_name="cme_options_agent",
            module="options",
            bias=AgentBias.BEARISH,
            confidence=0.68,
        ),
        created_at=_CREATED_AT,
    )

    assert isinstance(output, AgentOutput)
    assert output.agent_name == "risk_agent"
    assert output.module == "risk"
    assert output.status is AgentStatus.PARTIAL
    assert output.bias in {AgentBias.MIXED, AgentBias.NEUTRAL}
    assert any("conflict" in note.lower() or "diverge" in note.lower() for note in output.risk_points)
    assert 0.0 <= output.confidence <= 1.0
    assert output.input_payload["bullish_drivers"] == ["macro_liquidity_agent: macro finding"]
    assert output.input_payload["bearish_drivers"] == ["cme_options_agent: options finding"]


def test_unavailable_snapshot_modules_affect_confidence_and_invalid_conditions():
    output = analyze_risk(
        _snapshot(),
        macro_output=_agent_output(
            agent_name="macro_liquidity_agent",
            module="macro",
            bias=AgentBias.BULLISH,
            confidence=0.72,
        ),
        options_output=_agent_output(
            agent_name="cme_options_agent",
            module="options",
            bias=AgentBias.BULLISH,
            confidence=0.74,
        ),
        created_at=_CREATED_AT,
    )

    notes = output.risk_points + output.invalid_conditions
    assert output.status is AgentStatus.PARTIAL
    assert output.confidence < 0.8
    assert any("news" in note.lower() for note in notes)
    assert any("technical" in note.lower() for note in notes)


def test_both_prior_outputs_failed_or_unavailable_returns_low_confidence_partial_or_unavailable():
    output = analyze_risk(
        _snapshot(),
        macro_output=_agent_output(
            agent_name="macro_liquidity_agent",
            module="macro",
            bias=AgentBias.UNAVAILABLE,
            confidence=0.0,
            status=AgentStatus.UNAVAILABLE,
        ),
        options_output=_agent_output(
            agent_name="cme_options_agent",
            module="options",
            bias=AgentBias.UNAVAILABLE,
            confidence=0.0,
            status=AgentStatus.FAILED,
        ),
        created_at=_CREATED_AT,
    )

    assert output.status in {AgentStatus.PARTIAL, AgentStatus.UNAVAILABLE}
    assert output.bias is AgentBias.UNAVAILABLE
    assert output.confidence <= 0.25
    assert any("macro" in note.lower() for note in output.risk_points)
    assert any("options" in note.lower() for note in output.risk_points)


def test_missing_prior_outputs_returns_partial_or_unavailable_without_exception():
    output = analyze_risk(_snapshot(), macro_output=None, options_output=None, created_at=_CREATED_AT)

    assert output.status in {AgentStatus.PARTIAL, AgentStatus.UNAVAILABLE}
    assert output.bias is AgentBias.UNAVAILABLE
    assert output.confidence <= 0.25
    assert output.risk_points
    assert any("macro" in note.lower() for note in output.invalid_conditions + output.risk_points)
    assert any("options" in note.lower() for note in output.invalid_conditions + output.risk_points)


def test_dict_prior_outputs_are_accepted_and_output_schema_is_valid():
    macro = _agent_output(
        agent_name="macro_liquidity_agent",
        module="macro",
        bias=AgentBias.BULLISH,
        confidence=0.70,
    ).model_dump(mode="json")
    options = _agent_output(
        agent_name="cme_options_agent",
        module="options",
        bias=AgentBias.BULLISH,
        confidence=0.72,
    ).model_dump(mode="json")

    output = analyze_risk(_snapshot(), macro_output=macro, options_output=options, created_at=_CREATED_AT)

    assert isinstance(output, AgentOutput)
    assert output.status is AgentStatus.PARTIAL
    assert output.bias is AgentBias.BULLISH
    assert output.snapshot_id == "XAUUSD:2026-05-14:analysis"
    assert output.input_snapshot_ids == {
        "analysis_snapshot": "XAUUSD:2026-05-14:analysis",
        "macro": "macro:2026-05-14",
        "options": "options:2026-05-14",
    }
    assert output.source_refs == [
        {"source": "analysis_snapshot", "snapshot_id": "XAUUSD:2026-05-14:analysis"},
        {"source": "macro", "ref": "macro:2026-05-14"},
        {"source": "options", "ref": "options:2026-05-14"},
    ]


def test_analyze_risk_does_not_mutate_snapshot_or_prior_outputs():
    snapshot = _snapshot()
    macro = _agent_output(
        agent_name="macro_liquidity_agent",
        module="macro",
        bias=AgentBias.BULLISH,
        confidence=0.70,
    )
    options = _agent_output(
        agent_name="cme_options_agent",
        module="options",
        bias=AgentBias.BULLISH,
        confidence=0.72,
    ).model_dump(mode="json")
    before_snapshot = copy.deepcopy(snapshot)
    before_macro = macro.model_copy(deep=True)
    before_options = copy.deepcopy(options)

    analyze_risk(snapshot, macro_output=macro, options_output=options, created_at=_CREATED_AT)

    assert snapshot == before_snapshot
    assert macro == before_macro
    assert options == before_options


def test_analyze_risk_rejects_path_like_snapshot_without_file_reads():
    output = analyze_risk(
        "storage/features/snapshots/XAUUSD/example/analysis_snapshot.json",  # type: ignore[arg-type]
        macro_output=None,
        options_output=None,
        created_at=_CREATED_AT,
    )

    assert output.status is AgentStatus.UNAVAILABLE
    assert output.bias is AgentBias.UNAVAILABLE
    assert output.confidence == 0.0
    assert "analysis_snapshot" not in output.input_snapshot_ids
    assert any("file/path reads" in note or "文件/路径" in note for note in output.invalid_conditions)


def test_bias_normalization_accepts_textual_prior_bias_aliases():
    macro = _agent_output(
        agent_name="macro_liquidity_agent",
        module="macro",
        bias=AgentBias.NEUTRAL,
        confidence=0.76,
    ).model_dump(mode="json")
    macro["bias"] = "supportive"
    options = _agent_output(
        agent_name="cme_options_agent",
        module="options",
        bias=AgentBias.NEUTRAL,
        confidence=0.74,
    ).model_dump(mode="json")
    options["bias"] = "constructive"

    output = analyze_risk({**_snapshot(), "metadata": {"unavailable_modules": []}}, macro_output=macro, options_output=options, created_at=_CREATED_AT)

    assert output.status is AgentStatus.SUCCESS
    assert output.bias is AgentBias.BULLISH


def test_status_matrix_both_prior_outputs_unavailable_overrides_missing_snapshot_modules():
    output = analyze_risk(
        _snapshot(),
        macro_output=_agent_output(
            agent_name="macro_liquidity_agent",
            module="macro",
            bias=AgentBias.UNAVAILABLE,
            confidence=0.0,
            status=AgentStatus.UNAVAILABLE,
        ),
        options_output=_agent_output(
            agent_name="cme_options_agent",
            module="options",
            bias=AgentBias.UNAVAILABLE,
            confidence=0.0,
            status=AgentStatus.FAILED,
        ),
        created_at=_CREATED_AT,
    )

    assert output.status is AgentStatus.UNAVAILABLE
    assert output.confidence == 0.0


def test_evidence_trace_includes_prior_status_bias_and_confidence():
    output = analyze_risk(
        {**_snapshot(), "metadata": {"unavailable_modules": []}},
        macro_output=_agent_output(
            agent_name="macro_liquidity_agent",
            module="macro",
            bias=AgentBias.BULLISH,
            confidence=0.66,
        ),
        options_output=_agent_output(
            agent_name="cme_options_agent",
            module="options",
            bias=AgentBias.BULLISH,
            confidence=0.71,
        ),
        created_at=_CREATED_AT,
    )

    evidence = "\n".join(output.key_findings)
    assert "macro" in evidence.lower()
    assert "bullish" in evidence.lower()
    assert "0.66" in evidence
    assert "options" in evidence.lower()
    assert "0.71" in evidence


def test_risk_agent_does_not_emit_trade_entry_stop_or_target_levels():
    output = analyze_risk(
        {**_snapshot(), "metadata": {"unavailable_modules": []}},
        macro_output=_agent_output(
            agent_name="macro_liquidity_agent",
            module="macro",
            bias=AgentBias.BULLISH,
            confidence=0.70,
        ),
        options_output=_agent_output(
            agent_name="cme_options_agent",
            module="options",
            bias=AgentBias.BULLISH,
            confidence=0.72,
        ),
        created_at=_CREATED_AT,
    )

    text = "\n".join(output.key_findings + output.risk_points + output.watchlist + output.invalid_conditions + [output.summary]).lower()
    assert "entry" not in text
    assert "stop" not in text
    assert "target" not in text
