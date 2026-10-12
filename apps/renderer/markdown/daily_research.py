"""Versioned daily report projection of computed research and module outputs."""

from collections.abc import Mapping
from typing import Any


def daily_research_sections(snapshot: Mapping[str, Any], outputs: dict, assessment: Mapping[str, Any]) -> list[dict[str, Any]]:
    research = snapshot.get("daily_research", {})
    refs = list(research.get("source_refs", []))
    controls = assessment.get("report_controls", {})
    refs.extend(controls.get("source_refs", []))
    sections = []

    def add(key, title, body, *, category="system_inference", status="partial", section_refs=None):
        sections.append({"section_id": key, "title": title, "body": body, "status": status, "data_category": category, "source_refs": refs if section_refs is None else section_refs})

    coordinator = outputs.get("coordinator")
    summary = str(assessment.get("summary", "研究判断待验证。"))
    summary += f"\n\n研究视图阶段：{_text(assessment.get('research_stage'))}；这是本次证据下的情景选择，独立于正式 Gold 状态。"
    if coordinator:
        summary += f"\n\n研究综合方向：{coordinator.bias.value}；完整性：{coordinator.status.value}；证据覆盖置信度 {coordinator.confidence:.2f}（不是行情概率）。正式状态另见 Gold 状态边界。"
    summary += "\n\n本报告按各来源最新有效观察日复盘；采集时刻与行情观察时刻分别记录，正式状态另由 Gold 权威链确认。"
    add("research_summary", "综合判断", summary)

    rows = research.get("passport", [])
    body = ["| 指标/口径 | 最新有效值 | 观察日 | 上次观察/变化 | 周比较起点/变化 | 时效 | 来源 |", "|---|---:|---|---|---|---|---|"]
    for row in rows:
        comparison = f"{_text(row.get('previous_date'))} / {_num(row.get('change'), signed=True)}"
        if row.get("change") is None and row.get("provider_reported_change") is not None:
            comparison = f"前一会话 {_num(row.get('provider_previous_close'))}（日期未提供）/ {_num(row['provider_reported_change'], signed=True)}"
        body.append(f"| {_text(row.get('label'))} | {_num(row.get('value'))} {_text(row.get('unit'))} | {_text(row.get('observation_date'))} | {comparison} | {_text(row.get('weekly_anchor_date'))} / {_num(row.get('weekly_change'), signed=True)} | {_text(row.get('status'))} | {_links(row.get('source_refs', []))} |")
    body += ["", "变化为原单位的差值：利率单位为百分点（0.01 个百分点 = 1bp），余额 B 为十亿美元。周均指标的上次观察即前一周；日频上次观察未必是上一自然日。IORB 是行政设定利率，日历日期表示当日适用值，周末值不表示新政策决定；融资比较使用 SOFR/EFFR 的共同观察日。fresh 表示满足该频率的发布滞后窗口，不代表实时成交。完整采集时间、组件与原始归档在结构化快照中保留。"]
    add("data_passport", "数据护照", "\n".join(body), category="confirmed_data")

    employment = research.get("employment", {})
    add("employment", "就业、工资与修订", _employment_body(employment) + "\n\n" + _bullets(assessment.get("domain_notes", {}).get("employment", [])), status="partial")

    domain_notes = assessment.get("domain_notes", {})
    add("rates_transmission", "利率结构、实际利率与美元", _bullets(domain_notes.get("rates", [])) + "\n\n实际利率代理使用同日名义收益率 − T10YIE；DFII10 为独立 TIPS 观测。是否属于新冲击，要同时比较同窗口变化、美元与价格反应。")

    project_signals = research.get("project_signals", {})
    project_lines = ["项目框架依次检查：流动性数量 → 融资价格 → 2Y−3M 短端曲线 → 实际利率与美元 → 资金流与现货确认 → CME 到期结构。", ""]
    project_refs = []
    project_labels = {"short_curve": "2Y−3M 短端曲线", "long_curve": "10Y−2Y 长短端曲线", "policy_corridor": "融资利率走廊", "real_rate": "实际利率"}
    for name, signal in project_signals.items():
        if isinstance(signal, dict):
            project_lines.append(f"- **{_text(project_labels.get(name, name))}** [{_text(signal.get('status'))}]：{_text(signal.get('summary'))} {_links(signal.get('source_refs', []))}")
            project_refs.extend(signal.get("source_refs", []))
    if not project_signals:
        project_lines.append("本快照缺少项目框架特征，不能从旧报告补入 2Y−3M 或融资利差。")
    project_lines += ["", "2Y−3M 是项目使用的期限价差，不等于 FedWatch 概率或 Fed 的近端远期利差；3M 美债还含期限与供求影响，不能视为纯政策利率。"]
    add("project_framework", "项目框架：短端曲线与融资价格", "\n".join(project_lines), section_refs=project_refs)

    adjudication = assessment.get("adjudication", {})
    factor_lines = ["| 因子 | 用途 | 方向 | 观察日期 | 判断与证据 |", "|---|---|---|---|---|"]
    for factor in adjudication.get("factors", []):
        factor_lines.append(f"| {_text(factor['factor_id'])} | {_text(factor['role'])} / {_text(factor['family'])} | {_text(factor['bias'])} | {_text(', '.join(factor['observation_dates']))} | {_text(factor['rationale'])} {_links(factor['source_refs'])} |")
    factor_lines += ["", "主导因素：" + (", ".join(adjudication.get("dominant_factor_ids", [])) or "尚未形成") + "；反证：" + (", ".join(adjudication.get("counter_factor_ids", [])) or "未取得足够可用反证，不能视为没有风险") + "。", "同一证据家族只解释一次：利率与短曲线相互确认，GLD 日/周窗口保留分化，CME 仅作为结构约束；风险模块不替代方向裁决。"]
    add("evidence_adjudication", "主导驱动、确认与反证", "\n".join(factor_lines), section_refs=adjudication.get("source_refs", []))

    add("liquidity_credit", "流动性与信用验证", _bullets(domain_notes.get("liquidity", [])) + "\n\nTGA 日值、TGA 周均和银行准备金周均分别列示。准备金减少可能受到财政账户、货币发行和其他资产负债项共同影响，不能把 TGA 增量当作准备金变化的完整解释。\n\nSOFR、EFFR 与 IORB 用于检验融资压力是否向利率走廊传导；RRP 下降意味着缓冲减弱，但不能单凭余额小就确认流动性危机。HY OAS 与 VIX 用于核对信用和波动是否共振，未采到的实时融资压力仍保持待验证。")

    add("energy", "能源与通胀风险", _bullets(domain_notes.get("energy", [])) + "\n\n数据护照使用可得的 EIA/FRED WTI、Brent 现货序列，日期与期货结算分开。原油上涨可能通过能源成本、通胀预期和政策利率压制黄金；若增长受损或避险需求增强，也可能转为支撑。\n\n后续应看通胀实际值与可追溯预期的差异，再检查 2Y、实际利率、美元是否同向确认。当前缺乏可核验的 FedWatch 概率时，不沿用范例中的 58%—60%。")

    add("positioning_flows", "CFTC 与 ETF：持仓变化和配置需求", _flows_body(research))

    options = _section(snapshot, "options")
    add("cme_structure", "CME：期权墙、Gamma、Pin 与机构成交", _cme_body(options))
    tech = _section(snapshot, "technical")
    technical_lines = [f"现货代理观察日：{_text(tech.get('as_of'))}；收盘 {_num(tech.get('price'))}；MA20 {_num(tech.get('ma20'))}；MA50 {_num(tech.get('ma50'))}；RSI14 {_num(tech.get('rsi14'))}；ATR14 {_num(tech.get('atr14'))}。", f"计算方法：{_text(tech.get('indicator_method'))}。", "", "| 价格 | 类型 | 观察日期 | 生命周期 |", "|---:|---|---|---|"]
    for level in tech.get("key_levels", []):
        technical_lines.append(f"| {_num(level.get('price'))} | {_text(level.get('kind'))} | {_text(level.get('date'))} | {_text(level.get('status'))} |")
    technical_lines += ["", "daily_high/low 是最近完整日高低点；prior_5d/20d 是排除最新一日后计算的前期区间边界，状态记录本次收盘突破或盘中越界后收回，并非人为指定的重大支撑或正式状态线。现货与 CME 的不同期限远期锚存在基差；没有同时间、同合约基差时，不平移执行价。正式状态迁移必须沿唯一已验证 Gold 前序链，不以本报告自行建立 S5 或强制初始化。"]
    gold = controls.get("gold_policy", {})
    decision = gold.get("decision") or {}
    if gold:
        technical_lines += ["", f"本次 Gold 计算模式：{_text(gold.get('execution_mode'))}；质量状态：{_text(decision.get('quality_status'))}；方向：{_text(decision.get('direction'))}；阶段候选：{_text(decision.get('market_stage_candidate'))}。", f"状态依赖/冲突：{_text(', '.join(decision.get('conflicts') or [])) or '无'}。shadow 为本次影子计算，不代表正式基线已更新。"]
    add("technical_lifecycle", "现货技术位与状态边界", "\n".join(technical_lines))

    scenario_lines = ["以下为条件场景，未赋予统计概率或未经校准的规则权重。观察优先级由独立驱动与价格确认动态决定；数值为本次比较基线，不是固定买卖阈值。", "", "| 情景 / 优先级 | 触发条件 | 观察路径 | 反证/失效 |", "|---|---|---|---|"]
    for item in assessment.get("scenarios", []):
        scenario_lines.append(f"| {_text(item.get('name'))} / {_text(item.get('priority'))} | {_text(item.get('trigger'))} | {_text(item.get('path'))} | {_text(item.get('invalidated_by'))} |")
    add("conditional_scenarios", "后续三种路径", "\n".join(scenario_lines))

    news = _section(snapshot, "news")
    add("news_evidence", "相关新闻与事件证据", _news_body(news), section_refs=news.get("source_refs", []), status="partial" if news else "unavailable")
    calendar = news.get("official_calendar", {}).get("events", [])
    legacy_calendar = news.get("daily_market_brief", {}).get("next_7d_calendar", [])
    calendar_lines = ["| 事件 | 官方日期 | 时间精度 | 状态 | 来源 |", "|---|---|---|---|---|"]
    for event in calendar:
        title = "FOMC 会议" + ("（含经济预测）" if event.get("is_sep") else "") if event.get("event_type") == "fomc_meeting" else _text(event.get("title"))
        calendar_lines.append(f"| {title} | {_text(event.get('start_date'))} 至 {_text(event.get('end_date'))} | 日期；具体时刻未提供 | 已排期，尚未发生 | {_links(event.get('source_refs', []))} |")
    if legacy_calendar:
        calendar_lines += ["", _domain_table({"events": legacy_calendar})]
    calendar_lines += ["", "日程来自官方未来两周日历；FRED 补充 CPI/PPI 发布日期，Fed 提供 FOMC 会议日期。这些输入只提供日期精度，具体发布时间仍待核验；不能用采集时刻或会议日期替代声明发布时间。"]
    add("event_calendar", "下一阶段事件", "\n".join(calendar_lines) if calendar or legacy_calendar else "本次自动采集未获得有效的未来事件日历。待官方来源恢复后补充日期、原时区和北京时间。", category="confirmed_data", status="partial" if calendar or legacy_calendar else "unavailable")
    module_lines = ["| 模块 | 方向 | 完整性 | 摘要 |", "|---|---|---|---|"]
    for name, output in outputs.items():
        if output:
            module_lines.append(f"| {name} | {_text(output.bias.value)} | {_text(output.status.value)} | {_text(output.summary)} |")
    for name in ("market_odds", "fact_review"):
        item = controls.get(name)
        if item:
            module_lines.append(f"| {name} | 见证据覆盖 | {_text(item.get('status'))} | {_text(item.get('summary'))} |")
    module_lines += ["", "各模块方向不是独立统计投票：同一利率因子可能被多模块重复消费。综合判断按主导驱动、时间对齐与反证处理冲突；CME 正 GEX 主要描述模型波动结构，不等于做市商真实净多或金价必涨。", "fact_review 当前审查声明的引用完整性与显式结构冲突；它没有逐句读取新闻全文核验事实。日报中的确定性数值由 feature 公式及来源对齐检查约束，研究推断仍须接受后续数据检验。"]
    add("module_reconciliation", "模块分歧与反证", "\n".join(module_lines))
    control_lines = []
    if controls:
        health = controls.get("source_health", {})
        gate = controls.get("quality_gate", {})
        control_lines = ["", "| 判断权限 | 当前结果 |", "|---|---|", f"| 来源完整性 | {_text(health.get('overall_status'))} |", f"| 可形成综合研究 | {_text(health.get('can_build_gold_macro_overview'))} |", f"| 受阻主线 | {_text(', '.join(health.get('blocked_mainlines') or [])) or '无'} |", f"| 过期来源 | {_text(', '.join(health.get('stale_sources') or [])) or '无'} |", f"| 本报告质量门 / 强方向发布许可 | {_text(gate.get('action'))} / {_text(gate.get('publish_allowed'))} |", "", "允许生成低置信、分歧明确的研究报告，不等于允许强方向或 Gold 状态迁移。来源完整性与报告质量门各自保留原始 JSON 证据。"]
    add("research_limitations", "关键缺口与更新条件", _bullets(assessment.get("limitations", [])) + "\n" + "\n".join(control_lines) + "\n\n禁用来源：" + (", ".join(snapshot.get("disabled_sources", [])) or "无") + "。数据采集成功、研究报告生成与强方向发布许可分别记录；正式状态不可用时不隐含已通过发布门槛。")
    return sections


def _news_body(news):
    brief = news.get("daily_market_brief", {})
    quality = news.get("data_quality", {})
    freshness = news.get("news_freshness", {})
    lines = [f"新闻时效：{_text(freshness.get('status'))}；最新候选发布时间：{_text(freshness.get('latest_published_at'))}。", "本节区分已确认事实、标题/摘要候选和未确认风险。搜索结果来自何处不等于已经取得原文；报道的分析观点不作为官方统计事实。", ""]
    focus = brief.get("report_inputs", {}).get("research_focus", [])
    if focus:
        for item in focus:
            lines += [f"**{_text(item['topic'])}｜{_text(item['title'])}**", "",
                      f"{_text(item['event_time'])}；{_text(item['evidence_scope'])}。 {_links(item['source_refs'])}", "",
                      _text(item['interpretation']), ""]
            if item.get("quote"):
                lines += ["> " + _text(item["quote"]), ""]
    for key, label in (("confirmed_events", "已确认事件"), ("candidate_events", "候选报道"), ("unconfirmed_risks", "未确认风险")):
        events = brief.get(key, [])
        lines.append(f"{label}：{len(events)} 条。")
        for event in ([] if focus else events[:6]):
            lines.append(f"- {_text(event.get('title') or event.get('what_happened') or event.get('summary') or event.get('event_id'))}；事件/发布时间 {_text(event.get('published_at') or event.get('event_time'))}；证据状态 {_text(event.get('verification_status') or event.get('status'))}。 {_links(event.get('source_refs', []))}")
            if event.get("impact_path") and event["impact_path"] != "unknown":
                lines.append(f"  潜在传导：{_text(event['impact_path'])}；市场核验 {_text(event.get('pricing_status'))}；失效条件 {_text(event.get('invalidation_condition'))}。")
    coverage = news.get("news_coverage") or quality.get("news_coverage")
    if not any(brief.get(key) for key in ("confirmed_events", "candidate_events", "unconfirmed_risks")):
        lines.append("已覆盖来源在本窗口未识别到相关事件；结论只适用于已覆盖窗口。" if coverage and coverage.get("context_item_count", 0) > 0 else "当前没有可用于本报告的新闻上下文；这表示覆盖缺口，不能据此推断市场没有相关新闻。")
    if coverage:
        lines += ["", f"本次来源返回 {_num(coverage.get('collected_item_count'))} 条；新增 {_num(coverage.get('novel_item_count'))} 条；保留上下文 {_num(coverage.get('context_item_count'))} 条。新增数为零不意味着上下文为空。", "", "| 来源 | 本次状态 | 采集数 | 可用上下文 |", "|---|---|---:|---:|"]
        statuses = coverage.get("source_statuses", {})
        for name, status in (statuses.items() if isinstance(statuses, dict) else enumerate(statuses)):
            if isinstance(status, dict):
                lines.append(f"| {_text(status.get('source_key') or name)} | {_text(status.get('status'))} | {_num(status.get('collected_item_count'))} | {_num(status.get('context_item_count'))} |")
            else:
                lines.append(f"| {_text(name)} | {_text(status)} | unavailable | unavailable |")
    lines.append("没有公告前后的同源同步行情时，仅说明可能的传导路径，不确认某条新闻导致了金价涨跌。")
    return "\n".join(lines)


def render_daily_research_report(snapshot: Mapping[str, Any], sections: list[dict[str, Any]]) -> str:
    lines = [f"# {snapshot.get('trade_date')} 黄金综合研究日报", "", f"数据采集截止：{snapshot.get('snapshot_time')}；快照：{snapshot.get('snapshot_id')}。", ""]
    for section in sections:
        lines += [f"## {section['title']}", "", section["body"], ""]
    return "\n".join(lines).rstrip() + "\n"


def _cme_body(data):
    if not data:
        return "本次 CME 输入不可用；未根据历史报告补造墙位。"
    source, params = data.get("data_source", {}), data.get("parameters", {})
    audit = data.get("audit", {}).get("gex_audit", {})
    pricing_audit = data.get("audit", {}).get("data_audit", {})
    method = "结算价反推 IV 的 Black-76 模型 Gamma" if params.get("used_real_gex") else "近似 Gamma proxy，精度受限"
    lines = [f"CME 报告日：{_text(source.get('report_date'))}；状态：{_text(source.get('status'))}；覆盖到期：{', '.join(source.get('expiries', []))}。", f"计算口径：{method}；报告期货锚 {_num(params.get('report_p0'))}（{_text(params.get('report_p0_source'))}）。", f"Net GEX：{_num(audit.get('net_gex'))}；单位：{_text(audit.get('gex_unit'))}；Gamma Zero：{_num(audit.get('gamma_zero_full'))}。", f"原始行 {_num(pricing_audit.get('raw_rows'))}；有效定价行 {_num(pricing_audit.get('valid_pricing_rows'))}；因定价缺失排除 {_num(pricing_audit.get('excluded_by_missing_pricing_rows'))}；主分析执行价范围 {_num(pricing_audit.get('analysis_strike_min'))}—{_num(pricing_audit.get('analysis_strike_max'))}。", "", "| 评分前列墙位 | 到期 | OI | OI 变化 | 净 GEX | PNT | Block |", "|---:|---|---:|---:|---:|---:|---:|"]
    for wall in data.get("wall_scores", [])[:5]:
        lines.append(f"| {_num(wall.get('strike'))} | {_text(wall.get('expiry'))} | {_num(wall.get('oi'))} | {_num(wall.get('oi_change'), signed=True)} | {_num(wall.get('net_gex'))} | {_num(wall.get('pnt'))} | {_num(wall.get('block'))} |")
    lines += ["", "分类 Call OI 墙（按 OI 排序）：" + _wall_list(sorted(data.get("walls", {}).get("call_oi_walls", []), key=lambda wall: wall.get("oi", 0), reverse=True)), "分类 Put OI 墙（按 OI 排序）：" + _wall_list(sorted(data.get("walls", {}).get("put_oi_walls", []), key=lambda wall: wall.get("oi", 0), reverse=True)), "Pin 区域：" + _wall_list([wall for wall in data.get("wall_scores", []) if wall.get("wall_type") == "pin"]), "近端支撑（期货锚坐标）：" + _structure_list(data.get("support_resistance", {}).get("support", [])[:3]), "近端阻力（期货锚坐标）：" + _structure_list(data.get("support_resistance", {}).get("resistance", [])[:3]), "", "分类 OI 墙与综合评分前列墙的筛选条件不同；近端结构优先按距离与期货锚核对，远端高 OI 不是短线目标。", "", "按到期计算的远期锚："]
    for expiry, item in params.get("forward_by_expiry", {}).items():
        lines.append(f"- {expiry}：{_num(item.get('f_value'))}，来源 {_text(item.get('f_source'))}。")
    for expiry, item in data.get("audit", {}).get("black76_audit", {}).items():
        lines.append(f"- {expiry} 模型到期日 {_text(item.get('expiry_date'))}，依据 {_text(item.get('expiry_source'))}；IV 来源 {_text(item.get('iv_source'))}。")
    lines += ["", "换月信号："]
    for item in data.get("roll_signals", []):
        lines.append(f"- {_text(item.get('near_expiry'))} → {_text(item.get('far_expiry'))}：{_text(item.get('roll_type'))}；规则分数 {_num(item.get('confidence'))}，非事件概率。")
    lines += ["", "PRELIM 需等待 FINAL 复核；本次模型的到期日、远期价和 IV 来源以上方审计为准。推导参数会限制模型精度，模型 Gamma 不代表交易商真实库存。PNT 与 Block 独立保留，Block=0 只能表示本输入未验证出 Block。正 GEX 不构成单独多头信号。", "", "数据来源：" + _links([source])]
    if data.get("gex_semantics") or data.get("dealer_position_unknown"):
        lines = [line.replace("Net GEX", "OI-Signed GEX Proxy").replace("Gamma Zero", "Selected Expiry Window Proxy Gamma Flip").replace("净 GEX", "OI-Signed Proxy").replace("Pin 区域", "OI/Gamma Concentration Zone").replace("正 GEX", "正的 OI-Signed GEX Proxy") for line in lines]
        selection = data.get("expiry_selection") or source.get("expiry_selection", {})
        reconciliation = data.get("reconciliation") or data.get("version_reconciliation") or {}
        policy = selection.get("selection_policy", {})
        delta = reconciliation.get("delta", {})
        lines += ["", "[MODEL] Call/Put OI 不识别客户与 dealer 的持仓方向。正负号来自模型假设，本次仅表示所选到期窗口的 Proxy，不代表全市场或真实 Dealer Exposure。",
                  "到期选择：" + _text(", ".join(selection.get("selected_expiries", [])))
                  + "；策略 " + _text(policy.get("name"))
                  + "；合格到期 OI 覆盖 " + _num(selection.get("open_interest_coverage"))
                  + "；主力期货确认 " + _text(policy.get("front_active_future_status")) + "。",
                  "版本对账：" + _text(reconciliation.get("status")) + "；当前选择 " + _text(reconciliation.get("current_selection"))
                  + "；FINAL 变更行 " + _num(delta.get("changed")) + "；增加/移除 " + _num(delta.get("added_in_final")) + "/" + _num(delta.get("removed_from_final")) + "。完整差异保存在版本快照中。"]
    return "\n".join(lines)


def _employment_body(data):
    metrics = data.get("metrics", {})
    release = data.get("release_context", {})
    release_available = release.get("status") in {"available", "partial"} and bool(release.get("source_refs"))
    if not metrics and not release_available:
        return "BLS 就业数据不可用；未补造新增就业、工资或修订。"
    payroll = metrics.get("CES0000000001", {})
    wage = metrics.get("CES0500000003", {})
    lines = [f"{_text(payroll.get('current_month'))} 非农新增就业：{_num(payroll.get('new_jobs_thousands'), signed=True)} 千人（连续月就业水平之差）。", f"由时薪水平计算的工资环比：{_num(wage.get('monthly_change_pct'), signed=True)}%；同比：{_num(wage.get('yoy_change_pct'), signed=True)}%。", "", "| 官方指标 | 观察月 | 当前值 | 前期月/值 | 来源 |", "|---|---|---:|---|---|"]
    labels = {"CES0000000001":"非农就业总量（千人）", "CES0500000003":"平均时薪（美元/小时）", "LNS14000000":"失业率（%）", "LNS11300000":"劳动参与率（%）"}
    for key, label in labels.items():
        item = metrics.get(key, {})
        lines.append(f"| {label} | {_text(item.get('current_month'))} | {_num(item.get('current_value'))} | {_text(item.get('previous_month'))} / {_num(item.get('previous_value'))} | {_links([item.get('current_source') or {}])} |")
    lines += ["", "就业数量与工资压力应分开判断：新增就业影响经济韧性与政策空间，工资变化补充成本压力证据。当前未取得可核验的市场预期，不能计算超预期幅度；单月数据不足以彻底否定此前趋势。"]
    industry = data.get("industry_employment", {})
    if industry:
        lines += ["", "| 行业（季调） | 观察月 | 就业水平（千人） | 上月水平 | 月度差分（千人） | 来源 |", "|---|---|---:|---:|---:|---|"]
        for item in industry.values():
            lines.append(f"| {_text(item.get('label'))} | {_text(item.get('current_month'))} | {_num(item.get('current_value'))} | {_num(item.get('previous_value'))} | {_num(item.get('monthly_change'), signed=True)} | {_links([item.get('current_source') or {}])} |")
        lines.append("行业变化来自相邻月份的季调就业水平差分；这是所覆盖行业的结构核对，不是完整行业分解或新闻稿原文摘录。")
    if release_available:
        date_label = "FRED 版本日期" if release.get("source_kind") == "fred_vintage" else "发布日期"
        release_clock = f"{release['release_time_local']} {_text(release.get('release_timezone'))}" if release.get('release_time_local') else "未取得发布时间与时区"
        lines += ["", f"官方发布上下文：{_text(release.get('source_kind') or 'BLS release')}；状态 {_text(release.get('status'))}；{date_label} {_text(release.get('release_date'))}；{release_clock}。", "来源：" + _links(release.get("source_refs", []))]
        if release.get("fallback_from", {}).get("failure_kind") == "http_forbidden":
            lines.append("BLS 新闻稿 HTML 请求返回 HTTP 403；本次指标来自月度 API，修订使用 FRED 历史版本核对。新闻稿原文与精确发布时刻仍未采集成功。")
        if release.get("source_kind") == "fred_vintage":
            lines.append(f"比较 FRED {release.get('previous_vintage_date')} 与 {release.get('vintage_date')} 两个版本；先在各版本内计算连续月就业增量，再比较增量修订，不把总就业水平修订当作新增就业修订。")
        if release.get("revisions"):
            lines += ["", "| 修订月份 | 前次新增（千人） | 最新新增（千人） | 修订量（千人） |", "|---|---:|---:|---:|"]
            for item in release["revisions"]:
                lines.append(f"| {_text(item.get('observation_month'))} | {_num(item.get('previous_value_thousands'), signed=True)} | {_num(item.get('revised_value_thousands'), signed=True)} | {_num(item.get('delta_thousands'), signed=True)} |")
            lines.append("修订比较所引用的两个发布版本；前次值不一定是首次发布值。")
        else:
            lines.append("当前官方上下文仍缺可核验修订，不从同一版本的月度水平倒推修订。")
        if release.get("sector_contributions"):
            lines += ["", "官方列示的行业变化（千人；不是完整行业分解）："]
            for item in release["sector_contributions"]:
                lines.append(f"- {_text(item.get('sector'))}：{_num(item.get('change_thousands'), signed=True)}（{_text(item.get('observation_month'))}）。")
        elif not industry:
            lines.append("行业贡献未取得可核验原文。")
    else:
        lines.append("官方发布原文与历史版本未取得可核验证据，修订和发布时刻保持缺失；已采集行业序列另行展示，不复用范例中的数值。")
    return "\n".join(lines)


def _flows_body(research):
    reports = research.get("cot_reports", {})
    lines = ["| CFTC 口径 | 持仓日/前期日 | MM Long | MM Short | MM Net | ΔLong / ΔShort / ΔNet | 总 OI / ΔOI |", "|---|---|---:|---:|---:|---|---|"]
    for report_type, title in (("futures_only", "仅期货"), ("combined", "期货＋期权合并")):
        report = reports.get(report_type, {})
        mm = report.get("managed_money", {})
        current, delta = mm.get("latest", {}), mm.get("delta") or {}
        oi = report.get("open_interest", {})
        lines.append(f"| {title} | {_text(report.get('report_date'))} / {_text(report.get('previous_report_date'))} | {_num(current.get('long'))} | {_num(current.get('short'))} | {_num(current.get('net'))} | {_num(delta.get('long'), signed=True)} / {_num(delta.get('short'), signed=True)} / {_num(delta.get('net'), signed=True)} | {_num(oi.get('value'))} / {_num(oi.get('delta'), signed=True)} |")
    lines += ["单位为手；两种口径不可相加或互相替代。CFTC 持仓截至周二，通常周五发布；不能解释随后周五非农后的即时交易。净多减少须分解成长仓减少与短仓增加，总 OI 下降才进一步支持去杠杆解释。", ""]
    for report in reports.values():
        lines.append("CFTC 来源：" + _links(report.get("source_refs", [])))
    etf = research.get("official_etf", {})
    lines += ["", f"GLD 份额：{_num(etf.get('shares_outstanding'))} 份（{_text(etf.get('shares_reported_on'))}），较 {_text(etf.get('shares_previous_reported_on'))} 的 {_num(etf.get('shares_previous_value'))} 份变化 {_num(etf.get('shares_delta'), signed=True)} 份。", f"GLD 持金量：{_num(etf.get('gold_holdings_tonnes'))} 吨（{_text(etf.get('gold_holdings_tonnes_reported_on'))}），较 {_text(etf.get('gold_holdings_tonnes_previous_reported_on'))} 的 {_num(etf.get('gold_holdings_tonnes_previous_value'))} 吨变化 {_num(etf.get('gold_holdings_tonnes_delta'), signed=True)} 吨。", f"GLD 资产规模：{_num(etf.get('total_net_assets_usd'))} 美元（{_text(etf.get('total_net_assets_reported_on'))}）；份额/持金观察日对齐状态：{_text(etf.get('date_alignment'))}。", "来源：" + _links(etf.get("source_refs", [])), "", "份额和持金量的增减需按各自比较窗口判断：累计增配可以与最新一日赎回同时存在。它们不证明特定投资者身份、买入时点或某个价位的承接。GLD 为单一北美基金；AUM 只展示规模水平，不当成资金流，也不外推全球 ETF。"]
    for prefix, label, unit in (("shares", "GLD 份额周窗口", "份"), ("gold_holdings_tonnes", "GLD 持金周窗口", "吨")):
        if etf.get(f"{prefix}_weekly_anchor_date") and etf.get(f"{prefix}_weekly_delta") is not None:
            lines.append(f"{label}：{_text(etf.get(f'{prefix}_weekly_anchor_date'))} 基线 {_num(etf.get(f'{prefix}_weekly_anchor_value'))} {unit}，至 {_text(etf.get(f'{prefix}_reported_on'))} 累计变化 {_num(etf.get(f'{prefix}_weekly_delta'), signed=True)} {unit}。")
    return "\n".join(lines)


def _section(snapshot, name):
    value = snapshot.get(name, {})
    return value.get("data", {}) if value.get("status") == "available" else {}


def _domain_table(data, prefix=""):
    if not data:
        return "本次无可用结构化数据；保持 unavailable。"
    lines = []
    for key, value in data.items():
        if key in {"source_refs", "raw_payload", "input_snapshot_ids"}:
            if key == "source_refs" and isinstance(value, list):
                lines.append("来源：" + _links(value))
            continue
        if isinstance(value, dict):
            lines.append(f"**{_text(prefix + key)}**\n\n" + _domain_table(value))
        elif isinstance(value, list):
            for item in value[:12]:
                lines.append(_domain_table(item, prefix=key + ".") if isinstance(item, dict) else "- " + _text(item))
        else:
            lines.append(f"- {_text(key)}：{_num(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else _text(value)}")
    return "\n\n".join(lines)


def _wall_list(walls):
    return "；".join(f"{_num(w.get('strike'))} ({_text(w.get('expiry'))}, OI {_num(w.get('oi'))})" for w in walls[:3]) or "unavailable"


def _structure_list(levels):
    return "；".join(f"{_num(level.get('strike'))}（距锚 {_num(level.get('distance_pct'), signed=True)}%）" for level in levels) or "unavailable"


def _links(refs, *, limit=3):
    links = []
    seen_urls = set()
    for ref in refs:
        if ref.get("status") in {"failed", "unavailable", "error", "blocked"}:
            continue
        url = ref.get("source_url") or ref.get("url") or ref.get("reference")
        if isinstance(url, str) and url.startswith("https://") and url not in seen_urls:
            links.append(f"[{_text(ref.get('source') or ref.get('product') or 'source')}]({url})")
            seen_urls.add(url)
            if len(links) >= limit:
                break
    return " / ".join(links) or "见快照归档"


def _num(value, *, signed=False):
    if value is None:
        return "unavailable"
    if isinstance(value, (int, float)):
        return format(value, "+,.4f" if signed else ",.4f").rstrip("0").rstrip(".")
    return _text(value)


def _text(value):
    return str(value if value is not None else "unavailable").replace("|", "\\|").replace("\n", " ")


def _bullets(items):
    return "\n".join("- " + str(item) for item in items) or "缺少足够证据，保持待验证。"
