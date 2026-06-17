from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from apps.analysis.agents import AgentOutput, AgentStatus
from apps.renderer.contracts import (
    StructuredReportOutput,
    StructuredReportSection,
    StructuredReportVersion,
)

_AGENT_LABELS = {
    "macro": "宏观流动性视图",
    "options": "CME 期权结构视图",
    "risk": "风险审计",
    "technical": "技术面视图",
    "positioning": "CFTC COT 持仓视图",
    "news": "宏观事件风险视图",
    "coordinator": "协调器总结",
}

# Map agent name → data_category for report grouping
_AGENT_DATA_CATEGORY = {
    "macro": "confirmed_data",
    "positioning": "confirmed_data",
    "options": "system_inference",
    "risk": "system_inference",
    "technical": "system_inference",
    "news": "system_inference",
    "coordinator": "system_inference",
}

_DATA_CATEGORY_LABELS = {
    "confirmed_data": "已确认数据",
    "external_opinion": "外部观点",
    "system_inference": "系统推论",
}


def render_final_report_markdown(
    *,
    snapshot: Mapping[str, Any],
    macro_output: AgentOutput | Mapping[str, Any] | None,
    options_output: AgentOutput | Mapping[str, Any] | None,
    risk_output: AgentOutput | Mapping[str, Any] | None,
    technical_output: AgentOutput | Mapping[str, Any] | None = None,
    positioning_output: AgentOutput | Mapping[str, Any] | None = None,
    news_output: AgentOutput | Mapping[str, Any] | None = None,
    coordinator_output: AgentOutput | Mapping[str, Any] | None,
    created_at: datetime | None = None,
) -> str:
    """Render a deterministic Markdown final report from in-memory C3 outputs.

    This function is renderer-only: it does not read files, call agents, fetch
    data, write output artifacts, or produce trading/execution instructions.
    """

    generated_at = created_at or datetime.now(timezone.utc)
    snapshot_data, snapshot_warning = _coerce_snapshot(snapshot)
    outputs = {
        "macro": _coerce_agent_output(macro_output),
        "options": _coerce_agent_output(options_output),
        "risk": _coerce_agent_output(risk_output),
        "technical": _coerce_agent_output(technical_output),
        "positioning": _coerce_agent_output(positioning_output),
        "news": _coerce_agent_output(news_output),
        "coordinator": _coerce_agent_output(coordinator_output),
    }
    snapshot_id = _string_or_unavailable(snapshot_data.get("snapshot_id"))
    input_snapshot_ids = _collect_input_snapshot_ids(snapshot_data, outputs)
    source_refs = _collect_source_refs(snapshot_data, outputs)
    warnings = _collect_warnings(snapshot_warning, snapshot_data, outputs)

    lines: list[str] = [
        "# XAUUSD 盘前综合报告",
        "",
        f"- 生成时间: {generated_at.isoformat()}",
        f"- 快照 ID: {snapshot_id}",
        "- 报告类型: 确定性 Markdown 研究分析",
        "",
        "## 数据口径",
        "",
        "本报告仅消费内存中的分析快照和 Agent 输出负载。",
        "不调用任何外部 Agent、不读取文件、不抓取行情、不重算特征。",
        "",
    ]

    if warnings:
        lines.extend(["### 告警", ""])
        for warning in warnings:
            lines.append(f"- ⚠️ {warning}")
        lines.append("")

    lines.extend(["### 输入快照 ID", ""])
    if input_snapshot_ids:
        for key, value in input_snapshot_ids.items():
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- unavailable")
    lines.append("")

    lines.extend(_render_agent_section("coordinator", outputs["coordinator"]))

    # ── Group agent sections by data category ─────────────────────────
    _AGENT_RENDER_ORDER = ["macro", "positioning", "options", "risk", "technical", "news"]
    _CATEGORY_ORDER = ["confirmed_data", "external_opinion", "system_inference"]

    for category in _CATEGORY_ORDER:
        agents_in_category = [n for n in _AGENT_RENDER_ORDER if _AGENT_DATA_CATEGORY.get(n) == category]
        if not agents_in_category:
            continue
        label = _DATA_CATEGORY_LABELS.get(category, category)
        lines.extend([f"## {label}", ""])
        if category == "external_opinion":
            lines.append("> 以下内容来自外部来源（如 Jin10 报告），属于第三方观点，不代表系统确定性结论。")
            lines.append("")
        for name in agents_in_category:
            lines.extend(_render_agent_section(name, outputs[name]))

    lines.extend(_render_news_event_highlights(outputs["news"]))
    lines.extend(_render_list_section("无效条件", _collect_list(outputs, "invalid_conditions")))
    lines.extend(_render_list_section("观察列表", _collect_list(outputs, "watchlist")))
    lines.extend(_render_source_refs(source_refs))
    lines.extend(
        [
            "## 免责声明",
            "",
            "本报告仅为研究分析输出，不构成投资建议，不属自动交易系统，",
            "不含任何可执行的市场操作信号、下单计划、风险额度、止盈方案或可执行入场方案。",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _coerce_snapshot(snapshot: Mapping[str, Any]) -> tuple[dict[str, Any], str | None]:
    if isinstance(snapshot, str):
        return {}, "snapshot is path-like input; file/path reads are not allowed"
    if not isinstance(snapshot, Mapping):
        return {}, "snapshot is not a mapping; no complete final view can be rendered"
    return dict(snapshot), None


def _coerce_agent_output(value: AgentOutput | Mapping[str, Any] | None) -> AgentOutput | None:
    if value is None:
        return None
    if isinstance(value, AgentOutput):
        return value
    if isinstance(value, Mapping):
        return AgentOutput.model_validate(dict(value))
    return None


def _collect_input_snapshot_ids(
    snapshot: Mapping[str, Any], outputs: Mapping[str, AgentOutput | None]
) -> dict[str, Any]:
    collected: dict[str, Any] = {}
    snapshot_ids = snapshot.get("input_snapshot_ids")
    if isinstance(snapshot_ids, Mapping):
        collected.update(snapshot_ids)
    snapshot_id = snapshot.get("snapshot_id")
    if snapshot_id and "analysis_snapshot" not in collected:
        collected["analysis_snapshot"] = snapshot_id
    for output in outputs.values():
        if output is not None:
            for key, value in output.input_snapshot_ids.items():
                collected.setdefault(key, value)
    return collected


def _collect_source_refs(
    snapshot: Mapping[str, Any], outputs: Mapping[str, AgentOutput | None]
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    snapshot_refs = snapshot.get("source_refs")
    if isinstance(snapshot_refs, list):
        refs.extend(ref for ref in snapshot_refs if isinstance(ref, dict))
    for output in outputs.values():
        if output is not None:
            refs.extend(output.source_refs)
    return _dedupe_dicts(refs)


def _collect_warnings(
    snapshot_warning: str | None,
    snapshot: Mapping[str, Any],
    outputs: Mapping[str, AgentOutput | None],
) -> list[str]:
    warnings: list[str] = []
    if snapshot_warning:
        warnings.append(snapshot_warning)
    metadata = snapshot.get("metadata")
    if isinstance(metadata, Mapping):
        unavailable_modules = metadata.get("unavailable_modules")
        if unavailable_modules:
            warnings.append(f"unavailable modules declared by snapshot: {', '.join(map(str, unavailable_modules))}")
    for name, output in outputs.items():
        if output is None:
            warnings.append(f"{name}: unavailable; No complete final view because this AgentOutput is missing")
            continue
        if output.status is not AgentStatus.SUCCESS:
            warnings.append(f"{name}: {output.status.value}; No complete final view for this section")
        for condition in output.invalid_conditions:
            if output.status is not AgentStatus.SUCCESS:
                warnings.append(condition)
    return _dedupe_strings(warnings)


def _render_agent_section(name: str, output: AgentOutput | None) -> list[str]:
    title = _AGENT_LABELS[name]
    lines = [f"## {title}", ""]
    if output is None:
        return lines + ["- 状态: 不可用", "- ⚠️ 缺少 Agent 输出", ""]

    lines.extend(
        [
            f"- 代理: {output.agent_name}",
            f"- 状态: {output.status.value}",
            f"- 方向: {output.bias.value}",
            f"- 置信度: {output.confidence:.2f}",
            f"- 快照: {output.snapshot_id}",
            "",
            "### 摘要",
            "",
            output.summary or "无可用摘要；输入不可用或不完整。",
            "",
            "### 核心发现",
            "",
        ]
    )
    lines.extend(_bullets(output.key_findings))
    lines.extend(["", "### 风险点", ""])
    lines.extend(_bullets(output.risk_points))
    lines.append("")
    return lines


def _render_list_section(title: str, items: list[str]) -> list[str]:
    return [f"## {title}", "", *_bullets(items), ""]


def _render_news_event_highlights(output: AgentOutput | None) -> list[str]:
    lines = ["## 新闻与事件", ""]
    if output is None:
        return lines + ["- unavailable", ""]
    event_lines = [
        *_event_lines_from("确认/主线", output.key_findings),
        *_event_lines_from("风险", output.risk_points),
        *_event_lines_from("观察", output.watchlist),
    ]
    if not event_lines:
        return lines + ["- 无结构化新闻事件输入。", ""]
    for item in event_lines[:8]:
        lines.extend(
            [
                f"- {item['category']}:",
                f"  - 发生了什么: {item['title']}",
                f"  - 事实状态: {item['verification_status']}",
                f"  - 影响路径: {item['impact_path']}",
                f"  - 行情验证: {item['pricing_status']}",
                f"  - event_id: {item['event_id']}",
            ]
        )
    lines.append("")
    return lines


def _event_lines_from(category: str, values: list[str]) -> list[dict[str, str]]:
    parsed: list[dict[str, str]] = []
    for value in values:
        text = str(value)
        if " | " not in text or "event_id=" not in text:
            continue
        head, *parts = text.split(" | ")
        title = head.split(": ", 1)[1] if ": " in head else head
        verification_status = parts[0] if len(parts) > 0 else "unknown"
        impact_path = parts[1] if len(parts) > 1 else "unknown"
        pricing_status = "unknown"
        event_id = "unknown"
        for part in parts[2:]:
            if part.startswith("pricing="):
                pricing_status = part.removeprefix("pricing=")
            elif part.startswith("event_id="):
                event_id = part.removeprefix("event_id=")
        parsed.append(
            {
                "category": category,
                "title": title,
                "verification_status": verification_status,
                "impact_path": impact_path,
                "pricing_status": pricing_status,
                "event_id": event_id,
            }
        )
    return parsed


def _render_source_refs(source_refs: list[dict[str, Any]]) -> list[str]:
    lines = ["## 数据来源", ""]
    if not source_refs:
        return lines + ["- []", ""]
    for ref in source_refs:
        rendered = "; ".join(f"{key}: {value}" for key, value in ref.items())
        lines.append(f"- {rendered}")
    lines.append("")
    return lines


def _collect_list(outputs: Mapping[str, AgentOutput | None], attr: str) -> list[str]:
    items: list[str] = []
    for output in outputs.values():
        if output is not None:
            items.extend(getattr(output, attr))
    return _dedupe_strings(items)


def _bullets(items: list[str]) -> list[str]:
    if not items:
        return ["- unavailable"]
    return [f"- {item}" for item in items]


def _string_or_unavailable(value: Any) -> str:
    if value is None or value == "":
        return "unavailable"
    return str(value)


def _dedupe_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        if item not in seen:
            deduped.append(item)
            seen.add(item)
    return deduped


def _dedupe_dicts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[tuple[str, str], ...]] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        key = tuple(sorted((str(k), str(v)) for k, v in item.items()))
        if key not in seen:
            deduped.append(item)
            seen.add(key)
    return deduped


# ═══════════════════════════════════════════════════════════════════════
# P4-04: Structured Report builder
# ═══════════════════════════════════════════════════════════════════════


def build_structured_report(
    *,
    snapshot: Mapping[str, Any],
    macro_output: AgentOutput | Mapping[str, Any] | None,
    options_output: AgentOutput | Mapping[str, Any] | None,
    risk_output: AgentOutput | Mapping[str, Any] | None,
    technical_output: AgentOutput | Mapping[str, Any] | None = None,
    positioning_output: AgentOutput | Mapping[str, Any] | None = None,
    news_output: AgentOutput | Mapping[str, Any] | None = None,
    coordinator_output: AgentOutput | Mapping[str, Any] | None,
    created_at: datetime | None = None,
) -> StructuredReportOutput:
    """Build a deterministic StructuredReportOutput from in-memory C3 outputs.

    This is a parallel structured JSON output to the existing Markdown renderer.
    It does NOT read files, call agents, fetch data, or produce trading instructions.
    """

    generated_at = created_at or datetime.now(timezone.utc)
    snapshot_data, snapshot_warning = _coerce_snapshot(snapshot)
    outputs = {
        "macro": _coerce_agent_output(macro_output),
        "options": _coerce_agent_output(options_output),
        "risk": _coerce_agent_output(risk_output),
        "technical": _coerce_agent_output(technical_output),
        "positioning": _coerce_agent_output(positioning_output),
        "news": _coerce_agent_output(news_output),
        "coordinator": _coerce_agent_output(coordinator_output),
    }
    snapshot_id = _string_or_unavailable(snapshot_data.get("snapshot_id"))
    source_refs = _collect_source_refs(snapshot_data, outputs)
    trade_date = str(snapshot_data.get("trade_date", "")) or str(snapshot_data.get("as_of", ""))
    run_id = str(snapshot_data.get("run_id", "unknown"))
    asset = str(snapshot_data.get("asset", "XAUUSD"))
    warnings = _collect_warnings(snapshot_warning, snapshot_data, outputs)

    # ── Version metadata ───────────────────────────────────────────────
    report_id = f"{asset}:{trade_date}:{run_id}:final_report"
    source_agent_outputs = _build_source_agent_outputs_list(outputs)
    version = StructuredReportVersion(
        report_id=report_id,
        report_type="structured_final_report",
        report_version="1.0.0",
        snapshot_id=snapshot_id,
        run_id=run_id,
        trade_date=trade_date,
        created_at=generated_at,
        source_agent_outputs=source_agent_outputs,
        is_final=True,
        status="generated",
    )

    # ── Sections ────────────────────────────────────────────────────────
    sections: list[StructuredReportSection] = []

    # 1) One-line summary
    coordinator = outputs.get("coordinator")
    sections.append(_build_section(
        section_id="one_line_summary",
        title="One-line Summary",
        body=coordinator.summary if coordinator else "Coordinator output unavailable.",
        status="ok" if coordinator else "unavailable",
        source_refs=[{"agent": "coordinator"}],
        data_category="system_inference",
    ))

    # 2) Market phase
    sections.append(_build_section(
        section_id="market_phase",
        title="Market Phase",
        body=_extract_market_phase(outputs),
        status="ok",
        data_category="system_inference",
    ))

    # 3) Macro logic chain
    macro = outputs.get("macro")
    sections.append(_build_section(
        section_id="macro_logic_chain",
        title="Macro Logic Chain",
        body="\n".join(f"- {f}" for f in (macro.key_findings if macro else ["Macro agent unavailable."])),
        status="ok" if macro else "unavailable",
        source_refs=[{"agent": "macro_liquidity"}],
        data_category="confirmed_data",
    ))

    # 4) Options structure
    options = outputs.get("options")
    sections.append(_build_section(
        section_id="options_structure",
        title="Options Structure",
        body="\n".join(f"- {f}" for f in (options.key_findings if options else ["Options agent unavailable."])),
        status="ok" if options else "unavailable",
        source_refs=[{"agent": "cme_options"}],
        data_category="system_inference",
    ))

    # 5) Market odds (placeholder — deferred to P4-07~09)
    sections.append(_build_section(
        section_id="market_odds",
        title="Market Odds",
        body="Market odds layer not yet implemented (planned P4-07~09).",
        status="unavailable",
        data_category="system_inference",
    ))

    # 6) Conflicts
    conflicts = _collect_list(outputs, "invalid_conditions")
    sections.append(_build_section(
        section_id="conflicts",
        title="Conflicts & Divergences",
        body="\n".join(f"- {c}" for c in conflicts) if conflicts else "No conflicts identified.",
        status="ok",
        data_category="system_inference",
    ))

    # 7) Base scenario
    sections.append(_build_section(
        section_id="base_scenario",
        title="Base Scenario",
        body=coordinator.summary if coordinator else "Base scenario unavailable.",
        status="ok" if coordinator else "unavailable",
        source_refs=[{"agent": "coordinator"}],
        data_category="system_inference",
    ))

    # 8) Alternative scenario
    risk = outputs.get("risk")
    alt_body_parts: list[str] = []
    if risk and risk.risk_points:
        alt_body_parts.extend(f"- Risk: {rp}" for rp in risk.risk_points)
    if risk and risk.key_findings:
        alt_body_parts.extend(f"- {kf}" for kf in risk.key_findings)
    sections.append(_build_section(
        section_id="alternative_scenario",
        title="Alternative Scenario",
        body="\n".join(alt_body_parts) if alt_body_parts else "Alternative scenario not available.",
        status="ok" if alt_body_parts else "unavailable",
        source_refs=[{"agent": "risk"}],
        data_category="system_inference",
    ))

    # 9) Invalid conditions
    invalid_conditions = _collect_list(outputs, "invalid_conditions")
    sections.append(_build_section(
        section_id="invalid_conditions",
        title="Invalid Conditions",
        body="\n".join(f"- {ic}" for ic in invalid_conditions) if invalid_conditions else "No invalid conditions declared.",
        status="ok",
        data_category="system_inference",
    ))

    # 10) Risk points
    risk_points = _collect_list(outputs, "risk_points")
    sections.append(_build_section(
        section_id="risk_points",
        title="Risk Points",
        body="\n".join(f"- {rp}" for rp in risk_points) if risk_points else "No risk points declared.",
        status="ok",
        data_category="system_inference",
    ))

    # 11) Data quality
    quality_items: list[str] = []
    if warnings:
        quality_items.extend(warnings)
    else:
        quality_items.append("All data sources report nominal quality.")
    sections.append(_build_section(
        section_id="data_quality",
        title="Data Quality",
        body="\n".join(f"- {q}" for q in quality_items),
        status="ok" if not warnings else "partial",
    ))

    # 12) Source refs
    ref_lines = []
    for ref in source_refs:
        ref_lines.append("; ".join(f"{k}: {v}" for k, v in ref.items()))
    sections.append(_build_section(
        section_id="source_refs",
        title="Source Refs",
        body="\n".join(f"- {r}" for r in ref_lines) if ref_lines else "No source refs.",
        status="ok" if ref_lines else "unavailable",
        source_refs=source_refs,
    ))

    # ── Risk disclosures ────────────────────────────────────────────────
    risk_disclosures = [
        "Research output only; not investment advice.",
        "Not an automatic trading system.",
        "Contains no order plan, risk bracket, profit-taking plan, or executable entry plan.",
    ]
    if warnings:
        risk_disclosures.extend(warnings)

    return StructuredReportOutput(
        version=version,
        sections=sections,
        source_refs=source_refs,
        risk_disclosures=risk_disclosures,
    )


def _build_section(
    section_id: str,
    title: str,
    body: str,
    status: str = "ok",
    source_refs: list[dict[str, Any]] | None = None,
    data_category: str = "confirmed_data",
) -> StructuredReportSection:
    return StructuredReportSection(
        section_id=section_id,
        title=title,
        body=body,
        status=status,
        source_refs=source_refs or [],
        data_category=data_category,
    )


def _build_source_agent_outputs_list(
    outputs: dict[str, AgentOutput | None],
) -> list[dict[str, Any]]:
    agents: list[dict[str, Any]] = []
    for _, ao in outputs.items():
        if ao is not None:
            agents.append({
                "agent_name": ao.agent_name,
                "module": ao.module,
                "version": ao.version,
                "bias": ao.bias.value,
                "confidence": ao.confidence,
            })
    return agents


def _extract_market_phase(outputs: dict[str, AgentOutput | None]) -> str:
    """Derive a market phase label from agent outputs.

    P4-05: prefers macro agent's market_phase field from the regime engine.
    Falls back to coordinator/macro bias heuristic if not available.
    """
    macro = outputs.get("macro")
    coordinator = outputs.get("coordinator")

    # P4-05: use macro regime engine output
    if macro and macro.market_phase and macro.market_phase != "unavailable":
        phase = macro.market_phase
        conf = macro.confidence
        return f"{phase} (macro regime confidence: {conf:.2f})"

    # Fallback: coordinator bias heuristic
    if coordinator and coordinator.bias and coordinator.confidence > 0.5:
        bias = coordinator.bias.value.upper()
        return f"{bias} (coordinator confidence: {coordinator.confidence:.2f})"
    if macro and macro.bias:
        return f"{macro.bias.value.upper()} (macro view)"
    return "UNDETERMINED (insufficient agent output)"
