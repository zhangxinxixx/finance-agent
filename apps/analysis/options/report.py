"""Render options analysis as a Chinese Markdown report.

Sections follow the MVP template from cme_gold_options_analysis_rules_prompt.md:
  一句话结论 | 数据口径 | 核心 GEX 结果 | 重点墙位 |
  GEX / Gamma Zero | Delta/Vega/Theta | 订单墙 / WallScore |
  Roll / 换月迁移 | I1-I4 机构意图 | 支撑/阻力 |
  IV Smile / Skew | 实盘策略卡片 | 数据质量与局限性.
"""

from __future__ import annotations

from apps.analysis.options.snapshot import OptionsAnalysisResult

# ---------------------------------------------------------------------------
# Intent type labels (Chinese)
# ---------------------------------------------------------------------------

_INTENT_LABELS: dict[str, tuple[str, str]] = {
    "I1_defensive": ("I1 防守型", "Put 侧集中持仓，机构在保护下行风险"),
    "I2_structured_rebalance": ("I2 结构再平衡", "Call/Put GEX 结构相对均衡，机构更像在做区间再平衡或结构性对冲；单日 OI 变化需单独核对，不等同于双边增仓"),
    "I3_trap": ("I3 诱多/诱空", "近价 strike 出现 OI 减少 + 高成交量，存在假突破陷阱"),
    "I4_trend_launch": ("I4 趋势启动", "单边 Call 或 Put 大量增仓，机构可能在押注方向性突破"),
}

_WALL_TYPE_LABELS: dict[str, str] = {
    "active": "活墙",
    "static": "静墙",
    "turnover": "换手墙",
    "new": "新增墙",
    "pin": "Pin 墙",
    "resistance": "阻力墙",
    "support": "支撑墙",
}

_ROLL_TYPE_LABELS: dict[str, str] = {
    "call_roll_up": "Call Roll Up（看涨移仓上行）",
    "put_roll_down": "Put Roll Down（看跌移仓下行）",
    "protection_upshift": "保护性 Put 上移（收紧保护）",
    "upside_tail_migration": "上行尾部迁移",
}

_STRUCTURE_LABELS: dict[str, str] = {
    "net_call_dominated": "Call-GEX 主导，上方弹性更强",
    "net_put_dominated": "Put-GEX 主导，下方保护明显",
    "balanced": "Call/Put 均衡",
}


def _fmt_num(value: float, decimals: int = 2) -> str:
    if abs(value) >= 1e9:
        return f"{value / 1e9:.{decimals}f}B"
    if abs(value) >= 1e6:
        return f"{value / 1e6:.{decimals}f}M"
    if abs(value) >= 1e3:
        return f"{value / 1e3:.{decimals}f}K"
    return f"{value:.{decimals}f}"


def _fmt_pct(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:.{decimals}f}%"


def _wall_type_zh(wall_type: str) -> str:
    return _WALL_TYPE_LABELS.get(wall_type, wall_type)


def _fmt_maybe_num(value: object, decimals: int = 1) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.{decimals}f}"
    if value is None:
        return "N/A"
    return str(value)


def _dominant_side(net_gex: float, total_gex: float | None = None) -> str:
    """Classify economic GEX bias for display.

    Wall side can be BOTH for active/pin walls; this helper exposes whether
    CallGEX or PutGEX is economically dominant at the strike.
    """
    if total_gex and abs(net_gex) <= abs(total_gex) * 0.05:
        return "Balanced"
    if net_gex > 0:
        return "Call"
    if net_gex < 0:
        return "Put"
    return "Balanced"


def _wall_role_from_bias(net_gex: float, strike: int, gamma_zero: float | None) -> str:
    if gamma_zero is not None and abs(strike - gamma_zero) <= 25:
        return "Gamma Zero / 方向分水岭"
    if net_gex < 0:
        return "Put 防守 / 支撑"
    if net_gex > 0:
        return "Call 压制 / 修复目标"
    return "双边换手 / 磁吸"


def _audit_counts(result: OptionsAnalysisResult) -> dict[str, int | float]:
    proxy_rows = sum(1 for exposure in result.exposures if exposure.method == "proxy")
    black76_rows = sum(1 for exposure in result.exposures if exposure.method == "black76")
    total_abs_gex = sum(abs(exposure.gex_1pct) for exposure in result.exposures)
    proxy_abs_gex = sum(abs(exposure.gex_1pct) for exposure in result.exposures if exposure.method == "proxy")
    return {
        "raw_rows": result.norm_report.total_input_rows,
        "range_rows": sum(
            1 for row in result.normalized_rows
            if result.analysis_strike_min <= row.strike <= result.analysis_strike_max
        ),
        "valid_rows": len(result.normalized_rows),
        "black76_rows": black76_rows,
        "proxy_rows": proxy_rows,
        "proxy_gex_share": proxy_abs_gex / total_abs_gex if total_abs_gex > 0 else 0.0,
    }


def _intent_wording(label_zh: str, confidence: float) -> str:
    if "I2" in label_zh and confidence < 0.6:
        return "I2 结构再平衡，偏防守，置信度中低"
    return label_zh


def _directional_targets(
    candidates: list[float | int | None],
    *,
    anchor: float,
    direction: str,
) -> list[float]:
    unique: dict[float, float] = {}
    for candidate in candidates:
        if candidate is None:
            continue
        value = float(candidate)
        if direction == "up" and value <= anchor:
            continue
        if direction == "down" and value >= anchor:
            continue
        unique.setdefault(round(value, 6), value)
    return sorted(unique.values(), reverse=direction == "down")[:3]


def _target_label(index: int) -> str:
    return {1: "第一目标", 2: "第二目标", 3: "第三目标"}.get(index, f"目标 {index}")


def _aggregate_position_levels(result: OptionsAnalysisResult) -> list[dict[str, float | int | None]]:
    """Aggregate absolute CME inventory by strike across selected expiries."""
    levels: dict[int, dict[str, float | int]] = {}
    for metric in result.strike_metrics:
        level = levels.setdefault(
            metric.strike,
            {
                "strike": metric.strike,
                "call_oi": 0,
                "put_oi": 0,
                "oi_change": 0,
                "volume": 0,
                "pnt_block": 0,
                "total_gex": 0.0,
                "net_gex": 0.0,
            },
        )
        level["call_oi"] += metric.call_oi
        level["put_oi"] += metric.put_oi
        level["oi_change"] += metric.call_oi_change + metric.put_oi_change
        level["volume"] += metric.call_volume + metric.put_volume
        level["pnt_block"] += metric.call_pnt + metric.put_pnt + metric.call_block + metric.put_block
        level["total_gex"] += abs(metric.call_gex) + abs(metric.put_gex)
        level["net_gex"] += metric.net_gex

    for level in levels.values():
        level["total_oi"] = int(level["call_oi"]) + int(level["put_oi"])
        level["distance_pct"] = (
            (int(level["strike"]) - result.report_p0) / result.report_p0 * 100
            if result.report_p0
            else None
        )
    return sorted(levels.values(), key=lambda item: (int(item["total_oi"]), int(item["volume"])), reverse=True)


def _scenario_levels(
    result: OptionsAnalysisResult,
    *,
    anchor: float | None,
) -> tuple[list[float], list[float]]:
    if anchor is None:
        return [], []
    strikes = sorted({float(metric.strike) for metric in result.strike_metrics})
    supports = sorted((strike for strike in strikes if strike < anchor), reverse=True)[:3]
    resistances = sorted(strike for strike in strikes if strike > anchor)[:4]
    return supports, resistances


def render_options_report_markdown(result: OptionsAnalysisResult) -> str:
    """Render the full Chinese Markdown report."""
    lines: list[str] = []
    report_p0 = result.report_p0
    live_p0 = result.live_p0
    p0 = report_p0
    gz = result.netgex.gamma_zero
    near_month = result.expiries[0] if result.expiries else None
    next_month = result.expiries[1] if len(result.expiries) > 1 else None

    # =====================================================================
    # Title
    # =====================================================================
    lines.append(f"# CME 黄金期权结构分析报告 — {result.trade_date}")
    lines.append("")
    lines.append(f"> 数据产品: {result.product} | 生成时间: {result.generated_at}")
    lines.append(f"> 分析月份: {', '.join(result.expiries)}")
    lines.append(f"> 主交易区间: {result.analysis_strike_min}–{result.analysis_strike_max}（{result.analysis_range_source}）；区间外只作为尾部/异常提示")
    if near_month and next_month:
        lines.append(f"> 近月 / 次月对比: {near_month} vs {next_month}")
    lines.append("")

    # =====================================================================
    # 0. ⚠️ 数据声明
    # =====================================================================
    source_status = result.data_source_status
    status_display = {
        "PRELIM": "PRELIM（初步）",
        "PRELIMINARY": "PRELIM（初步）",
        "FINAL": "FINAL（最终）",
        "UNKNOWN": "未知",
        "PRELIM_assumed": "PRELIM（假定，来源未确认）",
    }.get(source_status, source_status)

    lines.append("## ⚠️ 数据声明")
    lines.append("")
    lines.append(f"- **数据状态: {status_display}**，最终数据可能修正。")
    if result.data_source_url:
        lines.append(f"- 来源: {result.data_source_url}")
    lines.append("- 价格口径: `model_f` / `report_p0` / `live_p0` 三者分离；算 Gamma/GEX 用各到期月自己的 model_f，不用实时 XAUUSD spot 代替。")
    model_f_text = ", ".join(
        f"{expiry}={_fmt_maybe_num((result.forward_by_expiry.get(expiry) or {}).get('f_value'))}"
        for expiry in result.expiries
    )
    lines.append(f"- model_f: {model_f_text}（Black-76 / GEX / Gamma Zero 用价）。")
    if result.report_p0 is not None:
        ts = f"，时间: {result.report_p0_timestamp}" if result.report_p0_timestamp else ""
        lines.append(f"- report_p0: {result.report_p0:.2f}（source={result.report_p0_source}{ts}），用于日终结构、主交易区和 WallScore 距离权重。")
    else:
        lines.append("- report_p0: 未提供；结构支撑/阻力仍可输出，但不按日终锚排序。")
    if result.live_p0 is not None:
        ts = f"，时间: {result.live_p0_timestamp}" if result.live_p0_timestamp else ""
        lines.append(f"- live_p0: {result.live_p0:.2f}（source={result.live_p0_source}{ts}），仅用于实盘策略卡片和当前价格上下排序。")
        lines.append("- 时间差提示: 期权结构基于 CME trade_date 数据；live_p0 是分析时实时价格，二者可能存在时间错配。")
    else:
        lines.append("- live_p0: 未提供；本报告不输出现价驱动的实盘策略卡片，只输出结构支撑/阻力。")
    lines.append("- IV 通过 Black-76 模型从结算价反推，未使用市场报价的隐含波动率。")
    lines.append("- GEX 为模型 Gamma Exposure，按标的期货价格 1% move 标准化，单位为美元/1% move 的估算敞口；不是 Delta 名义敞口，也不等于真实 dealer inventory。")
    lines.append("- Gamma Zero 仅基于可计算 Black-76 Gamma 的行；Proxy 行不参与零轴拟合，仅用于静态墙位/风险提示。")
    lines.append("- 本报告不构成交易建议，不涉及自动下单。")
    lines.append("- 所有分析仅为结构识别和情景推演，需人工判断后决策。")
    lines.append("")

    # =====================================================================
    # 1. 一句话结论
    # =====================================================================
    lines.append("## 一句话结论")
    lines.append("")

    intent = result.intent
    primary = intent.primary_intent
    intent_type_val = primary.intent_type.value if hasattr(primary.intent_type, "value") else str(primary.intent_type)
    label_zh, desc_zh = _INTENT_LABELS.get(intent_type_val, (intent_type_val, ""))

    display_intent = _intent_wording(label_zh, primary.confidence)
    near_summary = result.gex_summary_by_expiry.get(near_month, {}) if near_month else {}
    next_summary = result.gex_summary_by_expiry.get(next_month, {}) if next_month else {}
    near_gz = near_summary.get("gamma_zero")
    next_gz = next_summary.get("gamma_zero")
    next_f = next_summary.get("f_value")

    top_put_walls = [sw for sw in result.scored_walls if sw.wall.net_gex < 0]
    top_call_walls = [sw for sw in result.scored_walls if sw.wall.net_gex > 0]
    top_put_walls.sort(key=lambda sw: (sw.wall_score, abs(sw.wall.net_gex)), reverse=True)
    top_call_walls.sort(key=lambda sw: (sw.wall_score, abs(sw.wall.net_gex)), reverse=True)
    main_floor = top_put_walls[0].wall.strike if top_put_walls else None
    repair_floor = (gz + 40) if isinstance(gz, (int, float)) else ((report_p0 + 40) if report_p0 else None)
    repair_candidates = [
        sw.wall.strike
        for sw in result.scored_walls
        if sw.wall.net_gex > 0
        and (repair_floor is None or sw.wall.strike >= repair_floor)
        and (report_p0 is None or sw.wall.strike >= report_p0)
    ]
    repair_candidates = sorted(set(repair_candidates))
    # Prefer round 50/100 strike repair bands above Gamma Zero, not tiny walls
    # sitting on the zero-axis itself.
    round_repair_candidates = [strike for strike in repair_candidates if strike % 50 == 0]
    display_repair_candidates = round_repair_candidates or repair_candidates
    repair_text = "–".join(str(x) for x in display_repair_candidates[:2]) if display_repair_candidates else None

    sentence_parts = [
        f"{result.trade_date} {'+'.join(result.expiries[:2])} 黄金期权结构为 {display_intent}",
    ]
    if near_month and isinstance(near_gz, (int, float)):
        if main_floor:
            sentence_parts.append(f"{near_month} 主导短线 Gamma，{main_floor} 是主结构防守位，{near_gz:.0f} 附近是近月转强分水岭")
        else:
            sentence_parts.append(f"{near_month} 主导短线 Gamma，{near_gz:.0f} 附近是近月转强分水岭")
    if next_month and isinstance(next_gz, (int, float)) and isinstance(next_f, (int, float)) and next_f < next_gz:
        sentence_parts.append(f"{next_month} 当前也在 Gamma Zero 下方，说明次月仍偏保护")
    if gz is not None:
        if repair_text:
            sentence_parts.append(f"跨月 Gamma Zero 约 {gz:.0f}，只有重新站上零轴并接受 {repair_text}，结构才会从防守再平衡转向修复延续")
        else:
            sentence_parts.append(f"跨月 Gamma Zero 约 {gz:.0f}")
    lines.append("。".join(sentence_parts) + "。")
    if desc_zh:
        lines.append(f"> {desc_zh}")
    lines.append("")

    # =====================================================================
    # 2. 数据口径
    # =====================================================================
    lines.append("## 数据口径")
    lines.append("")
    nr = result.norm_report
    audit_counts = _audit_counts(result)
    lines.append("| 字段 | 数值 | 含义 |")
    lines.append("| :--- | ---: | :--- |")
    lines.append(f"| product_rows | {audit_counts['raw_rows']} | PDF 解析后、产品过滤后的原始明细行 |")
    lines.append(f"| valid_rows | {audit_counts['valid_rows']} | 全链标准化有效行，保留用于尾部/异常扫描 |")
    lines.append(f"| analysis_range | {result.analysis_strike_min}–{result.analysis_strike_max} | 主交易区间，用于 GEX Top / WallScore / 支撑阻力 / 策略 |")
    lines.append(f"| range_rows | {audit_counts['range_rows']} | 落在主交易区间内的行 |")
    lines.append(f"| excluded_outside_analysis_range | {audit_counts['valid_rows'] - audit_counts['range_rows']} | 不进入主排名，仅进入区间外异常/尾部提示 |")
    lines.append(f"| full_chain_filter_excluded | {nr.rows_filtered_by_strike} | 全链硬过滤剔除行，默认 2000–12000 外 |")
    lines.append(f"| rows_missing_settlement | {nr.rows_missing_settlement} | 缺失 settlement 的行 |")
    lines.append(f"| rows_missing_delta | {nr.rows_missing_delta} | 缺失 delta 的行 |")
    lines.append(f"| black76_rows | {audit_counts['black76_rows']} | 可反推 IV 并使用 Black-76 Gamma 的行 |")
    lines.append(f"| proxy_rows | {audit_counts['proxy_rows']} | 使用 Gamma Proxy 的行 |")
    lines.append(f"| proxy_gex_share | {audit_counts['proxy_gex_share']:.2%} | Proxy GEX 占总绝对 GEX 的比例 |")
    lines.append("")
    lines.append("- 模型: Black-76（优先结算价反推 IV；无法反推 IV 的行降级为 Gamma Proxy）。")
    lines.append("- Gamma Zero: 仅用主交易区间内的 Black-76 可估值行计算；Proxy 行不参与零轴拟合。")
    lines.append("- WallScore 默认只在主交易区间内排序；区间外 strike 只进入尾部/异常提示，不直接进入支撑阻力和策略卡片。")
    lines.append("- 贴现因子: r=0，D≈1；短期限黄金期权中对 Gamma/GEX 影响较小，但仍在审计字段中显式记录。")
    lines.append("")
    lines.append("| 到期月 | trade_date | expiry_date | T | F | F_source | D |")
    lines.append("| :---: | :---: | :---: | ---: | ---: | :--- | ---: |")
    for expiry in result.expiries:
        T = result.time_to_expiry.get(expiry, 0)
        exp_date = result.expiry_dates.get(expiry, "")
        fw = result.forward_by_expiry.get(expiry, {})
        f_val = fw.get("f_value", "N/A")
        f_src = fw.get("f_source", "")
        discount = 1.0
        f_display = f"{f_val:.1f}" if isinstance(f_val, (int, float)) else "N/A"
        lines.append(f"| {expiry} | {result.trade_date} | {exp_date} | {T:.4f} | {f_display} | {f_src} | {discount:.4f} |")
    lines.append("")

    # =====================================================================
    # 3. 核心 GEX 结果（per-expiry summary table，对标目标报告）
    # =====================================================================
    lines.append("## 核心 GEX 结果")
    lines.append("")
    lines.append("| 到期月 | F | Gamma Zero | NetGEX | CallGEX | PutGEX | 结构 |")
    lines.append("| :---: | ---: | ---: | ---: | ---: | ---: | :--- |")
    for expiry in result.expiries:
        summary = result.gex_summary_by_expiry.get(expiry, {})
        lines.append(
            f"| {expiry} "
            f"| {summary.get('f_value', 'N/A'):.1f}" if isinstance(summary.get("f_value"), (int, float))
            else f"| {expiry} | {summary.get('f_value', 'N/A')}"
        )
        lines[-1] += (
            f" | {summary.get('gamma_zero') or '—'} "
            f"| {_fmt_num(summary.get('net_gex', 0))} "
            f"| {_fmt_num(summary.get('call_gex', 0))} "
            f"| {_fmt_num(summary.get('put_gex', 0))} "
            f"| {_STRUCTURE_LABELS.get(summary.get('structure', ''), '')} |"
        )
    lines.append("")
    if gz is not None:
        lines.append(f"跨月 NetGEX 零轴（Gamma Zero）: **{gz:.1f}**（{result.netgex.gamma_zero_method}）")
        lines.append("")
        compared_expiries = " 与 ".join(result.expiries[:2])
        lines.append(
            f"> 跨月 Gamma Zero 是 {compared_expiries} 在同一假设价格网格下的 "
            "NetGEX 汇总曲线零点，即 `Σ NetGEX_expiry(F_grid)=0`，不是两个单月 "
            "Gamma Zero 的简单平均。"
        )
    lines.append("")

    if near_month and next_month:
        lines.append("## 近月 / 次月对比")
        lines.append("")
        lines.append("| 项目 | 近月 | 次月 |")
        lines.append("| :--- | ---: | ---: |")
        near_summary = result.gex_summary_by_expiry.get(near_month, {})
        next_summary = result.gex_summary_by_expiry.get(next_month, {})
        near_iv = result.iv_skew_by_expiry.get(near_month, {})
        next_iv = result.iv_skew_by_expiry.get(next_month, {})
        lines.append(f"| 到期月 | {near_month} | {next_month} |")
        lines.append(f"| F | {_fmt_maybe_num(near_summary.get('f_value'))} | {_fmt_maybe_num(next_summary.get('f_value'))} |")
        lines.append(f"| Gamma Zero | {_fmt_maybe_num(near_summary.get('gamma_zero'))} | {_fmt_maybe_num(next_summary.get('gamma_zero'))} |")
        lines.append(f"| NetGEX | {_fmt_num(near_summary.get('net_gex', 0))} | {_fmt_num(next_summary.get('net_gex', 0))} |")
        lines.append(f"| CallGEX | {_fmt_num(near_summary.get('call_gex', 0))} | {_fmt_num(next_summary.get('call_gex', 0))} |")
        lines.append(f"| PutGEX | {_fmt_num(near_summary.get('put_gex', 0))} | {_fmt_num(next_summary.get('put_gex', 0))} |")
        lines.append(
            f"| 结构 | {_STRUCTURE_LABELS.get(near_summary.get('structure', ''), '')} | {_STRUCTURE_LABELS.get(next_summary.get('structure', ''), '')} |"
        )
        lines.append(f"| ATM IV | {_fmt_pct(near_iv.get('atm_iv'), 2)} | {_fmt_pct(next_iv.get('atm_iv'), 2)} |")
        lines.append(f"| 25D Skew | {_fmt_pct(near_iv.get('skew_25d'), 2)} | {_fmt_pct(next_iv.get('skew_25d'), 2)} |")
        lines.append(f"| 10D Tail Skew | {_fmt_pct(near_iv.get('tail_skew_10d'), 2)} | {_fmt_pct(next_iv.get('tail_skew_10d'), 2)} |")
        lines.append("")
        for label, summary in [(near_month, near_summary), (next_month, next_summary)]:
            f_val = summary.get("f_value")
            gzero = summary.get("gamma_zero")
            if isinstance(f_val, (int, float)) and isinstance(gzero, (int, float)):
                if f_val < gzero:
                    lines.append(f"- {label}: 当前 F≈{f_val:.1f} 低于 Gamma Zero≈{gzero:.1f}，当前价格区间更偏 Put-GEX / 保护结构；价格修复到零轴上方后才逐步转向 Call-GEX 主导。")
                else:
                    lines.append(f"- {label}: 当前 F≈{f_val:.1f} 高于 Gamma Zero≈{gzero:.1f}，当前价格区间更偏 Call-GEX 主导。")
        lines.append("")

    # =====================================================================
    # 3b. GEX / Gamma Zero (existing heading, backward compat)
    # =====================================================================
    lines.append("## GEX / Gamma Zero")
    lines.append("")
    if result.used_real_gex:
        lines.append("> ✅ 使用 Black-76 真实 Gamma 计算 GEX")
    else:
        lines.append("> ⚠️ 使用 Gamma Proxy（|Δ| × (1 - |Δ|)），因为无法可靠计算 IV")
    lines.append("> 说明：每个 expiry 的 GEX / Greeks 使用该 expiry 自身的 F/T 计算；NetGEX 零轴为跨 expiry 的汇总曲线。")
    lines.append("> Gamma Zero 仅基于主交易区间内可反推 IV 的 Black-76 行；Proxy 行不参与零轴拟合，避免静态 proxy 污染零轴。")
    lines.append("")

    for expiry, gex_top in result.gex_top_by_expiry.items():
        lines.append(f"### {expiry} — GEX Top Strikes")
        lines.append("")
        lines.append("| Strike | Call GEX | Put GEX | Net GEX | Total GEX |")
        lines.append("| ---: | ---: | ---: | ---: | ---: |")
        for row in gex_top[:10]:
            lines.append(
                f"| {row['strike']} "
                f"| {_fmt_num(row['call_gex'])} "
                f"| {_fmt_num(row['put_gex'])} "
                f"| {_fmt_num(row['net_gex'])} "
                f"| {_fmt_num(row['total_gex'])} |"
            )
        lines.append("")

    if gz is not None:
        lines.append(f"**Gamma Zero（NetGEX 零轴）≈ {gz:.1f}**（方法: {result.netgex.gamma_zero_method}）")
        lines.append("> 4600 附近只代表进入 Call-GEX 更占优的结构区，仍需 4650/4700 接受确认，不能单独视为趋势启动。")
        if p0 is not None:
            if gz > p0:
                lines.append(f"> report_p0 {p0:.0f} 位于 Gamma Zero 下方 → 日终结构处于 Put-GEX/保护影响区；盘中另看 live_p0。")
            else:
                lines.append(f"> report_p0 {p0:.0f} 位于 Gamma Zero 上方 → 日终结构处于 Call-GEX 主导区；盘中另看 live_p0。")
    else:
        lines.append("**Gamma Zero: 无法确定**（NetGEX 未发生正负切换）")
    lines.append("")

    # =====================================================================
    # 3c. 重点墙位（per-expiry，对标目标报告）
    # =====================================================================
    for expiry in result.expiries:
        # Collect GEX and OI/ΔOI from strike_metrics for this expiry
        sm_for_expiry = [sm for sm in result.strike_metrics if sm.expiry == expiry]
        strike_info: dict[int, dict] = {}
        for sm in sm_for_expiry:
            strike_info[sm.strike] = {
                "call_oi": sm.call_oi,
                "put_oi": sm.put_oi,
                "call_oi_change": sm.call_oi_change,
                "put_oi_change": sm.put_oi_change,
                "call_volume": sm.call_volume,
                "put_volume": sm.put_volume,
                "call_block": sm.call_block,
                "put_block": sm.put_block,
                "call_pnt": sm.call_pnt,
                "put_pnt": sm.put_pnt,
            }

        gex_top = result.gex_top_by_expiry.get(expiry, [])
        if not gex_top:
            continue

        lines.append(f"### {expiry} 重点墙位")
        lines.append("")
        lines.append("| Strike | Total GEX | CallGEX | PutGEX | NetGEX | OI | ΔOI | 结论 |")
        lines.append("| ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |")
        for row in gex_top[:8]:
            strike = row["strike"]
            info = strike_info.get(strike, {})
            call_oi = info.get("call_oi", 0)
            put_oi = info.get("put_oi", 0)
            total_oi = call_oi + put_oi
            doi = (info.get("call_oi_change", 0) or 0) + (info.get("put_oi_change", 0) or 0)
            call_block = info.get("call_block", 0) or 0
            put_block = info.get("put_block", 0) or 0
            call_pnt = info.get("call_pnt", 0) or 0
            put_pnt = info.get("put_pnt", 0) or 0
            block_pnt = call_block + put_block + call_pnt + put_pnt

            # Generate conclusion sentence
            conclusions: list[str] = []
            if row["net_gex"] > 0:
                conclusions.append("Call 主导")
            else:
                conclusions.append("Put 主导")
            if doi > 0:
                conclusions.append("新增")
            elif doi < 0:
                conclusions.append("减仓")
            if block_pnt > 0:
                conclusions.append(f"PNT/Block {block_pnt}")
            if total_oi >= 5000:
                conclusions.append("大仓")

            lines.append(
                f"| {strike} "
                f"| {_fmt_num(row['total_gex'])} "
                f"| {_fmt_num(row['call_gex'])} "
                f"| {_fmt_num(row['put_gex'])} "
                f"| {_fmt_num(row['net_gex'])} "
                f"| {total_oi} "
                f"| {doi:+,} "
                f"| {', '.join(conclusions) if conclusions else '观测'} |"
            )
        lines.append("")

        # Support / resistance per expiry
        if p0 is not None:
            supports = []
            resistances = []
            for row in gex_top:
                s = row["strike"]
                if s < p0:
                    supports.append(row)
                elif s > p0:
                    resistances.append(row)

            lines.append(f"**{expiry} 支撑：**")
            lines.append("")
            if supports:
                for s in sorted(supports, key=lambda x: x["total_gex"], reverse=True)[:3]:
                    lines.append(f"- **{s['strike']}**：Total GEX {_fmt_num(s['total_gex'])}，下方核心支撑")
            else:
                lines.append("- 无明显支撑候选")
            lines.append("")

            lines.append(f"**{expiry} 阻力：**")
            lines.append("")
            if resistances:
                for r in sorted(resistances, key=lambda x: x["total_gex"], reverse=True)[:3]:
                    lines.append(f"- **{r['strike']}**：Total GEX {_fmt_num(r['total_gex'])}，上方核心阻力")
            else:
                lines.append("- 无明显阻力候选")
        lines.append("")

    # =====================================================================
    # 3d. 绝对持仓 / 近期流量（独立于 WallScore）
    # =====================================================================
    all_position_levels = _aggregate_position_levels(result)
    nearby_position_levels = [
        level for level in all_position_levels
        if level["distance_pct"] is not None and abs(float(level["distance_pct"])) <= 6.0
    ]
    position_levels = nearby_position_levels or all_position_levels
    lines.append("## CME 大额持仓与近期流量")
    lines.append("")
    if nearby_position_levels:
        lines.append("> 本表按 CME report_p0 约 ±6% 主战区筛选后，再按合并绝对 OI 排序；不等同于 WallScore。远端库存仅作参考，墙位与方向判断仍需同时参考 NetGEX、ΔOI 与 PNT/Block。")
    else:
        lines.append("> 未提供 CME report_p0 或主战区无有效点位，本表回退为全链绝对 OI 排序；不等同于 WallScore。墙位与方向判断仍需同时参考 NetGEX、ΔOI 与 PNT/Block。")
    lines.append("")
    lines.append("| Strike | Call OI | Put OI | Total OI | ΔOI | Volume | PNT/Block | Total GEX | NetGEX | 结构解读 |")
    lines.append("| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |")
    for level in position_levels[:10]:
        net_gex = float(level["net_gex"])
        interpretation = _wall_role_from_bias(net_gex, int(level["strike"]), gz)
        lines.append(
            f"| {level['strike']} | {int(level['call_oi']):,} | {int(level['put_oi']):,} "
            f"| {int(level['total_oi']):,} | {int(level['oi_change']):+,} | {int(level['volume']):,} "
            f"| {int(level['pnt_block']):,} | {_fmt_num(float(level['total_gex']))} "
            f"| {_fmt_num(net_gex)} | {interpretation} |"
        )
    lines.append("")
    remote_levels = [level for level in all_position_levels if level not in position_levels]
    if nearby_position_levels and remote_levels:
        lines.append("- 全链远端大仓参考：" + "、".join(f"{level['strike']}（OI {int(level['total_oi']):,}）" for level in remote_levels[:5]) + "。")
        lines.append("")
    block_total = sum(metric.call_block + metric.put_block for metric in result.strike_metrics)
    if block_total <= 0 and any(int(level["pnt_block"]) > 0 for level in all_position_levels):
        lines.append("- Block 数据本次没有观测到非零值，Block 总量按未核验处理；不要把 0 解读为确定没有 Block 成交。")
        lines.append("")
    active_pnt = [level for level in all_position_levels if int(level["pnt_block"]) > 0]
    if active_pnt:
        lines.append("### PNT / Block 质量分类")
        lines.append("")
        for level in sorted(active_pnt, key=lambda item: int(item["pnt_block"]), reverse=True)[:8]:
            flow_label = "新增候选" if int(level["oi_change"]) > 0 else "换手/迁仓候选"
            lines.append(
                f"- **{level['strike']}**：PNT/Block {int(level['pnt_block']):,}，"
                f"ΔOI {int(level['oi_change']):+,}，归类为{flow_label}；不将大宗成交单独解读为方向性新增。"
            )
        lines.append("")

    # =====================================================================
    # 4. Delta / Vega / Theta Exposure
    # =====================================================================
    lines.append("## Delta / Vega / Theta Exposure")
    lines.append("")
    lines.append("> Net DEX 判断方向敞口；Total VEX 判断波动率敏感度；Total Theta/day 判断 Pin / 时间衰减压力。策略默认使用 by-strike 聚合，by-leg 仅用于定位具体 Call/Put 合约腿。")
    lines.append("")
    lines.append("| 指标 | " + " | ".join(result.expiries) + " | 合并 |")
    lines.append("| :--- | " + " | ".join(["---:" for _ in result.expiries]) + " | ---: |")
    net_dex_by_expiry = {expiry: result.exposure_summary_by_expiry.get(expiry, {}).get("net_dex", 0.0) for expiry in result.expiries}
    total_vex_by_expiry: dict[str, float] = {}
    total_theta_by_expiry: dict[str, float] = {}
    top_vex_strike_by_expiry: dict[str, object] = {}
    top_theta_strike_by_expiry: dict[str, object] = {}
    for expiry in result.expiries:
        exp_sum = result.exposure_summary_by_expiry.get(expiry, {})
        total_vex_by_expiry[expiry] = sum(abs(item.get("vex", 0.0)) for item in exp_sum.get("vex_top_by_strike", []))
        total_theta_by_expiry[expiry] = sum(item.get("theta_exposure", 0.0) for item in exp_sum.get("theta_top_by_strike", []))
        top_vex_strike_by_expiry[expiry] = (exp_sum.get("vex_top_by_strike") or [{}])[0].get("strike", "—")
        top_theta_strike_by_expiry[expiry] = (exp_sum.get("theta_top_by_strike") or [{}])[0].get("strike", "—")
    lines.append("| Net Delta Exposure | " + " | ".join(_fmt_num(net_dex_by_expiry[e]) for e in result.expiries) + f" | {_fmt_num(sum(net_dex_by_expiry.values()))} |")
    lines.append("| Total Vega Exposure* | " + " | ".join(_fmt_num(total_vex_by_expiry[e]) for e in result.expiries) + f" | {_fmt_num(sum(total_vex_by_expiry.values()))} |")
    lines.append("| Total Theta/day* | " + " | ".join(_fmt_num(total_theta_by_expiry[e]) for e in result.expiries) + f" | {_fmt_num(sum(total_theta_by_expiry.values()))} |")
    lines.append("| Vega Top Strike | " + " | ".join(str(top_vex_strike_by_expiry[e]) for e in result.expiries) + " | — |")
    lines.append("| Theta Top Strike | " + " | ".join(str(top_theta_strike_by_expiry[e]) for e in result.expiries) + " | — |")
    lines.append("")
    lines.append("\* Total VEX/Theta 为主交易区 by-strike Top 列表的聚合摘要，用于报告层风险定位，不替代完整逐腿明细。")
    lines.append("")
    for expiry, exp_sum in result.exposure_summary_by_expiry.items():
        lines.append(f"### {expiry}")
        lines.append("")
        net_dex = exp_sum["net_dex"]
        lines.append(f"- **Net Delta Exposure (DEX):** {_fmt_num(net_dex)}")
        if net_dex > 0:
            lines.append("  > 正 DEX — Call 侧 delta 敞口更大，价格上涨时 delta 收益更高")
        elif net_dex < 0:
            lines.append("  > 负 DEX — Put 侧 delta 敞口更大，价格下跌时 delta 收益更高")
        else:
            lines.append("  > DEX 中性")

        if exp_sum.get("vex_top_by_strike"):
            lines.append("- **Vega Top by strike (1vol，主策略默认口径):**")
            for item in exp_sum["vex_top_by_strike"][:5]:
                lines.append(f"  - {item['strike']}: {_fmt_num(item['vex'])}")
        if exp_sum.get("theta_top_by_strike"):
            lines.append("- **Theta Top by strike (daily，主策略默认口径):**")
            for item in exp_sum["theta_top_by_strike"][:5]:
                lines.append(f"  - {item['strike']}: {_fmt_num(item['theta_exposure'])}")
        if exp_sum.get("vex_top_by_leg"):
            lines.append("- **Vega Top by leg（合约腿口径，仅供风险定位）:**")
            for item in exp_sum["vex_top_by_leg"][:3]:
                lines.append(f"  - {item['strike']} {item['option_type']}: {_fmt_num(item['vex'])}")
        if exp_sum.get("theta_top_by_leg"):
            lines.append("- **Theta Top by leg（合约腿口径，仅供风险定位）:**")
            for item in exp_sum["theta_top_by_leg"][:3]:
                lines.append(f"  - {item['strike']} {item['option_type']}: {_fmt_num(item['theta_exposure'])}")
        lines.append("")

    # =====================================================================
    # 5. 主交易区订单墙 / WallScore
    # =====================================================================
    lines.append("## 主交易区订单墙 / WallScore")
    lines.append("")

    lines.append(f"> 主交易区 WallScore 仅统计 {result.analysis_strike_min}–{result.analysis_strike_max}。区间外远端 strike 不进入本表。")
    lines.append("> WallScore = 0.30×GEX + 0.20×OI + 0.15×|ΔOI| + 0.15×Volume + 0.10×Block/PNT + 0.10×Distance，分项在同到期月内做 min-max 标准化。")
    lines.append("")
    if not result.scored_walls:
        lines.append("> 当前数据未识别到显著订单墙。")
    else:
        lines.append("| 排名 | Strike | dominant_side | NetGEX bias | 墙类型 | OI | OI变化 | 成交量 | WallScore | GEX/OI/ΔOI/Vol/PNT/Dist |")
        lines.append("| ---: | ---: | :---: | ---: | :---: | ---: | ---: | ---: | ---: | :--- |")
        for sw in result.scored_walls[:15]:
            w = sw.wall
            dominant = _dominant_side(w.net_gex, w.gex)
            lines.append(
                f"| {sw.rank} "
                f"| {w.strike} "
                f"| {dominant} "
                f"| {_fmt_num(w.net_gex)} "
                f"| {_wall_type_zh(w.wall_type.value if hasattr(w.wall_type, 'value') else str(w.wall_type))} "
                f"| {w.oi:,} "
                f"| {w.oi_change:+,} "
                f"| {w.volume:,} "
                f"| {sw.wall_score:.1f} "
                f"| {sw.gex_score:.2f}/{sw.oi_score:.2f}/{sw.doi_score:.2f}/{sw.volume_score:.2f}/{sw.block_pnt_score:.2f}/{sw.distance_score:.2f} |"
            )
    lines.append("")

    # =====================================================================
    # 5b. 区间外异常 / 尾部风险提示
    # =====================================================================
    out_of_range_scored = [
        sw for sw in result.full_chain_scored_walls
        if not (result.analysis_strike_min <= sw.wall.strike <= result.analysis_strike_max)
    ]
    if out_of_range_scored:
        lines.append("## 区间外异常 / 尾部风险提示")
        lines.append("")
        lines.append("> 以下 strike 来自全链扫描，不进入主交易区 WallScore、支撑阻力或策略卡片；仅用于观察远端库存、彩票仓、尾部保护或异常成交。")
        lines.append("")
        lines.append("| 排名 | Strike | 到期月 | 类型 | OI | OI变化 | 成交量 | WallScore |")
        lines.append("| ---: | ---: | :---: | :---: | ---: | ---: | ---: | ---: |")
        for sw in out_of_range_scored[:10]:
            w = sw.wall
            wt = _wall_type_zh(w.wall_type.value if hasattr(w.wall_type, 'value') else str(w.wall_type))
            lines.append(
                f"| {sw.rank} | {w.strike} | {w.expiry} | {wt} | {w.oi:,} | {w.oi_change:+,} | {w.volume:,} | {sw.wall_score:.2f} |"
            )
        lines.append("")

    # =====================================================================
    # 6. Roll / 换月迁移
    # =====================================================================
    lines.append("## Roll / 换月迁移信号")
    lines.append("")
    if not result.roll_signals:
        lines.append("> 未检测到显著换月迁移信号。")
    else:
        for signal in result.roll_signals:
            roll_val = signal.roll_type.value if hasattr(signal.roll_type, "value") else str(signal.roll_type)
            label = _ROLL_TYPE_LABELS.get(roll_val, roll_val)
            lines.append(f"- **{label}**（{signal.near_expiry} → {signal.far_expiry}，置信度 {signal.confidence:.0%}）")
            for ev in signal.evidence:
                lines.append(f"  - {ev}")
    lines.append("")

    # =====================================================================
    # 7. I1-I4 机构意图
    # =====================================================================
    lines.append("## I1-I4 机构意图分类")
    lines.append("")
    intent_type_val = primary.intent_type.value if hasattr(primary.intent_type, "value") else str(primary.intent_type)
    label_zh, desc_zh = _INTENT_LABELS.get(intent_type_val, (intent_type_val, ""))
    display_intent_heading = _intent_wording(label_zh, primary.confidence)
    lines.append(f"### 主意图: {display_intent_heading}（得分 {primary.score:.2f}，置信度 {primary.confidence:.0%}）")
    lines.append("")
    lines.append("| 口径 | 范围 | 作用 | 不应混用为 |")
    lines.append("| :--- | :--- | :--- | :--- |")
    lines.append("| intent_scope | full_chain | 判断机构总意图、全链库存与远端保护/库存墙 | 当前主战区支撑阻力 |")
    lines.append(f"| trading_scope | analysis_range={result.analysis_strike_min}–{result.analysis_strike_max} | 判断当前交易主战区、WallScore、支撑阻力、策略卡片 | 全链机构总意图 |")
    lines.append("")
    lines.append("> 因此，full-chain 中 Call OI 较大，不等于主交易区一定偏多；主交易区若 Put-GEX/防守墙增强，仍可呈现“总库存偏 Call、主战区偏防守”的组合。")
    if primary.confidence < 0.6:
        score_values = sorted(intent.all_scores.values(), reverse=True)
        score_gap = score_values[0] - score_values[1] if len(score_values) > 1 else score_values[0] if score_values else 0.0
        lines.append("")
        lines.append("#### 置信度偏低原因")
        lines.append("")
        lines.append("1. I1/I2/I3/I4 得分接近，没有单一 regime 压倒性胜出。")
        lines.append(f"2. 最高分与次高分差距约 {score_gap:.2f}，结构更像混合状态而非单边确认。")
        lines.append("3. 近月和次月都接近各自 Gamma Zero，方向切换敏感。")
        lines.append("4. Call/Put GEX 差距不大，Skew 有防守倾向，但上方 Call-GEX 仍存在。")
        max_roll = max((signal.confidence for signal in result.roll_signals), default=0.0)
        lines.append(f"5. Roll 信号置信度最高约 {max_roll:.0%}，不足以支持趋势迁移结论。")
    lines.append("> 若 evidence 中出现单日 OI 减仓，不应写成“双边增仓”；I2 判断主要来自 GEX 双边均衡、Gamma Zero 集中、Skew 偏防守和双边墙位共存。")
    if desc_zh:
        lines.append(f"> {desc_zh}")
    for ev in primary.evidence:
        lines.append(f"- {ev}")
    lines.append("")

    # Per-expiry intent commentary
    for expiry in result.expiries:
        summary = result.gex_summary_by_expiry.get(expiry, {})
        structure = summary.get("structure", "")
        gex_top = result.gex_top_by_expiry.get(expiry, [])
        # brief per-expiry intent
        if structure == "net_call_dominated":
            intent_note = f"{expiry} 偏 Call-GEX 主导，上方弹性较强"
        elif structure == "net_put_dominated":
            intent_note = f"{expiry} 偏 Put-GEX 主导，下方保护明显"
        else:
            intent_note = f"{expiry} 结构均衡"
        lines.append(f"- {intent_note}")
    lines.append("")

    # All scores
    lines.append("#### 各意图得分")
    lines.append("")
    lines.append("| 意图 | 得分 |")
    lines.append("| :--- | ---: |")
    for score_key, score_val in sorted(intent.all_scores.items(), key=lambda x: x[1], reverse=True):
        lbl, _ = _INTENT_LABELS.get(score_key, (score_key, ""))
        lines.append(f"| {lbl} | {score_val:.4f} |")
    lines.append("")

    if intent.secondary_intent is not None:
        sec = intent.secondary_intent
        sec_val = sec.intent_type.value if hasattr(sec.intent_type, "value") else str(sec.intent_type)
        sec_label, sec_desc = _INTENT_LABELS.get(sec_val, (sec_val, ""))
        lines.append(f"### 次意图: {sec_label}（得分 {sec.score:.2f}）")
        if sec_desc:
            lines.append(f"> {sec_desc}")
        lines.append("")

    # =====================================================================
    # 8. 支撑 / 阻力
    # =====================================================================
    lines.append("## 支撑 / 阻力候选")
    lines.append("")
    # Always output structural support/resistance from main-range walls.
    structural_supports: list[tuple] = []
    structural_resistances: list[tuple] = []
    for sw in result.scored_walls:
        w = sw.wall
        if w.net_gex < 0 or w.side == "PUT" or "support" in str(w.wall_type):
            structural_supports.append((w, sw))
        if w.net_gex > 0 or w.side == "CALL" or "resistance" in str(w.wall_type):
            structural_resistances.append((w, sw))
    structural_supports.sort(key=lambda x: (abs(x[0].gex), x[1].wall_score), reverse=True)
    structural_resistances.sort(key=lambda x: (abs(x[0].gex), x[1].wall_score), reverse=True)
    lines.append("### 结构支撑（不依赖 P0）")
    lines.append("")
    lines.append("| Strike | dominant_side | 类型 | NetGEX | WallScore | 结构含义 |")
    lines.append("| ---: | :---: | :---: | ---: | ---: | :--- |")
    for w, sw in structural_supports[:5]:
        wt = _wall_type_zh(w.wall_type.value if hasattr(w.wall_type, 'value') else str(w.wall_type))
        dominant = _dominant_side(w.net_gex, w.gex)
        lines.append(f"| {w.strike} | {dominant} | {wt} | {_fmt_num(w.net_gex)} | {sw.wall_score:.2f} | {_wall_role_from_bias(w.net_gex, w.strike, gz)} |")
    lines.append("")
    lines.append("### 结构阻力（不依赖 P0）")
    lines.append("")
    lines.append("| Strike | dominant_side | 类型 | NetGEX | WallScore | 结构含义 |")
    lines.append("| ---: | :---: | :---: | ---: | ---: | :--- |")
    for w, sw in structural_resistances[:5]:
        wt = _wall_type_zh(w.wall_type.value if hasattr(w.wall_type, 'value') else str(w.wall_type))
        dominant = _dominant_side(w.net_gex, w.gex)
        lines.append(f"| {w.strike} | {dominant} | {wt} | {_fmt_num(w.net_gex)} | {sw.wall_score:.2f} | {_wall_role_from_bias(w.net_gex, w.strike, gz)} |")
    lines.append("")
    if report_p0 is None:
        lines.append("> 未提供 report_p0：以上为纯结构支撑/阻力；若有同日结算价/平价 F，会额外输出按日报锚排序的支撑/阻力。")
    else:
        lines.append(f"> 以下按 report_p0={report_p0:.1f}（日终结构锚）排序，不代表当前实盘价格。")
        p0_or_f = report_p0

        # Use scored_walls to find support/resistance, including BOTH/pin/active near p0
        supports: list[tuple] = []
        resistances: list[tuple] = []
        for sw in result.scored_walls:
            w = sw.wall
            dist_pct = (w.strike - p0_or_f) / p0_or_f * 100
            if w.strike < p0_or_f:
                supports.append((w, sw, dist_pct))
            elif w.strike > p0_or_f:
                resistances.append((w, sw, dist_pct))

        supports.sort(key=lambda x: x[2], reverse=True)  # closest below
        resistances.sort(key=lambda x: x[2])  # closest above

        if supports:
            lines.append("### 支撑位（report_p0 下方）")
            lines.append("")
            lines.append("| Strike | 类型 | WallScore | 距report_p0 |")
            lines.append("| ---: | :---: | ---: | ---: |")
            for w, sw, dist in supports[:5]:
                wt = _wall_type_zh(w.wall_type.value if hasattr(w.wall_type, 'value') else str(w.wall_type))
                lines.append(f"| {w.strike} | {wt} | {sw.wall_score:.1f} | {dist:+.1f}% |")
            lines.append("")

        if resistances:
            lines.append("### 阻力位（report_p0 上方）")
            lines.append("")
            lines.append("| Strike | 类型 | WallScore | 距report_p0 |")
            lines.append("| ---: | :---: | ---: | ---: |")
            for w, sw, dist in resistances[:5]:
                wt = _wall_type_zh(w.wall_type.value if hasattr(w.wall_type, 'value') else str(w.wall_type))
                lines.append(f"| {w.strike} | {wt} | {sw.wall_score:.1f} | {dist:+.1f}% |")
            lines.append("")

        if not supports and not resistances:
            lines.append("> 当前无明确支撑/阻力候选。")
            lines.append("")

    # =====================================================================
    # 9. IV Smile / Skew
    # =====================================================================
    lines.append("## IV Smile / Skew")
    lines.append("")
    lines.append("> Skew = Put IV − Call IV。正值表示 Put 端更贵（下行保护溢价），负值表示 Call 端更贵（上行溢价）。")
    lines.append("> IV source: settlement-implied Black-76 IV；Skew interpolation: model_delta nearest target；Outlier filter: settlement >= 0, IV between 1% and 300%。")
    lines.append("")
    lines.append("| 到期月 | ATM IV | 25D Skew | 10D Tail Skew | 解读 |")
    lines.append("| :---: | ---: | ---: | ---: | :--- |")
    for expiry in result.expiries:
        iv_skew = result.iv_skew_by_expiry.get(expiry, {})
        atm = iv_skew.get("atm_iv")
        skew_25d = iv_skew.get("skew_25d")
        tail = iv_skew.get("tail_skew_10d")
        interp = iv_skew.get("interpretation", "")
        lines.append(
            f"| {expiry} "
            f"| {_fmt_pct(atm, 2)} "
            f"| {_fmt_pct(skew_25d, 2)} "
            f"| {_fmt_pct(tail, 2)} "
            f"| {interp} |"
        )
    lines.append("")

    # =====================================================================
    # 9b. 三路径推演
    # =====================================================================
    lines.append("## 三路径推演")
    lines.append("")
    lines.append("> 以日终结构锚生成，不分配主观概率；盘中是否激活，仍需使用当前策略的 5m 触发与 15m 确认。")
    lines.append("")
    scenario_anchor = live_p0 or report_p0 or result.forward_price or gz
    scenario_supports, scenario_resistances = _scenario_levels(result, anchor=scenario_anchor)
    lower_trigger = scenario_supports[0] if scenario_supports else None
    lower_targets = scenario_supports[1:]
    gamma_trigger = gz if gz is not None and (scenario_anchor is None or gz > scenario_anchor) else None
    upper_trigger = gamma_trigger or (scenario_resistances[0] if scenario_resistances else None)
    upper_targets = _directional_targets(
        scenario_resistances,
        anchor=upper_trigger if upper_trigger is not None else (scenario_anchor or 0.0),
        direction="up",
    )

    lines.append("### 主路径：修复震荡")
    lines.append("")
    if lower_trigger is not None and upper_trigger is not None:
        lines.append(f"- **触发/保持：** {lower_trigger:g} 未有效失守，价格围绕结构锚 {scenario_anchor:g} 反复。")
        lines.append(f"- **目标：** 先测试 {upper_trigger:g}，其后观察是否形成持续接受。")
        lines.append(f"- **失效：** 有效跌破 {lower_trigger:g} 且回抽不能收回。")
    else:
        lines.append("- 当前缺少完整上下边界，不激活区间修复路径。")
    lines.append("")

    lines.append("### 转强路径：接受 Gamma 翻转带")
    lines.append("")
    if upper_trigger is not None:
        lines.append(f"- **触发：** 重新站上 {upper_trigger:g}，回踩不破并由 15m 确认。")
        target_text = " → ".join(f"{target:g}" for target in upper_targets) or "上方 Call-GEX 墙"
        lines.append(f"- **目标：** {target_text}。")
        invalidation = lower_trigger if lower_trigger is not None else scenario_anchor
        lines.append(f"- **失效：** 跌回 {invalidation:g} 下方且无法快速收回。")
    else:
        lines.append("- Gamma 翻转与上方确认墙不可用，不激活转强路径。")
    lines.append("")

    lines.append("### 转弱路径：核心地板失守")
    lines.append("")
    if lower_trigger is not None:
        lines.append(f"- **触发：** 有效跌破 {lower_trigger:g}，回抽失败并伴随 Put 保护重新增强。")
        target_text = " → ".join(f"{target:g}" for target in lower_targets) or "下一 Put-GEX 防守带"
        lines.append(f"- **目标：** {target_text}。")
        lines.append(f"- **失效：** 重新收回 {lower_trigger:g} 并站稳。")
    else:
        lines.append("- 下方核心地板不可用，不生成转弱目标。")
    lines.append("")

    # =====================================================================
    # 10. 实盘策略卡片
    # =====================================================================
    lines.append("## 实盘策略卡片")
    lines.append("")
    lines.append("> ⚠️ 以下仅为基于期权结构的情景推演，不构成交易建议，不涉及自动下单。")
    lines.append("")

    if live_p0 is not None:
        p0 = live_p0
        lines.append(f"> live_p0={live_p0:.1f}（source={result.live_p0_source}）。以下策略卡片只用于盘中情景重排，不改变前文日终期权结构。")
        lines.append("")
        # Find nearest support and resistance
        support_candidates: list[dict] = []
        resistance_candidates: list[dict] = []
        for sw in result.scored_walls:
            w = sw.wall
            if w.strike < p0:
                support_candidates.append({"strike": w.strike, "score": sw.wall_score, "gex": w.gex})
            elif w.strike > p0:
                resistance_candidates.append({"strike": w.strike, "score": sw.wall_score, "gex": w.gex})
        support_candidates.sort(key=lambda x: (p0 - x["strike"]))  # nearest below
        resistance_candidates.sort(key=lambda x: (x["strike"] - p0))  # nearest above

        s1 = support_candidates[0]["strike"] if support_candidates else None
        s2 = support_candidates[1]["strike"] if len(support_candidates) > 1 else None
        r1 = resistance_candidates[0]["strike"] if resistance_candidates else None
        r2 = resistance_candidates[1]["strike"] if len(resistance_candidates) > 1 else None
        r3 = resistance_candidates[2]["strike"] if len(resistance_candidates) > 2 else None

        if s1 is not None and r1 is not None:
            no_trade_zone = f"{s1}–{r1}"
            no_trade_label = (
                f"**{no_trade_zone} 严格中段不适合追单，边界触发位不属于不交易区。**"
            )
        else:
            p0_low = int(p0 * 0.995)
            p0_high = int(p0 * 1.005)
            no_trade_zone = f"{p0_low}–{p0_high}"
            no_trade_label = f"**{no_trade_zone} 现价附近观察带不适合追单。**"

        # --- 主剧本 ---
        lines.append("### 主剧本")
        lines.append("")
        if s1:
            lines.append(f"回踩 {s1} 不破 → 看 {r1 or '上方阻力'} → {r2 or '进一步上行'}")
            lines.append("")
            lines.append("**条件：**")
            lines.append(f"- 价格回踩 {s1} 附近不破，或刺破后快速收回；")
            lines.append("- 15M 出现 failed breakout / second entry 确认；")
            if gz and p0 < gz:
                lines.append(
                    f"- 价格先重新站上 Gamma Zero（{gz:.0f}）；未收复前主剧本不激活。"
                )
            lines.append("")
            lines.append("**目标：**")
            upside_targets = _directional_targets(
                [r1, r2, r3],
                anchor=p0,
                direction="up",
            )
            for index, target in enumerate(upside_targets, start=1):
                lines.append(f"- {_target_label(index)}：{target:g}")
            if r1 and len(upside_targets) > 1:
                lines.append(f"- 升级条件：{r1:g} 被重新站上并回踩不破后，才启用后续目标。")
            lines.append("")
            lines.append("**失效：**")
            if s1:
                lines.append(f"- 跌破 {s1} 后无法收回；")
            if s2:
                lines.append(f"- {s2} 支撑失守；")
            if gz and p0 >= gz:
                lines.append(f"- 价格跌回 Gamma Zero（{gz:.0f}）下方。")
            lines.append("- 注：站上分水岭只代表进入 Call-GEX 更占优的结构区，仍需上方墙位接受确认，不能单独视为趋势启动。")
        else:
            lines.append("当前无明显支撑候选，无法构建主剧本。")
        lines.append("")

        # --- 备剧本 ---
        lines.append("### 备剧本")
        lines.append("")
        if r1 and p0 < r1:
            lines.append(f"{r1} 失败突破 → 回落看 {s1 or '下方支撑'}")
            lines.append("")
            lines.append("**条件：**")
            lines.append(f"- 价格冲 {r1} 后无法站稳；")
            lines.append("- 15M 出现 wedge reversal 或 failed breakout；")
            lines.append("- 期权结构上高 Gamma 压制未被消化。")
            lines.append("")
            lines.append("**目标：**")
            downside_targets = _directional_targets(
                [int(p0 * 0.98), s1, s2],
                anchor=p0,
                direction="down",
            )
            for index, target in enumerate(downside_targets, start=1):
                lines.append(f"- {_target_label(index)}：{target:g}")
        elif not r1:
            lines.append("当前无明显阻力候选，无法构建备剧本。")
        else:
            lines.append(f"价格已在 {r1} 之上，备剧本不适用。")
        lines.append("")

        # --- 不交易区 ---
        lines.append("### 不交易区")
        lines.append("")
        lines.append(no_trade_label)
        lines.append("")
        if s1 and r1:
            lines.append(
                f"原因：{s1}–{r1} 支撑与阻力之间缺少边缘优势，容易出现来回扫损、假突破和墙位磁吸。"
            )
        lines.append("更好的执行位置：")
        if s1:
            lines.append(f"- 下方靠近 {s1} 等失败确认；")
        if r1:
            lines.append(f"- 上方 {r1} 突破后回踩确认；")
        if r1:
            lines.append(f"- 或 {r1} 失败突破后的反向确认。")
    else:
        lines.append("> 未提供 live_p0：不生成现价驱动的实盘策略卡片。可使用 --live-p0 或 --live-p0-source jin10。")

    lines.append("")

    # =====================================================================
    # 11. 主/副剧本（existing backward-compat heading）
    # =====================================================================
    lines.append("## 主/副剧本（结构情景）")
    lines.append("")
    lines.append("> ⚠️ 以下仅为基于期权结构的情景推演，不构成交易建议，不涉及自动下单。")
    lines.append("")

    lines.append("### 主剧本")
    lines.append("")
    lines.append(f"- 机构意图: {label_zh}")
    if report_p0 is not None and gz is not None:
        if gz > report_p0:
            lines.append(f"- report_p0 在 Gamma Zero ({gz:.0f}) 下方，日终结构偏 Put-GEX/保护区；盘中需另看 live_p0")
        else:
            lines.append(f"- report_p0 在 Gamma Zero ({gz:.0f}) 上方，日终结构偏 Call-GEX 主导；盘中需另看 live_p0")

    if result.scored_walls:
        top_wall = result.scored_walls[0]
        w = top_wall.wall
        wt = _wall_type_zh(w.wall_type.value if hasattr(w.wall_type, 'value') else str(w.wall_type))
        side_zh = "Call" if w.side == "CALL" else "Put"
        lines.append(f"- 最强墙: {w.strike} {side_zh} {wt}（WallScore {top_wall.wall_score:.1f}）")
    lines.append("")

    lines.append("### 副剧本")
    lines.append("")
    if intent.secondary_intent is not None:
        sec = intent.secondary_intent
        sec_val = sec.intent_type.value if hasattr(sec.intent_type, "value") else str(sec.intent_type)
        sec_label, sec_desc = _INTENT_LABELS.get(sec_val, (sec_val, ""))
        lines.append(f"- 次意图: {sec_label}（{sec_desc}）")
    else:
        lines.append("- 无明显次意图信号")
    lines.append("")

    # =====================================================================
    # 12. 数据质量与局限性
    # =====================================================================
    lines.append("## 数据质量与局限性")
    lines.append("")
    dq = result.data_quality

    lines.append("### 数据质量分类统计")
    lines.append("")
    lines.append("| 类别 | 计数 |")
    lines.append("| :--- | ---: |")
    if dq.rows_missing_settlement > 0:
        lines.append(f"| 缺失 settlement | {dq.rows_missing_settlement} |")
    if dq.rows_missing_delta > 0:
        lines.append(f"| 缺失 delta | {dq.rows_missing_delta} |")
    if dq.zero_oi_count > 0:
        lines.append(f"| OI 为 0 | {dq.zero_oi_count} |")
    if dq.low_oi_count > 0:
        lines.append(f"| 低 OI (< 10) | {dq.low_oi_count} |")
    if dq.proxy_strike_count > 0:
        lines.append(f"| Gamma Proxy strike 数 | {dq.proxy_strike_count} |")
        lines.append(f"| Proxy GEX Share | {_audit_counts(result)['proxy_gex_share']:.2%} |")
    if dq.prelim_data_count > 0:
        lines.append(f"| PRELIM 标记行数 | {dq.prelim_data_count} |")
    if dq.rows_filtered_by_strike > 0:
        lines.append(f"| 价外过滤行数 | {dq.rows_filtered_by_strike} |")
    if dq.duplicates_merged > 0:
        lines.append(f"| 去重合并行数 | {dq.duplicates_merged} |")
    if not any([dq.rows_missing_settlement, dq.rows_missing_delta, dq.zero_oi_count,
                dq.low_oi_count, dq.proxy_strike_count, dq.prelim_data_count,
                dq.rows_filtered_by_strike, dq.duplicates_merged]):
        lines.append("| 无分类异常 | 0 |")
    lines.append("")

    if any("expiry_date_estimated" in w for w in dq.warnings):
        lines.append("### 到期日估算提示")
        lines.append("")
        lines.append("- expiry_source=estimated_from_delivery_month，expiry_confidence=medium。")
        expiry_text = " / ".join(result.expiries) or "相关月份"
        lines.append(
            "- 近月 T 对 Gamma 较敏感；若 CME 官方到期日与估算差 1 个交易日，"
            f"{expiry_text} GEX 与 Gamma Zero 可能小幅变化。"
        )
        lines.append("")
    if dq.warnings:
        lines.append("### 详细警告")
        lines.append("")
        for w in dq.warnings:
            lines.append(f"- {w}")
    else:
        lines.append("- 无异常警告。")
    lines.append("")
    lines.append("---")
    lines.append(f"*报告生成时间: {result.generated_at} | 模型: Black-76 | 产品: {result.product}*")
    lines.append("")

    return "\n".join(lines)
