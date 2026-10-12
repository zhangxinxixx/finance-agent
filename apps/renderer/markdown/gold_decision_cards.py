"""Reader cards from frozen research features; no state writes or scoring."""


def cell(value):
    if value is None or value == '':
        return '未取得'
    if isinstance(value, bool):
        return '是' if value else '否'
    if isinstance(value, (float, int)):
        return f'{value:,.4f}'.rstrip('0').rstrip('.')
    return str(value).replace('|', r'\|').replace('\n', '；')


def table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(headers) + ' |',
                      '|' + '---|' * len(headers),
                      *['| ' + ' | '.join(cell(v) for v in row) + ' |' for row in rows]])


def decision_cards(snapshot):
    flow = snapshot['gold_workflow']
    refs = flow.get('source_refs', [])
    cards = []

    def add(key, title, body, sources=None):
        cards.append({'section_id': key, 'title': title, 'body': body,
                      'status': 'partial' if flow['quality_gate']['data_quality'] == 'Partial' else 'ok',
                      'source_refs': refs if sources is None else sources,
                      'data_category': 'system_inference'})

    delta = flow.get('delta_vs_previous', {})
    labels = {'XAUUSD_DAILY': '黄金已收盘日线', 'DXY': '美元指数', 'US02Y': '2Y',
              'REAL10Y': '官方10Y实际利率', 'BRENT_FUTURES_PROXY': 'Brent日线代理',
              'WTI_FUTURES_PROXY': 'WTI日线代理', 'GDP_NOW': 'GDPNow', 'HY_OAS': 'HY OAS',
              'VIX': 'VIX', 'XAUUSD_QUOTE': '同源现货报价', 'GLD_SHARES': 'GLD份额',
              'GLD_TONNES': 'GLD持金吨数', 'CFTC_COMBINED_MM_NET': 'CFTC合并口径MM净仓'}
    kinds = {'unchanged': '无新增变化', 'new_observation': '新观察值',
             'same_observation_revised': '同观察日值更新（不等于官方修订）',
             'unavailable_or_source_changed': '缺失或来源变化，不作差'}
    if delta.get('status') == 'available':
        body = (f"比较基准：上一份**已核验研究报告** {cell(delta.get('previous_snapshot_id'))}，"
                f"截止 {cell(delta.get('previous_analysis_time'))}；不是上一份Accepted正式报告。\n\n")
        body += table(['指标', '前次值 / 日期', '本次值 / 日期', '差值 / 单位', '性质'], [
            [labels[r['symbol']], f"{cell(r.get('previous'))} / {cell(r.get('previous_date'))}",
             f"{cell(r.get('current'))} / {cell(r.get('current_date'))}",
             f"{cell(r.get('delta'))} {cell(r.get('unit'))}", kinds.get(r.get('change_kind'), r.get('change_kind'))]
            for r in delta.get('rows', []) if r['symbol'] in labels])
        body += '\n\n利率差值单位为百分点，不是bp。日线Delta不代表盘中回报；未取得前序同源盘中和资金窗口时，不从当前周变化反推报告间资金变化。'
    else:
        body = '上一研究报告身份或来源未通过核验，本次不生成报告间Delta，也不以单日涨跌代替。'
    add('reader_delta', '相对上一报告：什么变了', body, refs + delta.get('source_refs', []))

    record = flow.get('state_record', {})
    body = table(['字段', '账本结果'], [
        ['Previous Accepted State', record.get('previous_state')],
        ['Current Accepted State', record.get('accepted_state')],
        ['Candidate State（研究候选）', record.get('candidate_state')],
        ['Transition Status', record.get('transition_status') or '账本未提供'],
        ['Transition Confirmed', record.get('transition_confirmed')],
        ['Accepted At', record.get('accepted_at')]])
    if record.get('accepted_state') is None:
        body += '\n\n**Accepted尚未初始化。规则中性不等于正式中性，候选S4不等于已接受S4；不能据此编造S5→S4迁移。**'
    body += '\n\n以下为已保存的候选与数据校验条件；“通过”不表示价格迁移触发已经确认。\n\n'
    body += table(['类别', '条件'], [
        *[['校验通过', r['condition']] for r in record.get('confirmed_conditions', [])],
        *[['尚缺', r['condition']] for r in record.get('missing_conditions', [])],
        *[['失效', r] for r in record.get('invalidation_conditions', [])]])
    add('reader_state', 'Accepted与Candidate：状态有没有迁移', body)

    engine = flow.get('scenario_engine', {})
    display = flow.get('scenario_display', {})
    scenarios = {r['id']: r for r in display.get('scenarios', [])}
    main_id = engine.get('main_scenario_id')
    body = ('以下是规则参考路径，**Score Share不是统计概率**。总Agent可以提出不同排序；'
            '主路径由规则选出，可能是区间、多头或空头，不强制把区间当主路径。\n\n')
    for sid, label in [('range', '区间路径'), ('bull', 'Bull 多头路径'), ('bear', 'Bear 空头路径')]:
        row = scenarios.get(sid)
        if not row:
            body += f'**{label}**：数据不足，路径未生成。\n\n'
            continue
        weight = row.get('display_weight_pct')
        body += f"**{label}{' / Main 主路径' if sid == main_id else ''}：{cell(row.get('name'))}**\n\n"
        body += table(['项目', '条件'], [
            ['Score Share', f'{weight}%' if weight is not None else '未校准或不可评分'],
            ['触发', row.get('trigger')], ['宏观与资金确认', row.get('macro_confirmation')],
            ['价格路径（现货区间）', row.get('price_path')], ['失效', row.get('invalidation')]]) + '\n\n'
    add('reader_scenarios', '三路径：主路径与多空备选', body.strip())

    ex = flow.get('execution', {})
    trends = {'bearish': '短窗向下', 'bullish': '短窗向上', 'range_or_mixed': '区间或混合'}
    pa = flow.get('price_action')
    body = ('4H / 1H过滤环境，15m观察确认。' if pa else '4H / 1H过滤环境，15m观察确认，5m辅助。') + '以下是研究观察卡，不是已确认买卖信号。\n\n'
    body += table(['周期', '已收盘时点（UTC）', '短窗环境', '数据状态'], [
        [r['timeframe'], r.get('close_time'), trends.get(r.get('trend'), r.get('trend')), r.get('status')]
        for r in ex.get('timeframe_features', [])])
    body += '\n\n' + cell(ex.get('reason')) + '\n\n'
    if pa:
        body += table(['PA周期', '确认摆动结构', '最新结构事件'], [
            [k, v.get('structure_trend') or v.get('reason'),
             '；'.join(f"{e['time']} {e['type']}" for e in v.get('events', [])[-3:]) or '无已确认事件']
            for k,v in pa['timeframes'].items()]) + '\n\n'
        body += '15m前序已知区间状态：\n\n' + table(['区间', '角色', 'PA状态'], [
            [f"{z['low']}—{z['high']}", z['role'], z['state']]
            for z in pa['timeframes'].get('15m', {}).get('zone_states', [])]) + '\n\n'
        cme = pa['cme_context']
        body += (f"CME报告日：{cell(cme.get('report_date'))}；滞后{cell(cme.get('trading_days'))}个交易日 / "
                 f"{cell(cme.get('calendar_days'))}个自然日；研究证据系数 **{cell(cme['weight_multiplier'])}**；"
                 f"用途 {cme['role']}。系数不是概率；GC期货Proxy不能直接当XAUUSD关键位。\n\n")
    body += '\n\n'.join(cell(ex.get(k)) for k in ('flat', 'long', 'short', 'event_rule'))
    body += '\n\n观察区间采用上方三路径的已计算zone；原短窗突破代理与确认摆动事件分列，二次入场和楔形未实现。'
    add('reader_execution', '执行环境卡：空仓、已有多单、已有空单', body)

    health = flow.get('core_source_health', {})
    body = f"整体数据质量：**{cell(flow['quality_gate'].get('data_quality'))}**。按来源观察日和发布周期检查，不能把采集成功等同于行情新鲜。\n\n"
    body += table(['数据源', '本地最新', '预期时效', '采集状态', '健康 / 原因'], [
        [r['source_key'], r.get('actual_latest_date'), r.get('expected_freshness'), r.get('collector_status'),
         f"{cell(r.get('source_health'))} / {cell(r.get('reason'))}"] for r in health.get('items', [])])
    cross = flow.get('cross_asset_freshness', {})
    if cross:
        body += '\n\n' + table(['分析能力', '状态'], list(cross.get('analysis_capability', {}).items()))
    failures = [r for r in flow['quality_gate'].get('checks', []) if not r['passed']]
    if failures:
        body += '\n\n未通过检查：\n\n' + table(['项目', '原因'], [[r['name'], r['reason']] for r in failures])
    body += '\n\n详细逐指标日期、来源和缺口见[数据护照与审计附件](audit_report.md)。缺失不填零，天然披露滞后不能解释今日即时资金流。'
    add('reader_health', '数据健康与分析边界', body)
    return cards
