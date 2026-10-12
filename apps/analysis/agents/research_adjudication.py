"""Evidence-family adjudication for the existing daily research coordinator.

This is an observation view, never a second Gold state authority. Correlated
rate inputs share one family; option inventory models constrain scenarios and
do not cast a directional vote. All inputs are computed snapshot features.
"""

from __future__ import annotations

from datetime import date
from math import isfinite
from typing import Any


def adjudicate_research(snapshot: dict[str, Any]) -> dict[str, Any]:
    research = snapshot.get("daily_research", {})
    rows = {row["symbol"]: row for row in research.get("passport", [])}
    if not rows:
        return {}
    factors: list[dict[str, Any]] = []
    missing: list[str] = []

    def add(factor_id, family, role, bias, rationale, inputs, *, window="previous_observation", invalidation=""):
        refs = [ref for item in inputs for ref in item.get("source_refs", [])]
        factors.append({"factor_id": factor_id, "family": family, "role": role, "bias": bias,
                        "rationale": rationale, "comparison_window": window,
                        "observation_dates": sorted({str(item.get("observation_date")) for item in inputs if item.get("observation_date")}),
                        "source_refs": refs, "input_snapshot_ids": research.get("input_snapshot_ids", {}),
                        "data_category": "system_inference", "invalidated_by": invalidation})

    real = _row(rows, "REAL_10Y")
    real_label = "实际利率代理"
    if snapshot.get("gold_workflow", {}).get("schema_version") == "gold_workflow.v2":
        from apps.features.research.workflow import select_real_rate

        real, method = select_real_rate(rows)
        real_label = "官方 TIPS 实际利率" if method == "official_tips" else "实际利率估算"
    if real and _number(real.get("change")) is not None and real.get("previous_date"):
        delta = real["change"]
        add("real_yield", "rates", "primary", _inverse(delta),
            f"{real_label} {real['value']:.2f}%，较 {real['previous_date']} 变化 {delta * 100:+.1f}bp；这是日频持有成本变化，不能单独归因于某条公告。", [real],
            invalidation="同口径实际利率变化反向，或观察日落后于待解释的价格窗口")
    else:
        missing.append("同口径实际利率增量")

    short_curve = research.get("project_signals", {}).get("short_curve", {})
    if short_curve.get("status") in {"fresh", "available", "ready"}:
        add("short_curve_2y_3m", "rates", "confirmation", "neutral",
            short_curve.get("summary") or "2Y−3M 需要拆分两腿变化，曲线正负不能独立决定黄金方向。",
            [short_curve], window=short_curve.get("comparison_window", "previous_observation"),
            invalidation="2Y/3M 比较日期不一致，或两腿变化反向")
    else:
        missing.append("可对齐的 2Y−3M 两腿解释")

    usd = _row(rows, "DXY")
    if snapshot.get("gold_workflow"):
        usd = _row(rows, "BROAD_DOLLAR") or usd
    if usd and _number(usd.get("change")) is not None and usd.get("previous_date"):
        aligned = bool(real and usd.get("observation_date") == real.get("observation_date") and usd.get("previous_date") == real.get("previous_date"))
        add("dollar", "usd", "primary" if aligned else "context", _inverse(usd["change"]),
            f"{usd.get('symbol', 'DXY')} {usd['value']:.3f}，较 {usd['previous_date']} 变化 {usd['change']:+.3f}；" + ("与实际利率比较窗口对齐。" if aligned else "与实际利率窗口未对齐，不称为同步共振。"), [usd],
            invalidation="同源美元变化反向或窗口不再可比")
        if not aligned:
            missing.append("美元与实际利率同步窗口")
    elif usd and _number(usd.get("provider_reported_change")) is not None:
        add("dollar", "usd", "context", _inverse(usd["provider_reported_change"]),
            f"DXY {usd['value']:.3f}，来源报告较前一会话变化 {usd['provider_reported_change']:+.3f}；前收 {usd['provider_previous_close']:.3f}，前收日期未提供，不作与利率同步共振的证明。", [usd],
            window="provider_previous_session", invalidation="后续同源变化反向或前收字段校验不一致")
        missing.append("美元前收日期与实际利率同步窗口")
    else:
        missing.append("美元同源前值与变化；有最新点位也不等于已知涨跌")

    reserves, tga = _row(rows, "RESERVES"), _row(rows, "TGA_WEEKLY_AVERAGE")
    if reserves and tga and _same_week(reserves, tga):
        rd, td = reserves["weekly_change"], tga["weekly_change"]
        bias = "bearish" if rd < 0 < td else "bullish" if td < 0 < rd else "mixed"
        add("reserve_tga", "liquidity", "confirmation", bias,
            f"同周准备金变化 {rd:+.3f}B，TGA 周均变化 {td:+.3f}B；反映数量环境，须与利率走廊联合验证，不能用两项解释全部准备金变化。",
            [reserves, tga], window="weekly_average", invalidation="下一同周数量变化反向，或融资价格与数量叙事背离")

    cot = research.get("cot_reports", {}).get("combined", {})
    mm_delta = cot.get("managed_money", {}).get("delta") or {}
    if cot.get("readiness") == "ready" and cot.get("source_refs") and _recent(cot.get("report_date"), snapshot.get("trade_date"), 10) and _number(mm_delta.get("net")) is not None:
        net = mm_delta["net"]
        add("managed_money", "positioning", "confirmation", _direct(net),
            f"截至 {cot.get('report_date')}，Managed Money 净仓周变化 {net:+,.0f} 手；长仓 {mm_delta.get('long')}、短仓 {mm_delta.get('short')}，全市场 OI 变化 {cot.get('open_interest', {}).get('delta')}。周二持仓不代表随后公告后的即时交易。",
            [dict(cot, observation_date=cot.get("report_date"))], window="weekly_positions", invalidation="下一期长短仓增量反向；全市场 OI 不能单独量化基金杠杆")

    etf = research.get("official_etf", {})
    if etf.get("status") in {"available", "partial"} and etf.get("source_refs") and "shares_source_lineage" not in etf.get("missing_data", []) and _recent(etf.get("shares_reported_on"), snapshot.get("trade_date"), 4) and _number(etf.get("shares_delta")) is not None:
        daily, weekly = etf["shares_delta"], _number(etf.get("shares_weekly_delta"))
        bias = "mixed" if weekly is not None and daily * weekly < 0 else _direct(daily)
        note = f"GLD {etf.get('shares_reported_on')} 单日份额变化 {daily:+,.0f}；"
        note += f"自 {etf.get('shares_weekly_anchor_date')} 周窗口累计 {weekly:+,.0f}。" if weekly is not None else "周窗口待核验。"
        add("gld_creation_redemption", "etf", "confirmation", bias, note + "单日与周窗口归入一个资金因子，不重复计权；份额不能证明特定价位承接。",
            [dict(etf, observation_date=etf.get("shares_reported_on"))], window="daily_and_weekly_separate", invalidation="后续份额披露改变单日与周窗口的分化")

    technical = _section(snapshot, "technical")
    spot = _row(rows, "XAUUSD_DAILY")
    price_aligned = bool(spot and real and spot.get("observation_date") == real.get("observation_date"))
    if technical and spot:
        add("spot_confirmation", "price", "confirmation" if price_aligned else "context", technical.get("trend", "neutral"),
            f"现货 {technical.get('price')}，MA20 {technical.get('ma20')}、MA50 {technical.get('ma50')}；" + ("价格用于确认宏观解释，均线不是正式状态迁移线。" if price_aligned else "现货与利率观察日不同，暂不作为同窗口的价格确认。"),
            [spot], invalidation="后续完整收盘穿越对应结构，或日线不再新鲜")
        if not price_aligned:
            missing.append("现货与宏观同一观察日确认")

    options = _section(snapshot, "options")
    if options:
        source = options.get("data_source", {})
        audit = options.get("audit", {}).get("gex_audit", {})
        add("cme_structure", "options", "constraint", "neutral",
            f"CME {source.get('status', 'unavailable')}，模型 Net GEX {audit.get('net_gex')}、Gamma Zero {audit.get('gamma_zero_full')}；作为期限和波动结构约束，不把正 GEX、Call OI 或墙位当独立看涨票。",
            [{"source_refs": [ref for ref in snapshot.get("source_refs", []) if "cme" in str(ref.get("source", "")).lower()], "observation_date": source.get("report_date")}],
            window="exchange_report", invalidation="FINAL 修订、基差或到期结构变化；没有同时间基差不映射现货价位")

    news = _section(snapshot, "news")
    brief = news.get("daily_market_brief", {})
    confirmed, candidates = brief.get("confirmed_events", []), brief.get("candidate_events", [])
    event_refs = [ref for event in [*confirmed, *candidates] for ref in event.get("source_refs", [])]
    if event_refs:
        add("news_event_context", "news", "context", "neutral",
            f"本窗口有 {len(confirmed)} 条官方确认事件、{len(candidates)} 条待核验候选报道；官方日程另列。新闻用于解释潜在传导路径，标题摘要不能证明公告数值、市场预期或即时价格因果。",
            [{"source_refs": event_refs}], window="news_coverage_window",
            invalidation="原文核验否定候选、事件失去时效，或缺少同窗口价格反应")
    else:
        missing.append("可追溯新闻事件上下文；新闻缺失不能被解释为没有事件风险")

    # Only independent, aligned primary families decide the research tilt.
    primary = [item for item in factors if item["role"] == "primary"]
    directions = {item["bias"] for item in primary if item["bias"] in {"bullish", "bearish"}}
    tilt = next(iter(directions)) if len(directions) == 1 else "mixed" if directions else "neutral" if primary else "unavailable"
    dominant = [item for item in primary if item["bias"] == tilt]
    counters = [item for item in factors if item["role"] != "constraint" and (item["bias"] == "mixed" or item["bias"] in {"bullish", "bearish"} and item["bias"] != tilt)]
    corroborated = len({item["family"] for item in dominant}) >= 2
    price_bias = technical.get("trend") if spot else None
    preferred = "压力延续" if corroborated and price_aligned and tilt == price_bias == "bearish" else "修复展开" if corroborated and price_aligned and tilt == price_bias == "bullish" else "区间消化"
    overall_bias = tilt if preferred != "区间消化" or tilt in {"mixed", "unavailable"} else "neutral"
    family_count = len({item["family"] for item in factors if item["role"] in {"primary", "confirmation"}})
    # A transparent coverage score, deliberately not a forecast probability.
    confidence = round(min(0.65, 0.15 + 0.08 * family_count) if primary else 0.0, 2)
    if missing:
        confidence = min(confidence, 0.49)
    label = {"bearish": "偏空", "bullish": "偏多", "mixed": "分歧", "neutral": "中性", "unavailable": "不可判断"}[tilt]
    summary = f"当前优先观察“{preferred}”，" + (f"综合倾向{label}。" if preferred != "区间消化" else f"已取得的主导因子{label}，综合方向尚未确认。")
    summary += "主导证据：" + " ".join(item["rationale"] for item in dominant) if dominant else "当前缺少一致的独立主导证据。"
    if short_curve.get("summary") and short_curve.get("status") in {"fresh", "available", "ready"}:
        summary += " 短端辨析：" + short_curve["summary"]
    if counters:
        summary += " 反证与限制：" + " ".join(item["rationale"] for item in counters[:2])
    summary += " " + ("利率、美元与价格已提供同向确认，但仍需后续数据维持。" if corroborated and preferred != "区间消化" else "尚缺利率、美元与现货的共同方向确认，保留双向路径。")
    return {"schema_version": "research_adjudication.v1", "bias": overall_bias, "factor_tilt": tilt, "status": "partial" if missing else "success", "confidence": confidence,
            "confidence_semantics": "evidence_family_coverage_not_forecast_probability", "confidence_basis": {"independent_family_count": family_count, "base": 0.15, "per_family": 0.08, "cap": 0.65, "incomplete_cap": 0.49},
            "factors": factors, "dominant_factor_ids": [item["factor_id"] for item in dominant], "counter_factor_ids": [item["factor_id"] for item in counters],
            "missing_confirmations": missing, "preferred_scenario": preferred, "summary": summary,
            "formal_state_authority": False, "source_refs": [ref for factor in factors for ref in factor["source_refs"]], "input_snapshot_ids": research.get("input_snapshot_ids", {})}


def _row(rows, key):
    item = rows.get(key, {})
    return item if item.get("status") == "fresh" and item.get("lineage_status", "verified") == "verified" and item.get("source_refs") and _number(item.get("value")) is not None else {}


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) else None


def _direct(value):
    return "bullish" if value > 0 else "bearish" if value < 0 else "neutral"


def _inverse(value):
    return "bearish" if value > 0 else "bullish" if value < 0 else "neutral"


def _same_week(a, b):
    return all(_number(row.get("weekly_change")) is not None for row in (a, b)) and bool(a.get("observation_date") and a.get("weekly_anchor_date")) and a.get("observation_date") == b.get("observation_date") and a.get("weekly_anchor_date") == b.get("weekly_anchor_date")


def _recent(value, context, days):
    try:
        return 0 <= (date.fromisoformat(str(context)[:10]) - date.fromisoformat(str(value)[:10])).days <= days
    except ValueError:
        return False


def _section(snapshot, key):
    part = snapshot.get(key, {})
    return part.get("data", {}) if part.get("status") == "available" else {}
