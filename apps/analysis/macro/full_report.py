from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from apps.analysis.agents import AgentOutput
from apps.analysis.macro.conclusion import MacroConclusion
from apps.analysis.macro.summary import _format_change, _format_value
from apps.features.macro.snapshot import MacroSnapshot


def render_macro_full_report_markdown(
    snapshot: MacroSnapshot,
    conclusion: MacroConclusion,
    macro_output: AgentOutput | Mapping[str, Any] | None = None,
) -> str:
    if not snapshot.indicators:
        return _render_unavailable_report(snapshot)

    llm_markdown = _macro_llm_markdown(macro_output)
    llm_body = _strip_redundant_llm_sections(_strip_leading_heading(llm_markdown))
    lines: list[str] = [
        f"# XAUUSD 宏观 / 流动性更新（{snapshot.as_of}）", "",
        "## 一句话结论", "",
        _llm_one_line(llm_markdown) or _one_line(conclusion), "",
        "## 流动性与利率统一数据表", "",
        "| 指标 | 最新日期 | 最新值 | 1周变化 | 1月变化 | 方向解读 |",
        "|---|---|---:|---:|---:|---|",
    ]
    for symbol in _report_order():
        indicator = snapshot.indicators.get(symbol)
        label = _label_for(symbol)
        if indicator is None:
            lines.append(f"| {label} | 明确缺失 | 明确缺失 | 明确缺失 | 明确缺失 | 明确缺失 |")
            continue
        lines.append(
            f"| {indicator.label or label} | {indicator.date} | {_format_value(indicator)} | "
            f"{_format_change(indicator, indicator.weekly_change)} | "
            f"{_format_change(indicator, indicator.monthly_change)} | "
            f"{indicator.direction_note or '暂无可用方向解读'} |"
        )
    if llm_markdown:
        if llm_body:
            lines.extend(["", "## LLM 宏观分析", "", llm_body])
        lines.extend([
            "", "## 口径与规则校验", "",
            "- 10Y 实际利率主口径：**US10Y - T10YIE**；DFII10 / TIPS 只作补充观察。",
            "- 2Y-3M 主口径：**DGS2 - DGS3MO**；必须拆分 2Y 与 3M 的变化来源。",
            f"- 确定性规则预判：**{conclusion.state} / {conclusion.bias}**；仅用于和 LLM 结论交叉核对。",
        ])
        if conclusion.missing_inputs:
            lines.extend(["", "## 明确缺失输入", ""])
            lines.extend(f"- {s}" for s in conclusion.missing_inputs)
        lines.append("")
        return "\n".join(lines)
    lines.extend([
        "", "## 流动性数据底座", "",
        "以下为系统数据事实与规则预判，供 LLM 综合判断使用；最终阶段、主导变量和交易含义不得由模板直接锁死。", "",
        f"- **数量层规则预判：{conclusion.quantity_layer}。** {_quantity_sentence(snapshot)}",
        f"- **价格层规则预判：{conclusion.price_layer}。** {_price_sentence(snapshot)}",
        f"- **实际利率事实：** {_real_rate_fact_sentence(snapshot)}",
        f"- **美元事实 / 规则预判：{conclusion.dollar_layer}。** {_dollar_sentence(snapshot)}",
        "- **判断边界：** 流动性数量层只是底座，不是直接交易信号；LLM 必须再结合实际利率、DXY、短端价格、资金流和风险溢价确认。",
        "", "## LLM 阶段判断输入", "",
        f"- 规则预判阶段：**{conclusion.state}**",
        f"- 规则预判方向：**{conclusion.bias}**",
        f"- 规则预判主导变量：**{_dominant_variable(conclusion)}**",
        f"- 规则预判切换区：**{_switch_zone(conclusion, snapshot)}**",
        "- LLM 必须自行判断最终阶段，可选择并解释：利率压制态、过渡释放态、趋势顺风态、流动性踩踏态、货币信用重估态。",
        "", "## 利率结构模块", "",
        f"- 第一层 10Y 名义收益率：{_indicator_value(snapshot, 'US10Y')}；判断长端压力、财政与期限溢价。",
        f"- 是否接近 4.5%-4.7% 政策敏感区：{_rate_zone(snapshot)}",
        f"- 第二层 10Y 实际收益率 / TIPS：{_real_rate_pressure(snapshot)}；判断黄金机会成本。",
        f"- 第三层 2Y-3M 利差：{_short_curve_pressure(snapshot)}；判断短端政策拐点和周期低点窗口。",
        f"- 利率结构规则：{_rate_structure_rule(snapshot)}",
        f"- DXY 是否配合：{conclusion.dollar_layer}",
        "", "## 黄金六因子模型", "",
        "| 因子 | 系统已提取状态 | LLM评分 | 判断要求 |",
        "|---|---|---:|---|",
        f"| 实际收益率 | {_factor_state(snapshot, 'REAL_10Y')} | 待LLM判断 | 权重 +3/-3；主口径为 US10Y - T10YIE，判断黄金机会成本 |",
        f"| 通胀预期 | {_factor_state(snapshot, 'BREAKEVEN_10Y')} | 待LLM判断 | 权重 +2/-2；只使用 T10YIE 作为主通胀预期口径 |",
        f"| 利率曲线 / 2Y-3M利差 | {_factor_state(snapshot, 'YIELD_SPREAD_2Y_3M')} | 待LLM判断 | 不单独评分；必须拆分 2Y 与 3M 驱动，并由实际利率和 DXY 确认 |",
        "| ETF / COT 资金 | 未从识别结果中稳定提取 | 待LLM判断 | 权重 +2/-2；若联网补充，必须标为外部联网补充 / 待系统化接入 |",
        "| 期权结构 | 未从识别结果中稳定提取 | 待LLM判断 | 权重 +1/-1；短线节奏，不单独决定方向 |",
        "| 央行 / 实物需求 | 未从识别结果中稳定提取 | 待LLM判断 | 权重 +2/-1；若联网补充，必须标为外部联网补充 / 待系统化接入 |",
        "",
        "- **评分规则：** 中期分和短线分由 LLM 根据已提取数据与可追溯联网补充自行给出；模板只提供事实状态，不直接写死分数。",
        "- **缺失规则：** 期权、ETF/COT、央行/实物需求未稳定提取时，必须写“未从识别结果中稳定提取”。",
        "", "## 交易 / 配置含义", "",
        "- LLM 必须基于事实链条自行给出最终研究性交易 / 配置含义，不得照抄规则预判。",
        "- 规则预判方向与动作仅供对照，不是最终结论。",
        "- **规则候选触发条件：**",
    ])
    lines.extend(f"  - {item}" for item in conclusion.trigger_upgrade)
    lines.extend(f"  - 降级条件：{item}" for item in conclusion.trigger_downgrade)
    lines.append("- **规则候选约束：** 仅作为 LLM 再判断的输入，不得机械计数触发。")
    lines.extend(f"  - {item}。" for item in conclusion.no_go_actions)
    lines.extend(["", "## 风险识别点", ""])
    for idx, risk in enumerate(conclusion.risks, 1):
        lines.append(f"{idx}. **{risk.title}**：{risk.detail}")
    lines.extend([
        "",
        "**动作规则：以下风险点只作为 LLM 判断的候选输入，不得机械计数触发方向。**",
        "", "## 系统性风险雷达", "",
        "| 风险项 | 当前系统数据 | 判断 |",
        "|---|---|---|",
    ])
    lines.extend(_systemic_risk_rows(snapshot))
    lines.extend([
        "",
        "系统性风险最终结论由 LLM 根据系统数据、可追溯联网补充和缺失项自行判断；模板不直接写死为慢性挤压、信用扩散或货币信用重估。",
        "", "## 三路径推演", "",
        "LLM 必须自行生成三路径推演；模板只规定结构，不预设每条路径的方向和触发条件。",
        "",
        "### 路径A：主路径", "",
        "- 触发条件：由 LLM 根据实际利率、DXY、短端价格、流动性数量层、资金流和风险溢价自行填写。",
        "- 黄金含义：由 LLM 判断。",
        "- 交易 / 配置含义：只写研究性含义，不写下单指令。",
        "- 失效条件：由 LLM 明确写出。",
        "",
        "### 路径B：上行 / 修复路径", "",
        "- 触发条件：由 LLM 判断是否成立，不得机械套用固定阈值。",
        "- 黄金含义：由 LLM 判断。",
        "- 交易 / 配置含义：只写研究性含义，不写下单指令。",
        "- 失效条件：由 LLM 明确写出。",
        "",
        "### 路径C：失败 / 踩踏路径", "",
        "- 触发条件：由 LLM 判断是否存在美元现金需求、利率冲击、信用利差扩散或风险资产共振。",
        "- 黄金含义：由 LLM 判断。",
        "- 交易 / 配置含义：只写研究性含义，不写下单指令。",
        "- 失效条件：由 LLM 明确写出。",
    ])
    lines.extend([
        "", "## 当前所处环境阶段判断", "",
        "这里仅给出规则预判，不代表最终 LLM 结论。", "",
        f"规则预判更接近：**{conclusion.state}**。", "",
        _state_sentence(conclusion, snapshot),
        "",
        "最终阶段判断必须由 LLM 在完整报告中自行确认；如果 LLM 判断与规则预判不同，需说明差异原因。",
        "", "## 数据口径说明", "",
        "- 通胀只看 **T10YIE**。",
        "- 10Y 实际利率固定采用 **US10Y - T10YIE**。",
        "- 3M 使用 **US03M / DGS3MO**；2Y-3M 利差固定采用 **DGS2 - DGS3MO**。",
        "- 2Y-3M 必须拆分 2Y 与 3M 的变化来源，不把转正、走阔或收窄机械等同于宽松。",
        "- FRED:DFII10 / TIPS 实际收益率只作补充观察，不替代主结论评分。",
        "- DXY 采用系统输入的 DXY 最新值与其 1周 / 1月变化。",
        "- IORB 采用 Fed 官方 PRATES.json 自动采集。",
        "- TGA 采用 Treasury FiscalData API 自动采集；缺失时必须显式标记。",
    ])
    if conclusion.missing_inputs:
        lines.extend(["", "## 明确缺失输入", ""])
        lines.extend(f"- {s}" for s in conclusion.missing_inputs)
    lines.append("")
    return "\n".join(lines)


def _one_line(conclusion):
    return (
        f"今天黄金的宏观环境更接近 **{conclusion.bias}**：数量层{conclusion.quantity_layer}、"
        f"美元层{conclusion.dollar_layer}、价格层{conclusion.price_layer}；"
        f"所以更适合按 **{conclusion.state}下的{conclusion.action}** 来处理，而不是直接追高。"
    )


def _macro_llm_markdown(macro_output: AgentOutput | Mapping[str, Any] | None) -> str:
    if macro_output is None:
        return ""
    if isinstance(macro_output, Mapping):
        text = str(macro_output.get("llm_raw_output") or macro_output.get("summary") or "")
    else:
        text = str(macro_output.llm_raw_output or macro_output.summary or "")
    return text.strip()


def _strip_leading_heading(markdown: str) -> str:
    lines = markdown.splitlines()
    if lines and lines[0].lstrip().startswith("#"):
        return "\n".join(lines[1:]).lstrip()
    return markdown


def _strip_redundant_llm_sections(markdown: str) -> str:
    lines = markdown.splitlines()
    kept: list[str] = []
    skipped_level = 0
    for line in lines:
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading and re.search(
            r"一句话结论|流动性与利率统一数据表|固定指标表|新增指标说明|数据源|数据来源|Data Sources|Source Refs",
            heading.group(2),
            re.IGNORECASE,
        ):
            skipped_level = len(heading.group(1))
            continue
        if skipped_level and heading and len(heading.group(1)) <= skipped_level:
            skipped_level = 0
        if not skipped_level:
            kept.append(line)
    return "\n".join(kept).strip()


def _llm_one_line(markdown: str) -> str:
    for line in _strip_leading_heading(markdown).splitlines():
        candidate = line.strip()
        if not candidate or candidate.startswith("#") or candidate.startswith(("- ", "* ", "|")):
            continue
        return re.sub(r"^\*\*一句话结论[:：]?\*\*\s*", "", candidate).strip()
    return ""


def _render_unavailable_report(snapshot: MacroSnapshot) -> str:
    missing_count = len(set(snapshot.unavailable_symbols))
    return "\n".join(
        [
            f"# XAUUSD 宏观 / 流动性更新（{snapshot.as_of}）",
            "",
            "## 本次报告不可用",
            "",
            "本次宏观采集没有获得任何有效指标，因此不生成方向、阶段或交易含义判断。",
            "",
            f"- 缺失指标数：{missing_count}",
            "- 建议：在数据接入或调度中心检查采集失败原因并重试。",
            "",
        ]
    )


def _report_order():
    return ["ON_RRP_USAGE", "ON_RRP_AWARD_RATE", "TGA", "RESERVES", "SOFR", "EFFR", "IORB", "US03M", "US02Y", "YIELD_SPREAD_2Y_3M", "US10Y", "BREAKEVEN_10Y", "REAL_10Y", "YIELD_SPREAD_10Y_2Y", "DXY"]


def _label_for(symbol):
    return {
        "ON_RRP_USAGE": "ON RRP 使用量", "ON_RRP_AWARD_RATE": "ON RRP Award Rate", "TGA": "TGA",
        "RESERVES": "Reserve Balances", "SOFR": "SOFR", "EFFR": "EFFR", "IORB": "IORB",
        "US03M": "US03M", "US02Y": "US02Y", "US10Y": "US10Y", "BREAKEVEN_10Y": "10Y Breakeven（T10YIE）",
        "REAL_10Y": "10Y 实际利率 = US10Y - T10YIE", "YIELD_SPREAD_10Y_2Y": "10Y-2Y 利差",
        "YIELD_SPREAD_2Y_3M": "2Y-3M 利差", "DXY": "DXY"
    }.get(symbol, symbol)


def _fmt_signed(value: float | None, *, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return "暂无"
    return f"{value:+.{digits}f}{suffix}"


def _quantity_sentence(snapshot):
    tga, reserves, rrp = snapshot.indicators.get("TGA"), snapshot.indicators.get("RESERVES"), snapshot.indicators.get("ON_RRP_USAGE")
    if tga and reserves and rrp:
        return (
            f"RRP 当前 {rrp.value:.3f}B，"
            f"TGA 周变化 {_fmt_signed(tga.weekly_change, digits=3, suffix='B')}（{_tga_change_label(tga.weekly_change)}），"
            f"准备金周变化 {_fmt_signed(reserves.weekly_change, digits=3, suffix='B')}（{_reserves_change_label(reserves.weekly_change)}）。"
        )
    return "关键数量层输入不完整，系统只做降级判断。"


def _tga_change_label(change):
    if change is None:
        return "方向待确认"
    if change < 0:
        return "财政抽水缓和"
    if change > 0:
        return "财政抽水增加"
    return "基本持平"


def _reserves_change_label(change):
    if change is None:
        return "方向待确认"
    if change > 0:
        return "银行体系缓冲变厚"
    if change < 0:
        return "银行体系缓冲变薄"
    return "基本持平"


def _price_sentence(snapshot):
    vals = [snapshot.indicators.get(s) for s in ("SOFR", "EFFR", "IORB", "US03M", "US02Y")]
    if all(vals):
        sofr, effr, iorb, us03m, us02y = vals
        return f"SOFR {sofr.value:.2f}%，EFFR {effr.value:.2f}%，IORB {iorb.value:.2f}%，3M {us03m.value:.2f}%，2Y {us02y.value:.2f}%，短端机会成本仍在高位。"
    return "短端价格层输入不完整，不能确认真正宽松。"


def _real_rate_fact_sentence(snapshot):
    us10y = snapshot.indicators.get("US10Y")
    breakeven = snapshot.indicators.get("BREAKEVEN_10Y")
    real = snapshot.indicators.get("REAL_10Y")
    if us10y and breakeven and real:
        return f"US10Y {us10y.value:.2f}%，T10YIE {breakeven.value:.2f}%，10Y 实际利率约 {real.value:.2f}%（主口径）。"
    return "10Y 实际利率输入不完整，LLM 需要降级判断。"


def _dollar_sentence(snapshot):
    dxy = snapshot.indicators.get("DXY")
    if dxy:
        return f"DXY 当前约 {dxy.value:.3f}，1周变化 {_fmt_signed(dxy.weekly_change)}，1月变化 {_fmt_signed(dxy.monthly_change)}。"
    return "DXY 缺失，美元层只能降级为中性。"


def _indicator_value(snapshot, symbol):
    indicator = snapshot.indicators.get(symbol)
    if indicator is None:
        return "明确缺失"
    return _format_value(indicator)


def _rate_zone(snapshot):
    us10y = snapshot.indicators.get("US10Y")
    if us10y is None:
        return "无法判断"
    if 4.5 <= us10y.value < 4.7:
        return "是，处于政策敏感区"
    if us10y.value >= 4.7:
        return "已进入流动性踩踏风险区"
    return "否，暂未进入敏感区"


def _real_rate_pressure(snapshot):
    real = snapshot.indicators.get("REAL_10Y")
    if real is None:
        return "无法判断"
    if real.value >= 2.1:
        return "是，实际利率仍处高位压制黄金"
    if real.weekly_change is not None and real.weekly_change > 0:
        return "是，实际利率上行仍压制黄金"
    if real.weekly_change is not None and real.weekly_change < 0:
        return "否，实际利率回落缓和机会成本"
    return "横盘，暂不提供方向确认"


def _short_rate_pressure(snapshot):
    us02y = snapshot.indicators.get("US02Y")
    if us02y is None:
        return "无法判断"
    if us02y.weekly_change is not None and us02y.weekly_change > 0:
        return "是，2Y 边际变鹰"
    if us02y.weekly_change is not None and us02y.weekly_change < 0:
        return "否，2Y 边际转松"
    return "横盘"


def _short_curve_pressure(snapshot):
    spread = snapshot.indicators.get("YIELD_SPREAD_2Y_3M")
    if spread is None:
        return "无法判断"
    curve_state = "正斜率" if spread.value > 0 else "倒挂" if spread.value < 0 else "持平"
    if spread.weekly_change is None or spread.weekly_change == 0:
        curve_change = "周度基本不变"
    elif spread.value >= 0:
        curve_change = "周度走阔" if spread.weekly_change > 0 else "周度收窄"
    else:
        curve_change = "倒挂收窄" if spread.weekly_change > 0 else "倒挂加深"
    return f"当前 {_format_value(spread)}（{curve_state}、{curve_change}）；{_short_curve_driver(snapshot)}"


def _short_curve_driver(snapshot):
    us02y = snapshot.indicators.get("US02Y")
    us03m = snapshot.indicators.get("US03M")
    if us02y is None or us03m is None:
        return "2Y 或 3M 缺失，无法拆分变化来源"
    two_change = us02y.weekly_change
    three_change = us03m.weekly_change
    if two_change is None or three_change is None:
        return "2Y 或 3M 周变化缺失，无法拆分变化来源"
    if two_change > 0 and three_change < 0:
        return "2Y 上行而 3M 下行，鹰派预期与近期政策价格转松并存，曲线变化不能单向解读"
    if two_change < 0 and three_change > 0:
        return "2Y 下行而 3M 上行，未来紧缩溢价缓和但当前短端更紧，信号分裂"
    if two_change >= 0 and three_change >= 0:
        if two_change > three_change:
            return "2Y 与 3M 同升且 2Y 升幅更大，未来利率溢价偏鹰"
        if three_change > two_change:
            return "2Y 与 3M 同升且 3M 升幅更大，当前短端价格收紧更明显"
        if two_change > 0:
            return "2Y 与 3M 同幅上行，曲线未变但短端价格整体收紧"
        return "2Y 与 3M 均持平，曲线本身未提供新增方向确认"
    if two_change <= 0 and three_change <= 0:
        if abs(three_change) > abs(two_change):
            return "2Y 与 3M 同降且 3M 降幅更大，近期政策价格转松信号较强"
        if abs(two_change) > abs(three_change):
            if three_change == 0:
                return "2Y 下行而 3M 未降，仅代表未来紧缩溢价缓和，当前短端尚未宽松"
            return "2Y 与 3M 同降但 2Y 降幅更大，未来紧缩溢价缓和更明显"
        return "2Y 与 3M 同幅下行，短端价格整体转松但曲线未变"
    return "2Y 与 3M 变化接近，曲线本身未提供新增方向确认"


def _rate_structure_rule(snapshot):
    real = snapshot.indicators.get("REAL_10Y")
    us02y = snapshot.indicators.get("US02Y")
    us03m = snapshot.indicators.get("US03M")
    spread = snapshot.indicators.get("YIELD_SPREAD_2Y_3M")
    if real is None or us02y is None or us03m is None or spread is None:
        return "10Y 实际收益率、2Y、3M 或 2Y-3M 利差缺失，不能确认短端政策拐点。"
    real_falling = real.weekly_change is not None and real.weekly_change < 0
    two_falling = us02y.weekly_change is not None and us02y.weekly_change < 0
    two_rising = us02y.weekly_change is not None and us02y.weekly_change > 0
    three_falling = us03m.weekly_change is not None and us03m.weekly_change < 0
    three_not_falling = us03m.weekly_change is not None and us03m.weekly_change >= 0
    if real_falling and three_falling:
        return "10Y 实际收益率与 3M 同步下行，机会成本和近期政策价格共同转松，黄金宏观压力明显缓和。"
    if real_falling and two_falling and three_not_falling:
        return "10Y 实际收益率与 2Y 下行，但 3M 未降；未来紧缩溢价缓和，当前短端尚未确认宽松。"
    if real.value >= 2.1 and two_rising and three_not_falling:
        return "10Y 实际收益率高企且 2Y 上行，利率结构偏鹰，对黄金继续构成机会成本压力。"
    return "利率结构尚未形成明确共振，继续等待实际收益率、2Y 与 3M 的共同确认。"


def _dominant_variable(conclusion):
    if conclusion.state in {"利率压制态", "流动性踩踏态"}:
        return "实际利率 / DXY"
    if conclusion.state == "趋势顺风态":
        return "实际利率下行 / 美元转弱"
    return "实际利率"


def _switch_zone(conclusion, snapshot):
    if conclusion.state == "过渡释放态":
        return "是"
    us10y = snapshot.indicators.get("US10Y")
    real = snapshot.indicators.get("REAL_10Y")
    dxy = snapshot.indicators.get("DXY")
    easing_edges = [
        us10y is not None and us10y.value <= 4.4,
        real is not None and real.weekly_change is not None and real.weekly_change < 0,
        dxy is not None and dxy.value >= 101,
    ]
    if conclusion.state == "利率压制态" and all(easing_edges):
        return "是，强压制向过渡观察靠近，但尚未完成切换"
    return "否"


def _factor_state(snapshot, symbol):
    indicator = snapshot.indicators.get(symbol)
    if indicator is None:
        return "明确缺失"
    if symbol == "REAL_10Y" and indicator.value >= 2.1:
        return "高位压制"
    if indicator.weekly_change is None:
        return "方向不明"
    if indicator.weekly_change > 0:
        return "上行"
    if indicator.weekly_change < 0:
        return "下行"
    return "横盘"


def _breakeven_score(snapshot):
    breakeven = snapshot.indicators.get("BREAKEVEN_10Y")
    if breakeven is None:
        return 0
    if breakeven.monthly_change is not None and breakeven.monthly_change <= -0.1:
        return -1
    if breakeven.weekly_change is not None and breakeven.weekly_change > 0:
        return 1
    if breakeven.weekly_change is not None and breakeven.weekly_change < 0:
        return -1
    return 0


def _real_yield_score(snapshot):
    real = snapshot.indicators.get("REAL_10Y")
    if real is None:
        return 0
    if real.value >= 2.2:
        return -3
    if real.value >= 2.1:
        return -2
    if real.monthly_change is not None and real.monthly_change < -0.05:
        return 1
    return 0


def _medium_term_score(snapshot):
    return _breakeven_score(snapshot) + _real_yield_score(snapshot)


def _medium_term_judgment(snapshot):
    score = _medium_term_score(snapshot)
    if score >= 3:
        return "中期顺风"
    if score >= 1:
        return "弱顺风"
    if score == 0:
        return "不明"
    if score <= -4:
        return "强压制"
    return "中期承压"


def _source_for(snapshot, symbol: str) -> str:
    ref = snapshot.source_refs.get(symbol) or {}
    return str(ref.get("source") or "")


def _has_source(snapshot, *symbols: str) -> bool:
    refs = snapshot.source_refs
    for symbol in symbols:
        direct = refs.get(symbol)
        if direct:
            return True
    known_sources = " ".join(str(ref.get("source") or "") for ref in refs.values()).lower()
    return any(symbol.lower() in known_sources for symbol in symbols)


def _systemic_risk_rows(snapshot):
    rows = [
        "| 财政压力 | TGA 已进入系统快照 | 长期背景支撑，短线仍看 TGA 与准备金组合 |",
        "| 居民信用 | 未进入系统宏观快照 | 若联网补充，需标注为外部信息并沉淀为后续数据源 |",
        "| CRE / 中小银行 | 未进入系统宏观快照 | 若联网补充，需标注为外部信息并沉淀为后续数据源 |",
    ]
    rows.append(_source_row(snapshot, "HY OAS", ("HY_OAS", "BAMLH0A0HYM2"), "信用利差未系统化接入，不能直接升级为信用扩散"))
    rows.append(_source_row(snapshot, "VIX", ("VIX",), "波动率未系统化接入，不能直接升级为恐慌状态"))
    rows.append("| 黄金与实际利率关系 | 已用 US10Y - T10YIE 主口径观察 | 目前仍按实际利率与 DXY 主导处理 |")
    return rows


def _source_row(snapshot, label: str, symbols: tuple[str, ...], missing_judgment: str) -> str:
    if _has_source(snapshot, *symbols):
        return f"| {label} | 已有系统 source_ref | 可纳入系统风险判断 |"
    return f"| {label} | 未进入系统宏观快照 | {missing_judgment} |"


def _systemic_risk_conclusion(snapshot, conclusion):
    if conclusion.state == "流动性踩踏态":
        return "流动性事故风险"
    if _has_source(snapshot, "HY_OAS", "BAMLH0A0HYM2", "VIX"):
        return "需结合信用利差和波动率再确认"
    return "慢性挤压，尚未由系统数据确认信用扩散或货币信用重估"


def _state_sentence(conclusion, snapshot):
    return (
        f"原因是：数量层{conclusion.quantity_layer}、DXY {conclusion.dollar_layer}、"
        f"实际利率判断为{_real_rate_pressure(snapshot)}；短端价格层为{conclusion.price_layer}，"
        f"所以当前阶段仍需要由实际利率、DXY 与短端价格共同确认。"
    )
