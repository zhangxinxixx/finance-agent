"""Fixed v2 research format; renders feature/AgentOutput values without scoring."""

import re
from typing import Any

from apps.renderer.markdown.daily_research import daily_research_sections, _text, _num, _links


def gold_workflow_sections(snapshot, outputs, assessment):
    flow = snapshot["gold_workflow"]
    shadow = bool(flow.get("production_shadow"))
    research = snapshot["daily_research"]
    controls = assessment.get("report_controls", {})
    legacy = {s["section_id"]: s for s in daily_research_sections(snapshot, outputs, assessment)}
    sections: list[dict[str, Any]] = []
    refs = flow.get("source_refs", [])
    coordinator = outputs.get("coordinator")
    synthesis = (coordinator.input_payload or {}).get("research_synthesis", {}) if coordinator else {}
    shadow_record = controls.get("production_shadow", {}).get("record", {}) if shadow else {}
    model_record = shadow_record.get("model", {})
    report_output_record = shadow_record.get("report_output", {})

    def add(key, title, body, category="system_inference", source_refs=None):
        sections.append({"section_id": key, "title": title, "body": body, "status": "partial" if flow["quality_gate"]["data_quality"] == "Partial" else "ok", "source_refs": refs if source_refs is None else source_refs, "data_category": category})

    price = flow["price_anchor"]
    rows = research["passport"]
    dates = {x["symbol"]: x.get("observation_date") for x in rows}
    etf, cot = research.get("official_etf", {}), research.get("cot_reports", {}).get("combined", {})
    passport = ["| 字段 | 本次输入 |", "|---|---|", f"| 分析截止 | {_text(flow['analysis_time'])}；显示时区 Asia/Shanghai |",
                f"| 现货报价 | {_num(price.get('price'))}；时间 {_text(price.get('price_time'))}；延迟 {_text(price.get('delay'))}；{_text(price['status'])} |",
                f"| 最新完整日线 | XAUUSD OTC 现货代理 {_num(price.get('daily_close'))}；{_text(price.get('daily_close_date'))} |",
                f"| Treasury / 实际利率 / BE | {_text(dates.get('US10Y'))} / {_text(flow['real_rate'].get('date'))} / {_text(dates.get('BREAKEVEN_10Y'))} |",
                f"| 流动性 | 准备金 {_text(dates.get('RESERVES'))}；SOFR {_text(dates.get('SOFR'))}；HY {_text(dates.get('HY_OAS'))} |",
                f"| CFTC / ETF / CME | {_text(cot.get('report_date'))} / {_text(etf.get('shares_reported_on'))} / {_text(snapshot.get('options', {}).get('data', {}).get('data_source', {}).get('report_date'))} |",
                f"| Data Quality | **{flow['quality_gate']['data_quality']}** |", f"| 快照与版本 | {_text(snapshot['snapshot_id'])}；gold_workflow.v2 |", "",
                "[FACT] 原始来源、计算和推论分别留存。日线、实时现货与不同月份期货按各自观察时点使用。"]
    if price["status"] != "verified":
        passport.append("**最新价格锚点未完全验证，因此不做强方向确认。**")
    if shadow:
        session = price.get("session_quality", {})
        passport = [x.replace("最新完整日线", "最新已收盘 OTC 日线") for x in passport]
        passport += ["", f"[FACT] 日线所属会话：{_text(session.get('trade_date'))} / **{_text(session.get('session_class'))}**；CME 结算 {_text(session.get('cme_settlement', {}).get('status'))}。OTC 报价存在不等于美国市场具有正常流动性。",
                     f"[MODEL] 会话质量系数 {_text(session.get('confidence_multiplier'))}；仅折扣该会话产生的价格位。{_links(session.get('source_refs', []))}", "", "**Gold Research Agent v0.9 — Production Shadow**"]
    loop = snapshot.get('adaptive_research', {})
    if loop.get('schema_version') in {'adaptive_research.v2', 'adaptive_research.v3'}:
        passport += ['', '**自主研究循环记录**',
                     f"状态：{_text(loop.get('status'))}；停止原因：{_text(loop.get('stop_reason'))}；实际补采轮数：{loop.get('budget_used', {}).get('collection_rounds', 0)}。预算/无进展停止不等于证据充分。"]
        for turn in loop.get('rounds', []):
            decision = turn.get('plan', {})
            passport += [f"\n[MODEL] 第{turn['decision_index']}次决策：{_text(decision.get('action'))}；{_text(decision.get('question'))}",
                         f"当前驱动判断：{_text(decision.get('driver_assessment'))}；主假设：{_text(decision.get('hypothesis'))}",
                         _text(decision.get('evidence_assessment')),
                         f"归档：{_text(turn.get('decision_ref', {}).get('path'))}；新增证据条目：{turn.get('new_evidence_count', 0)}"]
            for request in decision.get('data_requests', []):
                passport.append(
                    f"- 选择 {_text(request.get('provider'))}:{_text(request.get('key'))}（{_text(request.get('freshness_need'))}）："
                    f"验证“{_text(request.get('claim'))}”；影响 {_text(request.get('decision_impact'))}。"
                )
        if loop.get('unavailable_data_needs'):
            passport += ['', '**当前能力外、仍会限制结论的数据**']
            for gap in loop['unavailable_data_needs']:
                passport.append(
                    f"- [{_text(gap.get('materiality'))}] {_text(gap.get('data'))}：{_text(gap.get('reason'))}；"
                    f"若取得将影响 {_text(gap.get('decision_impact'))}。"
                )
    add("data_passport", "数据护照 / 分析溯源", "\n".join(passport), "confirmed_data")

    state = flow["state"]
    rate = flow["real_rate"]
    scenario_names = {x['id']: x['name'] for x in flow['scenario_engine']['scenarios']}
    main_name = scenario_names.get(flow['scenario_engine']['main_scenario_id'], '待定')
    rate_effect = {'pressure': '处于本阶段经验压制区', 'high_risk': '处于本阶段经验高风险区', 'supportive': '处于本阶段经验有利区', 'neutral': '处于本阶段经验中性区'}.get(rate['zone'], '分区暂不可用')
    confirmation_note = '同窗口方向确认门尚未通过' if not next(x['passed'] for x in flow['quality_gate']['checks'] if x['id'] == 'Q9') else '同窗口价格与宏观已同向，仍需后续数据维持'
    headline = (f"[MODEL] 黄金当前按“{state['candidate_label']}”研究观察，规则评分优先检查“{main_name}”条件路径，正式状态仍待已接受决策确认。"
                f"{_text(rate.get('date'))} 实际利率 {_num(rate.get('value'))}%、{rate_effect}，{confirmation_note}。"
                "下一闸门是最新价格结构与同窗口实际利率、美元或资金共同确认，同时跟踪通胀数据、Fed 定价和能源风险。")
    independent_view = synthesis.get("analysis", {}).get("independent_assessment") or synthesis.get("analysis", {}).get("dominant_factor")
    model_summary = "".join(re.split(r"(?<=[。！？])", independent_view)[:3]) if independent_view else None
    add("research_summary", "一句话结论", "[MODEL] 总 Agent 研究判断（不代表正式状态已接受）：" + model_summary if model_summary else headline)

    delta = flow["delta_vs_previous"]
    delta_lines = [f"对比报告快照：{_text(delta.get('previous_snapshot_id'))}；分析截止 {_text(delta.get('previous_analysis_time'))}。", "", "| 指标 | 前次 → 本次 | 差值 | 变化性质 |", "|---|---|---:|---|"]
    for item in delta.get("rows", []):
        if item["symbol"] in {"XAUUSD_DAILY", "DXY", "US02Y", "REAL10Y", "BREAKEVEN_10Y", "BRENT_FUTURES_PROXY", "RESERVES", "TGA"} or item.get("change_kind") not in {"unchanged", "unavailable_or_source_changed"}:
            delta_lines.append(f"| {item['symbol']} | {_num(item['previous'])}（{_text(item['previous_date'])}）→ {_num(item['current'])}（{_text(item['current_date'])}） | {_num(item['delta'])} {item.get('unit', '')} | {_text(item['change_kind'])} |")
    if delta["status"] != "available":
        delta_lines.append("[UNCONFIRMED] 没有通过 DB 身份和产物哈希校验的前序研究报告；不把日变化冒充报告间变化。")
    delta_lines.append("same_observation_revised 表示同一观察日的数据修订，不代表新一个交易日。正式 State 的前后比较独立依赖 Gold 已接受决策链。")
    add("delta_vs_previous", "1. Delta vs Previous", "\n".join(delta_lines))

    table = ["| 因子 | 最新 / 观察日 | 1D（前观察日） | 1W（窗口起点） | 状态 | 黄金影响 |", "|---|---|---|---|---|---|"]
    for row in rows:
        influence = "利率家族" if row["symbol"] in {"US02Y", "US03M", "US05Y", "US10Y", "US30Y", "REAL10Y", "REAL_10Y"} else "背景 / 需交叉确认"
        table.append(f"| {row.get('label') or row['symbol']} | {_num(row.get('value'))} {row.get('unit', '')} / {_text(row.get('observation_date'))} | {_num(row.get('change'))} / {_text(row.get('previous_date'))} | {_num(row.get('weekly_change'))} / {_text(row.get('weekly_anchor_date'))} | {_text(row.get('status'))} | {influence} |")
    for label, value, day, week, observed in (
        ("GLD 份额", etf.get("shares_outstanding"), etf.get("shares_delta"), etf.get("shares_weekly_delta"), etf.get("shares_reported_on")),
        ("CFTC MM 净仓", cot.get("managed_money", {}).get("net"), None, (cot.get("managed_money", {}).get("delta") or {}).get("net"), cot.get("report_date")),
    ):
        table.append(f"| {label} | {_num(value)} / {_text(observed)} | {_num(day)} | {_num(week)} | 披露频率单列 | 资金确认 |")
    table += ["", "[FACT] 1D 实为前一可得观察值变化，1W 保留实际窗口起点；缺失不填零。美元指数和广义美元分别列示，直接 TIPS 与名义减 BE 不重复投票。"]
    add("unified_factor_table", "2. Unified Factor Table", "\n".join(table), "confirmed_data")

    macro = [f"[MODEL] 研究主实际利率：{_text(rate.get('symbol'))}，{_text(rate.get('method'))}；环境 {_text(rate['zone'])}。经验阈值有效期 {rate['profile']['valid_from']} 至 {rate['profile']['valid_until']}，状态 {rate['profile_status']}。", ""]
    for f in flow["factor_families"]:
        macro.append(f"- **{f['family']}**：{f['direction']} / {f['status']}。{f['explanation']} {_links(f['source_refs'])}")
    for key in ("rates", "project", "energy", "liquidity"):
        macro += ["", *assessment.get("domain_notes", {}).get(key, [])]
    monthly_rows = [x for x in rows if x.get("frequency") == "monthly"]
    if monthly_rows:
        macro += ["", "月度通胀与增长输入（不是日变化）：", "", "| 序列 | 观察月 | 水平 | 同口径环比 | 同版本同比 | 状态 |", "|---|---|---:|---:|---:|---|"]
        for row in monthly_rows:
            macro.append(f"| {_text(row.get('label') or row['symbol'])} | {_text(row.get('observation_date'))} | {_num(row.get('value'))} | {_num(row.get('monthly_change_pct'))}% | {_num(row.get('yoy_change_pct'))}% | {_text(row.get('status'))} |")
        macro += ["", "未取得可追溯市场预期时不计算 surprise；指数水平和 PMI 点数不是通胀率。" + ("GDPNow/ISM 以官方发布和核心采集健康核验为准。" if shadow else "GDPNow/ISM 未覆盖或已停止更新时保留缺口，不从新闻预测补入。")]
    if shadow:
        if flow.get('cross_asset_freshness'):
            from apps.renderer.markdown.gold_reader import cross_asset_table
            macro.append(cross_asset_table(flow['cross_asset_freshness']))
        macro += ["", "核心采集健康（监控结果，不是行情判断）：", "", "| 数据源 | 官方最新 / 本地最新 | 预期发布 / SLA | Collector | Health |", "|---|---|---|---|---|"]
        for item in flow.get("core_source_health", {}).get("items", []):
            macro.append(f"| {item['source_key']} | {_text(item.get('official_latest_date'))} / {_text(item.get('actual_latest_date'))} | {_text(item.get('expected_release_time'))} / {_text(item.get('expected_freshness'))} | {_text(item.get('collector_status'))} | **{item['source_health']}**：{_text(item.get('reason'))} |")
        macro += ["", *assessment.get("domain_notes", {}).get("growth", [])]
    macro += ["", "就业与增长：", legacy["employment"]["body"], "", "[MODEL] 油价的避险和通胀通道分开观察；没有发布前后同步价格时，不能断言某条新闻导致涨跌。FedWatch 未获授权数据时保留缺口，不从联邦基金期货 OI 构造加息概率。", *flow["method_boundaries"]]
    add("macro_diagnosis", "3. Macro Diagnosis", "\n".join(macro))
    flows = flow.get("flow_diagnostics", {})
    flow_lines = ["[MODEL] 同窗口资金分类：", "", "| CFTC 口径 | 精确价格窗口 | 价格变化 | 分类 | 状态 |", "|---|---|---:|---|---|"]
    for name, item in flows.get("reports", {}).items():
        window = item.get("window", {})
        flow_lines.append(f"| {name} | {_text(item.get('previous_report_date'))} → {_text(item.get('report_date'))} | {_num(window.get('price_delta'))} | {_text(item.get('classification'))} | {_text(item.get('classification_status'))} |")
    flow_lines += ["", "这里只检验持仓和价格是否符合分类规则；总 OI 不是基金本身杠杆的精确度量，也不能据此归因某次讲话。IAU/WGC 全球流向未覆盖时，GLD 不代表全球 ETF。"]
    add("funds", "4. Funds：CFTC、ETF、CME", "[FACT] CFTC 与 ETF：\n\n" + legacy["positioning_flows"]["body"] + "\n\n" + "\n".join(flow_lines) + "\n\n[MODEL] CME 期权结构：\n\n" + legacy["cme_structure"]["body"] + "\n\nCall/Put 多头期权自身 Gamma 均非负；当前代码把 Call/Put 暴露量记录为正值后相减，符号来自持仓方向假设。若使用带负号的 Put 才应直接相加。GEX 不是已知做市商仓位。")

    gold = controls.get("gold_policy", {})
    decision = gold.get("decision") or {}
    state_lines = ["| 项目 | 本次结果 |", "|---|---|", f"| Previous State | {_text(state.get('previous_state'))} |", f"| Current State | {_text(state.get('current_state'))}；需正式已接受决策 |", f"| Candidate State | {_text(state['candidate_state'])} / {_text(state['candidate_label'])}；研究候选 |", f"| State Confidence | {_text(state.get('state_confidence'))}；正式状态未确认时不生成精确置信度 |", f"| 正式 Gold 模式 / 质量 | {_text(gold.get('execution_mode'))} / {_text(decision.get('quality_status'))} |", f"| 阻塞 | {_text(', '.join(decision.get('conflicts') or []))} |", "", state["reason"], "至少两类独立证据支持升级；日内上涨、下跌、单个墙位或新闻不能单独迁移。"]
    if coordinator and coordinator.accepted_state_conclusion is not None:
        state_lines.append("已接受正式决策：" + _text(coordinator.accepted_state_conclusion.model_dump(mode="json")))
    if shadow:
        record = flow["state_record"]
        state_lines = ["S1–SX 研究状态账本（接受研究判断不授予交易权限）：", "", "| 字段 | 值 |", "|---|---|",
                       f"| State ID | {_text(record.get('state_id'))} |", f"| Previous Accepted State | {_text(record.get('previous_state'))} |",
                       f"| Current / Accepted State | {_text(record.get('accepted_state'))} |", f"| Candidate State | {_text(record.get('candidate_state'))} |",
                       f"| Transition Status / Confirmed | {_text(record.get('transition_status'))} / {_text(record.get('transition_confirmed'))} |",
                       f"| Predecessor / Accepted At | {_text(record.get('predecessor_id'))} / {_text(record.get('accepted_at'))} |",
                       f"| Rule Validation | {_text(record.get('rule_validation'))} |", "", state['reason'],
                       "", "确认条件：" + "；".join(x['condition'] for x in record['confirmed_conditions']),
                       "缺失条件：" + ("；".join(x['condition'] for x in record['missing_conditions']) or "无"),
                       "失效条件：" + "；".join(record['invalidation_conditions'])]
        if record.get("accepted_state") is None:
            state_lines += ["", "**首次初始化待明确审阅接受。** 当前已持久化候选及条件；历史 HOLD 不能当作 Accepted，旧报告示例 S5 也不能自动作为初始状态。"]
    add("current_state", "5. Current State", "\n".join(state_lines))

    level_lines = ["| Price / Instrument | Status | Role / Previous | Trigger | Invalidation / Valid Until |", "|---|---|---|---|---|"]
    zones = {(z['price'], z.get('source_type'), z.get('source_date')): z for z in flow.get('execution_zones', {}).get('zones', [])}
    for x in flow["key_levels"]:
        zone = zones.get((x['price'], x.get('source_type'), x.get('source_date')), {}) if shadow else {}
        label = zone.get('display_label') or ("区间待核验" if shadow and x['instrument'] == 'XAUUSD spot' else _num(x['price']))
        level_lines.append(f"| {label} / {_text(x['instrument'])} | {_text(x['status'])} | {_text(x['role'])} / {_text(x.get('previous_role'))} | {_text(zone.get('activation') or x['activation'])} | {_text(zone.get('invalidation') or x['invalidation'])} / {_text(x.get('valid_until'))} |")
    if shadow:
        zone_method = flow.get('execution_zones', {})
        level_lines += ["", f"[MODEL] 执行区间方法：{_text(zone_method.get('width_policy_version'))}；输入缺口：{_text(', '.join(zone_method.get('missing_inputs', [])))}。原始价格、原始边界和显示边界分别保存在 JSON；ATR 系数属于经验显示规则，未经收益校准。"]
    level_lines += ["", "[CHART] 现货位由完整价格窗口产生；[MODEL] CME 位保留各自期货坐标。Stale/Invalidated 不参与当前路径，未验证到期/基差的期权位仅作 Conditional。"]
    add("key_level_lifecycle", "6. Key Level Lifecycle", "\n".join(level_lines))

    engine = flow["scenario_engine"]
    scenario_lines = ["[MODEL] 下列为规则权重，**不是统计概率**。类别基准：Macro 35%、Price 25%、Options 20%、Funds 15%、Events 5%。数据覆盖与方向评分分开：direction_unavailable 表示有数据但未证明方向，不伪造中性票；仅可评分输入归一化，未覆盖部分降低置信度。期权和事件继续约束期限、结构及事件风险。", f"路径报价锚 {_num(engine['price_anchor'])}（{engine['price_anchor_kind']}），水平由完整日线产生；盘中越过水平仍需结构确认。", "", "| 类别 | 数据覆盖率 | 信号状态 | 归一化权重 |", "|---|---:|---|---:|"]
    for key in engine["base_weights"]:
        scenario_lines.append(f"| {key} | {engine['coverage'][key]:.0%} | {_text(engine.get('signal_status', {}).get(key))} | {engine['normalized_weights'][key]:.1%} |")
    scenario_lines += ["", f"规则：{engine['rule']}。证据覆盖折扣 {_num(engine['confidence'])}，不是预测正确率。", "", "| 路径 | 权重 | Trigger | Macro Confirmation | Price Path | Invalidation |", "|---|---:|---|---|---|---|"]
    displayed_scenarios = flow.get('scenario_display', {}).get('scenarios', engine['scenarios']) if shadow else engine['scenarios']
    for x in sorted(displayed_scenarios, key=lambda p: p["weight_pct"] or 0, reverse=True):
        weight = f"{x['display_weight_pct']}% / {x['display_level']}" if shadow and x.get('display_weight_pct') is not None else "待核验" if shadow else _num(x['weight_pct'])+"%"
        scenario_lines.append(f"| {x['priority']} / {x['name']} | {weight} | {_text(x['trigger'])} | {_text(x['macro_confirmation'])} | {_text(x['price_path'])} | {_text(x['invalidation'])} |")
    if shadow:
        scenario_lines += ["", "Score Share 以 5% 档展示，原始分数保留在特征中；尚无历史校准，不解释为胜率或统计概率。"]
    add("three_scenarios", "7. Three Scenarios", "\n".join(scenario_lines))
    ex = flow["execution"]
    frame_table = ["| 周期 | 最新完整收盘 UTC | 状态 | 短窗方向 | 结构代理 |", "|---|---|---|---|---|"]
    for item in ex.get("timeframe_features", []):
        frame_table.append(f"| {item['timeframe']} | {_text(item['close_time'])} | {item['status']} | {_text(item['trend'])} | {_text(', '.join(e.get('type', '') for e in item['events']) or '未确认')} |")
    execution_scope = "[MODEL] 4H → 1H → 15m；本轮不分析5m。" if flow.get('price_action') else "[MODEL] 4H → 1H → 15m → 5m；主执行观察 15m，5m 辅助触发。"
    add("execution_card", "8. Execution Card", "\n\n".join([execution_scope, ex["reason"], "\n".join(frame_table), ex["flat"], ex["long"], ex["short"], ex["event_rule"]]))

    risks = ["按当前影响渠道排序：官方通胀数据 → Fed 政策与实际利率 → 能源/地缘 → ETF/CFTC → 融资信用。排序为研究判断。", "", legacy["event_calendar"]["body"], "", "相关新闻核验：", legacy["news_evidence"]["body"], "", "质量门：", "| 检查 | 结果 | 原因 |", "|---|---|---|"]
    for q in flow["quality_gate"]["checks"]:
        risks.append(f"| {q['id']} {q['name']} | {'Pass' if q['passed'] else 'Partial'} | {q['reason']} |")
    risks += ["", legacy["research_limitations"]["body"]]
    add("risk_list", "9. Risk List", "\n".join(risks))

    final = ["[MODEL] 以下为总 Agent 的独立综合研判，可以不同意规则评分或领域模块；模型观点不会自动改写原始事实、系统关键位或正式 Gold 状态。", ""]
    if model_record:
        final += [
            f"模型综合：{_text(model_record.get('generated_by') or 'deterministic')}；状态 {_text(model_record.get('status'))}；完整审计 {_text(model_record.get('provenance_complete'))}。",
            f"报告输出选择：{_text(report_output_record.get('selection_kind'))}；Agent {_text(report_output_record.get('agent_name'))}；状态 {_text(report_output_record.get('agent_status'))}。",
        ]
    else:
        final += [f"总 Agent 执行方式：{_text(synthesis.get('generated_by') or 'deterministic')}；状态 {_text(synthesis.get('status'))}。"]
    explanation = synthesis.get("analysis", {})
    for key, label in (("independent_assessment", "独立判断"), ("dominant_factor", "主导因素"), ("counter_evidence", "反证"), ("module_challenges", "对模块结论的复核与质疑"), ("alternative_hypotheses", "替代解释与待验证假设"), ("state_limitations", "状态限制"), ("convergence_transition", "下一次共振条件"), ("what_would_change_my_mind", "什么会改变判断")):
        value = explanation.get(key)
        if value:
            final += ["", f"**{label}**：" + ("；".join(value) if isinstance(value, list) else value)]
    numeric_review = synthesis.get("numeric_review", {})
    if numeric_review.get("unverified_mentions"):
        final += ["", "[UNCONFIRMED] 模型新增数值提及：" + ", ".join(numeric_review["unverified_mentions"]) + "。这些提及尚未完成公式或来源核验，未提升为系统事实、关键位或状态触发条件。"]
    final += ["", "规则观察基线（供模型对照，不强制同意）：" + headline]
    if coordinator:
        final += ["", "[MODEL] " + coordinator.summary, "", *["- " + x for x in coordinator.key_findings]]
    final += ["", "模块分歧核对：", legacy["module_reconciliation"]["body"]]
    add("final_assessment", "10. Final Assessment：总 Agent 综合分析", "\n".join(final))

    official, news = [], []
    for ref in refs:
        url = ref.get("source_url") or ref.get("reference")
        if not url or not str(url).startswith("https://"):
            continue
        target = official if any(x in url for x in ("treasury.gov", "federalreserve.gov", "newyorkfed.org", "fred.stlouisfed.org", "bls.gov", "bea.gov", "cftc.gov", "cmegroup.com", "ssga.com", "spdrgoldshares.com", "ishares.com", "gold.org", "atlantafed.org", "ismworld.org")) else news
        entry = f"[{_text(ref.get('source') or url)}]({url})"
        if entry not in target:
            target.append(entry)
    add("analysis_sources", "数据来源", "\n\n".join(["**Official**\n\n" + ("；".join(official) or "见各节结构化 source_refs"), "**Real-time / News**\n\n" + ("；".join(news) or "本次未获得已核验实时来源"), "**Uploaded Files**\n\n本次未使用用户上传行情文件；用户提供的历史报告作为方法对照，不作为当前数据。", "**Model Inference**\n\n状态候选、场景权重、关键位角色、宏观传导和总 Agent 解释均为推断。完整 input_snapshot_ids、source_refs 保存在 JSON 和快照中；新闻标题仅候选，未核验内容为 [UNCONFIRMED]。"]), source_refs=refs)
    if shadow:
        versions = snapshot.get('research_versions', {})
        record = controls.get('production_shadow', {}).get('record', {})
        sections[-1]['body'] += "\n\n**版本与 Shadow 验收**\n\n" + f"代码/Skill 清单：{_text(versions.get('manifest_id'))}；规则版本 {_text(versions.get('rule_version'))}；模型 {_text(record.get('model', {}).get('llm_model'))}；LLM 审计 {_text(record.get('model', {}).get('audit_id'))}。原始快照、源引用、代码与 Skill 内容哈希、实际提示词和模型返回均留存。\n\n重放使用冻结输入和已记录模型输出；重新请求随机模型不保证逐字相同。20—30个真实交易日及 NFP/CPI/FOMC 覆盖尚待真实运行积累；同日重跑、回放和未来事件日历不计作验收完成。"
    return sections
