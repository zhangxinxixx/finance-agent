from __future__ import annotations

from typing import Any

from apps.analysis.macro.conclusion import MacroConclusion, build_macro_conclusion
from apps.features.macro.snapshot import MacroIndicator, MacroSnapshot


_MAINLINE_LABELS = {
    "fed_policy_path": "美联储利率路径",
    "real_rates_usd": "实际利率与美元",
    "oil_prices": "油价与通胀传导",
    "geopolitical_war_risk": "地缘风险",
    "etf_flows": "黄金 ETF 资金流",
    "institutional_sentiment": "机构持仓与期权情绪",
    "central_bank_gold": "央行购金",
    "china_asia_demand": "中国与亚洲需求",
    "gold_technical_levels": "黄金关键技术位",
}

_DRIVER_LABELS = {
    "higher_for_longer_rate_pressure": "高利率维持更久",
    "usd_strength_pressure": "美元强势",
    "oil_inflation_rate_pressure": "油价通胀与利率压力",
    "safe_haven_bid": "避险买盘",
    "rate_cut_expectation_support": "降息预期",
}

_PHASE_LABELS = {
    "weak_repair_watch": "弱修复观察",
    "rate_pressure": "利率压制态",
    "transition_release": "过渡释放态",
    "trend_tailwind": "趋势顺风态",
    "liquidity_crunch": "流动性踩踏态",
    "monetary_credit_repricing": "货币信用重定价态",
    "unavailable": "数据不足态",
    "policy_event_cycle": "政策事件窗口",
}

_VERIFIED_SPOT_PRICE_SOURCES = frozenset({"twelvedata_xauusd_quote", "research_snapshot_spot"})


def build_dashboard_integrated_analysis(
    *,
    macro_snapshot: dict[str, Any] | None,
    options_snapshot: dict[str, Any] | None,
    market_tickers: dict[str, Any],
    gold_macro_overview: dict[str, Any] | None,
    agent_summary: dict[str, Any],
    composite_analysis: dict[str, Any],
    source_trace: list[dict[str, Any]],
    jin10_analysis: dict[str, Any] | None = None,
    strategy_summary: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Build a deterministic, read-only integrated analysis for Dashboard consumers."""

    if macro_snapshot is None and options_snapshot is None and not gold_macro_overview:
        return None

    macro_conclusion = _macro_conclusion(macro_snapshot)
    indicators = _normalize_rate_aliases((macro_snapshot or {}).get("indicators") or {})
    conflict = (gold_macro_overview or {}).get("driver_conflict") or {}
    readiness = (gold_macro_overview or {}).get("analysis_readiness") or {}
    current_price = _market_price(market_tickers, "xauusd")
    current_price_source = _market_price_source(market_tickers, "xauusd")
    options_context = _options_context(
        options_snapshot,
        current_price=current_price,
        current_price_source=current_price_source,
    )

    overall_bias = _overall_bias(macro_conclusion, gold_macro_overview)
    direction = _direction(overall_bias)
    macro_regime = _macro_regime(macro_conclusion, gold_macro_overview)
    dominant_drivers = _dominant_drivers(gold_macro_overview, macro_conclusion)
    confidence = _analysis_confidence(agent_summary, strategy_summary)

    liquidity_state = _liquidity_state(indicators, macro_conclusion)
    rates_state = _rates_state(indicators, macro_conclusion)
    dollar_state = _dollar_state(indicators, macro_conclusion)
    options_alignment = _options_alignment(options_context)
    reasoning = _integrated_reasoning(
        overall_bias=overall_bias,
        macro_regime=macro_regime,
        rates_state=rates_state,
        dollar_state=dollar_state,
        conflict=conflict,
    )

    trigger_upgrade = _upgrade_conditions(indicators, options_context)
    trigger_downgrade = _downgrade_conditions(indicators, options_context)
    invalidation = _invalidation_conditions(options_context)
    risks = _risk_items(options_context, readiness)
    missing_inputs = _missing_inputs(macro_snapshot, readiness)

    return {
        "report_type": "integrated_macro_summary",
        "trade_date": composite_analysis.get("trade_date")
        or (macro_snapshot or {}).get("as_of")
        or (options_snapshot or {}).get("trade_date"),
        "run_id": _latest_composite_run_id(composite_analysis, agent_summary),
        "source": "macro_conclusion+gold_macro_overview+cme_options+agent_summary",
        "overall_bias": overall_bias,
        "direction": direction,
        "macro_regime": macro_regime,
        "dominant_driver": dominant_drivers,
        "liquidity_state": liquidity_state,
        "rates_state": rates_state,
        "dollar_state": dollar_state,
        "options_alignment": options_alignment,
        "confidence": confidence,
        "reasoning": reasoning,
        "trade_implication": _trade_implication(options_context),
        "quick_supports": _quick_supports(options_context),
        "trigger_upgrade": trigger_upgrade,
        "trigger_downgrade": trigger_downgrade,
        "invalidation": invalidation,
        "risks": risks,
        "missing_inputs": missing_inputs,
        "composite_status": composite_analysis.get("status"),
        "composite_trade_date": composite_analysis.get("trade_date"),
        "source_refs": _source_refs(
            source_trace=source_trace,
            macro_snapshot=macro_snapshot,
            options_snapshot=options_snapshot,
            gold_macro_overview=gold_macro_overview,
        ),
    }


def _quick_supports(
    options_context: dict[str, Any],
) -> list[dict[str, Any]]:
    gc_price = _optional_float(options_context.get("current_price"))
    supports: list[dict[str, Any]] = []

    cme_levels = options_context.get("supports") or []
    if len(cme_levels) >= 3:
        cme_level = _optional_float(cme_levels[2])
        if cme_level is not None:
            supports.append(
                {
                    "level": cme_level,
                    "label": "CME GC 期货快支撑",
                    "source": "cme_options",
                    "source_label": "CME",
                    "trade_date": options_context.get("trade_date"),
                    "timeframe": None,
                    "basis": "CME 期权快照第三档支撑（GC 期货坐标）",
                    "status": _level_status(gc_price, cme_level),
                    "source_ref": "GET /api/options/snapshot",
                }
            )

    return supports


def _level_status(current_price: float | None, level: float) -> str:
    if current_price is None:
        return "unknown"
    return "broken" if current_price < level else "active"


def _macro_conclusion(payload: dict[str, Any] | None) -> MacroConclusion | None:
    if not isinstance(payload, dict):
        return None
    raw_indicators = payload.get("indicators")
    if not isinstance(raw_indicators, dict) or not raw_indicators:
        return None

    indicators: dict[str, MacroIndicator] = {}
    try:
        for symbol, raw in _normalize_rate_aliases(raw_indicators).items():
            if not isinstance(raw, dict) or raw.get("value") is None:
                continue
            indicators[str(symbol)] = MacroIndicator(
                symbol=str(raw.get("symbol") or symbol),
                date=str(raw.get("date") or payload.get("as_of") or ""),
                value=float(raw["value"]),
                daily_change=_optional_float(raw.get("daily_change")),
                weekly_change=_optional_float(raw.get("weekly_change")),
                monthly_change=_optional_float(raw.get("monthly_change")),
                label=str(raw.get("label") or symbol),
                unit=str(raw.get("unit") or ""),
                direction_note=str(raw.get("direction_note") or ""),
            )
        snapshot = MacroSnapshot(
            as_of=str(payload.get("as_of") or ""),
            indicators=indicators,
            unavailable_symbols=[str(item) for item in payload.get("unavailable_symbols") or []],
            source_refs=dict(payload.get("source_refs") or {}),
        )
    except (TypeError, ValueError):
        return None
    return build_macro_conclusion(snapshot)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_rate_aliases(indicators: dict[str, Any]) -> dict[str, Any]:
    """Expose archived rate names to existing consumers without changing facts."""
    normalized = dict(indicators)
    for canonical, alias in (("REAL_10Y", "REAL10Y"), ("BREAKEVEN_10Y", "T10YIE")):
        if canonical not in normalized and alias in indicators:
            normalized[canonical] = indicators[alias]
        # Legacy conclusion consumers may otherwise retry an alias after an
        # explicitly empty canonical value. This is only a consumer-side copy.
        normalized.pop(alias, None)
    return normalized


def _indicator(indicators: dict[str, Any], symbol: str) -> dict[str, Any]:
    value = indicators.get(symbol)
    return value if isinstance(value, dict) else {}


def _fmt(value: Any, digits: int = 2) -> str:
    number = _optional_float(value)
    return "暂无" if number is None else f"{number:,.{digits}f}"


def _signed(value: Any, digits: int = 2, suffix: str = "") -> str:
    number = _optional_float(value)
    return "暂无" if number is None else f"{number:+.{digits}f}{suffix}"


def _liquidity_state(indicators: dict[str, Any], conclusion: MacroConclusion | None) -> str:
    tga = _indicator(indicators, "TGA")
    reserves = _indicator(indicators, "RESERVES")
    rrp = _indicator(indicators, "ON_RRP_USAGE")
    layer = conclusion.quantity_layer if conclusion else "待确认"
    return (
        f"数量层{layer}：TGA {_fmt(tga.get('value'))}B（周{_signed(tga.get('weekly_change'), suffix='B')}），"
        f"准备金 {_fmt(reserves.get('value'))}B（周{_signed(reserves.get('weekly_change'), suffix='B')}），"
        f"RRP {_fmt(rrp.get('value'))}B。财政抽水与银行体系缓冲用于判断背景，不能单独覆盖利率和美元信号。"
    )


def _rates_state(indicators: dict[str, Any], conclusion: MacroConclusion | None) -> str:
    nominal = _indicator(indicators, "US10Y")
    breakeven = _indicator(indicators, "BREAKEVEN_10Y")
    real = _indicator(indicators, "REAL_10Y")
    price_layer = conclusion.price_layer if conclusion else "待确认"
    causal_read = _rates_causal_read(nominal, breakeven, real)
    return (
        f"资金价格层{price_layer}：10Y 美债 {_fmt(nominal.get('value'))}%（周{_signed(nominal.get('weekly_change'), suffix='%')}），"
        f"10Y 盈亏平衡通胀 {_fmt(breakeven.get('value'))}%（周{_signed(breakeven.get('weekly_change'), suffix='%')}），"
        f"10Y 实际利率 {_fmt(real.get('value'))}%（{real.get('date') or '日期待核验'}，周{_signed(real.get('weekly_change'), suffix='%')}）。"
        f"{causal_read}"
    )


def _rates_causal_read(nominal: dict[str, Any], breakeven: dict[str, Any], real: dict[str, Any]) -> str:
    nominal_change = _optional_float(nominal.get("weekly_change"))
    breakeven_change = _optional_float(breakeven.get("weekly_change"))
    real_change = _optional_float(real.get("weekly_change"))
    if nominal_change is None or breakeven_change is None or real_change is None:
        return "周变化链条不完整，实际利率方向只按当前读数观察。"
    if nominal_change > breakeven_change and real_change > 0:
        return "名义利率快于通胀预期上行，实际利率抬升会提高持有黄金的机会成本。"
    if nominal_change < breakeven_change and real_change < 0:
        return "通胀预期强于名义利率，实际利率回落会缓和黄金的机会成本压力。"
    return "名义利率与通胀预期变化接近，实际利率尚未给出新的单边确认。"


def _dollar_state(indicators: dict[str, Any], conclusion: MacroConclusion | None) -> str:
    dxy = _indicator(indicators, "DXY")
    layer = conclusion.dollar_layer if conclusion else "待确认"
    return (
        f"美元层{layer}：DXY {_fmt(dxy.get('value'))}（{dxy.get('date') or '日期待核验'}）。"
        "美元走强通常增加黄金压力，走弱则缓和压力；需要同窗口利率和金价验证。"
    )


def _options_context(
    options: dict[str, Any] | None,
    *,
    current_price: float | None,
    current_price_source: str,
) -> dict[str, Any]:
    if not isinstance(options, dict):
        return {"available": False, "current_price": None, "spot_price": current_price}
    support_resistance = options.get("support_resistance")
    if not isinstance(support_resistance, dict):
        support_resistance = {}
    supports = _distinct_strikes(support_resistance.get("support"), reverse=True)
    resistances = _distinct_strikes(support_resistance.get("resistance"), reverse=False)
    gex = options.get("gex") if isinstance(options.get("gex"), dict) else {}
    gamma_flip = gex.get("gamma_flip") if isinstance(gex.get("gamma_flip"), dict) else {}
    aggregate = gex.get("netgex_aggregate") if isinstance(gex.get("netgex_aggregate"), dict) else {}
    gamma_zero = aggregate.get("gamma_zero") if isinstance(aggregate.get("gamma_zero"), dict) else {}
    data_source = options.get("data_source") if isinstance(options.get("data_source"), dict) else {}
    intent = options.get("intent") if isinstance(options.get("intent"), dict) else {}
    parameters = options.get("parameters") if isinstance(options.get("parameters"), dict) else {}
    forward_price = _optional_float(parameters.get("f_value"))
    quote_is_gc_futures = current_price_source == "cme_gc_futures"
    return {
        "available": True,
        "trade_date": options.get("trade_date"),
        "data_status": str(data_source.get("status") or "UNKNOWN"),
        "intent": str(intent.get("type") or "unknown"),
        "current_price": current_price if quote_is_gc_futures else forward_price,
        "current_price_source": current_price_source if quote_is_gc_futures else "cme_options_f_value" if forward_price is not None else "unavailable",
        "spot_price": current_price if current_price_source in _VERIFIED_SPOT_PRICE_SOURCES else None,
        "coordinate_space": "GC futures",
        "xauusd_mapping": "unavailable_without_verified_basis",
        "gamma_flip": _optional_float(gamma_flip.get("price") if gamma_flip.get("price") is not None else gamma_zero.get("price")),
        "supports": supports,
        "resistances": resistances,
    }


def _distinct_strikes(raw_items: Any, *, reverse: bool) -> list[float]:
    if not isinstance(raw_items, list):
        return []
    values: set[float] = set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        strike = _optional_float(item.get("strike"))
        if strike is not None:
            values.add(strike)
    return sorted(values, reverse=reverse)


def _options_alignment(context: dict[str, Any]) -> str:
    if not context.get("available"):
        return "CME 期权结构不可用，当前综合判断不使用期权确认。"
    price = context.get("current_price")
    gamma_flip = context.get("gamma_flip")
    supports = context.get("supports") or []
    resistances = context.get("resistances") or []
    status = context.get("data_status")
    support_text = "/".join(_fmt_level(item) for item in supports[:2]) or "暂无"
    resistance_text = _fmt_level(resistances[0]) if resistances else "暂无"
    gamma_text = _fmt_level(gamma_flip) if gamma_flip is not None else "暂无"
    relative = _price_structure_text(
        price=price,
        supports=supports[:2],
        resistance=resistances[0] if resistances else None,
        gamma_flip=gamma_flip,
    )
    status_note = (
        "当前使用最新 PRELIM 数据，可直接参与结构分析，但墙位和置信度仍可能修订。"
        if status.upper().startswith("PRELIM")
        else "当前期权数据可用于结构确认。"
    )
    return (
        f"{status_note} 以下墙位与 Proxy Flip 均为 GC 期货坐标；未提供可核验的 GC-XAUUSD 基差，"
        f"不能映射为 XAUUSD 现货确认位。GC 期货代理价 {_fmt_level(price)}，下方支撑带 {support_text}，"
        f"上方第一阻力 {resistance_text}，Selected Expiry Window Proxy Gamma Flip {gamma_text}。{relative}"
    )


def _price_structure_text(
    *,
    price: float | None,
    supports: list[float],
    resistance: float | None,
    gamma_flip: float | None,
) -> str:
    if price is None:
        return "缺少 GC 期货代理价，期权仅保留 GC 墙位与 Proxy Flip 观察。"
    parts: list[str] = []
    support_band = supports[:2]
    support_text = "/".join(_fmt_level(item) for item in support_band)
    support_floor = min(support_band) if support_band else None
    support_ceiling = max(support_band) if support_band else None
    support_broken = support_floor is not None and price < support_floor
    if support_broken:
        parts.append(
            f"GC 期货代理价已跌破 {support_text} 支撑带，较下沿低约 {_distance_pct(price, support_floor):.1f}%"
        )
    elif support_floor is not None and support_ceiling is not None and price <= support_ceiling:
        parts.append(f"GC 期货代理价位于 {support_text} 支撑带内，期货结构承接仍在验证")
    elif support_ceiling is not None:
        parts.append(f"GC 期货代理价位于 {support_text} 支撑带上方，距上沿约 {_distance_pct(price, support_ceiling):.1f}%")
    if resistance is not None:
        parts.append(f"距第一阻力约 {_distance_pct(price, resistance):.1f}%")
    if gamma_flip is not None:
        gamma_side = "下方" if price < gamma_flip else "上方"
        parts.append(f"位于 Proxy Flip {gamma_side}")
    conclusion = "；".join(parts)
    if support_broken:
        return (
            f"{conclusion}。GC 期货结构承接转弱；Proxy Flip 仅作结构观察，不能单独定义趋势闸门。"
        )
    if not support_band:
        return f"{conclusion}。缺少有效支撑带，当前只保留 GC 阻力与 Proxy Flip 观察，不判定趋势。"
    return f"{conclusion}。GC 支撑带未失效只说明期货结构尚在；Proxy Flip 不能单独定义趋势闸门。"


def _distance_pct(price: float, level: float) -> float:
    if price == 0:
        return 0.0
    return abs(level - price) / price * 100


def _fmt_level(value: Any) -> str:
    number = _optional_float(value)
    if number is None:
        return "暂无"
    return f"{number:,.1f}" if number % 1 else f"{number:,.0f}"


def _confirmation_levels(context: dict[str, Any]) -> list[float]:
    resistances = context.get("resistances") or []
    # Proxy Flip remains descriptive evidence; it is not a mandatory trend gate.
    candidates = [resistances[0] if resistances else None]
    return sorted({level for item in candidates if (level := _optional_float(item)) is not None})


def _market_price(market_tickers: dict[str, Any], symbol: str) -> float | None:
    tickers = market_tickers.get("tickers") if isinstance(market_tickers, dict) else None
    if not isinstance(tickers, dict):
        return None
    item = tickers.get(symbol) or tickers.get(symbol.upper())
    if not isinstance(item, dict):
        return None
    return _optional_float(item.get("price") if item.get("price") is not None else item.get("value"))


def _market_price_source(market_tickers: dict[str, Any], symbol: str) -> str:
    tickers = market_tickers.get("tickers") if isinstance(market_tickers, dict) else None
    if not isinstance(tickers, dict):
        return ""
    item = tickers.get(symbol) or tickers.get(symbol.upper())
    return str(item.get("source") or "") if isinstance(item, dict) else ""


def _integrated_reasoning(
    *,
    overall_bias: str,
    macro_regime: str,
    rates_state: str,
    dollar_state: str,
    conflict: dict[str, Any],
) -> str:
    conflict_text = str(conflict.get("explanation") or "宏观利多与利空驱动仍在竞争。")
    dominant = _DRIVER_LABELS.get(str(conflict.get("dominant_driver") or ""), str(conflict.get("dominant_driver") or "待确认"))
    return (
        f"综合判断为{overall_bias}，处于{macro_regime}。{rates_state}{dollar_state}"
        f"{conflict_text} 当前主导矛盾是{dominant}；数量层改善只能缓冲波动，"
        "尚不足以单独推翻实际利率与美元给出的宏观约束。"
    )


def _overall_bias(conclusion: MacroConclusion | None, overview: dict[str, Any] | None) -> str:
    net_bias = str((overview or {}).get("net_bias") or "")
    labels = {
        "neutral_bearish": "中性偏空",
        "neutral_bullish": "中性偏多",
        "bearish": "偏空",
        "bullish": "偏多",
        "neutral": "中性",
        "mixed": "中性",
    }
    return labels.get(net_bias, conclusion.bias if conclusion else "中性")


def _direction(overall_bias: str) -> str:
    if overall_bias == "偏多":
        return "bullish"
    if overall_bias == "偏空":
        return "bearish"
    return "neutral"


def _macro_regime(conclusion: MacroConclusion | None, overview: dict[str, Any] | None) -> str:
    if conclusion is not None:
        return _PHASE_LABELS.get(conclusion.market_phase, conclusion.state)
    phase = str((overview or {}).get("phase") or "")
    return _PHASE_LABELS.get(phase, phase or "宏观阶段待确认")


def _dominant_drivers(overview: dict[str, Any] | None, conclusion: MacroConclusion | None) -> list[str]:
    result: list[str] = []
    dominant_mainline = str((overview or {}).get("dominant_mainline") or "")
    if dominant_mainline:
        result.append(_MAINLINE_LABELS.get(dominant_mainline, dominant_mainline))
    conflict = (overview or {}).get("driver_conflict") or {}
    dominant_driver = str(conflict.get("dominant_driver") or "")
    if dominant_driver:
        result.append(_DRIVER_LABELS.get(dominant_driver, dominant_driver))
    if conclusion is not None:
        result.extend([f"美元层：{conclusion.dollar_layer}", f"实际利率/资金价格：{conclusion.price_layer}"])
    return list(dict.fromkeys(result))[:4]


def _analysis_confidence(
    agent_summary: dict[str, Any],
    strategy_summary: dict[str, Any] | None = None,
) -> float | None:
    strategy_confidence = _optional_float((strategy_summary or {}).get("confidence"))
    if strategy_confidence is not None:
        return max(0.0, min(strategy_confidence, 1.0))
    for key in ("synthesis", "coordinator"):
        item = agent_summary.get(key)
        if not isinstance(item, dict):
            continue
        value = _optional_float(item.get("confidence"))
        if value is not None:
            return max(0.0, min(value, 1.0))
    return None


def _upgrade_conditions(indicators: dict[str, Any], context: dict[str, Any]) -> list[str]:
    conditions = [
        "美元持续走弱且与金价处于可比观察窗口。",
        "10Y 实际利率持续回落，黄金机会成本下降。",
    ]
    supports = context.get("supports") or []
    price = _optional_float(context.get("current_price"))
    confirmation_levels = _confirmation_levels(context)
    if supports:
        support_band = supports[:2]
        support_text = "/".join(_fmt_level(item) for item in support_band)
        if price is not None and price < min(support_band):
            conditions.append(f"GC 期货代理价重新收复 {support_text} 支撑带并站稳，确认 GC 结构下破失败。")
        else:
            conditions.append(f"GC 期货代理价守住 {_fmt_level(supports[0])} 附近支撑，仅确认 GC 期货结构。")
    if confirmation_levels:
        levels = [_fmt_level(item) for item in confirmation_levels]
        conditions.append(
            f"GC 期货代理价重新站上 {'/'.join(levels)} 阻力，期权结构改善；"
            "Proxy Flip 不单独构成趋势闸门。"
        )
    conditions.append("10Y 美债收益率回落至 4.35% 下方，且不是由通胀预期更快下跌造成。")
    return conditions


def _downgrade_conditions(indicators: dict[str, Any], context: dict[str, Any]) -> list[str]:
    real = _optional_float(_indicator(indicators, "REAL_10Y").get("value"))
    conditions = [
        "美元持续走强且与金价处于可比观察窗口。",
        f"10Y 实际利率由当前 {_fmt(real)}% 继续上行。" if real is not None else "10Y 实际利率继续上行。",
    ]
    supports = context.get("supports") or []
    if supports:
        support_band = supports[:2]
        zone = "/".join(_fmt_level(item) for item in support_band)
        price = _optional_float(context.get("current_price"))
        if price is not None and price < min(support_band):
            conditions.append(f"GC 期货代理价维持在 {zone} 支撑带下方，说明 GC 期货结构承接转弱。")
        else:
            conditions.append(f"GC 期货代理价跌破 {zone} 支撑带，说明 GC 期货结构承接转弱。")
    return conditions


def _invalidation_conditions(context: dict[str, Any]) -> list[str]:
    supports = context.get("supports") or []
    confirmation_levels = _confirmation_levels(context)
    items = [
        "若美元与实际利率同步转弱，当前中性偏空框架需要上调。",
        "若避险买盘不能抵消高利率维持更久的压力，则不能把地缘风险直接等同于黄金趋势上涨。",
    ]
    if supports:
        support_floor = min(supports[:2])
        price = _optional_float(context.get("current_price"))
        if price is not None and price < support_floor:
            items.append(
                f"GC 期货参考价低于 {_fmt_level(support_floor)}；是否破位仍需收盘与回测确认，"
                "不能由代理价直接确认趋势。"
            )
        else:
            items.append(f"GC 期货代理价有效跌破 {_fmt_level(support_floor)}，GC 短线支撑结构失效。")
    if confirmation_levels:
        levels = [_fmt_level(item) for item in confirmation_levels]
        items.append(f"GC 期货代理价站稳 {'/'.join(levels)} 且利率回落，可上调 GC 结构评估；仍需独立现货证据。")
    return items


def _risk_items(context: dict[str, Any], readiness: dict[str, Any]) -> list[str]:
    items: list[str] = []
    status = str(context.get("data_status") or "")
    if status.upper().startswith("PRELIM"):
        items.append("CME 为最新 PRELIM 数据，可用于当前结构分析，但后续版本可能调整墙位、Proxy Flip 与置信度。")
    if readiness.get("status") and readiness.get("status") != "ready":
        items.append(
            f"Gold 主线覆盖仍为 {readiness.get('status')}："
            f"{readiness.get('ready_count', 0)}/{readiness.get('total_count', 0)} 条主线达到 ready。"
        )
    items.extend(
        [
            "CPI、FOMC 表态或油价冲击可能同时改变通胀预期、名义利率和实际利率，需在事件后重算。",
            "GC 期货期权墙位与 Proxy Flip 是结构证据，不是方向预测；缺少可核验基差时不能映射为 XAUUSD 现货确认。",
        ]
    )
    return items


def _missing_inputs(macro: dict[str, Any] | None, readiness: dict[str, Any]) -> list[str]:
    missing = [str(item) for item in (macro or {}).get("unavailable_symbols") or []]
    missing.extend(str(item) for item in (readiness.get("next_gaps") or [])[:3])
    return list(dict.fromkeys(missing))


def _trade_implication(context: dict[str, Any]) -> str:
    supports = context.get("supports") or []
    support_text = "/".join(_fmt_level(item) for item in supports[:2]) or "下方支撑"
    confirmation = [_fmt_level(item) for item in _confirmation_levels(context)]
    confirmation_text = "/".join(confirmation) or "上方确认区"
    price = _optional_float(context.get("current_price"))
    support_band = supports[:2]
    if price is not None and support_band and price < min(support_band):
        return (
            f"GC 期货代理价 {_fmt_level(price)} 已跌破 {support_text} 承接带，GC 结构转弱。"
            f"重新收复 {support_text} 并站上 {confirmation_text} 可改善 GC 结构；"
            "缺少可核验基差时不能映射为 XAUUSD 现货确认。"
        )
    if price is not None and support_band and price <= max(support_band):
        return (
            f"GC 期货代理价 {_fmt_level(price)} 正在 {support_text} 支撑带内接受结构验证；"
            f"站上 {confirmation_text} 可改善 GC 结构，但 Proxy Flip 不单独构成趋势闸门。"
        )
    return (
        f"以 {support_text} 作为 GC 期货承接观察，以 {confirmation_text} 作为 GC 阻力观察。"
        "Proxy Flip 不单独构成趋势闸门；缺少可核验基差时不能映射为 XAUUSD 现货确认。"
    )


def _source_refs(
    *,
    source_trace: list[dict[str, Any]],
    macro_snapshot: dict[str, Any] | None,
    options_snapshot: dict[str, Any] | None,
    gold_macro_overview: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    refs = [dict(item) for item in source_trace[:4] if isinstance(item, dict)]
    if macro_snapshot:
        refs.append(
            {
                "name": "Macro Latest",
                "trade_date": macro_snapshot.get("as_of"),
                "file": "api://macro/latest",
                "snapshot_id": None,
                "source_ref": "GET /api/macro/latest",
                "status": "ok",
            }
        )
    if options_snapshot:
        data_source = options_snapshot.get("data_source")
        if not isinstance(data_source, dict):
            data_source = {}
        status = str(data_source.get("status") or "UNKNOWN")
        refs.append(
            {
                "name": "CME Options",
                "trade_date": options_snapshot.get("trade_date"),
                "file": data_source.get("source_url") or "api://options/snapshot",
                "snapshot_id": options_snapshot.get("snapshot_id"),
                "source_ref": "GET /api/options/snapshot",
                "status": "warn" if status.upper().startswith("PRELIM") else "ok",
            }
        )
    if gold_macro_overview:
        refs.append(
            {
                "name": "Gold Mainlines",
                "trade_date": gold_macro_overview.get("as_of"),
                "file": "api://gold/mainlines/latest",
                "snapshot_id": None,
                "source_ref": "GET /api/gold/mainlines/latest",
                "status": "warn" if (gold_macro_overview.get("analysis_readiness") or {}).get("status") != "ready" else "ok",
            }
        )
    return refs


def _latest_composite_run_id(composite_analysis: dict[str, Any], agent_summary: dict[str, Any]) -> str | None:
    if composite_analysis.get("run_id"):
        return str(composite_analysis["run_id"])
    for key in ("synthesis", "coordinator"):
        item = agent_summary.get(key)
        if isinstance(item, dict) and item.get("run_id"):
            return str(item["run_id"])
    degraded = composite_analysis.get("degraded_newer_reports") or []
    if degraded and isinstance(degraded[0], dict):
        return degraded[0].get("run_id")
    return None
