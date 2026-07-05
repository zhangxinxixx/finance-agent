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

_PROFESSIONAL_REPORT_ORDER = ["macro", "technical", "positioning", "options", "news", "risk"]
_MACRO_INDICATOR_ORDER = [
    "ON_RRP_USAGE",
    "ON_RRP_AWARD_RATE",
    "TGA",
    "RESERVES",
    "SOFR",
    "EFFR",
    "IORB",
    "US02Y",
    "US10Y",
    "BREAKEVEN_10Y",
    "REAL_10Y",
    "YIELD_SPREAD_10Y_2Y",
    "YIELD_SPREAD_2Y_3M",
    "DXY",
]

_BIAS_LABELS = {
    "bullish": "偏多",
    "bearish": "偏空",
    "neutral": "中性",
    "mixed": "分歧",
    "unavailable": "不可用",
}

_STATUS_LABELS = {
    "success": "完整",
    "partial": "部分可用",
    "unavailable": "不可用",
    "failed": "失败",
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
        "# XAUUSD 相关报告",
        "",
        f"- 数据刷新时间: {_data_refresh_time(snapshot_data, generated_at)}",
        f"- 快照 ID: {snapshot_id}",
        "- 报告类型: 宏观数据报告 + 综合报告（确定性生成）",
        "",
    ]

    lines.extend(_render_macro_data_report(snapshot_data, outputs["macro"], warnings))
    lines.extend(["## 综合报告", ""])
    lines.extend(["### 报告主题", "", _build_report_theme(snapshot_data, outputs), ""])
    lines.extend(_render_executive_summary(snapshot_data, outputs, warnings, heading_level=3))
    lines.extend(_render_market_view(outputs, heading_level=3))
    lines.extend(_render_evidence_chain(outputs, heading_level=3))
    lines.extend(_render_gold_macro_overview(snapshot_data, heading_level=3))
    lines.extend(_render_scenarios(outputs, heading_level=3))
    lines.extend(_render_data_quality(warnings, heading_level=3))
    lines.extend(_render_list_section("观察列表", _collect_list(outputs, "watchlist"), limit=12, heading_level=3))

    lines.extend(["## 数据口径与血缘", ""])
    lines.append("本报告仅消费本次运行内存中的分析快照和 Agent 输出负载；不调用外部 Agent、不读取任意路径、不抓取实时行情、不重算特征。")
    lines.append("")
    lines.extend(["### 输入快照 ID", ""])
    if input_snapshot_ids:
        for key, value in input_snapshot_ids.items():
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- unavailable")
    lines.append("")

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


def _build_report_theme(
    snapshot: Mapping[str, Any],
    outputs: Mapping[str, AgentOutput | None],
) -> str:
    coordinator = outputs.get("coordinator")
    macro = outputs.get("macro")
    trade_date = str(snapshot.get("trade_date") or snapshot.get("as_of") or "")
    direction = _bias_label(coordinator.bias.value if coordinator else None)
    confidence = f"{coordinator.confidence:.2f}" if coordinator else "unavailable"
    market_phase = _market_phase_text(macro, coordinator)
    date_part = f"{trade_date} " if trade_date else ""
    return (
        f"{date_part}XAUUSD 的核心主题是：在{market_phase}背景下，"
        f"综合方向为{direction}，报告置信度 {confidence}。"
        "正文按宏观流动性、技术结构、持仓、CME 期权、新闻事件与风险审计组织证据，"
        "用于形成可复盘的研究判断，而不是交易指令。"
    )


def _data_refresh_time(snapshot: Mapping[str, Any], generated_at: datetime) -> str:
    return str(
        snapshot.get("snapshot_time")
        or snapshot.get("updated_at")
        or snapshot.get("as_of")
        or snapshot.get("trade_date")
        or generated_at.isoformat()
    )


def _render_macro_data_report(
    snapshot: Mapping[str, Any],
    macro: AgentOutput | None,
    warnings: list[str],
) -> list[str]:
    lines = ["## 宏观数据报告", ""]
    lines.extend(["### 宏观数据主题", ""])
    if macro is None:
        lines.extend(["宏观数据输出不可用；本节仅保留数据缺口提示。", ""])
    else:
        phase = _market_phase_text(macro, None)
        lines.extend(
            [
                f"当前宏观阶段为 {phase}；宏观方向为{_bias_label(macro.bias.value)}，置信度 {macro.confidence:.2f}。",
                "",
            ]
        )
        if macro.summary:
            lines.extend([macro.summary, ""])

    lines.extend(_render_macro_indicator_table(snapshot))
    lines.extend(_render_v21_macro_framework(snapshot, macro))
    if macro and macro.key_findings:
        lines.extend(["### 宏观结论", ""])
        lines.extend(_bullets(macro.key_findings[:6]))
        lines.append("")

    macro_warnings = [item for item in warnings if _is_macro_warning(item)]
    lines.extend(["### 宏观数据限制", ""])
    if macro_warnings:
        lines.extend(_bullets(macro_warnings[:8]))
    else:
        lines.append("- 本次宏观数据报告未报告关键宏观数据缺口。")
    lines.append("")
    return lines


def _render_macro_indicator_table(snapshot: Mapping[str, Any]) -> list[str]:
    indicators = _macro_indicators(snapshot)
    lines = ["### 核心宏观指标", ""]
    if not indicators:
        return lines + ["- 宏观指标快照不可用。", ""]

    lines.extend(
        [
            "| 指标 | 最新值 | 日期 | 日变 | 周变 | 月变 | 解读 |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for symbol, item in _ordered_macro_indicators(indicators):
        lines.append(
            "| "
            + " | ".join(
                [
                    _table_text(str(item.get("label") or symbol)),
                    _format_indicator_value(item),
                    _table_text(_string_or_unavailable(item.get("date"))),
                    _format_change(item, "daily_change"),
                    _format_change(item, "weekly_change", fallback="change_1w"),
                    _format_change(item, "monthly_change"),
                    _table_text(str(item.get("direction_note") or "")) or "-",
                ]
            )
            + " |"
        )
    lines.append("")
    return lines


def _render_executive_summary(
    snapshot: Mapping[str, Any],
    outputs: Mapping[str, AgentOutput | None],
    warnings: list[str],
    *,
    heading_level: int = 2,
) -> list[str]:
    coordinator = outputs.get("coordinator")
    macro = outputs.get("macro")
    lines = [_heading(heading_level, "执行摘要"), ""]
    if coordinator is None:
        lines.extend(["综合协调器输出不可用；本报告只能作为分项证据汇总。", ""])
    else:
        lines.extend(
            [
                f"综合结论为{_bias_label(coordinator.bias.value)}，置信度 {coordinator.confidence:.2f}；"
                f"当前市场阶段为 {_market_phase_text(macro, coordinator)}。"
            ]
        )
        if coordinator.summary:
            lines.extend(["", coordinator.summary])
        lines.append("")

    lines.extend(["| 维度 | 状态 | 方向 | 置信度 | 核心信息 |", "| --- | --- | --- | --- | --- |"])
    for name in ["coordinator", *_PROFESSIONAL_REPORT_ORDER]:
        output = outputs.get(name)
        title = _AGENT_LABELS[name]
        if output is None:
            lines.append(f"| {title} | 不可用 | 不可用 | - | 缺少 Agent 输出 |")
            continue
        finding = _first_text(output.key_findings) or output.summary or "无摘要"
        lines.append(
            f"| {title} | {_status_label(output.status.value)} | {_bias_label(output.bias.value)} | "
            f"{output.confidence:.2f} | {_table_text(finding)} |"
        )
    lines.append("")
    if warnings:
        lines.append(f"数据完整性：本次运行存在 {len(warnings)} 条质量提示，详见“数据质量与限制”。")
        lines.append("")
    return lines


def _render_market_view(outputs: Mapping[str, AgentOutput | None], *, heading_level: int = 2) -> list[str]:
    coordinator = outputs.get("coordinator")
    lines = [_heading(heading_level, "核心判断"), ""]
    if coordinator is None:
        return lines + ["- 综合判断不可用。", ""]
    lines.extend(_bullets(coordinator.key_findings[:6]))
    if coordinator.risk_points:
        lines.extend(["", _heading(heading_level + 1, "主要约束"), ""])
        lines.extend(_bullets(coordinator.risk_points[:6]))
    lines.append("")
    return lines


def _render_evidence_chain(outputs: Mapping[str, AgentOutput | None], *, heading_level: int = 2) -> list[str]:
    lines = [_heading(heading_level, "分项证据链"), ""]
    for name in _PROFESSIONAL_REPORT_ORDER:
        lines.extend(_render_professional_agent_section(name, outputs.get(name), heading_level=heading_level + 1))
    lines.extend(_render_news_event_highlights(outputs.get("news"), limit=6, heading_level=heading_level + 1))
    return lines


def _render_gold_macro_overview(snapshot: Mapping[str, Any], *, heading_level: int = 2) -> list[str]:
    overview = _find_gold_macro_overview(snapshot)
    if not overview:
        return []
    readiness = overview.get("analysis_readiness") if isinstance(overview.get("analysis_readiness"), Mapping) else {}
    chain = overview.get("war_oil_rate_chain") if isinstance(overview.get("war_oil_rate_chain"), Mapping) else {}
    rankings = [item for item in overview.get("theme_rankings") or [] if isinstance(item, Mapping)]
    requirements = [item for item in overview.get("mainline_requirements") or [] if isinstance(item, Mapping)]

    lines = [_heading(heading_level, "黄金九主线总览"), ""]
    lines.append(
        "- 主导主线: "
        f"{overview.get('dominant_mainline') or 'unknown'}；"
        f"优先环境: {overview.get('priority_regime') or 'unknown'}；"
        f"净影响: {overview.get('net_bias') or 'unknown'}。"
    )
    if overview.get("priority_reason"):
        lines.append(f"- 优先级原因: {overview.get('priority_reason')}")
    if readiness:
        lines.append(
            "- 能力覆盖: "
            f"{readiness.get('status') or 'unknown'}，"
            f"ready {readiness.get('ready_count', 0)}/"
            f"{readiness.get('total_count', 0)}，"
            f"partial {readiness.get('partial_count', 0)}，"
            f"missing {readiness.get('missing_count', 0)}。"
        )
    if chain:
        lines.append(
            "- 战争-石油-利率链: "
            f"{chain.get('conclusion_code') or 'unknown'} / "
            f"{chain.get('conclusion_label') or chain.get('net_effect') or 'unknown'}。"
        )
    if rankings:
        lines.extend(["", "| Rank | 主线 | 方向 | 分数 | 证据 |", "| --- | --- | --- | --- | --- |"])
        for item in rankings[:5]:
            lines.append(
                "| "
                f"{item.get('rank') or '-'} | "
                f"{item.get('label') or item.get('mainline_id') or '-'} | "
                f"{item.get('direction') or '-'} | "
                f"{item.get('theme_score') if item.get('theme_score') is not None else item.get('score') or '-'} | "
                f"{item.get('evidence_count', 0)} |"
            )
    gaps = _gold_macro_gaps(requirements, overview)
    if gaps:
        lines.extend(["", "待补证据："])
        lines.extend(_bullets(gaps[:6]))
    lines.append("")
    return lines


def _find_gold_macro_overview(snapshot: Mapping[str, Any]) -> Mapping[str, Any] | None:
    direct = snapshot.get("gold_macro_overview")
    if isinstance(direct, Mapping) and direct:
        return direct
    news = snapshot.get("news")
    if isinstance(news, Mapping):
        news_data = news.get("data")
        if isinstance(news_data, Mapping):
            nested = news_data.get("gold_macro_overview")
            if isinstance(nested, Mapping) and nested:
                return nested
    payload = snapshot.get("payload")
    if isinstance(payload, Mapping):
        nested = payload.get("gold_macro_overview")
        if isinstance(nested, Mapping) and nested:
            return nested
    return None


def _gold_macro_gaps(requirements: list[Mapping[str, Any]], overview: Mapping[str, Any]) -> list[str]:
    gaps: list[str] = []
    for item in requirements:
        if item.get("readiness_status") == "ready":
            continue
        label = item.get("label") or item.get("mainline_id") or "unknown"
        missing_sources = ", ".join(str(source) for source in item.get("missing_sources") or [])
        missing_fields = ", ".join(str(field) for field in item.get("missing_fields") or [])
        detail = missing_sources or missing_fields
        if detail:
            gaps.append(f"{label}: {detail}")
    if not gaps:
        gaps.extend(str(item) for item in overview.get("architecture_gaps") or [] if str(item))
    return gaps


def _render_professional_agent_section(name: str, output: AgentOutput | None, *, heading_level: int = 3) -> list[str]:
    title = _AGENT_LABELS[name]
    lines = [_heading(heading_level, title), ""]
    if output is None:
        return lines + ["- 状态：不可用；缺少 Agent 输出。", ""]
    lines.append(
        f"- 结论：{_bias_label(output.bias.value)}；状态：{_status_label(output.status.value)}；置信度：{output.confidence:.2f}。"
    )
    if output.summary:
        lines.append(f"- 摘要：{output.summary}")
    if output.key_findings:
        lines.extend(["", "关键证据："])
        lines.extend(_bullets(output.key_findings[:6]))
    if output.risk_points:
        lines.extend(["", "约束与风险："])
        lines.extend(_bullets(output.risk_points[:5]))
    lines.append("")
    return lines


def _render_scenarios(outputs: Mapping[str, AgentOutput | None], *, heading_level: int = 2) -> list[str]:
    coordinator = outputs.get("coordinator")
    risk = outputs.get("risk")
    macro = outputs.get("macro")
    options = outputs.get("options")
    news = outputs.get("news")
    lines = [_heading(heading_level, "情景推演"), ""]
    base = coordinator.summary if coordinator and coordinator.summary else "基准情景不可用；需先补齐协调器输出。"
    lines.extend([_heading(heading_level + 1, "基准情景"), "", base, ""])

    upside = _scenario_items([macro, options, news], preferred_biases={"bullish"}, include_risks=False)
    downside = _scenario_items([macro, options, news, risk], preferred_biases={"bearish", "mixed", "neutral"}, include_risks=True)
    lines.extend([_heading(heading_level + 1, "上行情景触发"), ""])
    lines.extend(_bullets(upside[:5]))
    lines.extend(["", _heading(heading_level + 1, "下行/失效情景"), ""])
    invalid = _collect_list(outputs, "invalid_conditions")
    downside_items = [*downside[:5], *invalid[:5]]
    lines.extend(_bullets(downside_items))
    lines.append("")
    return lines


def _render_data_quality(warnings: list[str], *, heading_level: int = 2) -> list[str]:
    lines = [_heading(heading_level, "数据质量与限制"), ""]
    if not warnings:
        return lines + ["- 本次运行未报告关键数据质量限制。", ""]
    for warning in warnings[:12]:
        lines.append(f"- {warning}")
    if len(warnings) > 12:
        lines.append(f"- 另有 {len(warnings) - 12} 条质量提示已折叠；详见结构化产物或源数据血缘。")
    lines.append("")
    return lines


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


def _render_list_section(
    title: str,
    items: list[str],
    *,
    limit: int | None = None,
    heading_level: int = 2,
) -> list[str]:
    limited = items if limit is None else items[:limit]
    lines = [_heading(heading_level, title), "", *_bullets(limited)]
    if limit is not None and len(items) > limit:
        lines.append(f"- 另有 {len(items) - limit} 条观察项已折叠；详见结构化产物。")
    lines.append("")
    return lines


def _render_news_event_highlights(
    output: AgentOutput | None,
    *,
    limit: int = 8,
    heading_level: int = 3,
) -> list[str]:
    lines = [_heading(heading_level, "新闻与事件要点"), ""]
    if output is None:
        return lines + ["- unavailable", ""]
    event_lines = [
        *_event_lines_from("确认/主线", output.key_findings),
        *_event_lines_from("风险", output.risk_points),
        *_event_lines_from("观察", output.watchlist),
    ]
    if not event_lines:
        return lines + ["- 无结构化新闻事件输入。", ""]
    for item in event_lines[:limit]:
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
    lines.append("以下为来源分组摘要；完整来源明细保留在结构化产物 `source_refs` 和原始血缘中。")
    lines.append("")
    for item in _summarize_source_ref_groups(source_refs):
        lines.append(f"- {item}")
    lines.append("")
    return lines


def _summarize_source_ref_groups(source_refs: list[dict[str, Any]], *, limit: int = 12) -> list[str]:
    grouped: dict[str, dict[str, Any]] = {}
    for ref in source_refs:
        source_name = _source_ref_group_name(ref)
        group = grouped.setdefault(source_name, {"count": 0, "examples": []})
        group["count"] += 1
        example = _source_ref_example(ref)
        if example and example not in group["examples"] and len(group["examples"]) < 3:
            group["examples"].append(example)

    rows: list[str] = []
    for source_name, group in sorted(grouped.items(), key=lambda item: (-item[1]["count"], item[0]))[:limit]:
        examples = "；样例：" + " / ".join(group["examples"]) if group["examples"] else ""
        rows.append(f"{source_name}: {group['count']} 条血缘明细{examples}")
    if len(grouped) > limit:
        rows.append(f"另有 {len(grouped) - limit} 个来源分组已折叠；详见结构化血缘。")
    return rows


def _source_ref_group_name(ref: Mapping[str, Any]) -> str:
    for key in ("source", "source_name", "provider", "source_key", "source_type"):
        value = ref.get(key)
        if value:
            return str(value)
    source_ref = ref.get("source_ref") or ref.get("id")
    if source_ref:
        return str(source_ref).split(":", 1)[0]
    return "unknown"


def _source_ref_example(ref: Mapping[str, Any]) -> str:
    for key in ("source_ref", "symbol", "feed_key", "query_group", "method", "endpoint", "raw_path", "parsed_path"):
        value = ref.get(key)
        if value:
            text = str(value)
            return text if len(text) <= 80 else f"{text[:77]}..."
    return ""


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


def _heading(level: int, title: str) -> str:
    return f"{'#' * max(1, level)} {title}"


def _bias_label(value: str | None) -> str:
    if not value:
        return "不可用"
    return _BIAS_LABELS.get(value, value)


def _status_label(value: str | None) -> str:
    if not value:
        return "不可用"
    return _STATUS_LABELS.get(value, value)


def _market_phase_text(macro: AgentOutput | None, coordinator: AgentOutput | None) -> str:
    if macro and macro.market_phase and macro.market_phase != "unavailable":
        return _phase_label(macro.market_phase)
    if coordinator and coordinator.market_phase and coordinator.market_phase != "unavailable":
        return _phase_label(coordinator.market_phase)
    if coordinator:
        return f"{_bias_label(coordinator.bias.value)}研究视图"
    if macro:
        return f"{_bias_label(macro.bias.value)}宏观视图"
    return "输入不足"


def _first_text(items: list[str]) -> str:
    return next((str(item) for item in items if str(item).strip()), "")


def _table_text(value: str) -> str:
    text = str(value or "-").replace("|", "\\|").replace("\r", " ").replace("\n", " ")
    text = " ".join(text.split()).strip() or "-"
    if len(text) > 120:
        return text[:117].rstrip() + "..."
    return text


def _macro_indicators(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    macro = snapshot.get("macro")
    if not isinstance(macro, Mapping):
        return {}
    data = macro.get("data")
    if not isinstance(data, Mapping):
        return {}
    indicators = data.get("indicators")
    if not isinstance(indicators, Mapping):
        return {}
    return {str(key): value for key, value in indicators.items() if isinstance(value, Mapping)}


def _ordered_macro_indicators(indicators: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    ordered: list[tuple[str, Mapping[str, Any]]] = []
    seen: set[str] = set()
    for key in _MACRO_INDICATOR_ORDER:
        item = indicators.get(key)
        if isinstance(item, Mapping):
            ordered.append((key, item))
            seen.add(key)
    for key in sorted(indicators):
        if key in seen:
            continue
        item = indicators.get(key)
        if isinstance(item, Mapping):
            ordered.append((key, item))
    return ordered


def _format_indicator_value(item: Mapping[str, Any]) -> str:
    value = item.get("value")
    unit = str(item.get("unit") or "").strip()
    if value is None or value == "":
        return "unavailable"
    if isinstance(value, float):
        rendered = f"{value:.3f}".rstrip("0").rstrip(".")
    else:
        rendered = str(value)
    return _table_text(f"{rendered} {unit}".strip())


def _format_change(item: Mapping[str, Any], key: str, *, fallback: str | None = None) -> str:
    value = item.get(key)
    if value is None and fallback is not None:
        value = item.get(fallback)
    if value is None or value == "":
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _table_text(str(value))
    sign = "+" if number > 0 else ""
    rendered = f"{sign}{number:.3f}".rstrip("0").rstrip(".")
    return rendered or "0"


def _render_v21_macro_framework(snapshot: Mapping[str, Any], macro: AgentOutput | None) -> list[str]:
    indicators = _macro_indicators(snapshot)
    drivers = macro.regime_drivers.get("drivers", {}) if macro and isinstance(macro.regime_drivers, Mapping) else {}
    phase = _phase_label(macro.market_phase if macro else None)
    lines = ["### v2.1 流动性数据底座判断", ""]
    lines.extend(
        [
            f"- 数量层：{_liquidity_quantity_label(drivers.get('liquidity_quantity'))}",
            f"- 价格层：{_liquidity_price_label(drivers.get('liquidity_price'), indicators)}",
            f"- 实际利率：{_driver_direction_label(drivers.get('real_yield'), rising='上行', falling='下行', flat='横盘')}",
            f"- 美元：{_driver_direction_label(drivers.get('dxy'), rising='逆风', falling='顺风', flat='中性')}",
            "- 判断规则：流动性数量层只作为底座，必须继续经过实际利率、DXY 和阶段判断后才进入交易/配置含义。",
            "",
            "### 当前阶段判断",
            "",
            f"- 当前阶段：{phase}",
            f"- 置信度：{macro.confidence:.2f}" if macro else "- 置信度：unavailable",
            f"- 当前主导变量：{_dominant_macro_variable(drivers, macro)}",
            f"- 是否处于切换区：{_is_switch_zone(macro)}",
            "",
            "### 当前主导变量排序",
            "",
            "| 排名 | 主导变量 | 当前方向 | 对黄金影响 |",
            "|---:|---|---|---|",
        ]
    )
    for idx, row in enumerate(_dominant_variable_rows(drivers), 1):
        lines.append(f"| {idx} | {row[0]} | {row[1]} | {row[2]} |")
    lines.extend(
        [
            "",
            "### 利率结构模块",
            "",
            f"- 第一层 10Y 名义收益率：{_indicator_value_by_keys(indicators, ('US10Y', 'DGS10'))}；判断长端压力和财政/期限溢价。",
            f"- 是否接近 4.5%-4.7% 政策敏感区：{_rate_game_zone(indicators)}",
            f"- 第二层 10Y 实际收益率 / TIPS：{_real_yield_pressure(drivers)}；判断黄金机会成本。",
            f"- 第三层 2Y-3M 利差：{_short_curve_label(indicators)}；判断短端政策拐点和周期低点窗口。",
            f"- 利率结构规则：{_rate_structure_label(indicators)}",
            f"- DXY 是否配合：{_driver_direction_label(drivers.get('dxy'), rising='美元逆风', falling='美元顺风', flat='中性')}",
            "",
            "### 黄金六因子模型",
            "",
            "| 因子 | 状态 | 评分 | 含义 |",
            "|---|---|---:|---|",
            f"| 实际收益率 | {_factor_state(indicators, ('REAL_10Y', 'REAL_YIELD_10Y'))} | {_factor_score(indicators, ('REAL_10Y', 'REAL_YIELD_10Y'), positive_is_bullish=False, weight=3)} | 权重 +3/-3；主口径为 US10Y - T10YIE |",
            f"| 通胀预期 | {_factor_state(indicators, ('BREAKEVEN_10Y', 'T10YIE'))} | {_factor_score(indicators, ('BREAKEVEN_10Y', 'T10YIE'), positive_is_bullish=True, weight=2)} | 权重 +2/-2；T10YIE 是主通胀预期口径 |",
            f"| 利率曲线 / 2Y-3M利差 | {_factor_state(indicators, ('YIELD_SPREAD_2Y_3M',))} | {_factor_score(indicators, ('YIELD_SPREAD_2Y_3M',), positive_is_bullish=True, weight=2)} | 权重 +2/-2；改善提高周期低点确认概率 |",
            "| ETF / COT 资金 | 未从识别结果中稳定提取 | 0 | 权重 +2/-2；未进入本宏观快照 |",
            "| 期权结构 | 未从识别结果中稳定提取 | 0 | 权重 +1/-1；短线节奏，由 CME options Agent 单独确认 |",
            "| 央行 / 实物需求 | 未从识别结果中稳定提取 | 0 | 权重 +2/-1；未进入本宏观快照 |",
            "",
            "### 关键触发条件与失效条件",
            "",
        ]
    )
    change_conditions = macro.regime_drivers.get("change_conditions", []) if macro and isinstance(macro.regime_drivers, Mapping) else []
    if change_conditions:
        lines.extend(_bullets([str(item) for item in change_conditions[:5]]))
    else:
        lines.append("- unavailable")
    lines.extend(
        [
            "",
            "### 交易 / 配置含义",
            "",
            f"- 研究含义：{_phase_research_meaning(macro.market_phase if macro else None)}",
            "- 执行边界：本报告只输出研究和配置含义，不输出下单、止损、止盈或仓位比例。",
            "",
        ]
    )
    return lines


def _phase_label(value: str | None) -> str:
    labels = {
        "rate_pressure": "利率压制态",
        "transition_release": "过渡释放态",
        "trend_tailwind": "趋势顺风态",
        "liquidity_crunch": "流动性踩踏态",
        "monetary_credit_repricing": "货币信用重估态",
        "unavailable": "不可用",
    }
    if not value:
        return "输入不足"
    return labels.get(value, value)


def _phase_research_meaning(value: str | None) -> str:
    meanings = {
        "rate_pressure": "反弹先按修复观察，趋势反转需要实际利率和 DXY 同步确认。",
        "transition_release": "进入反转观察区，优先等待确认或回踩后的研究性试探。",
        "trend_tailwind": "宏观顺风增强，回踩与突破的研究价值上升。",
        "liquidity_crunch": "先防流动性踩踏，不用避险逻辑盲目追多。",
        "monetary_credit_repricing": "中长期配置逻辑增强，短线仍需触发位确认。",
    }
    return meanings.get(value or "", "数据不足，保持观察。")


def _liquidity_quantity_label(value: Any) -> str:
    if not isinstance(value, Mapping):
        return "输入不足"
    trend = value.get("trend")
    if trend == "easing":
        return "偏松"
    if trend == "tightening":
        return "偏紧"
    if trend == "neutral":
        return "分裂 / 中性"
    return "输入不足"


def _liquidity_price_label(value: Any, indicators: Mapping[str, Any]) -> str:
    if not isinstance(value, Mapping):
        return "输入不足"
    high_count = 0
    for key in ("SOFR", "EFFR", "IORB", "US02Y"):
        metric = indicators.get(key)
        raw = metric.get("value") if isinstance(metric, Mapping) else None
        try:
            high_count += 1 if raw is not None and float(raw) >= 3.5 else 0
        except (TypeError, ValueError):
            continue
    if high_count >= 3:
        return "钱贵"
    return "稳定"


def _driver_direction_label(value: Any, *, rising: str, falling: str, flat: str) -> str:
    if not isinstance(value, Mapping):
        return "输入不足"
    direction = value.get("direction")
    if direction == "rising":
        return rising
    if direction == "falling":
        return falling
    if direction == "flat":
        return flat
    return "方向不明"


def _dominant_macro_variable(drivers: Mapping[str, Any], macro: AgentOutput | None) -> str:
    phase = macro.market_phase if macro else None
    if phase in {"rate_pressure", "liquidity_crunch"}:
        return "实际利率 / DXY"
    if phase == "monetary_credit_repricing":
        return "货币信用"
    if phase == "trend_tailwind":
        return "实际利率下行 / 美元转弱"
    if isinstance(drivers.get("real_yield"), Mapping):
        return "实际利率"
    return "输入不足"


def _is_switch_zone(macro: AgentOutput | None) -> str:
    return "是" if macro and macro.market_phase == "transition_release" else "否"


def _dominant_variable_rows(drivers: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    return [
        ("10Y实际利率", _driver_direction_label(drivers.get("real_yield"), rising="上行", falling="下行", flat="横盘"), "核心机会成本"),
        ("DXY", _driver_direction_label(drivers.get("dxy"), rising="上行", falling="下行", flat="横盘"), "美元计价压力"),
        ("US02Y", _driver_direction_label(drivers.get("us02y"), rising="上行", falling="下行", flat="横盘"), "短端政策预期"),
        ("流动性数量层", _liquidity_quantity_label(drivers.get("liquidity_quantity")), "底座，不是直接信号"),
        ("Breakeven", _driver_direction_label(drivers.get("breakeven"), rising="上行", falling="下行", flat="横盘"), "通胀预期"),
        ("风险溢价 / 货币信用", "未稳定提取", "只在触发时展开"),
    ]


def _indicator_value_by_keys(indicators: Mapping[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        item = indicators.get(key)
        if isinstance(item, Mapping):
            return _format_indicator_value(item)
    return "unavailable"


def _rate_game_zone(indicators: Mapping[str, Any]) -> str:
    value = _indicator_float(indicators, ("US10Y", "DGS10"))
    if value is None:
        return "无法判断"
    if 4.5 <= value < 4.7:
        return "是，处于政策敏感区"
    if value >= 4.7:
        return "已进入流动性踩踏风险区"
    return "否"


def _real_yield_pressure(drivers: Mapping[str, Any]) -> str:
    label = _driver_direction_label(drivers.get("real_yield"), rising="继续压制", falling="压制缓和", flat="横盘")
    return label


def _short_curve_label(indicators: Mapping[str, Any]) -> str:
    value = _indicator_value_by_keys(indicators, ("YIELD_SPREAD_2Y_3M",))
    change = _indicator_change(indicators, ("YIELD_SPREAD_2Y_3M",))
    if change is None:
        return f"{value}，方向待确认"
    if change > 0:
        return f"{value}，利差改善"
    if change < 0:
        return f"{value}，利差恶化"
    return f"{value}，横盘"


def _rate_structure_label(indicators: Mapping[str, Any]) -> str:
    real = _indicator_float(indicators, ("REAL_10Y", "REAL_YIELD_10Y"))
    real_change = _indicator_change(indicators, ("REAL_10Y", "REAL_YIELD_10Y"))
    spread_change = _indicator_change(indicators, ("YIELD_SPREAD_2Y_3M",))
    if real is None or real_change is None or spread_change is None:
        return "10Y 实际收益率或 2Y-3M 利差缺失，不能确认短端政策拐点。"
    if real_change < 0 and spread_change > 0:
        return "10Y 实际收益率下行 + 2Y-3M 利差改善，黄金低点确认概率提高。"
    if real >= 2.1 and spread_change < 0:
        return "10Y 实际收益率高企 + 2Y-3M 利差恶化，4100 低点失败概率提高，警惕 3720 剧本。"
    return "利率结构尚未形成明确共振，继续等待实际收益率与短端利差同向确认。"


def _factor_state(indicators: Mapping[str, Any], keys: tuple[str, ...]) -> str:
    change = _indicator_change(indicators, keys)
    if change is None:
        return "方向不明"
    if change > 0:
        return "上行"
    if change < 0:
        return "下行"
    return "横盘"


def _factor_score(indicators: Mapping[str, Any], keys: tuple[str, ...], *, positive_is_bullish: bool, weight: int = 2) -> int:
    change = _indicator_change(indicators, keys)
    if change is None or change == 0:
        return 0
    bullish = change > 0 if positive_is_bullish else change < 0
    return weight if bullish else -weight


def _indicator_float(indicators: Mapping[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        item = indicators.get(key)
        if not isinstance(item, Mapping):
            continue
        value = item.get("value")
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _indicator_change(indicators: Mapping[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        item = indicators.get(key)
        if not isinstance(item, Mapping):
            continue
        for field in ("weekly_change", "change_1w", "daily_change", "monthly_change"):
            value = item.get(field)
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


def _is_macro_warning(value: str) -> bool:
    text = value.lower()
    return any(key in text for key in ["macro", "10y", "dxy", "real-yield", "t10yie", "unavailable macro"])


def _scenario_items(
    outputs: list[AgentOutput | None],
    *,
    preferred_biases: set[str],
    include_risks: bool,
) -> list[str]:
    items: list[str] = []
    for output in outputs:
        if output is None:
            continue
        if output.bias.value in preferred_biases:
            items.extend(output.key_findings[:3])
            if include_risks:
                items.extend(output.risk_points[:2])
    return _dedupe_strings(items)


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
    ref_lines = _summarize_source_ref_groups(source_refs)
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
