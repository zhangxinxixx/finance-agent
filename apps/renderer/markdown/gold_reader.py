"""Reader-facing report from frozen facts and recorded model interpretation."""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from apps.analysis.agents.research_input import RESEARCH_PRESENTATION_VERSION
from apps.renderer.markdown.daily_research import _links


def prose(value):
    if isinstance(value, list):
        return '\n\n'.join(prose(x) for x in value if x)
    text = str(value or '')
    # Model labels are not independently verified FACTs. These paragraphs live
    # under an explicitly identified model interpretation in the reader report.
    text = re.sub(r'\[(?:FACT|CALC|MODEL|NEWS|CHART)\]\s*', '', text)
    return text.strip()


def fmt(value):
    return f'{value:,.2f}'.rstrip('0').rstrip('.') if isinstance(value, (int, float)) else str(value or '未取得')


def cross_asset_table(cross):
    if not cross:
        return ''
    labels = {'FRESH_MINUTE_BAR': '近期分钟bar（非tick）', 'DELAYED_CLOCK_UNVERIFIED': '延迟，精确报价时点未验证',
              'CLOCK_UNVERIFIED': '报价时点未验证', 'STALE_BAR': '分钟bar滞后', 'STALE_CAPTURE': '采集已过期',
              'DELAYED_BAR': '延迟分钟bar', 'DELAY_UNVERIFIED': '延迟未验证', 'INVALID_TIME': '时间无效',
              'INVALID': '数据无效', 'MISSING': '未取得'}
    lines = ['\n\n**TradingView 盘中补充：与上表官方日终分列**',
             '| 标的 | 观测值 | 分钟bar起始时间（UTC） | 源延迟 | 时效判断 |', '|---|---:|---|---|---|']
    for row in cross['observations']:
        delay = row.get('delay_seconds')
        lines.append(f"| {row['ticker']} | {fmt(row.get('display_value'))} {row['unit']} | {row.get('minute_bar_time') or '未提供'} | {str(delay) + '秒' if delay is not None else '未知'} | {labels.get(row['freshness'], row['freshness'])} |")
    captured = sorted({r.get('retrieved_at') for r in cross['observations'] if r.get('retrieved_at')})
    lines.append('\n抓取时间（UTC）：' + ' / '.join(captured) + '。抓取时间不等于行情成交时间；CL1!/BRN1!是连续期货，不能当现货或官方结算。\n')
    if cross['critical_freshness_failures']:
        lines.append('**能源盘中时效未完全通过：ENERGY_INTRADAY。** 可以观察延迟价格和讨论风险，不能据此确认实时跨资产共振。')
    for curve in cross['curves']:
        lines.append(f"TV {curve['label']}：" + (f"{fmt(curve['value_bp'])}bp（两腿近期分钟bar相差不超过2分钟）" if curve['value_bp'] is not None else '未计算，两腿时点不同或有滞后。'))
    windows = cross.get('chart_windows', {}).get('windows', [])
    usable = [w for w in windows if w.get('aligned_comparison_allowed') and w.get('group') in {'energy', 'policy'}]
    if usable:
        lines.extend(['\n**共同已完成K线窗口（UTC；收盘到收盘）**',
                      '\n延迟数据可以用于以下同一历史窗口；这些变化不等于实时行情，也不单独证明新闻因果。',
                      '\n| 窗口 | 起止时间 | 各资产变化 | 最大源延迟 |', '|---|---|---|---|'])
        for window in usable:
            changes = '；'.join(f"{r['symbol']} {r['change_bp']:+.2f}bp" if 'change_bp' in r
                                else f"{r['symbol']} {r['change_pct']:+.2f}%" for r in window['changes'])
            lines.append(f"| {window['group']} {window['horizon_minutes']}分钟 | {window['window_start']} → {window['window_end']} | {changes} | {window['max_delay_seconds']}秒 |")
    return '\n'.join(lines)


def etf_window_table(etf):
    if not etf.get('shares_weekly_anchor_date'):
        return ''
    return ('\n\n**GLD 比较窗口（单基金，不代表全球ETF流量）**\n\n'
            '| 指标 | 起点日期 / 数值 | 终点日期 / 数值 | 变化 |\n|---|---|---|---:|\n'
            f"| 份额 | {etf.get('shares_weekly_anchor_date')} / {fmt(etf.get('shares_weekly_anchor_value'))} | {etf.get('shares_reported_on')} / {fmt(etf.get('shares_outstanding'))} | {fmt(etf.get('shares_weekly_delta'))} |\n"
            f"| 持金量（吨） | {etf.get('gold_holdings_tonnes_weekly_anchor_date')} / {fmt(etf.get('gold_holdings_tonnes_weekly_anchor_value'))} | {etf.get('gold_holdings_tonnes_reported_on')} / {fmt(etf.get('gold_holdings_tonnes'))} | {fmt(etf.get('gold_holdings_tonnes_weekly_delta'))} |")


def reader_sections(snapshot, outputs, assessment):
    flow = snapshot['gold_workflow']
    coordinator = outputs.get('coordinator')
    synthesis = (coordinator.input_payload or {}).get('research_synthesis', {}) if coordinator else {}
    analysis = synthesis.get('analysis', {})
    if flow.get('reader_report_version') == 'gold_reader.v4':
        from apps.renderer.markdown.gold_detailed import concise_sections, detailed_sections
        if flow.get('reader_presentation') == 'gold_reader.concise.v1':
            return concise_sections(snapshot, synthesis)
        if flow.get('reader_presentation') == RESEARCH_PRESENTATION_VERSION:
            return research_sections(snapshot, synthesis)
        return detailed_sections(snapshot, synthesis)
    rows = {r['symbol']: r for r in snapshot['daily_research']['passport']}
    if flow.get('reader_report_version') == 'gold_reader.v3':
        return readable_sections(snapshot, synthesis)
    sections = []
    refs = flow.get('source_refs', [])

    def add(key, title, text, category='system_inference'):
        sections.append({'section_id': key, 'title': title, 'body': text,
                         'status': 'partial' if flow['quality_gate']['data_quality'] == 'Partial' else 'ok',
                         'source_refs': refs, 'data_category': category})

    summary = prose(analysis.get('independent_assessment') or analysis.get('dominant_factor'))
    add('research_summary', '核心判断', summary or '本次模型综合未完成，当前只能观察已采集数据，暂不作完整方向判断。', 'external_opinion')
    anchor = flow['price_anchor']
    table = ['| 指标 | 最新有效值 | 观察时间 |', '|---|---:|---|',
             f"| 现货黄金 | {fmt(anchor.get('price'))} 美元/盎司 | {anchor.get('price_time', '未验证')} |",
             f"| 已收盘OTC日线 | {fmt(anchor.get('daily_close'))} 美元/盎司 | {anchor.get('daily_close_date')} |"]
    labels = {'DXY': '美元指数', 'US02Y': '2Y美债', 'US10Y': '10Y美债', 'US30Y': '30Y美债',
              'REAL10Y': '官方10Y实际利率', 'BREAKEVEN_10Y': '10Y通胀预期',
              'YIELD_SPREAD_2Y_3M': '2Y−3M', 'YIELD_SPREAD_10Y_2Y': '10Y−2Y',
              'BRENT_FUTURES_PROXY': 'Brent期货日线代理', 'WTI_FUTURES_PROXY': 'WTI期货日线代理',
              'GDP_NOW': 'GDPNow', 'ISM_MANUFACTURING': 'ISM制造业', 'ISM_SERVICES': 'ISM服务业',
              'ISM_SERVICES_PRICES': 'ISM服务业价格', 'SOFR': 'SOFR', 'EFFR': 'EFFR', 'IORB': 'IORB', 'HY_OAS': '高收益债利差'}
    for symbol, label in labels.items():
        row = rows.get(symbol, {})
        table.append(f"| {label} | {fmt(row.get('value'))} {row.get('unit', '')} | {row.get('observation_date') or '未取得'} |")
    market_body = '\n'.join(table) + '\n\n日线价格、官方利率与盘中报价来自不同观察窗口。期货日线代理不代表当前盘中报价或官方结算。'
    market_body += cross_asset_table(flow.get('cross_asset_freshness'))
    market_body += etf_window_table(snapshot['daily_research'].get('official_etf', {}))
    add('market_snapshot', '市场快照：盘中与日终分别看', market_body, 'confirmed_data')
    add('market_move', '这次价格变化，哪些解释有证据？', prose(analysis.get('market_move_explanation') or analysis.get('dominant_factor')) or '当前缺少同窗口价格与事件证据，不能把涨跌确定归因于某条新闻。')
    add('alternatives', '其他可能解释与判断失效条件', prose(analysis.get('alternative_hypotheses')) + '\n\n' + prose(analysis.get('what_would_change_my_mind')))
    source_rows = ('REAL10Y', 'US02Y', 'BREAKEVEN_10Y', 'GDP_NOW', 'ISM_SERVICES', 'SOFR', 'HY_OAS', 'DIESEL_GULF_SPOT', 'GASOLINE_GULF_SPOT')
    selected_refs = [ref for symbol in source_rows for ref in rows.get(symbol, {}).get('source_refs', [])]
    sources = _links(selected_refs)
    if flow.get('cross_asset_freshness'):
        sources += '\n\nTradingView盘中来源：' + ' / '.join(
            f"[{r['ticker']}](https://www.tradingview.com/symbols/{r['ticker'].replace(':', '-')}/)"
            for r in flow['cross_asset_freshness']['observations'])
    quality_note = '数据仍有缺口，当前适合条件分析，尚不足以作强方向确认。' if flow['quality_gate']['data_quality'] == 'Partial' else ''
    add('sources', '数据范围与来源',
        '正文中的解释与情景属于模型研究观点，不能替代已经核验的原始数据。' + quality_note + '\n\n'
        + sources + '\n\n[完整数据护照与审计附件](audit_report.md)', 'confirmed_data')
    # Core market anchors and source boundaries are stable. The model decides
    # the day's subject, arguments, section ordering and counter-hypotheses.
    narrative = prose(analysis.get('reader_narrative'))
    selected = [s for s in sections if s['section_id'] in {'research_summary', 'market_snapshot'}]
    if flow.get("macro_causal"):
        from apps.renderer.markdown.macro_causal import macro_causal_section
        selected.append(macro_causal_section(flow["macro_causal"]))
        review = synthesis.get("macro_review") or {}
        if review:
            selected.append({"section_id":"macro_review", "title":"宏观审阅与置信度", "body":
                "Reviewer："+review.get("status","unavailable")+"；研究置信度系数 "+str(review.get("confidence_multiplier"))+"（不是概率）。\n\n"+
                "\n".join("- "+str(c["id"])+"："+c["reason"] for c in review.get("checks",[]) if not c["passed"]),
                "status":"partial", "source_refs":refs, "data_category":"external_opinion"})
        answers = analysis.get("macro_answers", {})
        narrative_states = analysis.get("macro_narrative", {})
        if answers:
            body = "\n\n".join("**"+q["question"]+"**\n\n"+answers.get(q["id"], "未完成") for q in flow["macro_causal"]["questions"])
            states = "\n".join("- "+k+"："+str(v) for k,v in narrative_states.items())
            selected.append({"section_id":"macro_answers", "title":"当前宏观叙事与八项因果判断", "body":states+"\n\n"+body,
                             "status":"partial", "source_refs":refs, "data_category":"external_opinion"})
    if narrative:
        selected.append({'section_id': 'model_research', 'title': '综合研判', 'body': narrative,
                         'status': sections[0]['status'], 'source_refs': refs, 'data_category': 'external_opinion'})
    else:
        selected.extend(s for s in sections if s['section_id'] in {'market_move', 'alternatives'})
    if flow.get('reader_report_version') == 'gold_reader.v2':
        from apps.renderer.markdown.gold_decision_cards import decision_cards

        cards = decision_cards(snapshot)
        # Stable cards expose the contract without choosing the model's topic
        # or changing its recorded narrative. v1 sections remain replayable.
        selected.insert(1, cards[0])
        selected.extend(cards[1:])
    selected.extend(s for s in sections if s['section_id'] == 'sources')
    return selected


def readable_sections(snapshot, synthesis):
    """Narrative first; detailed contracts remain in the audit sibling."""
    flow = snapshot['gold_workflow']
    analysis = synthesis.get('analysis', {})
    refs = flow.get('source_refs', [])
    sections = []

    def add(key, title, body, category='external_opinion'):
        sections.append({'section_id': key, 'title': title, 'body': body,
                         'status': 'partial' if flow['quality_gate']['data_quality'] == 'Partial' else 'ok',
                         'source_refs': refs, 'data_category': category})

    complete = synthesis.get('status') == 'success' and bool(analysis.get('reader_narrative'))
    if complete:
        # The full narrative is the reader contract. Internal adjudication
        # fields can discuss revisions and must not become a second headline.
        add('model_research', '市场判断与推演', reader_prose(analysis['reader_narrative']))
    else:
        add('research_summary', '当前判断',
            '本次完整分析尚未生成，下面只展示已经取得的数据，不据此给出新的方向判断。')
    anchor = flow['price_anchor']
    session = snapshot.get('daily_research', {}).get('market_session', {})
    closed = not session.get('new_intraday_confirmation_allowed', False)
    lines = ['| 指标 | 观察值 | 数据日期 |', '|---|---:|---|',
             f"| 黄金最近已收盘日线 | {fmt(anchor.get('daily_close'))} 美元/盎司 | {anchor.get('daily_close_date') or '未取得'} |"]
    if not closed and anchor.get('status') in {'verified', 'available'}:
        lines.append(f"| 现货黄金报价 | {fmt(anchor.get('price'))} 美元/盎司 | {anchor.get('price_time') or '未验证'} |")
    labels = {'US02Y': '2年美债收益率', 'US10Y': '10年美债收益率', 'US30Y': '30年美债收益率',
              'REAL10Y': '10年实际利率', 'BREAKEVEN_10Y': '10年盈亏平衡通胀率', 'DXY': '美元指数',
              'BRENT_FUTURES_PROXY': 'Brent连续期货日线', 'WTI_FUTURES_PROXY': 'WTI连续期货日线'}
    units = {'%': '%', 'index': '', 'USD/bbl': '美元/桶'}
    for row in snapshot['daily_research']['passport']:
        if row['symbol'] in labels:
            unit = units.get(row.get('unit'), row.get('unit', ''))
            lines.append(f"| {labels[row['symbol']]} | {fmt(row.get('value'))} {unit} | {row.get('observation_date') or '未取得'} |")
    note = ('市场休市或交易时段尚未确认，不把供应商刷新时间当成新成交，也不产生新的日内交易确认。'
            if closed else '报价和官方日终数据的时点不同，请按表中日期理解。')
    add('market_snapshot', '理解本次行情需要的几个数', '\n'.join(lines)+'\n\n'+note+
        ' 连续期货日线不等于现货或官方结算价。', 'confirmed_data')
    from apps.renderer.markdown.research_evidence import multi_horizon_table, policy_path_table
    policy = flow.get('macro_causal', {}).get('engines', {}).get('policy', {})
    evidence = [policy_path_table(policy), multi_horizon_table(flow.get('cross_asset_freshness') or {})]
    if any(evidence):
        add('policy_and_windows', '政策路径与行情窗口', '\n\n'.join(x for x in evidence if x), 'deterministic_calculation')
    review = synthesis.get('macro_review') or {}
    notes = []
    if review.get('status') == 'unavailable':
        notes.append('独立审阅暂未完成，研究可信度已下调；这不表示已经发现具体分析错误。')
    elif review and review.get('status') != 'pass':
        notes.append('本次分析仍有尚未通过核验的判断，研究可信度已下调，请结合附件中的具体问题阅读。')
    if not (flow.get('state_record') or {}).get('accepted_state'):
        notes.append('本次属于研究判断，不宣布正式市场状态已经升级或降级。')
    notes.append('数据来源、观察时间、计算过程及审查记录见[数据与审计附件](audit_report.md)。')
    add('sources', '数据与判断的范围', '\n\n'.join(notes), 'confirmed_data')
    return sections


def research_sections(snapshot, synthesis):
    """New daily reader: one full model body plus one scoped limitation note."""
    flow = snapshot['gold_workflow']
    analysis = synthesis.get('analysis') or {}
    narrative = analysis.get('reader_narrative')
    complete = synthesis.get('status') == 'success' and isinstance(narrative, str) and bool(narrative.strip())
    refs = flow.get('source_refs') or []
    status = 'partial' if (snapshot.get('input_validation') or {}).get('status') == 'partial' else 'ok'
    if complete:
        primary = narrative
    else:
        primary = '本次完整日报正文未通过生成契约，不根据残留字段拼接或发明研究结论。'

    validation = snapshot.get('input_validation') or {}
    missing = [key for key, item in (validation.get('domains') or {}).items()
               if isinstance(item, dict) and item.get('status') == 'unavailable']
    review = synthesis.get('macro_review') or {}
    gate = flow.get('quality_gate') or {}
    limits = []
    if missing:
        labels = {'spot': '现货报价', 'growth': '增长', 'inflation': '通胀', 'rates': '利率',
                  'policy': '政策定价', 'oil': '原油', 'options': 'CME期权', 'flows': '资金',
                  'execution': '日内价格结构', 'news': '新闻原文', 'cross_asset': '跨资产行情'}
        limits.append('缺失输入：' + '、'.join(labels.get(key, key) for key in missing) + '；只限制依赖这些输入的判断。')
    if review.get('status') != 'pass':
        limits.append('独立因果审阅：' + str(review.get('status') or '未完成') + '。')
    if gate.get('publish_allowed') is not True:
        limits.append('当前快照未证明发布条件通过；生成正文不授予 Accepted、发布或交易权限。')
    if not limits:
        limits.append('正文是研究判断；Accepted、发布与交易权限仍由既有独立门禁决定。')
    limits.append('事实来源、输入缺口、内部结构化推理与确定性明细见[数据与审计附件](audit_report.md)。')
    return [
        {'section_id': 'model_research', 'title': '完整研判', 'body': primary,
         'status': status if complete else 'partial', 'source_refs': refs,
         'data_category': 'external_opinion' if complete else 'system_inference'},
        {'section_id': 'research_scope', 'title': '数据、审阅与权限边界', 'body': '\n\n'.join(limits),
         'status': 'partial' if limits else status, 'source_refs': [], 'data_category': 'confirmed_data'},
    ]


def reader_prose(value):
    """Translate stable technical labels without changing the recorded thesis."""
    text = prose(value)
    for label, chinese in {
        'Selected Expiry Window Proxy Gamma Flip': '所选到期窗口的估算Gamma转折点',
        'OI-Signed GEX Proxy': '按公开持仓加符号估算的Gamma敞口',
        'OI/Gamma Concentration Zone': '持仓与Gamma集中区',
        'quote_time': '报价时点', 'minute_bar_time': '分钟行情时点',
        'failed-breakout': '失败突破', 'PRELIM': '初步版',
        'Medium': '中等', 'High': '高', 'Low': '低',
    }.items():
        text = re.sub(r'(?<![A-Za-z_])'+re.escape(label)+r'(?![A-Za-z_])', chinese, text)
    text = re.sub(r'(?m)^# ', '### ', text)
    return re.sub(r'(?m)^([一二三四五六七八九十]+、[^\n]+)$', r'### \1', text)


def reader_audit_details(snapshot, outputs):
    """Keep internal v4 evidence visible without duplicating it in reader prose."""
    from copy import deepcopy
    from apps.renderer.markdown.gold_decision_cards import decision_cards
    if snapshot['gold_workflow'].get('reader_presentation') == RESEARCH_PRESENTATION_VERSION:
        from apps.renderer.markdown.gold_detailed import detailed_sections
        coordinator = outputs.get('coordinator')
        synthesis = (coordinator.input_payload or {}).get('research_synthesis', {}) if coordinator else {}
        internal = detailed_sections(snapshot, synthesis)
        return '\n\n' + '\n\n'.join('## ' + s['title'] + '\n\n' + s['body'] for s in internal) + '\n'
    if snapshot['gold_workflow'].get('reader_presentation') == 'gold_reader.concise.v1':
        from apps.renderer.markdown.gold_detailed import detailed_sections
        coordinator = outputs.get('coordinator')
        synthesis = (coordinator.input_payload or {}).get('research_synthesis', {}) if coordinator else {}
        full = detailed_sections(snapshot, synthesis)
        return '\n\n' + '\n\n'.join('## ' + s['title'] + '\n\n' + s['body'] for s in full) + '\n'
    audit = deepcopy(snapshot)
    audit['gold_workflow']['reader_report_version'] = 'gold_reader.v2'
    internal = [s for s in reader_sections(audit, outputs, {})
                if s['section_id'] in {'macro_review', 'macro_answers'}]
    if audit['gold_workflow'].get('macro_causal'):
        from apps.renderer.markdown.macro_causal import macro_causal_section
        internal.insert(0, macro_causal_section(audit['gold_workflow']['macro_causal']))
    internal.extend(decision_cards(audit))
    return '\n\n' + '\n\n'.join('## '+s['title']+'\n\n'+s['body'] for s in internal)+'\n'


def render_reader_report(snapshot, sections):
    raw_cutoff = datetime.fromisoformat(snapshot['snapshot_time'].replace('Z', '+00:00'))
    if (snapshot.get('gold_workflow', {}).get('reader_presentation') == RESEARCH_PRESENTATION_VERSION
            and (raw_cutoff.tzinfo is None or raw_cutoff.utcoffset() is None)):
        raise ValueError('gold_reader.research.v1 requires a timezone-aware snapshot cutoff')
    cutoff = raw_cutoff.astimezone(ZoneInfo('Asia/Shanghai'))
    parts = [f"# {snapshot['trade_date']} 黄金综合分析", f"分析截止北京时间 **{cutoff:%Y年%m月%d日 %H:%M}**。不使用金十数据。"]
    if snapshot.get('gold_workflow', {}).get('reader_presentation') == RESEARCH_PRESENTATION_VERSION:
        parts.append(_reference_spot_line(snapshot))
    if snapshot.get('benchmark_replay', {}).get('mode') == 'engineering_replay':
        parts.append('**分析回放说明**：本报告复用归档快照，并补入人工核实的官方利率与已收盘现货历史资料。'
                     '它用于新版报告内容验收，尚不代表自动采集已经恢复；正式市场状态保持原记录。')
    for s in sections:
        if (snapshot.get('gold_workflow', {}).get('reader_presentation') == RESEARCH_PRESENTATION_VERSION
                and s['section_id'] == 'model_research'):
            parts.append(s['body'])
        else:
            parts.extend([f"## {s['title']}", s['body']])
    return '\n\n'.join(parts) + '\n'


def _reference_spot_line(snapshot):
    anchor = (snapshot.get('gold_workflow') or {}).get('price_anchor') or {}
    price_time = anchor.get('price_time')
    price = anchor.get('price')
    from math import isfinite
    if (not isinstance(price, (int, float)) or isinstance(price, bool)
            or not isfinite(price) or price <= 0
            or anchor.get('instrument', 'XAUUSD') != 'XAUUSD'):
        return '参考现货报价：**不可用**。未取得有效XAUUSD现货报价。'
    if anchor.get('status') not in {'available', 'fresh', 'verified'} or price is None or not price_time:
        return '参考现货报价：**不可用**。未以GC期货或日线代理替代当前XAUUSD现货。'
    try:
        parsed = datetime.fromisoformat(str(price_time).replace('Z', '+00:00'))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError('naive quote time')
        if parsed > datetime.fromisoformat(snapshot['snapshot_time'].replace('Z', '+00:00')):
            raise ValueError('quote after analysis cutoff')
        display_time = parsed.astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y年%m月%d日 %H:%M')
    except (TypeError, ValueError):
        return '参考现货报价：**不可用**。报价时点未通过截止与时区校验，未以GC期货替代。'
    refs = anchor.get('source_refs') or []
    ref = next((item for item in refs if isinstance(item, dict)), {})
    source = ref.get('source_name') or ref.get('source')
    if not source:
        return '参考现货报价：**不可用**。来源身份未通过校验，未以GC期货替代。'
    from apps.analysis.agents.research_input import _redact_url_credentials
    url = ref.get('source_url') or ref.get('url')
    label = f'[{source}]({_redact_url_credentials(url)})' if isinstance(url, str) and url.startswith('https://') else source
    return f"参考现货 **{fmt(price)} 美元/盎司**；报价时间（北京时间）**{display_time}**；来源：{label}。"
