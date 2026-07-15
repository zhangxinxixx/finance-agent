from __future__ import annotations

from apps.documents.schemas import Jin10AgentAnalysisReport


def render_jin10_agent_analysis_markdown(report: Jin10AgentAnalysisReport) -> str:
    """Render Markdown exclusively from the validated report object."""
    return _render_structured_narrative(report)


def _render_structured_narrative(report: Jin10AgentAnalysisReport) -> str:
    update_lines = _render_update_section(report)
    daily_context_lines = _render_daily_context(report)
    confirmation_model_lines = _render_confirmation_model(report.logic_chain)
    confirmation_rule_lines = _render_confirmation_rules(report) if confirmation_model_lines else []
    title_suffix = "｜Agent 二次分析报告"
    report_title = report.title.strip()
    while report_title.endswith(title_suffix):
        report_title = report_title[: -len(title_suffix)].rstrip()
    lines = [
        f"# {report_title}{title_suffix}",
        "",
        "## 一句话结论",
        "",
        report.one_line_conclusion,
        "",
        "# 分析溯源 / 数据来源",
        "",
        *_render_list(report.provenance),
        "",
        *(
            ["## 分析基准与当日上下文", "", *daily_context_lines, ""]
            if daily_context_lines
            else []
        ),
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
        "# 3. 黄金为什么涨 / 为什么跌？",
        "",
        *_render_list(report.logic_chain or [report.final_summary]),
        "",
        "# 4. 报告核心观点：短线、中期、长期分开",
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
        "# 5. 当前阶段判断与确认矩阵",
        "",
        *_render_confirmation_matrix(report.market_stage),
        "",
        "# 6. 关键位更新",
        "",
        *_render_key_levels(report.key_levels),
    "",
        "# 7. 三条路径推演",
        "",
        *_render_scenarios(report.scenario_paths),
        "",
        "# 8. 操作层面怎么理解？",
        "",
        *_render_trading_implications(report.trading_implications),
        "",
        "# 风险与仍待确认项",
        "",
        *_render_list(report.risk_points),
        "",
        "## 尚未确认部分",
        "",
        *_render_list(report.unresolved_items),
        "",
        "# 最终综合判断",
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
        insert_at = lines.index("# 7. 三条路径推演")
        lines[insert_at:insert_at] = confirmation_block + [""]
    return "\n".join(lines)


def _render_daily_context(report: Jin10AgentAnalysisReport) -> list[str]:
    context = report.generated_from.get("daily_context")
    if not isinstance(context, dict) or not context:
        return []
    anchor = context.get("analysis_baseline") or context.get("weekly_anchor") or {}
    baseline_kind = str(context.get("baseline_kind") or anchor.get("source_kind") or "weekly_anchor")
    baseline_label = {
        "weekly_anchor": "周末周报",
        "weekly_fallback": "周报回退（前一日最终综合分析报告缺失）",
        "previous_analysis_report": "前一日最新综合分析报告",
        "previous_daily": "前一日最新综合分析报告",
    }.get(baseline_kind, "前序分析")
    freshness = context.get("freshness") or {}
    lines = [
        (
            f"- 分析基准（{baseline_label}）："
            f"{anchor.get('trade_date') or anchor.get('context_as_of') or 'missing'} / "
            f"ref={anchor.get('article_id') or anchor.get('report_id') or anchor.get('run_id') or 'missing'} / "
            f"{anchor.get('title') or '未提供标题'}"
        ),
        (
            "- 基准状态："
            f"quality={anchor.get('quality_status') or 'unknown'}；"
            f"publication={anchor.get('publication_status') or 'unknown'}；"
            f"publish_allowed={anchor.get('publish_allowed') if anchor.get('publish_allowed') is not None else 'unknown'}"
        ),
    ]
    for key, label in (("market", "市场"), ("news", "新闻"), ("oil", "油价")):
        item = freshness.get(key) or {}
        lines.append(
            f"- {label}上下文：status={item.get('status') or 'missing'}；as_of={item.get('as_of') or 'missing'}；age_days={item.get('age_days') if item.get('age_days') is not None else 'unknown'}"
        )
    return lines


def _render_confirmation_matrix(market_stage: dict[str, object]) -> list[str]:
    matrix = market_stage.get("confirmation_matrix")
    if not isinstance(matrix, dict) or not matrix:
        return ["- 确认矩阵：未提供"]
    return [f"- {key}：{value}" for key, value in matrix.items()]


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
        rendered.extend(_render_key_level(row) for row in trading)
    if long_term:
        if rendered:
            rendered.append("")
        rendered.append("### 长期情景位（报告作者长期观点，不作为短线追单依据）")
        rendered.extend(_render_key_level(row, default_label="长期情景") for row in long_term)
    return rendered


def _render_key_level(row: dict[str, object], *, default_label: str = "关键位") -> str:
    label = row.get("label") or row.get("asset") or default_label
    details = [str(row.get("source_category") or "").strip(), str(row.get("meaning") or "").strip()]
    suffix = "｜".join(item for item in details if item)
    return f"- {label}：{row.get('value')}{f'｜{suffix}' if suffix else ''}"


def _render_scenarios(rows: list[dict[str, object]]) -> list[str]:
    if not rows:
        return ["- 未提供"]
    rendered: list[str] = []
    for row in rows:
        risk_points = _joined_items(row.get("risk_points"))
        confidence = str(row.get("confidence") or "").strip()
        rendered.extend([
            f"### {row.get('name') or row.get('path') or '路径'}",
            f"- 概要：{row.get('summary') or row.get('path') or ''}",
            f"- 触发条件：{row.get('trigger', '')}",
            f"- 失效条件：{row.get('invalid', '')}",
        ])
        if risk_points:
            rendered.append(f"- 风险点：{risk_points}")
        if confidence:
            rendered.append(f"- 置信度：{confidence}")
        rendered.append("")
    rendered.pop()
    return rendered


def _render_trading_implications(rows: list[dict[str, object]]) -> list[str]:
    if not rows:
        return ["- 未提供"]
    rendered: list[str] = []
    for row in rows:
        role = str(row.get("role", "")).strip()
        stance = str(row.get("stance") or "").strip()
        wait_for = str(row.get("wait_for") or "").strip()
        trigger = str(row.get("trigger") or row.get("wait_for") or "").strip()
        invalid = str(row.get("invalid", "")).strip()
        risk_points = _joined_items(row.get("risk_points"))
        watch_variables = _joined_items(row.get("watch_variables"))
        if role:
            rendered.append(f"### {role}")
        rendered.append(_sentence_line("当前更适合的做法是", stance or wait_for or "继续观察"))
        if trigger and trigger != wait_for:
            rendered.append(_sentence_line("只有当以下条件出现，才考虑顺着报告方向推进", trigger))
        if invalid:
            rendered.append(_sentence_line("如果出现以下情况，当前判断需要回撤或重做", invalid))
        if risk_points:
            rendered.append(_sentence_line("执行层最需要提前防的风险", risk_points))
        if watch_variables:
            rendered.append(_sentence_line("这一步真正要盯的变量", watch_variables))
    return rendered


def _joined_items(value: object) -> str:
    if not isinstance(value, list):
        return ""
    return "；".join(str(item).strip() for item in value if str(item).strip())


def _sentence_line(label: str, value: str) -> str:
    sentence = value.strip()
    suffix = "" if sentence.endswith(("。", "！", "？", ".", "!", "?")) else "。"
    return f"- {label}：{sentence}{suffix}"
