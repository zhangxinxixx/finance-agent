"""Evidence-bound context for the existing coordinator, not a state authority."""

from typing import Any
from datetime import date

from apps.analysis.agents.research_adjudication import adjudicate_research


def build_research_assessment(snapshot: dict[str, Any]) -> dict[str, Any]:
    research = snapshot.get("daily_research", {})
    rows = {row["symbol"]: row for row in research.get("passport", [])}
    if not rows:
        return {}
    facts: list[str] = []
    drivers: list[str] = []
    counterevidence: list[str] = []
    limitations: list[str] = []

    def change(key: str) -> float | None:
        row = rows.get(key, {})
        return row.get("change") if row.get("status") == "fresh" else None

    real_key = snapshot.get("gold_workflow", {}).get("real_rate", {}).get("symbol") or "REAL_10Y"
    short, long, real = change("US02Y"), change("US10Y"), change(real_key)
    if research.get("rate_changes_same_window") and short is not None and long is not None:
        if short > long and short > 0:
            drivers.append("同一观察窗口内短端利率上行更明显，政策路径重定价是当前需要优先观察的黄金压力来源。")
        elif short < 0 and long < 0:
            drivers.append("短端与长端收益率同步回落，利率通道对黄金的边际压制有所缓解。")
        else:
            facts.append("短端与长端利率变化未形成单一方向，应分别跟踪政策路径与期限溢价。")
    else:
        limitations.append("2Y 与 10Y 的本期/前期日期未全部对齐，不能声称曲线在同一事件窗口内发生了何种冲击。")
    if real is not None:
        (drivers if real > 0 else counterevidence).append(
            ("官方 TIPS 实际利率" if real_key == "REAL10Y" else "同日名义收益率减 Breakeven 的实际利率代理")
            + "较前次上升，增加黄金持有的机会成本。"
            if real > 0
            else "同口径实际利率未继续上升，暂不支持新一轮实际利率上冲的解释。"
        )
    rate_notes = []
    for key, label in (("US02Y", "2Y"), ("US10Y", "10Y"), ("US30Y", "30Y"), ("REAL10Y", "10Y 实际利率")):
        row = rows.get(key, {})
        if row.get("status") == "fresh" and row.get("value") is not None:
            delta = (
                f"，较 {row.get('previous_date')} 变化 {row['change'] * 100:+.1f}bp"
                if row.get("change") is not None
                else ""
            )
            rate_notes.append(f"{label} 为 {row['value']:.2f}%（{row.get('observation_date')}）{delta}。")
    rate_notes.extend([*facts, *drivers, *counterevidence])
    price_date = rows.get("XAUUSD_DAILY", {}).get("observation_date")
    rate_date = rows.get("US02Y", {}).get("observation_date")
    rates_lag_price = bool(price_date and rate_date and rate_date < price_date)
    if rates_lag_price:
        boundary = (
            f"利率可得观察日停在 {rate_date}，早于现货 {price_date}：上述变化不能用于判断这一天的事件后利率反应。"
        )
        limitations.append(boundary)
        rate_notes.append(boundary)
    limitations.append(
        "日频收益率只能描述日间变化；没有发布前后的同步行情时，不将其直接归因于某条公告，也不据此证明金价反弹原因。"
    )
    reserves_row, tga_row = rows.get("RESERVES", {}), rows.get("TGA_WEEKLY_AVERAGE", {})
    reserves = reserves_row.get("weekly_change") if reserves_row.get("status") == "fresh" else None
    tga = tga_row.get("weekly_change") if tga_row.get("status") == "fresh" else None
    if reserves is not None and tga is not None and reserves < 0 < tga:
        drivers.append("银行准备金周均下降、TGA 周均回补，流动性边际收紧；TGA 日值另列，不能用不同时间窗做机械抵消。")
    liquidity_notes = []
    if reserves is not None and tga is not None:
        liquidity_notes.append(
            f"准备金周均变化 {reserves:+.3f} 十亿美元，TGA 周均变化 {tga:+.3f} 十亿美元；周均统计窗口截至 {reserves_row.get('observation_date')}。"
        )
    hy = rows.get("HY_OAS", {})
    if hy.get("status") == "fresh" and hy.get("value") is not None:
        facts.append(
            f"最新可得 HY OAS 为 {hy['value']:.2f}%（{hy['observation_date']}），结合其变化检查信用市场是否共振；单一低水平不能证明没有任何融资风险。"
        )
        liquidity_notes.append(facts[-1])
    for key, label in (("SOFR", "SOFR"), ("EFFR", "EFFR"), ("IORB", "IORB"), ("VIX", "VIX")):
        row = rows.get(key, {})
        if row.get("status") == "fresh":
            liquidity_notes.append(
                f"{label}：{row.get('value')} {row.get('unit')}，观察日 {row.get('observation_date')}。"
            )
    oil = [rows.get(key, {}) for key in ("WTI_SPOT", "BRENT_SPOT")]
    energy_notes = [
        f"{row.get('label')} 为 {row.get('value')} 美元/桶（{row.get('observation_date')}），较 {row.get('weekly_anchor_date')} 变化 {row.get('weekly_change')} 美元/桶。"
        for row in oil
        if row.get("status") == "fresh"
    ]
    for key in ("WTI_FUTURES_PROXY", "BRENT_FUTURES_PROXY"):
        row = rows.get(key, {})
        if row.get("status") == "fresh":
            energy_notes.append(
                f"{row.get('label')}：{row.get('value'):.2f} 美元/桶，交易日 {row.get('observation_date')}。它提供较新的连续合约行情，仍不能替代交易所指定月份的结算价。"
            )
    if any(row.get("status") == "fresh" and (row.get("weekly_change") or 0) > 0 for row in oil):
        drivers.append(
            "可得原油现货周变化上升，能源成本可能经通胀预期和短端利率压制黄金；增长放缓与避险需求也可能产生相反作用。"
        )
    limitations.append("EIA/FRED 原油是延迟发布的现货价格；不能把它写成最新 Brent/WTI 期货结算。")
    limitations.append(
        "ETF、CFTC、宏观利率与 CME 的观察频率不同；共存的信号可以描述资金结构，但不能推断同一时点的买卖因果。"
    )

    employment_domain = research.get("employment", {})
    employment = employment_domain.get("metrics", {})
    jobs = employment.get("CES0000000001", {})
    wages = employment.get("CES0500000003", {})
    if jobs.get("new_jobs_thousands") is not None:
        facts.append(
            f"{jobs.get('current_month')} 非农新增 {jobs['new_jobs_thousands']:g} 千人；未取得可核验市场预期，不计算超预期幅度。"
        )
        if wages.get("monthly_change_pct") is not None and wages.get("yoy_change_pct") is not None:
            facts.append(
                f"时薪环比 {wages['monthly_change_pct']:.2f}%、同比 {wages['yoy_change_pct']:.2f}%；就业数量与工资压力需分别判断。"
            )
    release = employment_domain.get("release_context", {})
    industry = [
        item
        for item in employment_domain.get("industry_employment", {}).values()
        if item.get("status") == "available"
        and item.get("current_source")
        and item.get("current_month") == jobs.get("current_month")
        and item.get("monthly_change") is not None
    ]
    employment_notes = []
    growth_notes = []
    for symbol in ("GDP_NOW", "ISM_MANUFACTURING", "ISM_SERVICES", "ISM_SERVICES_PRICES"):
        row = rows.get(symbol, {})
        if row.get("status") == "fresh" and row.get("value") is not None:
            statement = f"[FACT] {row.get('label', symbol)}：{row['value']:g} {row.get('unit', '')}，参考期 {row.get('reference_period')}，发布 {row.get('release_date')}。"
            facts.append(statement)
            growth_notes.append(statement)
    if all(
        rows.get(k, {}).get("status") == "fresh"
        for k in ("GDP_NOW", "ISM_MANUFACTURING", "ISM_SERVICES", "ISM_SERVICES_PRICES")
    ):
        if (
            rows["GDP_NOW"]["value"] > 0
            and rows["ISM_MANUFACTURING"]["value"] > 50
            and rows["ISM_SERVICES"]["value"] > 50
        ):
            growth_notes.append(
                "[MODEL] GDPNow 与两项 PMI 共同支持增长仍有韧性；GDPNow 是实时跟踪估计，PMI 是扩散指数，均不能当作最终 GDP 或直接证明 Fed 将加息。"
            )
        if rows["ISM_SERVICES_PRICES"]["value"] > 50:
            growth_notes.append(
                "[MODEL] 服务业价格指数高于 50 表示报告成本上涨的企业更普遍；它不是 CPI 同比，需由后续 PPI/CPI 与实际利率反应确认黄金的通胀传导。"
            )
    positive = sorted(
        (item for item in industry if item["monthly_change"] > 0), key=lambda item: item["monthly_change"], reverse=True
    )
    negative = [item for item in industry if item["monthly_change"] < 0]
    if positive and negative:
        growth = "、".join(f"{item['label']}（+{item['monthly_change']:g}千人）" for item in positive[:2])
        declines = "、".join(f"{item['label']}（{item['monthly_change']:g}千人）" for item in negative)
        employment_notes.append(
            f"已覆盖行业中，{growth}增量居前，而{declines}仍减少。总量需结合这种行业分化解读，不能把新增就业直接等同于各行业全面过热；这五个行业并非完整分解。"
        )
    if release.get("status") in {"available", "partial"} and release.get("source_refs"):
        for revision in release.get("revisions", []):
            facts.append(
                f"{revision.get('observation_month')} 新增就业：前版本 {revision.get('previous_value_thousands')} 千人，最新版本 {revision.get('revised_value_thousands')} 千人，修订 {revision.get('delta_thousands')} 千人。"
            )
    if not release.get("revisions") or not release.get("source_refs"):
        limitations.append("就业修订尚无可核验的发布原文或跨版本证据；同一版本月度水平无法提供修订量。")
    combined = research.get("cot_reports", {}).get("combined", {})
    mm = combined.get("managed_money", {})
    delta = mm.get("delta") or {}
    oi = combined.get("open_interest", {})
    if (
        combined.get("quality_status") not in {None, "blocked"}
        and combined.get("freshness_status") != "stale"
        and combined.get("alignment_status") != "misaligned"
        and delta.get("net") is not None
    ):
        facts.append(
            f"CFTC 合并口径截至 {combined.get('report_date')}，Managed Money 净仓周变化 {delta['net']:+g} 手，总 OI 变化 {oi.get('delta')} 手。"
        )
        if (delta.get("long") or 0) < 0 and (oi.get("delta") or 0) < 0:
            drivers.append("Managed Money 长仓和总 OI 同降，支持杠杆多头收缩的解释；这不是新增空仓单独主导的充分证据。")
    etf = research.get("official_etf", {})
    if etf.get("status") in {"available", "partial"}:
        if (
            _recent(etf.get("shares_reported_on"), snapshot.get("trade_date"), days=4)
            and etf.get("shares_delta") is not None
            and "shares_source_lineage" not in etf.get("missing_data", [])
        ):
            facts.append(
                f"GLD 份额在 {etf.get('shares_reported_on')} 较 {etf.get('shares_previous_reported_on')} 变化 {etf['shares_delta']:+,.0f} 份。"
            )
            if etf["shares_delta"] < 0:
                drivers.append("GLD 最新份额减少，最近一日申赎证据转弱；较长窗口的累计增配不能替代这一新变化。")
            if etf.get("shares_weekly_delta") is not None and etf.get("shares_weekly_anchor_date"):
                facts.append(
                    f"GLD 份额在 {etf.get('shares_weekly_anchor_date')} 至 {etf.get('shares_reported_on')} 累计变化 {etf['shares_weekly_delta']:+,.0f} 份，周窗口与最新单日分别判断。"
                )
                if etf["shares_weekly_delta"] > 0:
                    counterevidence.append(
                        "GLD 近一周份额仍净增加，说明累计配置需求尚未被最新单日赎回完全抵消；不能把最近一天外推为持续流出。"
                    )
        if etf.get("date_alignment") != "same_date":
            limitations.append("GLD 份额与持金量披露日期不同，分别判断各自变化，不称为同日 ETF 资金共振。")
    if (
        etf.get("status") == "available"
        and etf.get("date_alignment") == "same_date"
        and _recent(etf.get("as_of"), snapshot.get("trade_date"), days=4)
        and etf.get("shares_delta") is not None
    ):
        if etf["shares_delta"] > 0 and (etf.get("gold_holdings_tonnes_delta") or 0) > 0:
            counterevidence.append(
                "GLD 份额与持金量各自较前次披露增加，为基金配置需求提供反向证据；两组比较起点分别列示，不能据此确认特定现货价位已被买盘守住。"
            )

    technical = snapshot.get("technical", {}).get("data", {})
    levels = technical.get("key_levels", [])
    low = next((row.get("price") for row in levels if row.get("kind") == "daily_low"), None)
    high = next((row.get("price") for row in levels if row.get("kind") == "daily_high"), None)
    level_note = (
        f"独立现货源最近完整日低点 {low:g}、高点 {high:g}"
        if low is not None and high is not None
        else "有来源和日期的现货结构区间"
    )
    scenarios = [
        {
            "name": "区间消化",
            "trigger": "后续通胀数据未带来一致方向，实际利率和美元缺乏共振",
            "path": f"围绕{level_note}观察承接与反弹；不将期货墙位直接替代现货位。",
            "invalidated_by": "实际利率、美元与现货突破同步确认",
        },
        {
            "name": "压力延续",
            "trigger": "通胀实际值强于有来源的预期，2Y 与实际利率上行，美元走强",
            "path": "检查现货日低点失守及后续完整收盘确认，再核对对应期限 CME 下方结构。",
            "invalidated_by": "通胀降温、实际利率回落或现货快速收回失守区",
        },
        {
            "name": "修复展开",
            "trigger": "通胀降温、2Y 与实际利率回落，美元同步转弱",
            "path": "检查现货日高点收复及均线恢复，再确认 ETF、CFTC 与 CME 的后续增量。",
            "invalidated_by": "反弹无法持续、利率或美元重新走强",
        },
    ]
    if low is None or high is None or rows.get("XAUUSD_DAILY", {}).get("status") != "fresh":
        limitations.append("缺少新鲜且有来源的完整现货日高低点，价格路径暂不可用，仅保留宏观触发条件。")
        for scenario in scenarios:
            scenario["path"] = "价格路径不可用；等待有来源的完整现货日线。"
    summary = "当前可验证的信息更适合分解为政策利率、实际利率、持仓结构与波动约束，正式状态以唯一 Gold 权威链为准。"
    if drivers:
        summary = drivers[0] + (" " + counterevidence[0] if counterevidence else " 仍需资金流和价格行为共同确认。")
    if rates_lag_price:
        summary = f"利率数据尚未覆盖 {price_date} 的现货交易日，无法确认最新事件是否造成新的利率冲击。"
    if delta.get("long") is not None and delta["long"] < 0 and combined.get("readiness") == "ready":
        summary += (
            " CFTC 管理基金长仓减少、全市场总 OI 下降，与去杠杆解释一致；尚不能量化基金杠杆变化。"
            if (oi.get("delta") or 0) < 0
            else " CFTC 管理基金长仓减少，需继续核对总持仓变化。"
        )
    if (
        etf.get("status") in {"available", "partial"}
        and "shares_source_lineage" not in etf.get("missing_data", [])
        and etf.get("shares_delta") is not None
        and etf["shares_delta"] < 0
        and _recent(etf.get("shares_reported_on"), snapshot.get("trade_date"), days=4)
    ):
        summary += (
            " GLD 最新单日份额减少，但近一周仍净增加，配置需求呈现不同窗口的分化。"
            if (etf.get("shares_weekly_delta") or 0) > 0
            else " GLD 最新披露份额减少，最新单日申赎证据转弱。"
        )
    adjudication = adjudicate_research(snapshot)
    if adjudication:
        summary = adjudication["summary"]
        if rates_lag_price:
            summary += f" 利率观察日 {rate_date} 早于现货 {price_date}，当前利率解释仍是上一可得窗口的背景，无法确认最新一日价格变化的原因。"
        news = snapshot.get("news", {}).get("data", {})
        focus = news.get("daily_market_brief", {}).get("report_inputs", {}).get("research_focus", [])
        policy_counter = next(
            (
                item
                for item in focus
                if item.get("evidence_scope") == "official_full_text" and "两条路径" in item.get("interpretation", "")
            ),
            None,
        )
        if policy_counter:
            counterevidence.append(policy_counter["interpretation"])
            summary += " 政策反证：" + policy_counter["interpretation"]
        limitations.extend(adjudication["missing_confirmations"])
        preferred = adjudication["preferred_scenario"]
        scenarios.sort(key=lambda item: item["name"] != preferred)
        for index, item in enumerate(scenarios):
            item["priority"] = "优先观察" if index == 0 else "条件备选"
            item["selection_basis"] = "按独立利率/美元证据与现货确认排序；不按模块票数或任意概率分配。"
            item["supporting_factor_ids"] = adjudication["dominant_factor_ids"] if index == 0 else []
            item["counter_factor_ids"] = adjudication["counter_factor_ids"]
            item["source_refs"] = adjudication["source_refs"]
        fresh_spot = rows.get("XAUUSD_DAILY", {}).get("status") == "fresh"
        price = technical.get("price")
        structure = technical.get("price_structure", {})
        if fresh_spot and price is not None and structure.get("status") == "available":
            supports = sorted({level["price"] for level in structure["levels"] if level["price"] < price}, reverse=True)
            resistances = sorted({level["price"] for level in structure["levels"] if level["price"] > price})
            for item in scenarios:
                path = supports if item["name"] == "压力延续" else resistances if item["name"] == "修复展开" else []
                if path:
                    item["path"] = (
                        "已计算的现货前期区间边界依次为 "
                        + " → ".join(f"{value:g}" for value in path)
                        + "；逐级检查完整收盘是否突破，未确认前不视为目标价。"
                    )
                elif item["name"] == "区间消化" and supports and resistances:
                    item["path"] = (
                        f"当前现货 {price:g}，最近已计算的下方边界 {supports[0]:g}、上方边界 {resistances[0]:g}；区间内先看收盘承接或反弹受阻，突破后再核对利率、美元与资金流。"
                    )
        options = snapshot.get("options", {}).get("data", {})
        option_structure = options.get("support_resistance", {})
        for item in scenarios:
            side = "support" if item["name"] == "压力延续" else "resistance" if item["name"] == "修复展开" else None
            option_levels = option_structure.get(side, []) if side else []
            if option_levels:
                item["path"] += (
                    f" CME 另在对应期货坐标检查 {_option_level(option_levels[0])} 的结构变化；它与现货观察位分别验证。"
                )
        for item in scenarios:
            if item["name"] in {"压力延续", "修复展开"}:
                direction = "上行" if item["name"] == "压力延续" else "回落"
                anchors = [
                    f"{label} 当前 {rows[key]['value']:g}%（{rows[key].get('observation_date')}）"
                    for key, label in (("US02Y", "2Y"), ("US03M", "3M"), ("REAL_10Y", "实际利率"))
                    if rows.get(key, {}).get("status") == "fresh" and rows[key].get("value") is not None
                ]
                if anchors:
                    item["trigger"] += (
                        "；以 "
                        + "、".join(anchors)
                        + f" 为已观察比较基线，后续同口径增量{direction}才追加确认；2Y−3M 必须拆分两腿，不能仅看转正。"
                    )
    project_signals = research.get("project_signals", {})
    project_notes = [
        signal["summary"] for signal in project_signals.values() if isinstance(signal, dict) and signal.get("summary")
    ]
    focus_refs = [
        ref
        for item in snapshot.get("news", {})
        .get("data", {})
        .get("daily_market_brief", {})
        .get("report_inputs", {})
        .get("research_focus", [])
        for ref in item.get("source_refs", [])
    ]
    result = {
        "schema_version": "daily_research_assessment.v1",
        "summary": summary,
        "research_stage": adjudication.get("preferred_scenario", "待确认"),
        "facts": facts,
        "drivers": drivers,
        "counterevidence": counterevidence,
        "domain_notes": {
            "employment": employment_notes,
            "rates": rate_notes,
            "liquidity": liquidity_notes,
            "energy": energy_notes,
            "project": project_notes,
        },
        "limitations": list(dict.fromkeys(limitations)),
        "scenarios": scenarios,
        "scenario_weight_semantics": "unweighted_conditions_not_statistical_probabilities",
        "adjudication": adjudication,
        "source_refs": [*research.get("source_refs", []), *focus_refs],
        "input_snapshot_ids": research.get("input_snapshot_ids", {}),
    }
    workflow = snapshot.get("gold_workflow", {})
    if growth_notes:
        result["domain_notes"]["growth"] = growth_notes
    if workflow.get("schema_version") == "gold_workflow.v2":
        result["gold_workflow"] = workflow
        result["scenario_weight_semantics"] = workflow["scenario_engine"]["semantics"]
        projected = workflow.get("scenario_display", {}).get("scenarios") or workflow["scenario_engine"]["scenarios"]
        result["scenarios"] = [
            {**item, "path": item["price_path"], "invalidated_by": item["invalidation"]} for item in projected
        ]
        result["source_refs"] = [*result["source_refs"], *workflow.get("source_refs", [])]
        result["input_snapshot_ids"] = workflow["input_snapshot_ids"]
    return result


def _option_level(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("strike") or value.get("price") or "已登记的最近墙位")
    return str(value)


def _recent(observation: str | None, context: str | None, *, days: int) -> bool:
    try:
        return 0 <= (date.fromisoformat(str(context)[:10]) - date.fromisoformat(str(observation)[:10])).days <= days
    except ValueError:
        return False
