from __future__ import annotations

from apps.analysis.jin10.agent_analysis import sanitize_agent_analysis_markdown
from apps.documents.schemas import Jin10AgentAnalysisReport


def render_jin10_agent_analysis_markdown(report: Jin10AgentAnalysisReport) -> str:
    narrative = sanitize_agent_analysis_markdown(
        str(report.generated_from.get("narrative_markdown") or report.evidence_basis.get("llm_markdown") or "")
    )
    if narrative:
        return narrative.rstrip() + "\n"

    return _render_structured_narrative(report)


def _render_structured_narrative(report: Jin10AgentAnalysisReport) -> str:
    update_lines = _render_update_section(report)
    confirmation_model_lines = _render_confirmation_model(report.logic_chain)
    confirmation_rule_lines = _render_confirmation_rules(report) if confirmation_model_lines else []
    lines = [
        f"# {report.title}｜Agent 二次分析报告",
        "",
        "## 一句话结论",
        "",
        report.one_line_conclusion,
        "",
        "# 分析溯源 / 数据来源",
        "",
        *_render_list(report.provenance),
        "",
        "# 1. 最新报告相对前序判断的变化",
        "",
        *_render_list(update_lines),
        "",
        "# 2. 报告中的行情回顾",
        "",
        *_render_list([str(item) for item in report.evidence_basis.get("report_facts", [])]),
        "",
        "## 报告作者观点",
        "",
        *_render_list([str(item) for item in report.evidence_basis.get("author_views", [])]),
        "",
        "# 3. 报告核心逻辑",
        "",
        *_render_list(report.logic_chain or [report.final_summary]),
        "",
        "# 4. 当前阶段判断",
        "",
        f"- 阶段标签：{report.market_stage.get('label', '')}",
        f"- 判断依据：{report.market_stage.get('reason', '')}",
        "",
        report.gold_analysis,
        "",
        "## 白银相对判断",
        "",
        report.silver_analysis,
        "",
        "## 美元 / 美债 / 日元 / 原油",
        "",
        *_render_mapping(report.cross_asset_analysis),
        "",
        "# 5. 关键位与触发条件",
        "",
        *_render_key_levels(report.key_levels),
    "",
        "# 6. 交易 / 配置含义",
        "",
        *_render_scenarios(report.scenario_paths),
        "",
        "## 执行含义",
        "",
        *_render_trading_implications(report.trading_implications),
        "",
        "# 7. 风险与仍待确认项",
        "",
        *_render_list(report.risk_points),
        "",
        "## 尚未确认部分",
        "",
        *_render_list(report.unresolved_items),
        "",
        "## 收口",
        "",
        report.final_summary,
        "",
    ]
    if confirmation_model_lines:
        confirmation_block = [
            "",
            "## 三确认模型：利率 / 价格 / 期权",
            "",
            *confirmation_model_lines,
        ]
        if confirmation_rule_lines:
            confirmation_block.extend(
                [
                    "",
                    "## 确认口径与时间尺度",
                    "",
                    *confirmation_rule_lines,
                ]
            )
        insert_at = lines.index("# 6. 交易 / 配置含义")
        lines[insert_at:insert_at] = confirmation_block + [""]
    return "\n".join(lines)


def _render_update_section(report: Jin10AgentAnalysisReport) -> list[str]:
    lines = [report.one_line_conclusion]
    stage_label = str(report.market_stage.get("label") or "").strip()
    stage_reason = str(report.market_stage.get("reason") or "").strip()
    if stage_label:
        if stage_reason:
            lines.append(f"本次阶段判断更接近「{stage_label}」，主要依据是：{stage_reason}")
        else:
            lines.append(f"本次阶段判断更接近「{stage_label}」。")
    level_values = [str(item.get("value") or "").strip() for item in report.key_levels if str(item.get("value") or "").strip()]
    if level_values:
        lines.append(f"这次最需要盯住的关键位是：{'、'.join(level_values[:4])}")
    unresolved = [str(item).strip() for item in report.unresolved_items if str(item).strip()]
    meaningful_unresolved = [item for item in unresolved if "暂无新增未确认项" not in item]
    if meaningful_unresolved:
        lines.append(f"本次仍未确认的部分主要是：{meaningful_unresolved[0]}")
    risk_points = [str(item).strip() for item in report.risk_points if str(item).strip()]
    if risk_points:
        lines.append(f"如果后续出现反向变化，优先警惕：{risk_points[0]}")
    return lines


def _render_list(items: list[str]) -> list[str]:
    return [f"- {item}" for item in items] if items else ["- 未提供"]


def _render_mapping(mapping: dict[str, str]) -> list[str]:
    if not mapping:
        return ["- 未提供"]
    return [f"- {key}：{value}" for key, value in mapping.items()]


def _render_confirmation_model(logic_chain: list[str]) -> list[str]:
    model_line = next((item for item in logic_chain if "三确认模型" in item), "")
    if model_line:
        parts = [part.strip(" ；。") for part in model_line.replace("三确认模型：", "").split("；") if part.strip()]
        return [f"- {part}" for part in parts]
    return []


def _render_confirmation_rules(report: Jin10AgentAnalysisReport) -> list[str]:
    yield_level = _first_matching_level(report.key_levels, "收益率确认位") or "unavailable"
    balance_zone = _level_by_role(report.key_levels, "balance_zone", prefer_range=True) or "unavailable"
    _, balance_high = _split_range(balance_zone)
    price_primary = balance_high or "unavailable"
    price_confirmed = _first_matching_level(report.key_levels, "趋势修复位") or "unavailable"
    return [
        f"- 10Y观察信号：盘中跌破 {yield_level}。",
        f"- 10Y有效跌破 / 确认信号：至少日内持续低于 {yield_level}，或日线收盘低于 {yield_level}；若只是盘中短暂跌破后快速收回，不视为确认。",
        "- 10Y强确认：有效跌破后继续下行；若报告未给出强确认区间，则标记为 unavailable。",
        f"- {price_primary}：4H收盘站回，视为黄金短线修复有效；缺失则标记为 unavailable。",
        f"- {price_confirmed}：日线收盘站稳，视为黄金趋势修复确认；缺失则标记为 unavailable。",
        "- 期权成交量确认：Call volume 回升，Put volume 不扩张。",
        "- 期权持仓确认：Call OI 增加，Put OI 未明显增加；若 Call 成交量回升但 OI 不增，可能只是短线换手，不足以确认多头重新建仓。",
        "- Put/Call 进入 0.45-0.50 只能说明空方保护需求相对下降、盘整晚期概率提高，必须结合利率和价格确认使用。",
    ]


def _render_agent_storage_fields(report: Jin10AgentAnalysisReport) -> list[str]:
    yield_level = _first_matching_level(report.key_levels, "收益率确认位") or "unavailable"
    upside = _level_by_role(report.key_levels, "upside_target") or "unavailable"
    downside_risk = _level_by_role(report.key_levels, "support") or "unavailable"
    balance_zone = _level_by_role(report.key_levels, "balance_zone", prefer_range=True) or "unavailable"
    balance_low, balance_high = _split_range(balance_zone)
    price_primary = balance_high or "unavailable"
    price_confirmed = _first_matching_level(report.key_levels, "趋势修复位") or "unavailable"
    downside_primary = balance_low or downside_risk
    gold_anchor = _first_matching_level(report.key_levels, "黄金期权最大痛点") or "unavailable"
    silver_anchor = _first_matching_level(report.key_levels, "白银期权最大痛点", prefer_decimal=True) or "unavailable"
    silver_range = (
        _level_by_asset_role(report.key_levels, "白银", "support", prefer_range=True)
        or _level_by_asset_any_range(report.key_levels, "白银")
        or "unavailable"
    )
    _, silver_range_high = _split_range(silver_range)
    silver_repair = silver_range_high or "unavailable"
    gold_long_term = _level_by_asset_role(report.key_levels, "黄金", "long_term_target", prefer_range=True) or "unavailable"
    silver_long_term = _join_levels_by_asset_role(report.key_levels, "白银", "long_term_target") or "unavailable"

    macro_observe = _macro_observe_text(yield_level)
    macro_confirmed = _macro_confirmed_text(yield_level)
    price_primary_text = _price_trigger_text("4H", price_primary)
    price_confirmed_text = _price_trigger_text("daily", price_confirmed)
    upside_primary = _combined_trigger("US10Y_effective_break_below", yield_level, "XAUUSD_4h_close_above", price_primary)
    upside_confirmed = _combined_trigger("US10Y_daily_close_below", yield_level, "XAUUSD_daily_close_above", price_confirmed)
    downside_primary_text = _downside_trigger_text(downside_primary)
    valid_until_event = "2026-06 gold option expiry" if balance_zone != "unavailable" else "unavailable"
    post_expiry_required_review = "true" if balance_zone != "unavailable" else "false"

    return [
        "```yaml",
        "agent_stage_label: reversal_watch_window",
        "main_asset: XAUUSD",
        "secondary_asset: XAGUSD",
        "primary_driver: US10Y",
        "secondary_driver: gold_options_structure",
        "",
        "confirmation_level: options_leading_only",
        "macro_confirmed: false",
        "price_confirmed: false",
        "options_confirmed: partial",
        "",
        "trade_stance: wait_for_confirmation",
        "",
        f'macro_trigger_observe: "{macro_observe}"',
        f'macro_trigger_confirmed: "{macro_confirmed}"',
        f'price_trigger_primary: "{price_primary_text}"',
        f'price_trigger_confirmed: "{price_confirmed_text}"',
        'options_trigger_confirmed: "Call volume rises + Call OI increases + Put volume does not expand"',
        "",
        f'upside_trigger_primary: "{upside_primary}"',
        f'upside_trigger_confirmed: "{upside_confirmed}"',
        f'downside_trigger_primary: "{downside_primary_text}"',
        "",
        f'balance_zone: "{balance_zone}"',
        f"options_anchor_gold: {gold_anchor}",
        f"next_upside_target: {upside}",
        f"next_downside_risk: {downside_risk}",
        "",
        f"silver_options_anchor: {silver_anchor}",
        f'silver_range: "{silver_range}"',
        f"silver_repair_level: {silver_repair}",
        "",
        f'long_term_gold_scenario: "{gold_long_term}"',
        f'long_term_silver_scenario: "{silver_long_term}"',
        "",
        f'valid_until_event: "{valid_until_event}"',
        f"post_expiry_required_review: {post_expiry_required_review}",
        "",
        "data_quality_flags:",
        '  - "report_based_analysis"',
        '  - "options_signal_leads_price"',
        '  - "requires_live_market_confirmation"',
        '  - "chart_extraction_noise_possible"',
        "",
        "evidence_refs:",
        "  us10y_level:",
        '    source: "raw_article_report.key_levels"',
        '    type: "macro_level"',
        "  gold_call_activity_rebound:",
        '    source: "raw_article_report.article_markdown"',
        '    type: "options_flow_text"',
        "  put_call_ratio_key_zone:",
        '    source: "raw_article_report.article_markdown"',
        '    type: "options_ratio"',
        "  gold_balance_zone:",
        '    source: "raw_article_report.key_levels"',
        '    type: "option_expiry_zone"',
        "```",
    ]


def _first_matching_level(rows: list[dict[str, object]], label_part: str, *, prefer_decimal: bool = False) -> str:
    matches = [str(row.get("value", "")) for row in rows if label_part in str(row.get("label", ""))]
    if prefer_decimal:
        decimal_match = next((value for value in matches if "." in value), "")
        if decimal_match:
            return decimal_match
    return matches[0] if matches else ""


def _level_by_role(rows: list[dict[str, object]], role: str, *, prefer_range: bool = False) -> str:
    matches = [str(row.get("value", "")) for row in rows if row.get("role") == role]
    if prefer_range:
        range_match = next((value for value in matches if "-" in value), "")
        if range_match:
            return range_match
    return matches[0] if matches else ""


def _level_by_asset_role(rows: list[dict[str, object]], asset: str, role: str, *, prefer_range: bool = False) -> str:
    matches = [str(row.get("value", "")) for row in rows if row.get("asset") == asset and row.get("role") == role]
    if prefer_range:
        range_match = next((value for value in matches if "-" in value), "")
        if range_match:
            return range_match
    return matches[0] if matches else ""


def _join_levels_by_asset_role(rows: list[dict[str, object]], asset: str, role: str) -> str:
    values = [str(row.get("value", "")) for row in rows if row.get("asset") == asset and row.get("role") == role]
    return " / ".join(values)


def _level_by_asset_any_range(rows: list[dict[str, object]], asset: str) -> str:
    return next((str(row.get("value", "")) for row in rows if row.get("asset") == asset and "-" in str(row.get("value", ""))), "")


def _split_range(value: str) -> tuple[str, str]:
    if "-" not in value:
        return "", ""
    left, right = value.split("-", 1)
    return left.strip(), right.strip()


def _macro_observe_text(yield_level: str) -> str:
    return "unavailable" if yield_level == "unavailable" else f"US10Y intraday break below {yield_level}"


def _macro_confirmed_text(yield_level: str) -> str:
    return "unavailable" if yield_level == "unavailable" else f"US10Y daily close below {yield_level}"


def _price_trigger_text(timeframe: str, level: str) -> str:
    return "unavailable" if level == "unavailable" else f"XAUUSD {timeframe} close above {level}"


def _combined_trigger(left_prefix: str, left_level: str, right_prefix: str, right_level: str) -> str:
    if left_level == "unavailable" or right_level == "unavailable":
        return "unavailable"
    return f"{left_prefix}_{left_level} AND {right_prefix}_{right_level}"


def _downside_trigger_text(level: str) -> str:
    return "unavailable" if level == "unavailable" else f"XAUUSD_break_below_{level}_and_fail_to_reclaim"


def _render_key_variables(rows: list[dict[str, object]]) -> list[str]:
    if not rows:
        return ["- 未提供"]
    return [
        f"- {row.get('name', '未命名变量')}｜观察：{row.get('observation', '')}｜含义：{row.get('meaning', '')}"
        for row in rows
    ]


def _render_key_levels(rows: list[dict[str, object]]) -> list[str]:
    if not rows:
        return ["- 未提供"]
    trading = [row for row in rows if row.get("layer") != "long_term"]
    long_term = [row for row in rows if row.get("layer") == "long_term"]
    rendered: list[str] = []
    if trading:
        rendered.append("### 短中期交易位")
        rendered.extend(f"- {row.get('label', '关键位')}：{row.get('value')}" for row in trading)
    if long_term:
        if rendered:
            rendered.append("")
        rendered.append("### 长期情景位（报告作者长期观点，不作为短线追单依据）")
        rendered.extend(f"- {row.get('label', '长期情景')}：{row.get('value')}" for row in long_term)
    return rendered


def _render_scenarios(rows: list[dict[str, object]]) -> list[str]:
    if not rows:
        return ["- 未提供"]
    rendered: list[str] = []
    for row in rows:
        rendered.extend(
            [
                f"### {row.get('path', '路径')}",
                f"- 概要：{row.get('summary', '')}",
                f"- 触发条件：{row.get('trigger', '')}",
                f"- 失效条件：{row.get('invalid', '')}",
                f"- 风险点：{'；'.join(str(item) for item in row.get('risk_points', []))}",
                f"- 置信度：{row.get('confidence', '')}",
                "",
            ]
        )
    rendered.pop()
    return rendered


def _render_trading_implications(rows: list[dict[str, object]]) -> list[str]:
    if not rows:
        return ["- 未提供"]
    rendered: list[str] = []
    for row in rows:
        stance = str(row.get("stance", "")).strip()
        trigger = str(row.get("trigger", "")).strip()
        invalid = str(row.get("invalid", "")).strip()
        risk_points = "；".join(str(item) for item in row.get("risk_points", []))
        watch_variables = "；".join(str(item) for item in row.get("watch_variables", []))
        rendered.extend(
            [
                f"- 当前更适合的做法是：{stance or '继续观察'}。",
                f"- 只有当以下条件出现，才考虑顺着报告方向推进：{trigger or 'unavailable'}。",
                f"- 如果出现以下情况，当前判断需要回撤或重做：{invalid or 'unavailable'}。",
                f"- 执行层最需要提前防的风险：{risk_points or 'unavailable'}。",
                f"- 这一步真正要盯的变量：{watch_variables or 'unavailable'}。",
            ]
        )
    return rendered
