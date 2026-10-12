"""Versioned, deterministic inputs for the final gold research coordinator.

These rules describe research candidates. They cannot accept a canonical Gold
state or change its predecessor. No network, file access, or LLM arithmetic.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from math import isfinite
from typing import Any

BASE_WEIGHTS = {"macro": .35, "price": .25, "options": .20, "funds": .15, "events": .05}
RATE_PROFILE = {"id": "gold_real_rate_2026_09", "valid_from": "2026-09-01", "valid_until": "2026-10-01", "thresholds_pct": [2.35, 2.40, 2.45], "kind": "empirical_regime_thresholds_not_statistical_law"}
_DAILY_MAX_BUSINESS_AGE = 4
_WEEKLY_MAX_CALENDAR_AGE = 10
_MONTHLY_MAX_CALENDAR_AGE = {
    "CPI": 75,
    "PPI": 75,
    "PPI_ALL_COMMODITIES": 75,
    "ISM_MANUFACTURING": 75,
    "ISM_SERVICES": 75,
    "ISM_SERVICES_PRICES": 75,
    "PCE": 100,
    "JOLTS": 100,
}


def number(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) else None


def usable(row, *, analysis_cutoff=None, trade_date=None):
    """Return true only for a numerically valid, lineaged, timely row.

    ``status=fresh`` is retained as an upstream assertion, but it is not
    trusted on its own: a malformed snapshot can label a future or years-old
    observation fresh.  When snapshot dates are supplied, this gate checks
    both the observation date and any available source retrieval timestamp.
    """

    return bool(
        isinstance(row, dict)
        and row.get("status") == "fresh"
        and row.get("source_refs")
        and row.get("lineage_status", "verified") == "verified"
        and number(row.get("value")) is not None
        and _row_time_valid(row, analysis_cutoff=analysis_cutoff, trade_date=trade_date)
    )


def same_window(a, b):
    return bool(a.get("observation_date") and a.get("previous_date") and all(a.get(key) == b.get(key) for key in ("observation_date", "previous_date")))


def select_real_rate(rows, *, analysis_cutoff=None, trade_date=None):
    """Official published TIPS takes precedence for v2 research only."""
    official, estimated = rows.get("REAL10Y", {}), rows.get("REAL_10Y", {})
    if usable(official, analysis_cutoff=analysis_cutoff, trade_date=trade_date):
        return official, "official_tips"
    if usable(estimated, analysis_cutoff=analysis_cutoff, trade_date=trade_date):
        components = estimated.get("components", [])
        dates = {str(x.get("date")) for x in components if isinstance(x, dict) and x.get("date")}
        if len(dates) == 1 and len(components) >= 2 and all(isinstance(x, dict) and x.get("date") == estimated.get("observation_date") for x in components):
            return estimated, "estimated_same_date"
    return {}, "unavailable"


def build_gold_workflow(snapshot: dict[str, Any], *, previous: dict[str, Any] | None = None, rate_profile=None) -> dict[str, Any]:
    research = snapshot.get("daily_research", {})
    rows = {row["symbol"]: deepcopy(row) for row in research.get("passport", [])}
    previous = previous or {"status": "unavailable", "reason": "previous_research_not_supplied"}
    analysis_cutoff = _time(snapshot.get("snapshot_time"))
    trade_date = snapshot.get("trade_date")
    # Downstream state/scoring helpers consume only this validated projection;
    # raw passports stay unchanged for audit and historical display.
    for row in rows.values():
        if not _row_time_valid(row, analysis_cutoff=analysis_cutoff, trade_date=trade_date):
            row["status"] = "stale_or_invalid_time"
    real, real_method = select_real_rate(rows, analysis_cutoff=analysis_cutoff, trade_date=trade_date)
    spot = rows.get("XAUUSD_DAILY", {})
    live = research.get("spot_anchor", {})
    now = _time(snapshot.get("snapshot_time"))
    quoted = _time(live.get("price_time"))
    live_verified = bool(live.get("status") == "verified" and live.get("instrument_type") == "spot" and number(live.get("price")) is not None and live.get("source_refs") and quoted and now and 0 <= (now - quoted).total_seconds() <= 900)
    broad = rows.get("BROAD_DOLLAR", {})
    usd = broad if usable(broad, analysis_cutoff=analysis_cutoff, trade_date=trade_date) else rows.get("DXY", {})
    usd_aligned = usable(usd, analysis_cutoff=analysis_cutoff, trade_date=trade_date) and same_window(real, usd)
    price_aligned = usable(spot, analysis_cutoff=analysis_cutoff, trade_date=trade_date) and bool(real.get("observation_date")) and spot.get("observation_date") == real.get("observation_date")
    profile = deepcopy(rate_profile or RATE_PROFILE)
    calibrated = profile["valid_from"] <= str(snapshot.get("trade_date", "")) < profile["valid_until"]
    rate_value = number(real.get("value"))
    zone = "unavailable"
    if rate_value is not None and calibrated:
        a, b, c = profile["thresholds_pct"]
        zone = "supportive" if rate_value < a else "neutral" if rate_value < b else "pressure" if rate_value <= c else "high_risk"

    factors = _factors(snapshot, rows, real, usd, usd_aligned)
    from apps.features.research.levels import build_key_levels

    levels = build_key_levels(snapshot, previous_levels=previous.get("key_levels", []) if previous.get("status") == "verified" else [])
    price_levels = [x for x in levels if x["instrument"] == "XAUUSD spot" and x["status"] in {"Active", "Watch", "Conditional"} and x.get("source_refs") and x.get("eligible_for_target")]
    primary = [f for f in factors if f["direction"] in {"bullish", "bearish"} and f["status"] == "available" and f["role"] == "primary" and f.get("confirmation_aligned", True)]
    independent = {f["family"] for f in primary}
    common_direction = {f["direction"] for f in primary}
    direction_confirmed = len(independent) >= 2 and len(common_direction) == 1 and _data(snapshot, "technical").get("trend") in common_direction
    options = _data(snapshot, "options")
    option_rows = _oi_walls(options)
    option_lineage = _cme_refs(snapshot, options)
    audits = options.get("audit", {}).get("black76_audit", {})
    covered_expiries = set(options.get("data_source", {}).get("expiries", []))
    options_timely = _recent(options.get("data_source", {}).get("report_date"), trade_date, 7)
    expiry_verified = bool(covered_expiries) and options_timely and all(
        isinstance(audits.get(expiry), dict) and audits[expiry].get("expiry_source")
        and not any(word in str(audits[expiry]["expiry_source"]).lower() for word in ("estimat", "fallback", "unknown"))
        and _date_value(audits[expiry].get("expiry_date")) is not None
        and _date_value(trade_date) is not None
        and _date_value(audits[expiry]["expiry_date"]) > _date_value(trade_date)
        for expiry in covered_expiries
    )
    checks = [
        ("Q1", live_verified, "现货锚点", "已验证近期现货报价" if live_verified else "最新价格锚点未完全验证；日线收盘另列，禁止当实时价"),
        ("Q2", all(_row_time_valid(x, analysis_cutoff=analysis_cutoff, trade_date=trade_date) for x in rows.values() if number(x.get("value")) is not None), "时间护照", "每个非空数值的观察日不得晚于 analysis cutoff/trade_date，并按日、周、月频率检查新鲜度"),
        ("Q3", bool(real), "实际利率", real_method),
        ("Q4", bool(option_rows and option_lineage and options_timely), "OI 与成交量", "墙位只消费有引用且时效有效的 OI 特征；Volume/PNT/Block 分列"),
        ("Q5", bool(research.get("official_etf", {}).get("shares_source_refs") or research.get("official_etf", {}).get("source_refs")), "ETF 申赎", "仅份额/持金量变化进入资金分析；AUM 不投方向票"),
        ("Q6", True, "新闻与推论", "官方事实、新闻候选和模型推断分列，标题不证明市场因果"),
        ("Q7", expiry_verified, "期权到期", "确切到期待核验；估算到期只作 Conditional 结构" if not expiry_verified else "按核验到期过滤失效结构"),
        ("Q8", bool(levels) and all(x.get("source_refs") for x in levels if x.get("status") in {"Active", "Watch"}), "关键位生命周期", "现货和期货各自维护；旧窗口退出后 Stale；活跃位必须有来源"),
        ("Q9", direction_confirmed and price_aligned and usd_aligned, "独立方向确认", "至少两个同窗口独立因子及价格同向确认；2Y/Fed 预期仅为利率家族"),
        ("Q10", all(usable(rows.get(k, {}), analysis_cutoff=analysis_cutoff, trade_date=trade_date) for k in ("SOFR", "EFFR", "HY_OAS", "RESERVES")), "关键数据缺口", "融资、信用及准备金必须可用；缺失不等于没有危机"),
    ]
    quality = {"data_quality": "Complete" if all(x[1] for x in checks) else "Partial", "strong_direction_allowed": all(x[1] for x in checks),
               "checks": [{"id": i, "passed": bool(ok), "name": name, "reason": reason} for i, ok, name, reason in checks]}
    scenarios = _scenarios(snapshot, rows, factors, price_levels, quality, expiry_verified, current_spot=live.get("price") if live_verified else None)
    state = _state(snapshot, rows, factors, quality, previous, real, usd)
    live_label = "现货报价有效" if live_verified else "缺少已验证实时现货锚点"
    execution = {
        "status": "unavailable", "timeframes": ["4H", "1H", "15m", "5m"], "primary": "15m", "trigger": "5m",
        "reason": live_label + "；当前快照没有完整且同步的 4H/1H/15m/5m 结构，未确认 BOS/CH/二次入场。",
        "event_rule": "CPI/PPI/NFP/FOMC 后不追第一根 15m 数据 K；先核验扫单、回踩和结构确认。",
        "flat": "空仓：先观察候选路径的价格与宏观共同触发；执行时间框架补齐前不生成入场信号。",
        "long": "已有多单：检查上涨假设是否得到实际利率、美元及资金确认；关键位失效后重新评估，当前数据不足以生成个性化仓位调整。",
        "short": "已有空单：检查下跌是否伴随宏观压力而非单次扫单；若反向突破并获资金确认，原假设失效。",
        "is_trade_instruction": False,
    }
    frames = research.get("execution_timeframes", {}).get("timeframes", {})
    intervals = {"4h": 14400, "1h": 3600, "15m": 900, "5m": 300}
    frame_rows = []
    for key, seconds in intervals.items():
        item = frames.get(key, {})
        close_time, retrieved = _time(item.get("latest_closed_time")), _time(item.get("retrieved_at"))
        current = bool(item.get("status") == "available" and item.get("raw_path") and close_time and retrieved and now and close_time <= retrieved <= now and 0 <= (now - close_time).total_seconds() <= seconds + 300)
        frame_rows.append({"timeframe": key, "status": "available" if current else "unavailable", "close_time": item.get("latest_closed_time"),
                           "trend": item.get("trend") if current else "unavailable", "trend_method": item.get("trend_method"),
                           "events": item.get("events", []) if current else [], "raw_path": item.get("raw_path"),
                           "retrieved_at": item.get("retrieved_at"), "bar_count": item.get("bar_count")})
    execution["timeframe_features"] = frame_rows
    if live_verified and all(x["status"] == "available" for x in frame_rows):
        execution["status"] = "available"
        execution["reason"] = "已取得同期现货锚点和四周期完整 K 线。趋势为短窗收盘方向，区间突破仅为结构代理，不能直接认定摆动结构 BOS/CH 或已获入场确认。"
        execution["flat"] = "空仓：先检查 4H/1H 是否同向，再观察 15m 回踩与 5m 配合；仅出现区间突破代理尚不能视为完成入场确认。"
    execution["trigger_permission"] = "observation_only"
    execution["unimplemented_patterns"] = ["swing_BOS", "CH", "second_entry", "wedge", "retest_confirmation"]
    refs = deepcopy(research.get("source_refs", [])) + deepcopy(previous.get("source_refs", [])) + deepcopy(live.get("source_refs", []))
    refs.extend({"source": "twelvedata_xauusd_" + x["timeframe"], "source_url": "https://api.twelvedata.com/time_series", "raw_path": x["raw_path"], "retrieved_at": x["retrieved_at"]} for x in frame_rows if x.get("raw_path") and x.get("retrieved_at"))
    ids = deepcopy(snapshot.get("input_snapshot_ids", {}))
    if previous.get("status") == "verified":
        ids["previous_research"] = previous["snapshot_id"]
    from apps.features.research.flows import build_flow_diagnostics

    flow_diagnostics = build_flow_diagnostics(snapshot)
    return {
        "schema_version": "gold_workflow.v2", "analysis_time": snapshot.get("snapshot_time"), "analysis_timezone": "UTC", "display_timezone": "Asia/Shanghai",
        "price_anchor": {**deepcopy(live), "status": "verified" if live_verified else "partial", "daily_close": spot.get("value"), "daily_close_date": spot.get("observation_date"), "daily_instrument": "XAUUSD spot/OTC proxy", "delay": "unknown" if not live_verified else live.get("delay", "provider_not_stated")},
        "real_rate": {"symbol": real.get("symbol"), "method": real_method, "value": rate_value, "change": real.get("change"), "previous_date": real.get("previous_date"), "date": real.get("observation_date"), "source_refs": real.get("source_refs", []), "zone": zone, "profile": profile, "profile_status": "active" if calibrated else "requires_recalibration"},
        "factor_families": factors, "quality_gate": quality, "key_levels": levels, "flow_diagnostics": flow_diagnostics,
        "scenario_engine": scenarios, "state": state, "execution": execution,
        "delta_vs_previous": _delta({**rows, **report_comparison_rows(research, as_of=snapshot.get('snapshot_time'))}, previous), "previous_research": {k: previous.get(k) for k in ("status", "reason", "snapshot_id", "snapshot_time", "run_id")},
        "previous_pa_zones": deepcopy(previous.get('execution_zones', [])) if previous.get('status') == 'verified' else [],
        "source_refs": refs, "input_snapshot_ids": ids, "formal_state_authority": False,
        "method_boundaries": ["USD 未回归残差化，标为美元确认；不声称估计了 Residual Dollar Shock。", "四家族均诊断；宏观方向来自实际利率、美元及融资信用。油价/BE 的通胀传导归属利率渠道，不另加同一冲击的方向票。", "HY OAS 只在流动性/信用压力家族计权，通胀段引用时不重复投票。", "规则场景权重描述研究条件排序，未经历史频率校准，不是统计概率。"],
    }


def _factors(snapshot, rows, real, usd, usd_aligned):
    def item(family, inputs, direction, status, explanation, role="primary"):
        return {"family": family, "factor_id": family, "direction": direction, "status": status, "role": role, "explanation": explanation,
                "symbols": [r.get("symbol") for r in inputs if r], "source_refs": [ref for r in inputs for ref in r.get("source_refs", [])]}
    rd = number(real.get("change"))
    factors = [item("real_rate", [real], _direction(-rd) if rd is not None else "unavailable", "available" if real and rd is not None else "partial", "官方 TIPS 优先；名义利率/Fed 预期/2Y−3M 作为同一利率家族的背景。")]
    ud = number(usd.get("change"))
    factors.append(item("dollar", [usd], _direction(-ud) if ud is not None else "unavailable", "available" if usd_aligned and ud is not None else "partial", "广义美元优先，DXY 为盘中辅助；没有同窗口数据不确认与实际利率共振。", "primary" if usd_aligned else "context"))
    reserves, tga = rows.get("RESERVES", {}), rows.get("TGA_WEEKLY_AVERAGE", {})
    valid = all(usable(x) for x in (reserves, tga)) and same_window(reserves, tga)
    rdelta, tdelta = number(reserves.get("weekly_change")), number(tga.get("weekly_change"))
    quantity_direction = "bearish" if valid and rdelta is not None and tdelta is not None and rdelta < 0 < tdelta else "bullish" if valid and rdelta is not None and tdelta is not None and tdelta < 0 < rdelta else "mixed"
    corridor, hy = rows.get("SOFR_MINUS_IORB", {}), rows.get("HY_OAS", {})
    prices_valid = usable(corridor) and usable(hy) and same_window(corridor, hy)
    financing_change, credit_change = number(corridor.get("change")), number(hy.get("change"))
    direction = "mixed"
    if valid and prices_valid and financing_change is not None and credit_change is not None:
        if quantity_direction == "bearish" and financing_change > 0 and credit_change > 0:
            direction = "bearish"
        elif quantity_direction == "bullish" and financing_change <= 0 and credit_change < 0:
            direction = "bullish"
    factors.append(item("liquidity_credit", [reserves, tga, corridor, hy], direction, "available" if valid and prices_valid else "partial", "准备金/TGA 为周频数量背景；同窗口融资利差和信用价格共同确认后进入宏观评分。RRP 接近零不单独触发 SX。", "primary"))
    factors[-1]["quantity_direction"] = quantity_direction
    factors[-1]["confirmation_aligned"] = prices_valid and same_window(corridor, real)
    be, oil = rows.get("BREAKEVEN_10Y", {}), rows.get("BRENT_SPOT", {})
    infl_valid = usable(be) and usable(oil) and same_window(be, oil)
    factors.append(item("inflation", [be, oil], "mixed", "available" if infl_valid else "partial", "油价分为避险需求和成本通胀两通道；成本压力是否传到黄金须由同期实际利率验证，其方向归属 real_rate 家族而不重复计权。", "context"))
    bd, od = number(be.get("change")), number(oil.get("change"))
    factors[-1]["cost_pressure"] = "rising" if infl_valid and bd is not None and od is not None and bd > 0 and od > 0 else "not_confirmed"
    factors[-1]["transmission_family"] = "real_rate"
    return factors


def _scenarios(snapshot, rows, factors, levels, quality, expiry_verified, *, current_spot=None):
    research = snapshot.get("daily_research", {})
    macro = [x for x in factors if x["status"] == "available" and x["role"] == "primary"]
    technical = _data(snapshot, "technical")
    cot = research.get("cot_reports", {}).get("combined", {})
    etf = research.get("official_etf", {})
    fund_values = []
    if cot.get("readiness") == "ready" and cot.get("source_refs") and _recent(cot.get("report_date"), snapshot.get("trade_date"), 10):
        d = number((cot.get("managed_money", {}).get("delta") or {}).get("net"))
        if d is not None:
            fund_values.append(_sign(d))
    if etf.get("source_refs") and "shares_source_lineage" not in etf.get("missing_data", []) and _recent(etf.get("shares_reported_on"), snapshot.get("trade_date"), 4):
        d = number(etf.get("shares_delta"))
        if d is not None:
            # Mixed daily/weekly flow is neutral, not two independent votes.
            w = number(etf.get("shares_weekly_delta"))
            fund_values.append(0 if w is not None and d * w < 0 else _sign(d))
    options = _data(snapshot, "options")
    oi_present = bool(_oi_walls(options) and _cme_refs(snapshot, options) and _recent(options.get("data_source", {}).get("report_date"), snapshot.get("trade_date"), 7))
    events = _data(snapshot, "news").get("daily_market_brief", {})
    directions = {"bullish": 1, "bearish": -1}
    signals = {"macro": sum(directions.get(x["direction"], 0) for x in macro) / len(macro) if macro else 0,
               "price": directions.get(technical.get("trend"), 0), "options": 0,
               "funds": sum(fund_values) / len(fund_values) if fund_values else 0, "events": 0}
    coverage = {"macro": min(1., len(macro) / 3), "price": 1. if usable(rows.get("XAUUSD_DAILY", {})) else 0.,
                "options": (1. if expiry_verified and options.get("data_source", {}).get("status") == "FINAL" else .5) if oi_present else 0.,
                "funds": len(fund_values) / 2, "events": .5 if events.get("confirmed_events") or events.get("candidate_events") else 0.}
    # Observing a wall/news item does not establish a direction or a range.
    # Retain its data coverage and constraints, but do not invent a neutral vote.
    signal_status = {k: "missing" if coverage[k] == 0 else "available_neutral" if signals[k] == 0 else "directional" for k in BASE_WEIGHTS}
    for key in ("options", "events"):
        if coverage[key]:
            signal_status[key] = "direction_unavailable"
    scoring_coverage = {k: coverage[k] if signal_status[k] not in {"direction_unavailable", "missing"} else 0. for k in BASE_WEIGHTS}
    available_mass = sum(BASE_WEIGHTS[k] * scoring_coverage[k] for k in BASE_WEIGHTS)
    normalized = {k: BASE_WEIGHTS[k] * scoring_coverage[k] / available_mass if available_mass else 0. for k in BASE_WEIGHTS}
    scores = {"range": 0., "bull": 0., "bear": 0.}
    for key, weight in normalized.items():
        strength = abs(signals[key])
        # Neutral input contributes 50/25/25; a directional input 20/60/20.
        allocation = {"range": .5 - .3 * strength, "bull": .25 + (.35 if signals[key] > 0 else -.05) * strength, "bear": .25 + (.35 if signals[key] < 0 else -.05) * strength}
        for path in scores:
            scores[path] += weight * allocation[path]
    if not available_mass:
        weights = {k: None for k in scores}
    else:
        weights = {k: round(100 * v, 2) for k, v in scores.items()}
        weights["range"] += round(100 - sum(weights.values()), 2)
    price = number(current_spot)
    anchor_kind = "verified_spot_quote" if price is not None else "completed_daily_close"
    if price is None:
        price = number(rows.get("XAUUSD_DAILY", {}).get("value"))
    supports = sorted({x["price"] for x in levels if price is not None and x["price"] < price}, reverse=True)
    resistances = sorted({x["price"] for x in levels if price is not None and x["price"] > price})
    low = "下方结构待核验" if not supports else " → ".join(f"{v:g}" for v in supports[:3])
    high = "上方结构待核验" if not resistances else " → ".join(f"{v:g}" for v in resistances[:3])
    paths = [
        {"id": "range", "name": "区间消化", "trigger": "最近完整现货区间内反复，价格与两类独立因子尚未形成同向确认。", "macro_confirmation": "实际利率与美元分化；检查资金单日/周窗口分歧。", "price_path": f"下方 {low}；上方 {high}", "invalidation": "现货突破区间且获同窗口利率、美元或资金确认。"},
        {"id": "bull", "name": "修复展开", "trigger": f"现货收复并回踩上方结构：{high}；需要新完整观察窗口验证。", "macro_confirmation": "官方实际利率回落、美元不强，ETF 或 CFTC 至少一个窗口出现资金确认；2Y 用作政策背景。", "price_path": high, "invalidation": "收复失败且实际利率/美元重新形成压力，或份额/持仓确认消失。"},
        {"id": "bear", "name": "压力延续", "trigger": f"现货有效跌破下方结构：{low}；盘中刺穿未单独确认。", "macro_confirmation": "同窗口实际利率上行、美元走强，并观察是否伴随多头收缩；避险新闻本身不构成方向票。", "price_path": low, "invalidation": "跌破后重新收回且实际利率下降，资金承接得到新披露确认。"},
    ]
    main = max(scores, key=scores.get) if available_mass else None
    for path in paths:
        path.update(weight_pct=weights[path["id"]], priority="Main" if path["id"] == main else "Alternative", instrument="XAUUSD", status="conditional")
    return {"schema_version": "gold_scenario_rules.v2", "base_weights": BASE_WEIGHTS.copy(), "coverage": coverage, "normalized_weights": normalized,
            "scoring_coverage": scoring_coverage, "signal_status": signal_status, "direction_signals": signals,
            "macro_scoring_families": [x["family"] for x in macro],
            "constraints": {"options": {"role": "structure_and_expiry_only", "expiry_verified": expiry_verified, "gex": deepcopy(options.get("gex", {}))}, "events": {"role": "event_risk_without_verified_price_reaction", "confirmed_event_count": len(events.get("confirmed_events") or [])}},
            "price_anchor": price, "price_anchor_kind": anchor_kind, "level_basis": "completed_daily_structure_no_intraday_role_reversal",
            "confidence": round(available_mass * (1. if quality["strong_direction_allowed"] else .5), 3), "confidence_semantics": "coverage_discount_not_forecast_probability",
            "rule": "category weight x scoring coverage, normalized; direction_unavailable excluded; neutral=50/25/25, directional=20/60/20; mixed linearly interpolated", "semantics": "rule_weights_not_statistical_probability",
            "main_scenario_id": main, "scenarios": paths}


def _state(snapshot, rows, factors, quality, previous, real, usd):
    technical = _data(snapshot, "technical")
    trend = technical.get("trend")
    rd, ud = number(real.get("change")), number(usd.get("change"))
    aligned = same_window(real, usd) and usable(rows.get("XAUUSD_DAILY", {})) and rows["XAUUSD_DAILY"].get("observation_date") == real.get("observation_date")
    candidate = "S1" if aligned and trend == "bearish" and rd is not None and rd > 0 and ud is not None and ud > 0 else None
    structure = technical.get("price_structure", {})
    boundaries = {x.get("kind"): number(x.get("price")) for x in structure.get("levels", [])}
    price = number(technical.get("price"))
    low, high = boundaries.get("prior_5d_low"), boundaries.get("prior_5d_high")
    structure_valid = bool(structure.get("source_refs")) and structure.get("status") == "available" and structure.get("as_of") == technical.get("as_of")
    previous_price = number(technical.get("previous_price"))
    if candidate is None and structure_valid and usable(rows.get("XAUUSD_DAILY", {})) and None not in (price, previous_price, low, high) and low <= price <= high and low <= previous_price <= high:
        candidate = "S4"
    research = snapshot.get("daily_research", {})
    etf = research.get("official_etf", {})
    cot = research.get("cot_reports", {}).get("combined", {})
    ed = number(etf.get("shares_delta"))
    cd = number((cot.get("managed_money", {}).get("delta") or {}).get("net"))
    funds = bool(ed is not None and ed > 0 and etf.get("source_refs") and "shares_source_lineage" not in etf.get("missing_data", []) and _recent(etf.get("shares_reported_on"), snapshot.get("trade_date"), 4)) or bool(cd is not None and cd > 0 and cot.get("readiness") == "ready" and cot.get("source_refs") and _recent(cot.get("report_date"), snapshot.get("trade_date"), 10))
    macro_relief = aligned and rd is not None and ud is not None and rd <= 0 and ud <= 0
    high20 = boundaries.get("prior_20d_high")
    atr = number(technical.get("atr14"))
    if structure_valid and price is not None and funds:
        if aligned and low is not None and atr is not None and atr > 0 and abs(price - low) <= .25 * atr and (rd or 0) > 0:
            candidate = "S2"
        reclaimed = any(x.get("kind") == "prior_5d_low" and x.get("status") == "reclaimed_after_intraday_breach" for x in structure.get("levels", []))
        if macro_relief and reclaimed and trend == "bullish":
            candidate = "S3"
        if macro_relief and rd < 0 and high is not None and price > high and trend == "bullish":
            candidate = "S5"
        if macro_relief and rd < 0 and high20 is not None and price > high20 and trend == "bullish":
            candidate = "S6"
    corridor, hy, reserves = rows.get("SOFR_MINUS_IORB", {}), rows.get("HY_OAS", {}), rows.get("RESERVES", {})
    sx = all(usable(x) for x in (corridor, hy, reserves)) and same_window(corridor, hy) and number(corridor.get("value")) is not None and corridor["value"] >= .20 and (number(hy.get("weekly_change")) or 0) >= .50 and (number(reserves.get("weekly_change")) or 0) < 0
    if sx:
        candidate = "SX"
    labels = {"S1": "Rates Pressure / 利率压制候选", "S2": "Support Defense / 支撑防守候选", "S3": "Bottom Confirmation / 底部确认候选", "S4": "Range Accumulation / 区间候选", "S5": "Active Repair / 主动修复候选", "S6": "Trend Continuation / 趋势延续候选", "SX": "Liquidity Selloff / 流动性抛售候选"}
    return {"previous_state": previous.get("research_state", {}).get("current_state"), "current_state": None,
            "candidate_state": candidate, "candidate_label": labels.get(candidate, "证据不足，候选待定"),
            "candidate_scope": "research_hypothesis_only", "state_confidence": None, "transition": "not_evaluated_by_canonical_authority",
            "reason": "正式状态由已接受 Gold 决策及前序链决定；研究区间候选不能自行写为当前 S4，也不能从用户旧报告初始化 S5。",
            "requirements": {"S1": "实际利率与美元同窗口上升、黄金走弱", "S2": "重要支撑附近且有可追溯资金承接，宏观仍受压", "S3": "实际利率和美元停止上升、资金与价格反转共同确认", "S4": "稳定价格区间和混合宏观资金", "S5": "区间突破、价格改善、宏观改善和资金回归", "S6": "主要趋势闸门突破、实际利率下降、美元不强、ETF/CFTC 至少一项确认", "SX": "融资利差异常、准备金压力和信用走阔共同验证"},
            "strong_direction_allowed": quality["strong_direction_allowed"], "formal_state_authority": False}


def _observation_time(value):
    # Official day observations have no intraday clock; quotes retain a zone.
    return _time(value + 'T00:00:00+00:00' if isinstance(value, str) and len(value) == 10 else value)


def report_comparison_rows(research, *, as_of=None):
    """Level comparisons across verified reports, never substitute weekly flows."""
    result = {}

    def add(symbol, value, observed, unit, refs, valid):
        if as_of is not None:
            cutoff, observed_time = _time(as_of), _observation_time(observed)
            valid = valid and cutoff is not None and observed_time is not None and observed_time <= cutoff
            if valid and symbol == 'XAUUSD_QUOTE':
                valid = (cutoff - observed_time).total_seconds() <= 900
        result[symbol] = {'symbol': symbol, 'value': value if valid else None,
                          'observation_date': observed, 'unit': unit, 'source_refs': deepcopy(refs)}

    spot = research.get('spot_anchor', {})
    add('XAUUSD_QUOTE', spot.get('price'), spot.get('price_time'), 'USD/oz', spot.get('source_refs', []),
        spot.get('status') == 'verified' and spot.get('instrument_type') == 'spot')
    etf = research.get('official_etf', {})
    for symbol, field, date_field, unit in [('GLD_SHARES', 'shares_outstanding', 'shares_reported_on', 'shares'),
                                           ('GLD_TONNES', 'gold_holdings_tonnes', 'gold_holdings_tonnes_reported_on', 'tonnes')]:
        add(symbol, etf.get(field), etf.get(date_field), unit, etf.get('source_refs', []),
            etf.get('status') == 'available' and etf.get('ticker') == 'GLD')
    cot = research.get('cot_reports', {}).get('combined', {})
    add('CFTC_COMBINED_MM_NET', cot.get('managed_money', {}).get('latest', {}).get('net'), cot.get('report_date'),
        'contracts', cot.get('source_refs', []), cot.get('readiness') == 'ready' and cot.get('report_type') == 'combined')
    return result


def _delta(rows, previous):
    if previous.get("status") != "verified":
        return {"status": "unavailable", "reason": previous.get("reason"), "rows": []}
    old = {r["symbol"]: r for r in previous.get("passport", [])}
    old.update(previous.get('comparison_rows', {}))
    changes = []
    for symbol, row in rows.items():
        before = old.get(symbol, {})
        a, b = number(before.get("value")), number(row.get("value"))
        old_time, new_time = _observation_time(before.get('observation_date')), _observation_time(row.get('observation_date'))
        comparable = (a is not None and b is not None and row.get("unit") == before.get("unit")
                      and _source_identity(row) == _source_identity(before) and bool(_source_identity(row))
                      and old_time is not None and new_time is not None and new_time >= old_time
                      and row.get('status') != 'stale_or_invalid_time'
                      and _time(previous.get('snapshot_time')) is not None
                      and old_time <= _time(previous['snapshot_time']))
        same_date = row.get("observation_date") == before.get("observation_date")
        changes.append({"symbol": symbol, "previous": a, "current": b, "delta": b - a if comparable else None, "unit": row.get("unit"),
                        "previous_date": before.get("observation_date"), "current_date": row.get("observation_date"),
                        "change_kind": "unavailable_or_source_changed" if not comparable else "same_observation_revised" if same_date and a != b else "unchanged" if same_date else "new_observation"})
    return {"status": "available", "previous_snapshot_id": previous["snapshot_id"], "previous_analysis_time": previous["snapshot_time"], "rows": changes, "source_refs": previous.get("source_refs", [])}


def _source_identity(row):
    return sorted({(str(x.get("source")), str(x.get("source_url") or x.get("reference"))) for x in row.get("source_refs", []) if x.get("source")})


def _oi_walls(options):
    walls = options.get("walls", {})
    values = [item for group in walls.values() if isinstance(group, list) for item in group] if isinstance(walls, dict) else walls if isinstance(walls, list) else []
    return [x for x in values if isinstance(x, dict) and number(x.get("strike")) is not None and number(x.get("oi")) is not None and x["oi"] >= 0]


def _cme_refs(snapshot, options):
    refs = [*options.get("source_refs", []), *snapshot.get("source_refs", [])]
    return [x for x in refs if "cme" in str(x.get("source", "")).lower() and (x.get("raw_path") or x.get("artifact_ref")) and (x.get("source_url") or x.get("reference"))]


def _data(snapshot, key):
    section = snapshot.get(key, {})
    return section.get("data", {}) if section.get("status") == "available" else {}


def _row_time_valid(row, *, analysis_cutoff=None, trade_date=None):
    """Validate observation/freshness dates without changing row contents."""

    if not isinstance(row, dict):
        return False
    observed = _date_value(row.get("observation_date"))
    if observed is None:
        return False
    cutoff_dt = _datetime_value(analysis_cutoff)
    cutoff_date = cutoff_dt.date() if cutoff_dt is not None else _date_value(analysis_cutoff)
    trade = _date_value(trade_date)
    upper_bounds = [value for value in (cutoff_date, trade) if value is not None]
    as_of = min(upper_bounds) if upper_bounds else None
    if as_of is not None and observed > as_of:
        return False

    # Preserve the existing freshness vocabulary when a producer supplies it;
    # a value with an explicit stale/unavailable marker cannot become usable
    # merely because its date parses.
    for key in ("freshness_status", "freshness"):
        value = row.get(key)
        if value is not None and str(value).lower() not in {"fresh", "current", "available"}:
            return False
    status = row.get("status")
    if status is not None and status not in {"fresh", "current"}:
        return False

    if as_of is not None:
        age = (as_of - observed).days
        if age < 0 or not _freshness_window_valid(row, observed=observed, as_of=as_of):
            return False

    if cutoff_dt is not None:
        for ref in row.get("source_refs") or []:
            if not isinstance(ref, dict) or not ref.get("retrieved_at"):
                continue
            retrieved = _datetime_value(ref.get("retrieved_at"))
            if retrieved is None or retrieved > cutoff_dt:
                return False
    return True


def _freshness_window_valid(row, *, observed, as_of):
    frequency = str(row.get("frequency") or row.get("expected_frequency") or "daily").lower()
    explicit = row.get("freshness_max_age_days", row.get("max_age_days"))
    if isinstance(explicit, (int, float)) and not isinstance(explicit, bool) and explicit >= 0:
        return (as_of - observed).days <= float(explicit)
    if frequency in {"monthly", "month"}:
        return (as_of - observed).days <= _MONTHLY_MAX_CALENDAR_AGE.get(str(row.get("symbol") or ""), 100)
    if frequency in {"weekly", "week", "weekly_average"}:
        return (as_of - observed).days <= _WEEKLY_MAX_CALENDAR_AGE
    return _business_day_age(observed, as_of) <= _DAILY_MAX_BUSINESS_AGE


def _business_day_age(start, end):
    days = 0
    cursor = start
    while cursor < end:
        cursor = cursor.fromordinal(cursor.toordinal() + 1)
        if cursor.weekday() < 5:
            days += 1
    return days


def _date_value(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _datetime_value(value):
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else None
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _time(value):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result if result.tzinfo is not None else None
    except ValueError:
        return None


def _recent(value, as_of, days):
    try:
        return 0 <= (date.fromisoformat(str(as_of)[:10]) - date.fromisoformat(str(value)[:10])).days <= days
    except ValueError:
        return False


def _sign(value):
    return 1 if value > 0 else -1 if value < 0 else 0


def _direction(value):
    return "bullish" if value > 0 else "bearish" if value < 0 else "neutral"
