"""Opt-in Gold reader v4. Format frozen evidence; never calculate indicators."""

from apps.analysis.agents.research_input import (
    detailed_report_profile, detailed_source_refs, DETAILED_REASONING_FIELDS,
)
from apps.analysis.agents.research_synthesis import validate_report_sections
from apps.renderer.markdown.daily_research import _links


_LABELS = {
    'technical': '历史价格与技术结构', 'price_anchor': '价格锚', 'market_session': '市场会话',
    'price': '价格', 'as_of': '观察截止', 'daily_close': '已收盘日线', 'daily_close_date': '日线观察日',
    'status': '状态', 'reason': '原因', 'value': '值', 'unit': '单位', 'symbol': '指标',
    'observations': '观察', 'observation_date': '观察日', 'previous_date': '前端观察日',
    'previous_value': '前端值', 'change': '已提供变化', 'weekly_change': '已提供周变化',
    'weekly_anchor_date': '周锚观察日', 'weekly_anchor_value': '周锚值',
    'report_date': '报告观察日', 'trade_date': '交易日', 'retrieved_at': '抓取时刻',
    'release_date': '发布日期', 'published_at': '发布时间', 'source_date': '来源观察日',
    'lineage_status': '血缘校验', 'frequency': '频率', 'comparison': '比较口径',
    'treasury': '美债证据', 'policy': '政策证据', 'growth': '增长', 'inflation': '通胀',
    'employment': '就业发布', 'labor': '劳动力', 'liquidity': '流动性', 'credit': '信用',
    'energy': '能源证据', 'response': '市场响应', 'residual': '残差证据',
    'windows': '比较窗口', 'window_start': '起始时刻', 'window_end': '结束时刻',
    'start_date': '起始日期', 'end_date': '结束日期', 'changes': '窗口变化',
    'aligned_comparison_allowed': '允许同步比较', 'change_bp': '变化bp', 'change_pct': '变化%',
    'diagnostics': '资金诊断', 'official_etf': '官方ETF', 'cot_reports': 'CFTC分口径报告',
    'shares_outstanding': '份额', 'gold_holdings_tonnes': '持金吨数', 'reported_on': '报告观察日',
    'projection': '期权事实摘要', 'walls': '期权墙', 'oi_walls': '持仓墙',
    'strike_metrics': '执行价事实', 'block_pnt_walls': 'Block/PNT集中',
    'strike': 'GC执行价', 'expiry': '到期月份', 'open_interest': 'OI持仓',
    'delta_oi': 'OI变化', 'oi_change': 'OI变化', 'volume': '成交量', 'block': 'Block成交',
    'pnt': 'PNT成交', 'delta': 'Delta', 'settlement': '结算价', 'version': '版本',
    'state_record': '权威状态记录', 'accepted_state': '正式Accepted', 'candidate_state': '研究Candidate',
    'previous_state': '前次Accepted', 'transition_confirmed': '迁移确认', 'transition_status': '迁移状态',
    'accepted_at': '接受时刻', 'confirmed_conditions': '已核验条件', 'missing_conditions': '尚缺条件',
    'invalidation_conditions': '失效条件', 'condition': '条件', 'key_levels': '关键位',
    'execution_zones': '现货观察区域', 'zones': '区域', 'instrument': '市场标的',
    'role': '角色', 'previous_role': '前次角色', 'activation': '确认条件', 'invalidation': '失效条件',
    'scenario_display': '规则路径', 'scenario_engine': '规则排序', 'scenarios': '情景',
    'display_weight_pct': '规则份额%（非概率）', 'main_scenario_id': '规则主路径',
    'trigger': '触发', 'price_path': '价格路径', 'macro_confirmation': '宏观确认',
    'official_calendar': '官方事件日历', 'events': '事件', 'title': '名称', 'timezone': '原时区',
    'execution': '条件观察', 'price_action': '价格行为', 'timeframes': '周期结构',
    'timeframe_features': '已收盘周期', 'timeframe': '周期', 'close_time': '收盘时刻',
    'flat': '空仓观察', 'long': '已有多单观察', 'short': '已有空单观察',
    'source_health': '来源健康', 'quality_gate': '已保存数据门禁', 'publish_allowed': '允许发布',
    'data_quality': '数据质量', 'checks': '检查项', 'passed': '通过',
    'delta_vs_previous': '前报告接续', 'previous_snapshot_id': '前报告快照身份',
    'previous_analysis_time': '前报告截止', 'current_date': '本次观察日',
    'current': '本次值', 'previous': '前次值', 'change_kind': '变化性质',
    'new_intraday_confirmation_allowed': '允许盘中新确认',
}

_LABELS.update({
    'record_name': '记录口径', 'macro': '宏观确认', 'funds': '资金确认',
    'region': '观察区域', 'window': '观察窗口', 'interpretation': '含义',
    'limitations': '限制', 'projection_note': '展示范围', 'daily_instrument': '日线市场口径',
    'live_confirmation_allowed': '允许实时确认', 'ticker': '标的',
    'start_close': '起点收盘', 'end_close': '终点收盘', 'front_contract': '前月合约',
    'reference_period': '参考期', 'current_month': '本次参考月', 'current_value': '本次值',
    'previous_month': '前次参考月', 'monthly_change': '月变化', 'monthly_change_pct': '月变化%',
    'new_jobs_thousands': '新增就业千人', 'unavailable_reason': '缺失原因',
    'vintage_status': '发布版本', 'wage_mom': '工资环比', 'wage_yoy': '工资同比',
    'classification': '分类', 'classification_status': '分类确认', 'primary_report_type': '主要报告口径',
    'managed_money_long_delta': '管理资金多仓变化', 'managed_money_short_delta': '管理资金空仓变化',
    'open_interest_delta': '总OI变化', 'price_attribution': '价格归因已确认',
    'long': '多仓', 'short': '空仓位', 'net': '净仓',
    'managed_money_long': '管理资金多仓', 'managed_money_short': '管理资金空仓',
    'managed_money_net': '管理资金净仓', 'noncommercial_long': '非商业多仓',
    'noncommercial_short': '非商业空仓', 'noncommercial_net': '非商业净仓',
    'oi': 'OI', 'oi_change': 'OI变化', 'side': '看涨/看跌', 'wall_type': '墙类型',
    'expiry_date': '到期日', 'expiry_estimated': '估算到期',
    'level_status': '关键位状态', 'zone_status': '区域状态', 'eligible_for_target': '可作目标参考',
    'display_label': '显示区间', 'display_lower': '显示下界', 'display_upper': '显示上界',
    'missing_inputs': '缺失输入', 'is_probability': '是否统计概率', 'weight_semantics': '权重口径',
    'price_path': '价格路径', 'macro_confirmation': '宏观确认',
    'trigger_permission': '触发权限', 'event_rule': '事件观察规则',
    'unimplemented_patterns': '尚未实现的形态', 'reason': '原因',
    'event_count': '事件数', 'pivot_count': '已确认摆动数',
    'source_key': '来源项目', 'source_health': '来源健康', 'actual_latest_date': '最近实际观察日',
    'expected_release_time': '预期发布时间', 'strong_direction_allowed': '允许强方向判断',
    'source_snapshot_id': '输入快照身份', 'state_id': '状态身份', 'predecessor_id': '前序身份',
    'calculation_version': '计算版本', 'namespace': '状态命名空间', 'schema_version': '契约版本',
    'source': '来源核验', 'semantics': '指标含义', 'expiry_window': '所选到期窗口',
    'reconciliation': '版本对账', 'coordinate_policy': '市场坐标与定价边界',
    'auction_supply': '拍卖与发行证据', 'term_premium': '期限溢价模型',
    'label': '指标名称', 'method': '计算口径', 'scope': '覆盖范围',
    'selected_expiries': '所选月份', 'selected_open_interest': '所选OI',
    'eligible_open_interest': '完整合格链OI', 'open_interest_coverage': 'OI覆盖比例',
    'dealer_position_unknown': '做市商仓位方向未知', 'comparison_available': '可进行版本比较',
    'changed': '是否修订', 'xauusd_mapping': '映射现货条件', 'model': '定价模型',
    'forward_source': '期货远期锚口径', 'call_oi_walls': '看涨侧OI主要观察行',
    'put_oi_walls': '看跌侧OI主要观察行', 'block_pnt_walls': 'Block/PNT集中行',
    'absolute_gamma_exposure': '模型Gamma绝对暴露', 'net_gex': 'OI符号GEX代理',
    'omitted_level_count': '未展示集中记录数',
})


def label(path):
    import re
    return ' / '.join(_LABELS.get(part, part) for part in re.sub(r'\[(\d+)\]', r'.记录\1', path).split('.'))


def cell(value):
    if value is None:
        return '未取得'
    if value is True:
        return '是'
    if value is False:
        return '否'
    if isinstance(value, dict):
        # Structured evidence has dedicated tables; never dump internal objects into cells.
        scalars = [label(k) + ': ' + cell(v) for k, v in value.items() if not isinstance(v, (dict, list))]
        return '；'.join(scalars) or '结构化材料见审计附件'
    if isinstance(value, list):
        return '；'.join(cell(v) for v in value) if all(not isinstance(v, (dict, list)) for v in value) else '结构化记录见审计附件'
    # No rounding: supplied observations remain exact, including zero.
    return str(value).replace('|', r'\|').replace('\n', '<br>')


def table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(headers) + ' |',
                      '|' + '---|' * len(headers),
                      *['| ' + ' | '.join(cell(v) for v in row) + ' |' for row in rows]])


def record_table(records, fields, *, name=None):
    """One supplied record per row; never recursively flatten arbitrary evidence."""
    if isinstance(records, dict):
        records = [dict(record_name=k, **v) for k, v in records.items() if isinstance(v, dict)]
        fields = ('record_name', *fields)
    records = [r for r in records or [] if isinstance(r, dict)]
    if not records:
        return ''
    missing = [k for k in fields if not any(r.get(k) is not None for r in records)]
    fields = tuple(k for k in fields if k not in missing)
    # These saved field aliases have the same meaning. A populated OI column
    # must not be accompanied by a claim that its unused alias is missing.
    aliases = {'oi': 'open_interest', 'open_interest': 'oi',
               'oi_change': 'delta_oi', 'delta_oi': 'oi_change'}
    missing = [k for k in missing if aliases.get(k) not in fields]
    body = table([label(k) for k in fields], [[r.get(k) for k in fields] for r in records])
    if missing:
        body += '\n\n本组未保存：' + '、'.join(label(k) for k in missing) + '。缺失不视为零。'
    return ('**' + label(name) + '**\n\n' if name else '') + body


def summary_table(record, fields, *, name=None):
    if not isinstance(record, dict):
        return ''
    rows = [[label(k), record[k]] for k in fields if k in record]
    return (('**' + label(name) + '**\n\n' if name else '') + table(['字段', '保存值 / 限制'], rows)) if rows else ''


_OBSERVATION = ('symbol', 'value', 'unit', 'observation_date', 'previous_date',
                'previous_value', 'change', 'weekly_anchor_date', 'weekly_anchor_value',
                'weekly_change', 'status')
_LEVEL = ('instrument', 'price', 'role', 'previous_role', 'source_date', 'expiry',
          'expiry_date', 'status', 'level_status', 'activation', 'invalidation', 'eligible_for_target')
_STATUS = ('status', 'reason', 'as_of', 'interpretation', 'limitations', 'projection_note')


def curated_evidence(key, evidence):
    """Topic-specific, deliberately finite table schemas for reader consumption."""
    blocks = []
    def records(value, fields, name):
        blocks.append(record_table(value, fields, name=name))
    def summary(value, fields, name):
        blocks.append(summary_table(value, fields, name=name))
    records(evidence.get('observations'), _OBSERVATION, '本模块实际观察')
    if key == 'market_evolution':
        summary(evidence.get('technical'), ('price', 'as_of', 'status', 'reason'), '历史价格')
        summary(evidence.get('price_anchor'), ('price', 'price_time', 'daily_close', 'daily_close_date',
                'daily_instrument', 'instrument_type', 'status', 'reason', 'live_confirmation_allowed'), '历史 / 实时锚')
        windows = evidence.get('completed_windows') or {}
        records(windows.get('windows'), ('group', 'window_start', 'window_end', 'status',
                'aligned_comparison_allowed', 'reason'), '已收盘窗口')
        for w in windows.get('windows') or []:
            records(w.get('changes'), ('ticker', 'start_close', 'end_close', 'change_pct', 'change_bp',
                    'unit', 'front_contract'), str(w.get('group')) + '：' + str(w.get('window_start')) + ' → ' + str(w.get('window_end')))
    if key in {'growth_inflation', 'labor'}:
        for field in ('growth', 'inflation', 'labor'):
            item = evidence.get(field) or {}
            records(item.get('facts'), _OBSERVATION + ('reference_period', 'release_date', 'frequency'), field)
            records(item.get('series'), _OBSERVATION + ('reference_period', 'release_date'), field)
            summary(item, _STATUS + ('inflation_type', 'value_semantics'), field + '边界')
        employment = evidence.get('employment') or {}
        records(employment.get('metrics'), ('label', 'current_month', 'current_value', 'previous_month',
                'previous_value', 'monthly_change', 'monthly_change_pct', 'new_jobs_thousands',
                'unit', 'status', 'unavailable_reason'), '就业和工资')
        summary(employment, ('as_of', 'release_date', 'vintage_status', 'new_jobs_thousands', 'wage_mom', 'wage_yoy'), '发布口径')
    if key in {'real_rates', 'curve_policy', 'treasury_turn'}:
        treasury = evidence.get('treasury') or {}
        records(treasury.get('curves'), _OBSERVATION, '曲线')
        records(treasury.get('windows'), ('status', 'reason'), '同步分解窗口')
        for field in ('auction_supply', 'term_premium'):
            summary(treasury.get(field), _STATUS + ('value', 'observation_date', 'model'), field)
        policy = evidence.get('policy') or {}
        summary(policy, _STATUS + ('observed_at', 'confirmation'), '政策路径')
        records(policy.get('meetings'), ('meeting_date', 'status', 'expected_rate', 'prob_below_current_target'), '会议定价')
        summary(evidence.get('turning_evidence'), _STATUS + ('support', 'opposition', 'upgrade', 'invalidation'), '拐点证据')
    if key == 'oil':
        energy = evidence.get('energy') or {}
        summary(energy, ('dominant_channel', 'analysis_capability', 'window_comparison_capability', 'unavailable'), '能源渠道')
        records(energy.get('observations'), _OBSERVATION + ('instrument_type', 'contract_code'), '油价口径')
    if key == 'flows':
        diagnostics = evidence.get('diagnostics') or {}
        summary(diagnostics, _STATUS + ('classification', 'classification_status', 'primary_report_type'), '资金诊断')
        records(diagnostics.get('position_contraction'), ('managed_money_long_delta', 'managed_money_short_delta',
                'open_interest_delta', 'classification', 'status', 'price_attribution'), '仓位变化：不同口径分开')
        cot_reports = evidence.get('cot_reports') or {}
        summary(cot_reports, _STATUS, 'CFTC覆盖')
        for name, report in cot_reports.items():
            if not isinstance(report, dict):
                continue
            summary(report, ('report_type', 'report_date', 'previous_report_date', 'status', 'reason'), 'CFTC ' + name)
            summary(report.get('open_interest'), ('value', 'previous', 'delta', 'unit'), name + ' OI')
            for group in ('managed_money', 'producer_merchant', 'swap_dealers', 'other_reportables'):
                records((report.get(group) or {}), ('long', 'short', 'net', 'unit'), name + ' ' + group)
            for field in ('current', 'previous', 'delta'):
                summary(report.get(field), ('managed_money_long', 'managed_money_short', 'managed_money_net',
                        'noncommercial_long', 'noncommercial_short', 'noncommercial_net', 'open_interest'), name + ' ' + field)
        etf = evidence.get('official_etf') or {}
        summary(etf, ('fund_name', 'fund_scope', 'status', 'missing_data', 'shares_outstanding', 'shares_reported_on',
                'shares_previous_value', 'shares_previous_reported_on', 'shares_delta', 'shares_weekly_anchor_value',
                'shares_weekly_anchor_date', 'shares_weekly_delta', 'gold_holdings_tonnes', 'gold_holdings_tonnes_reported_on',
                'gold_holdings_tonnes_previous_value', 'gold_holdings_tonnes_previous_reported_on', 'gold_holdings_tonnes_delta',
                'gold_holdings_tonnes_weekly_anchor_value', 'gold_holdings_tonnes_weekly_anchor_date', 'gold_holdings_tonnes_weekly_delta'), 'ETF份额与吨位')
    if key == 'options':
        projection = evidence.get('projection') or {}
        summary(projection, ('status', 'reason', 'trade_date'), 'CME截面')
        for field in ('source', 'semantics', 'expiry_window', 'reconciliation', 'coordinate_policy'):
            summary(projection.get(field), ('status', 'version', 'report_date', 'selected_expiries',
                    'selected_open_interest', 'eligible_open_interest', 'open_interest_coverage',
                    'label', 'method', 'scope', 'dealer_position_unknown', 'interpretation',
                    'comparison_available', 'changed', 'instrument', 'xauusd_mapping', 'model', 'forward_source'), field)
        concentration = projection.get('concentration') or {}
        records(concentration.get('levels'), ('expiry', 'strike', 'open_interest',
                'absolute_gamma_exposure', 'net_gex'), '所选窗口OI/Gamma集中记录（独立于墙候选）')
        summary(concentration, ('scope', 'selected_expiries', 'omitted_level_count', 'limitations'),
                '集中记录覆盖与边界')
        strikes = evidence.get('strike_metrics') or {}
        records(strikes.get('rows'), ('strike', 'expiry', 'expiry_date', 'side', 'open_interest', 'oi',
                'oi_change', 'delta_oi', 'delta', 'settlement', 'volume', 'block', 'pnt', 'trade_date'), '逐Strike保存事实')
        summary(strikes, ('status', 'omitted_count', 'projection_note', 'audit_ref'), '全链投影边界')
        for name, rows in (evidence.get('walls') or {}).items():
            if isinstance(rows, list):
                records(rows, ('strike', 'expiry', 'side', 'oi', 'open_interest', 'oi_change', 'delta_oi',
                        'delta', 'volume', 'block', 'pnt', 'settlement', 'wall_type'), name)
            else:
                blocks.append(label(name) + '：' + cell(rows))
    if key == 'gold_response':
        for field in ('response', 'residual'):
            summary(evidence.get(field), _STATUS + ('condition', 'channel_check', 'research_question'), field)
    if key == 'state':
        state = evidence.get('state_record') or {}
        summary(state, ('accepted_state', 'previous_state', 'candidate_state', 'candidate_label', 'accepted_at',
                'transition_status', 'transition_confirmed', 'rule_validation', 'schema_version', 'calculation_version',
                'namespace', 'source_snapshot_id', 'state_id', 'predecessor_id'), '权威状态')
        for field in ('confirmed_conditions', 'missing_conditions', 'trigger_conditions', 'invalidation_conditions'):
            records(state.get(field), ('id', 'condition', 'passed'), field)
    if key == 'levels':
        levels = evidence.get('key_levels') or []
        spot = [r for r in levels if str(r.get('instrument', '')).lower() in {'xauusd spot', 'xauusd_spot', 'spot'}]
        records(spot, _LEVEL, '现货坐标')
        records([r for r in levels if r not in spot], _LEVEL, 'GC期货 / 其他独立坐标（不转换现货）')
        zones = evidence.get('execution_zones') or {}
        records(zones.get('zones'), ('instrument', 'display_label', 'display_lower', 'display_upper', 'role',
                'source_date', 'level_status', 'zone_status', 'activation', 'invalidation'), '现货观察区域')
        summary(zones, ('status', 'missing_inputs', 'omitted_zone_count', 'projection_note'), '区域边界')
    if key == 'scenarios':
        display = evidence.get('scenario_display') or {}
        records(display.get('scenarios'), ('id', 'name', 'priority', 'display_weight_pct', 'instrument',
                'price_path', 'macro_confirmation', 'trigger', 'invalidation', 'status'), '保存的规则路径（非概率）')
        summary(display, ('status', 'is_probability', 'weight_semantics', 'note', 'reason'), '权重口径')
        summary(evidence.get('scenario_engine'), ('main_scenario_id', 'signal_status', 'semantics'), '规则排序')
    if key == 'calendar':
        calendar = evidence.get('official_calendar') or {}
        summary(calendar, ('as_of', 'status', 'time_precision', 'window_start_date', 'window_end_date'), '日历精度')
        records(calendar.get('events'), ('title', 'start_date', 'end_date', 'date_text', 'event_status', 'verification_status', 'time_status', 'date', 'release_date', 'release_datetime', 'time', 'timezone',
                'release_timezone', 'time_precision', 'status', 'consensus', 'source_url'), '官方事件')
    if key == 'observation':
        execution = evidence.get('execution') or {}
        summary(execution, ('status', 'reason', 'flat', 'long', 'short', 'event_rule', 'trigger_permission',
                'unimplemented_patterns'), '持仓观察卡')
        records(execution.get('timeframe_features'), ('timeframe', 'close_time', 'status', 'trend', 'reason'), '已收盘周期')
        records((evidence.get('price_action') or {}).get('timeframes'), ('status', 'reason', 'event_count', 'pivot_count'), '价格行为')
        summary(evidence.get('market_session'), ('state', 'as_of', 'reason', 'new_intraday_confirmation_allowed'), '会话')
    if key == 'risks':
        records((evidence.get('source_health') or {}).get('items'), ('source_key', 'source_health', 'actual_latest_date',
                'expected_release_time', 'reason'), '来源健康')
        gate = evidence.get('quality_gate') or {}
        summary(gate, ('data_quality', 'publish_allowed', 'strong_direction_allowed'), '保存门禁')
        records(gate.get('checks'), ('id', 'passed', 'reason'), '门禁检查')
    if key == 'continuity':
        delta = evidence.get('delta_vs_previous') or {}
        summary(delta, ('status', 'reason', 'previous_snapshot_id', 'previous_analysis_time', 'unchanged_symbols',
                'omitted_empty_symbols'), '前报告身份')
        records(delta.get('changed_or_noncomparable_rows'), ('symbol', 'previous_date', 'previous', 'current_date',
                'current', 'delta', 'unit', 'change_kind', 'reason'), '接续比较')
    return '\n\n'.join(b for b in blocks if b)


def concise_sections(snapshot, synthesis):
    """Reader summary; full reasoning, exact comparisons and lineage stay in audit."""
    flow = snapshot['gold_workflow']
    analysis = synthesis.get('analysis') or {}
    validation = snapshot.get('input_validation') or {}
    review = synthesis.get('macro_review') or {}
    sections = []

    def add(key, title, body, category='external_opinion'):
        sections.append({'section_id': key, 'title': title, 'body': body,
                         'status': 'partial' if validation.get('status') == 'partial' else 'ok',
                         'source_refs': [], 'data_category': category})

    judgment = analysis.get('dominant_factor') or '研究未完成'
    counter = analysis.get('counter_evidence') or []
    if counter:
        judgment += '\n\n主要反证：\n' + '\n'.join('- ' + item for item in counter[:3])
    add('research_judgment', '核心判断', judgment)

    gate = flow.get('quality_gate') or {}
    state = flow.get('state_record') or {}
    status_labels = {'valid': '通过', 'partial': '部分可用', 'blocked': '阻断',
                     'success': '成功', 'pass': '通过', 'failed': '失败', 'unavailable': '不可用'}
    def status_label(value):
        return status_labels.get(value, '待核验')
    status = table(['项目', '状态'], [
        ['输入数据', status_label(validation.get('status'))],
        ['模型生成 / 因果审阅', status_label(synthesis.get('status')) + ' / ' + status_label(review.get('status'))],
        ['发布条件', '通过' if gate.get('publish_allowed') is True else '未通过'],
        ['正式状态', state.get('accepted_state') or '尚未初始化'],
    ])
    missing = [key for key, item in (validation.get('domains') or {}).items() if item.get('status') == 'unavailable']
    if missing:
        domain_labels = {'macro': '宏观', 'growth': '增长', 'employment': '就业', 'inflation': '通胀',
                         'spot': '现货', 'options': '期权', 'positioning': '持仓'}
        status += '\n\n数据缺口：' + '、'.join(domain_labels.get(key, key) for key in missing) + '。相关判断保持待确认。'
    add('research_status', '数据与分析状态', status, 'confirmed_data')

    wanted = {'XAUUSD_DAILY', 'US02Y', 'US10Y', 'REAL10Y', 'BREAKEVEN_10Y', 'DXY', 'BROAD_DOLLAR', 'HY_OAS'}
    rows = [row for row in snapshot.get('daily_research', {}).get('passport', []) if row.get('symbol') in wanted]
    add('market_snapshot', '关键证据', table(['指标', '值', '单位', '观察日', '状态'], [
        [row.get('label') or row.get('symbol'), row.get('value'), row.get('unit'), row.get('observation_date'), row.get('status')]
        for row in rows
    ]) + '\n\n盘中与日终数据按各自观察时间使用；GC 期货与现货坐标分开。', 'confirmed_data')

    paths = ((analysis.get('report_sections') or {}).get('scenarios') or {}).get('paths') or {}
    if paths:
        add('conditional_paths', '后续观察条件', table(['路径', '触发条件', '失效条件', '观察窗口'], [
            [title, paths[name].get('trigger'), paths[name].get('invalidation'), paths[name].get('window')]
            for name, title in [('main', '主路径'), ('up', '上行'), ('down', '下行')] if name in paths
        ]))
    add('research_sources', '溯源', '完整事实、来源、比较窗口与逐模块推理见[数据与审计附件](audit_report.md)。\n\n'
        '输入快照：' + cell(snapshot.get('snapshot_id')), 'confirmed_data')
    return sections


def detailed_sections(snapshot, synthesis):
    profile = detailed_report_profile(snapshot)
    analysis = synthesis.get('analysis') or {}
    model = analysis.get('report_sections')
    allowed = {'detailed:' + key for key in profile['modules']}
    allowed.update(synthesis.get('evidence_catalog_ids') or [])
    try:
        validate_report_sections(model, allowed_ids=allowed)
        valid = synthesis.get('status') == 'success'
    except ValueError:
        valid = False
    sections = []

    def add(key, title, body, *, refs=None, category='system_inference', status='partial'):
        sections.append({'section_id': key, 'title': title, 'body': body,
                         'status': status, 'source_refs': refs or [], 'data_category': category})

    if valid:
        lead = analysis.get('dominant_factor') or model['gold_response']['judgment']
        counter = analysis.get('counter_evidence') or []
        if counter:
            lead += '\n\n**主要反证**\n\n' + '\n'.join('- ' + value for value in counter)
        add('research_judgment', '核心判断与改变判断的条件', lead,
            refs=detailed_source_refs(profile['passport']), category='external_opinion')

    coverage = table(['维度', '结果'], [
        ['模型生成', synthesis.get('status', '未完成')],
        ['结构化正文覆盖', '完整' if valid else '待完成 / 契约未通过'],
        ['分析内容质量', '仍须逐主张审阅；结构合规不证明推理正确'],
        ['金融证据', '按模块与实际端点分别列示'],
        ['宏观因果审阅', (synthesis.get('macro_review') or {}).get('status', '未完成')],
        ['发布门禁', '沿用快照保存值（详见风险表）；正文不授予发布许可'],
    ])
    add('detailed_coverage', '研究覆盖与验收边界', coverage)
    passport = profile['passport']
    passport_rows = []
    for row in passport:
        refs = row.get('source_refs') or []
        # Each source gets its own date row; collection does not overwrite it.
        for ref in refs or [{}]:
            passport_rows.append([
                row.get('label') or row.get('symbol'), row.get('value'), row.get('unit'),
                row.get('observation_date'),
                ref.get('observation_date') or ref.get('date') or ref.get('report_date'),
                ref.get('release_date') or ref.get('published_at'),
                ref.get('retrieved_at') or row.get('retrieved_at'),
                row.get('instrument_type') or ref.get('instrument_type'),
                row.get('contract_code') or ref.get('contract_code'),
                row.get('status'), _links([ref]) if ref else '未提供',
            ])
    body = f"分析截止：{cell(profile['cutoff'])}。每个来源保留自己的观察日、发布日、抓取时间和标的口径；旧观察不冒称最新交易。\n\n"
    body += table(['指标', '值', '单位', '指标观察日', '来源观察日', '发布日', '抓取时间', '市场口径', '合约', '状态', '来源'], passport_rows)
    body += '\n\n' + curated_evidence('market_evolution', profile['modules']['market_evolution']['evidence'])
    add('detailed_passport', '数据护照与历史 / 实时锚点', body,
        refs=detailed_source_refs(passport), category='confirmed_data')
    for key, title in [('weekly_comparisons', '周度市场比较：各指标实际起止日'),
                       ('daily_comparisons', '前次观察比较：日频与周均分开')]:
        body = table(['指标', '起点日 / 值', '终点日 / 值', '已提供变化 / 单位', '比较校验', '范围来源'], [
            [row['symbol'], f"{cell(row['start_date'])} / {cell(row['start_value'])}",
             f"{cell(row['end_date'])} / {cell(row['end_value'])}",
             f"{cell(row['supplied_change'])} / {cell(row['change_unit'])}" if row['comparison_allowed'] else '不作比较（缺口见校验）',
             '端点与lineage通过' if row['comparison_allowed'] else '；'.join(row['constraints']),
             _links(row['source_refs']) or '未提供'] for row in profile[key]])
        body += ('\n\n变化仅格式化features已给值，不计算缺端点、不按报告日假设周五锚。'
                 '利率原单位若为%则变化是百分点（0.01百分点=1bp）；只有上游明确提供bp才按bp显示。'
                 '周均和日频不混算；异步组件不得用于同窗口分解。')
        add('detailed_' + key, title, body, refs=detailed_source_refs(profile[key]))
    labels = dict(zip(DETAILED_REASONING_FIELDS, ('事实与时间窗口', '传导机制', '市场响应', '竞争解释', '研究判断', '反证 / 升级 / 失效')))
    for key, module in profile['modules'].items():
        body = ''
        if valid:
            entry = model[key]
            body += '\n\n'.join('**' + labels[field] + '**\n\n' + entry[field]
                                  for field in DETAILED_REASONING_FIELDS)
            if entry['pending']:
                body += '\n\n**尚不能确认的结论**\n\n' + '\n'.join('- ' + p for p in entry['pending'])
            if key in {'scenarios', 'observation'}:
                group = entry['paths' if key == 'scenarios' else 'cards']
                titles = {'main': '主路径', 'up': '上行路径', 'down': '下行路径',
                          'flat': '空仓', 'long': '已有多单', 'short': '已有空单'}
                body += '\n\n' + table(['路径 / 持仓', '条件项目', '模型条件（external_opinion）'],
                    [[titles[name], label(field), value] for name, row in group.items() for field, value in row.items()])
        else:
            body += '结构化研究正文尚未通过契约，保留以下已保存证据，等待完成研究；不据此生成新方向。'
        body += '\n\n**局部证据边界**：' + '；'.join(module['constraints'])
        body += '\n\n证据可用性：' + module['availability'] + '（材料存在不代表完整因果已证实）。'
        if key == 'state' and not (module['evidence'].get('state_record') or {}).get('accepted_state'):
            body += '\n\n**Accepted尚未初始化；空值保持空，不接受研究候选迁移。**'
        facts = curated_evidence(key, module['evidence'])
        if facts:
            body += '\n\n**已保存的确定性证据**\n\n' + facts
        else:
            body += '\n\n本范围未保存独立证据；需补充上述依赖材料后再确认。'
        body += '\n\n范围来源：' + (_links(module['source_refs']) or '未提供独立范围来源；详见审计附件')
        # Lifecycle coordinates stay separate even when model challenges ranking.
        refs = list(module['source_refs'])
        if valid:
            for cited in model[key]['evidence_ids']:
                scope = profile['modules'].get(cited.removeprefix('detailed:')) if cited.startswith('detailed:') else None
                if scope:
                    refs.extend(r for r in scope['source_refs'] if r not in refs)
        add('detailed_' + key, module['title'], body, refs=refs,
            category='external_opinion' if valid else 'system_inference')
    add('detailed_sources', '溯源与复盘入口',
        '上述正文是external_opinion；数据表来自冻结快照，不能写回Accepted、规则权重或发布门禁。'
        '\n\n[完整原始血缘与审计附件](audit_report.md)；输入快照：' + cell(snapshot.get('snapshot_id')))
    return sections
