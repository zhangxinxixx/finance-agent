from __future__ import annotations

from datetime import datetime, timezone

from apps.analysis.agents import AgentBias, AgentOutput, AgentStatus
from apps.renderer.markdown.final_report import render_final_report_markdown

_CREATED_AT = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
_REQUIRED_SECTIONS = [
    "# XAUUSD 盘前综合报告",
    "## 数据口径",
    "## 协调器总结",
    "## 宏观流动性视图",
    "## CME 期权结构视图",
    "## 风险审计",
    "## 宏观事件风险视图",
    "## 无效条件",
    "## 观察列表",
    "## 数据来源",
    "## 免责声明",
]


def _snapshot() -> dict:
    return {
        "snapshot_id": "XAUUSD:2026-05-14:analysis",
        "input_snapshot_ids": {
            "analysis_snapshot": "XAUUSD:2026-05-14:analysis",
            "macro": "macro:2026-05-14",
            "options": "cme-options:2026-05-14",
        },
        "metadata": {"symbol": "XAUUSD", "as_of": "2026-05-14", "unavailable_modules": []},
        "source_refs": [{"source": "analysis_snapshot", "snapshot_id": "XAUUSD:2026-05-14:analysis"}],
    }


def _agent_output(
    *,
    agent_name: str,
    module: str,
    bias: AgentBias,
    confidence: float,
    status: AgentStatus = AgentStatus.SUCCESS,
    key_findings: list[str] | None = None,
    risk_points: list[str] | None = None,
    watchlist: list[str] | None = None,
    invalid_conditions: list[str] | None = None,
    summary: str | None = None,
) -> AgentOutput:
    return AgentOutput(
        version="1.0",
        agent_name=agent_name,
        module=module,
        snapshot_id="XAUUSD:2026-05-14:analysis",
        input_snapshot_ids={"analysis_snapshot": "XAUUSD:2026-05-14:analysis", module: f"{module}:2026-05-14"},
        bias=bias,
        confidence=confidence,
        key_findings=key_findings or [f"{module} finding"],
        risk_points=risk_points or [f"{module} risk"],
        watchlist=watchlist or [f"{module} watch"],
        invalid_conditions=invalid_conditions or [],
        summary=summary or f"{module} summary",
        source_refs=[{"source": module, "ref": f"{module}:2026-05-14"}],
        status=status,
        created_at=_CREATED_AT,
    )


def _macro() -> AgentOutput:
    return _agent_output(
        agent_name="macro_liquidity_agent",
        module="macro",
        bias=AgentBias.BULLISH,
        confidence=0.72,
        key_findings=["Real yields fell and DXY softened."],
        watchlist=["DGS10", "DXY"],
        summary="Macro liquidity is supportive but not sufficient for execution.",
    )


def _options() -> AgentOutput:
    return _agent_output(
        agent_name="cme_options_agent",
        module="options",
        bias=AgentBias.BULLISH,
        confidence=0.70,
        key_findings=["Call wall near 4300 and put support near 4100."],
        watchlist=["gamma zero", "option walls"],
        summary="CME options structure is constructive with capped confidence.",
    )


def _risk(status: AgentStatus = AgentStatus.PARTIAL) -> AgentOutput:
    return _agent_output(
        agent_name="risk_agent",
        module="risk",
        bias=AgentBias.BULLISH,
        confidence=0.62,
        status=status,
        risk_points=["Technical/news/positioning inputs are unavailable."],
        invalid_conditions=["Invalidate if snapshot lineage changes."],
        summary="Risk audit caps confidence because important modules are missing.",
    )


def _coordinator(status: AgentStatus = AgentStatus.PARTIAL) -> AgentOutput:
    return _agent_output(
        agent_name="coordinator_agent",
        module="coordinator",
        bias=AgentBias.BULLISH,
        confidence=0.61,
        status=status,
        key_findings=["Macro and options are aligned; risk caps final confidence."],
        watchlist=["DGS10", "CME option walls"],
        invalid_conditions=["No precise trade execution plan is produced."],
        summary="Bullish research view with constrained confidence.",
    )


def _news() -> AgentOutput:
    return _agent_output(
        agent_name="news_agent",
        module="news",
        bias=AgentBias.NEUTRAL,
        confidence=0.66,
        key_findings=[
            "确认事件: Consumer Price Index | official_confirmed | scheduled_macro_release_to_rates | pricing=scheduled | event_id=event:inflation_release:cpi",
        ],
        risk_points=[
            "待确认风险: Iran warns over Strait of Hormuz shipping | multi_source | geo_risk_to_oil_to_inflation | pricing=partially_priced | event_id=event:hormuz_risk:abc123",
        ],
        watchlist=[
            "观察事件: Jin10 report says gold ETF money is waiting for catalysts | single_source | gold_etf_flow_watchlist | pricing=unknown | event_id=event:gold_fund_flow:jin10",
        ],
        summary="新闻事件雷达：确认事件 1 条，候选事件 2 条。",
    )


def test_render_final_report_markdown_contains_required_sections_lineage_and_sources():
    markdown = render_final_report_markdown(
        snapshot=_snapshot(),
        macro_output=_macro(),
        options_output=_options(),
        risk_output=_risk(),
        coordinator_output=_coordinator(),
        created_at=_CREATED_AT,
    )

    assert markdown.strip()
    for section in _REQUIRED_SECTIONS:
        assert section in markdown
    assert "snapshot_id: XAUUSD:2026-05-14:analysis" in markdown
    assert "analysis_snapshot: XAUUSD:2026-05-14:analysis" in markdown
    assert "macro: macro:2026-05-14" in markdown
    assert "options: cme-options:2026-05-14" in markdown
    assert "source: analysis_snapshot" in markdown
    assert "source: macro" in markdown
    assert "source: options" in markdown
    assert "source: risk" in markdown
    assert "source: coordinator" in markdown
    assert "Bullish research view with constrained confidence." in markdown
    assert "Real yields fell" in markdown
    assert "Call wall near 4300" in markdown
    assert "Technical/news/positioning inputs are unavailable." in markdown


def test_render_final_report_markdown_adds_structured_news_event_highlights():
    markdown = render_final_report_markdown(
        snapshot=_snapshot(),
        macro_output=_macro(),
        options_output=_options(),
        risk_output=_risk(),
        news_output=_news(),
        coordinator_output=_coordinator(),
        created_at=_CREATED_AT,
    )

    assert "## 新闻与事件" in markdown
    assert "发生了什么: Consumer Price Index" in markdown
    assert "事实状态: official_confirmed" in markdown
    assert "影响路径: scheduled_macro_release_to_rates" in markdown
    assert "行情验证: scheduled" in markdown
    assert "event_id: event:inflation_release:cpi" in markdown
    assert "Iran warns over Strait of Hormuz shipping" in markdown
    assert "single_source" in markdown


def test_render_final_report_markdown_warns_on_partial_or_unavailable_outputs_without_fake_completeness():
    unavailable_options = _agent_output(
        agent_name="cme_options_agent",
        module="options",
        bias=AgentBias.UNAVAILABLE,
        confidence=0.0,
        status=AgentStatus.UNAVAILABLE,
        key_findings=[],
        risk_points=[],
        watchlist=[],
        invalid_conditions=["CME options snapshot is missing."],
        summary="",
    )

    markdown = render_final_report_markdown(
        snapshot={**_snapshot(), "metadata": {"symbol": "XAUUSD", "as_of": "2026-05-14", "unavailable_modules": ["options"]}},
        macro_output=_macro(),
        options_output=unavailable_options,
        risk_output=_risk(),
        coordinator_output=_coordinator(),
        created_at=_CREATED_AT,
    )

    assert "### 告警" in markdown
    assert "options: unavailable" in markdown
    assert "CME options snapshot is missing." in markdown
    assert "No complete final view" in markdown
    assert "fully complete" not in markdown.lower()


def test_render_final_report_markdown_accepts_dict_agent_outputs_and_does_not_mutate_inputs():
    snapshot = _snapshot()
    macro = _macro().model_dump(mode="json")
    options = _options().model_dump(mode="json")
    risk = _risk().model_dump(mode="json")
    coordinator = _coordinator().model_dump(mode="json")
    before = (snapshot.copy(), macro.copy(), options.copy(), risk.copy(), coordinator.copy())

    markdown = render_final_report_markdown(
        snapshot=snapshot,
        macro_output=macro,
        options_output=options,
        risk_output=risk,
        coordinator_output=coordinator,
        created_at=_CREATED_AT,
    )

    assert "## 协调器总结" in markdown
    assert (snapshot.copy(), macro.copy(), options.copy(), risk.copy(), coordinator.copy()) == before


def test_render_final_report_markdown_rejects_path_like_snapshot_without_file_reads():
    markdown = render_final_report_markdown(
        snapshot="storage/features/snapshots/XAUUSD/example/analysis_snapshot.json",  # type: ignore[arg-type]
        macro_output=_macro(),
        options_output=_options(),
        risk_output=_risk(),
        coordinator_output=_coordinator(),
        created_at=_CREATED_AT,
    )

    assert "### 告警" in markdown
    assert "file/path reads are not allowed" in markdown
    assert "快照 ID: unavailable" in markdown


def test_render_final_report_markdown_does_not_emit_trade_execution_instructions():
    markdown = render_final_report_markdown(
        snapshot=_snapshot(),
        macro_output=_macro(),
        options_output=_options(),
        risk_output=_risk(),
        coordinator_output=_coordinator(),
        created_at=_CREATED_AT,
    ).lower()

    forbidden = ["execute long", "execute short", "place order", "stop loss", "take profit"]
    assert all(term not in markdown for term in forbidden)
    assert "本报告仅为研究分析输出" in markdown
    assert "不构成投资建议" in markdown
