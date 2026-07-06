from __future__ import annotations

import copy
from datetime import datetime, timezone

from apps.analysis.agents import AgentBias, AgentOutput, AgentStatus
from apps.analysis.agents.coordinator import coordinate_agent_outputs

_CREATED_AT = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)


def _snapshot(*, unavailable_modules: list[str] | None = None) -> dict:
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
            "unavailable_modules": unavailable_modules or [],
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
    source_ref: dict | None = None,
    risk_points: list[str] | None = None,
    invalid_conditions: list[str] | None = None,
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
        risk_points=risk_points or [f"{module} risk"],
        watchlist=[f"{module} watch"],
        invalid_conditions=invalid_conditions or [],
        summary=f"{module} summary",
        source_refs=[source_ref or {"source": module, "ref": f"{module}:2026-05-14"}],
        status=status,
        created_at=_CREATED_AT,
    )


def _macro(bias: AgentBias = AgentBias.BULLISH, confidence: float = 0.72) -> AgentOutput:
    return _agent_output(agent_name="macro_liquidity_agent", module="macro", bias=bias, confidence=confidence)


def _options(bias: AgentBias = AgentBias.BULLISH, confidence: float = 0.74) -> AgentOutput:
    return _agent_output(agent_name="cme_options_agent", module="options", bias=bias, confidence=confidence)


def _risk(bias: AgentBias = AgentBias.BULLISH, confidence: float = 0.68) -> AgentOutput:
    return _agent_output(agent_name="risk_agent", module="risk", bias=bias, confidence=confidence)


def _technical(bias: AgentBias = AgentBias.BULLISH, confidence: float = 0.65) -> AgentOutput:
    return _agent_output(agent_name="technical_agent", module="technical", bias=bias, confidence=confidence)


def _positioning(bias: AgentBias = AgentBias.BEARISH, confidence: float = 0.55) -> AgentOutput:
    return _agent_output(agent_name="positioning_agent", module="positioning", bias=bias, confidence=confidence)


def _news(bias: AgentBias = AgentBias.NEUTRAL, confidence: float = 0.65) -> AgentOutput:
    return _agent_output(agent_name="news_agent", module="news", bias=bias, confidence=confidence)


def test_aligned_macro_options_outputs_schema_valid_final_view():
    output = coordinate_agent_outputs(
        _snapshot(),
        macro_output=_macro(),
        options_output=_options(),
        risk_output=_risk(),
        technical_output=_technical(),
        positioning_output=_positioning(),
        news_output=_news(),
        created_at=_CREATED_AT,
    )

    assert isinstance(output, AgentOutput)
    assert output.agent_name == "coordinator_agent"
    assert output.module == "coordinator"
    assert output.snapshot_id == "XAUUSD:2026-05-14:analysis"
    assert output.status is AgentStatus.SUCCESS
    assert output.bias is AgentBias.BULLISH
    assert 0.0 <= output.confidence <= 1.0
    assert any("macro" in finding.lower() for finding in output.key_findings)
    assert any("options" in finding.lower() for finding in output.key_findings)
    assert output.input_snapshot_ids["risk"] == "risk:2026-05-14"


def test_conflicting_macro_options_exposes_conflict_and_caps_confidence():
    output = coordinate_agent_outputs(
        _snapshot(),
        macro_output=_macro(AgentBias.BULLISH, 0.82),
        options_output=_options(AgentBias.BEARISH, 0.80),
        risk_output=_risk(AgentBias.MIXED, 0.62),
        created_at=_CREATED_AT,
    )

    assert output.status is AgentStatus.PARTIAL
    assert output.bias in {AgentBias.MIXED, AgentBias.NEUTRAL}
    assert output.confidence <= 0.55
    assert any("conflict" in note.lower() or "冲突" in note for note in output.risk_points + output.invalid_conditions)


def test_coordinator_attaches_confidence_kernel_debug_payload():
    options = _options(AgentBias.BEARISH, 0.80)
    options.evidence_items.append(
        {
            "factor": "option_wall",
            "direction": "bearish",
            "strength": 0.7,
            "confidence": 0.8,
            "source_tier": "exchange",
        }
    )
    output = coordinate_agent_outputs(
        _snapshot(unavailable_modules=["technical"]),
        macro_output=_macro(AgentBias.BULLISH, 0.82),
        options_output=options,
        risk_output=_risk(AgentBias.MIXED, 0.62),
        created_at=_CREATED_AT,
    )

    assert output.input_payload is not None
    kernel = output.input_payload["confidence_kernel"]
    assert kernel["version"] == "1.0"
    assert kernel["overall"] <= 0.55
    assert "macro_options_conflict" in kernel["caps"]
    assert "technical_unavailable" in kernel["caps"]
    assert any(item.get("factor") == "option_wall" for item in output.evidence_items)


def test_missing_risk_output_returns_partial_without_exception():
    output = coordinate_agent_outputs(
        _snapshot(),
        macro_output=_macro(),
        options_output=_options(),
        risk_output=None,
        created_at=_CREATED_AT,
    )

    assert output.status is AgentStatus.PARTIAL
    assert output.bias is AgentBias.BULLISH
    assert output.confidence < 0.75
    assert any("risk" in note.lower() for note in output.risk_points + output.invalid_conditions)


def test_source_refs_merge_and_deduplicate_across_inputs():
    shared = {"source": "shared", "ref": "duplicate"}
    output = coordinate_agent_outputs(
        {**_snapshot(), "source_refs": [shared]},
        macro_output=_agent_output(
            agent_name="macro_liquidity_agent",
            module="macro",
            bias=AgentBias.BULLISH,
            confidence=0.70,
            source_ref=shared,
        ),
        options_output=_agent_output(
            agent_name="cme_options_agent",
            module="options",
            bias=AgentBias.BULLISH,
            confidence=0.72,
            source_ref={"source": "options", "ref": "unique"},
        ),
        risk_output=_agent_output(
            agent_name="risk_agent",
            module="risk",
            bias=AgentBias.BULLISH,
            confidence=0.66,
            source_ref=shared,
        ),
        created_at=_CREATED_AT,
    )

    assert output.source_refs == [shared, {"source": "options", "ref": "unique"}]


def test_unavailable_technical_news_positioning_prevents_precise_entry_strategy_and_lowers_confidence():
    output = coordinate_agent_outputs(
        _snapshot(unavailable_modules=["technical", "news", "positioning"]),
        macro_output=_macro(AgentBias.BULLISH, 0.82),
        options_output=_options(AgentBias.BULLISH, 0.80),
        risk_output=_risk(AgentBias.BULLISH, 0.78),
        created_at=_CREATED_AT,
    )

    combined_text = " ".join(output.key_findings + output.risk_points + output.invalid_conditions + [output.summary]).lower()
    assert output.status is AgentStatus.PARTIAL
    assert output.confidence <= 0.65
    assert "technical" in combined_text
    assert "news" in combined_text
    assert "positioning" in combined_text
    assert "entry" not in combined_text
    assert "stop" not in combined_text
    assert "target" not in combined_text


def test_coordinate_agent_outputs_accepts_dict_inputs_and_does_not_mutate():
    snapshot = _snapshot()
    macro = _macro().model_dump(mode="json")
    options = _options().model_dump(mode="json")
    risk = _risk().model_dump(mode="json")
    before_snapshot = copy.deepcopy(snapshot)
    before_macro = copy.deepcopy(macro)
    before_options = copy.deepcopy(options)
    before_risk = copy.deepcopy(risk)

    output = coordinate_agent_outputs(
        snapshot,
        macro_output=macro,
        options_output=options,
        risk_output=risk,
        created_at=_CREATED_AT,
    )

    assert output.status is AgentStatus.PARTIAL  # missing technical/positioning = partial
    assert snapshot == before_snapshot
    assert macro == before_macro
    assert options == before_options
    assert risk == before_risk


def test_coordinator_rejects_path_like_snapshot_without_file_reads():
    output = coordinate_agent_outputs(
        "storage/features/snapshots/XAUUSD/example/analysis_snapshot.json",  # type: ignore[arg-type]
        macro_output=None,
        options_output=None,
        risk_output=None,
        created_at=_CREATED_AT,
    )

    assert output.status is AgentStatus.UNAVAILABLE
    assert output.bias is AgentBias.UNAVAILABLE
    assert output.confidence == 0.0
    assert "analysis_snapshot" not in output.input_snapshot_ids
    assert any("file/path reads" in note or "文件/路径" in note for note in output.invalid_conditions)
