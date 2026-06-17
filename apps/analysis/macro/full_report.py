from __future__ import annotations

from apps.analysis.macro.conclusion import MacroConclusion
from apps.analysis.macro.summary import _format_change, _format_value
from apps.features.macro.snapshot import MacroSnapshot


def render_macro_full_report_markdown(snapshot: MacroSnapshot, conclusion: MacroConclusion) -> str:
    lines: list[str] = [
        f"# XAUUSD 宏观 / 流动性更新（{snapshot.as_of}）", "",
        "## 一句话结论", "",
        _one_line(conclusion), "",
        "## 统一表格", "",
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
    lines.extend([
        "", "## 今日结论（黄金 + 机会成本 + 短端利率 / 通胀 + 美元）", "",
        f"**结论：{conclusion.bias}。**", "",
        f"- **流动性数量层：{conclusion.quantity_layer}。** {_quantity_sentence(snapshot)}",
        f"- **流动性价格层：{conclusion.price_layer}。** {_price_sentence(snapshot)}",
        f"- **黄金核心定价层：{conclusion.reasoning}**",
        f"- **美元层：{conclusion.dollar_layer}。** {_dollar_sentence(snapshot)}",
        f"- **综合判断：{conclusion.bias}但不激进。** 真正最有利于黄金的是数量层偏松与 DXY 转弱；真正还没完全配合的是短端资金价格和 2Y 仍高，所以现在更像 **过渡释放态**，不是 **趋势顺风态**。",
        "", "## 做单方向建议", "",
        f"- **基准方向：{conclusion.bias}**",
        f"- **更优打法：{conclusion.action_priority}**",
        "- **触发条件：**",
    ])
    lines.extend(f"  - {item}" for item in conclusion.trigger_upgrade)
    lines.extend(f"  - 降级条件：{item}" for item in conclusion.trigger_downgrade)
    lines.append("- **不建议做什么：**")
    lines.extend(f"  - {item}。" for item in conclusion.no_go_actions)
    lines.extend(["", "## 风险识别点", ""])
    for idx, risk in enumerate(conclusion.risks, 1):
        lines.append(f"{idx}. **{risk.title}**：{risk.detail}")
    lines.extend([
        "",
        '**动作规则：出现任意两条 → 黄金多头降级 / 防守；如果其中包含"DXY 反抽 + 10Y 实际利率回升"这一组组合，则短线反弹只按修复看，不按转势看。**',
        "", "## 当前所处环境三态判断", "",
        f"**当前更接近：{conclusion.state}。**", "",
        _state_sentence(conclusion),
        "", "## 数据口径说明", "",
        "- 通胀只看 **T10YIE**。",
        "- 10Y 实际利率固定采用 **FRED:DFII10（10年TIPS实际收益率）**。",
        "- DXY 采用系统输入的 DXY 最新值与其 1周 / 1月变化。",
        "- IORB 采用 Fed 官方 PRATES.json 自动采集。",
        "- TGA 采用 Treasury FiscalData API 自动采集；缺失时必须显式标记。",
        "", "## 数据源",
    ])
    if snapshot.source_refs:
        for symbol, ref in snapshot.source_refs.items():
            lines.append(f"- {symbol}: {ref.get('source', '')} {ref.get('source_url', '')} {ref.get('raw_path', '')}".rstrip())
    else:
        lines.append("- None")
    if conclusion.missing_inputs:
        lines.extend(["", "## 明确缺失输入", ""])
        lines.extend(f"- {s}" for s in conclusion.missing_inputs)
    lines.append("")
    return "\n".join(lines)


def _one_line(conclusion):
    return (
        f"今天黄金的宏观环境更接近 **{conclusion.bias}**：数量层和美元层偏向支持黄金；"
        f"但短端资金价格仍高，所以更适合按 **{conclusion.state}下的{conclusion.action}** 来处理，而不是直接追高。"
    )


def _report_order():
    return ["ON_RRP_USAGE", "ON_RRP_AWARD_RATE", "TGA", "RESERVES", "SOFR", "EFFR", "IORB", "US02Y", "US10Y", "BREAKEVEN_10Y", "REAL_10Y", "YIELD_SPREAD_10Y_2Y", "DXY"]


def _label_for(symbol):
    return {
        "ON_RRP_USAGE": "ON RRP 使用量", "ON_RRP_AWARD_RATE": "ON RRP Award Rate", "TGA": "TGA",
        "RESERVES": "Reserve Balances", "SOFR": "SOFR", "EFFR": "EFFR", "IORB": "IORB",
        "US02Y": "US02Y", "US10Y": "US10Y", "BREAKEVEN_10Y": "10Y Breakeven（T10YIE）",
        "REAL_10Y": "10Y 实际利率（FRED:DFII10）", "YIELD_SPREAD_10Y_2Y": "10Y-2Y 利差", "DXY": "DXY"
    }.get(symbol, symbol)


def _fmt_signed(value: float | None, *, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return "暂无"
    return f"{value:+.{digits}f}{suffix}"


def _quantity_sentence(snapshot):
    tga, reserves, rrp = snapshot.indicators.get("TGA"), snapshot.indicators.get("RESERVES"), snapshot.indicators.get("ON_RRP_USAGE")
    if tga and reserves and rrp:
        return f"RRP 当前 {rrp.value:.3f}B，TGA 周变化 {_fmt_signed(tga.weekly_change, digits=3, suffix='B')}，准备金周变化 {_fmt_signed(reserves.weekly_change, digits=3, suffix='B')}，组合上更接近 RRP低位 + TGA下降 + 准备金上升。"
    return "关键数量层输入不完整，系统只做降级判断。"


def _price_sentence(snapshot):
    vals = [snapshot.indicators.get(s) for s in ("SOFR", "EFFR", "IORB", "US02Y")]
    if all(vals):
        sofr, effr, iorb, us02y = vals
        return f"SOFR {sofr.value:.2f}%，EFFR {effr.value:.2f}%，IORB {iorb.value:.2f}%，2Y {us02y.value:.2f}%，短端机会成本仍在高位。"
    return "短端价格层输入不完整，不能确认真正宽松。"


def _dollar_sentence(snapshot):
    dxy = snapshot.indicators.get("DXY")
    if dxy:
        return f"DXY 当前约 {dxy.value:.3f}，1周变化 {_fmt_signed(dxy.weekly_change)}，1月变化 {_fmt_signed(dxy.monthly_change)}。"
    return "DXY 缺失，美元层只能降级为中性。"


def _state_sentence(conclusion):
    return (
        f"原因是：数量层{conclusion.quantity_layer}、DXY {conclusion.dollar_layer}、10Y 实际利率中期缓和，"
        f"这些都说明黄金对宏观利空的压力在减轻；但 EFFR / IORB / 2Y 的绝对水平仍高，所以还不是趋势顺风态。"
    )
