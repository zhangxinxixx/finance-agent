"""Small deterministic tables alongside, rather than replacing, model prose."""


def _cell(value):
    return str(value if value is not None else '—').replace('|', '\\|').replace('\n', ' ')


def _number(value, digits=2):
    return '—' if value is None else f'{value:.{digits}f}'


def _reason(code):
    return {
        'available': '已覆盖', 'AVAILABLE': '可比', 'AVAILABLE_DELAYED': '可比（延迟行情）',
        'verified_market_distribution_missing': '未取得可核验市场分布',
        'cme_fedwatch_entitled_oauth_token_missing': 'CME数据访问未配置',
        'verified_current_target_midpoint_missing': '当前目标区间未核验',
        'meeting_coverage_missing': '未覆盖该期限',
        'stale_or_future_policy_distribution': '政策分布时点无效或过期',
        'verified_year_end_sep_missing': '尚无可核验年底SEP数据',
        'market_year_end_distribution_missing': '缺少年底市场分布',
        'market_observation_precedes_sep': '市场观测早于SEP发布',
        'invalid_or_incompatible_sep': 'SEP时间或统计口径不可比',
        'VERIFIED_ANCHOR_MISSING_OR_INVALID': '未取得可核验起点',
        'MISSING_ENDPOINT_OR_INTERIOR_BAR': '起止或中间行情缺失',
        'MISSING_SERIES_OR_COMMON_RESOLUTION': '标的缺失或行情粒度不同',
        'SESSION_NOT_STARTED': '该时段尚未开始',
        'ANCHOR_NOT_ON_BAR_GRID_OR_HISTORY_LIMIT': '起点不匹配K线或历史不足',
        'STALE_OR_UNKNOWN_SESSION': '数据过期或交易时段未确认',
        'STALE_CAPTURE_OR_SERIES': '行情采集已过期',
        'CROSS_DATE_CONTRACT_CONTINUITY_UNVERIFIED': '跨日合约连续性未核验',
    }.get(code, '数据尚不可用')


def policy_path_table(policy):
    path = policy.get('policy_path') or {}
    if not path:
        return ''
    labels = {'next_meeting': 'Next Meeting', 'year_end': 'Year-end', '3m': '3M', '6m': '6M', '12m': '12M'}
    lines = ['**Fed Policy Path（目标区间中点期望）**',
             '| 时点 | 对应会议 | Expected Policy Rate（%） | 1D（bp） | 1W（bp） | 1M（bp） | 覆盖 / 缺口 |',
             '|---|---|---:|---:|---:|---:|---|']
    for row in path['rows']:
        lines.append('| ' + ' | '.join([
            labels[row['horizon']], _cell(row['meeting_date']),
            _number(row['expected_target_midpoint_pct'], 3), _number(row['repricing_1d_bp']),
            _number(row['repricing_1w_bp']), _number(row.get('repricing_1m_bp')), _reason(row.get('reason') or row['status']),
        ]) + ' |')
    sep = path['market_vs_sep']
    lines.append('Market vs Fed SEP：' + (
        f"同年年底市场期望 − SEP中位数 = {_number(sep['market_minus_sep_bp'])}bp。"
        if sep['status'] == 'available' else '未取得可比结果（' + _reason(sep['reason']) + '）。'))
    lines.append('— 表示缺失，不是零；1D/1W只比较同来源、同会议的历史分布。SEP是政策判断，不是概率或承诺。')
    if policy.get('source_health'):
        h = policy['source_health']
        lines.append(f"FedWatch：{_cell(h.get('status'))}；源数据时点：{_cell(policy.get('observed_at'))}；snapshot_id：{_cell(policy.get('snapshot_id'))}。")
        r = policy.get('repricing', {})
        direction = {'hawkish': '偏鹰', 'dovish': '偏鸽', 'neutral': '中性'}.get(r.get('direction'), '不可用')
        lines.append(f"政策路径重定价：{direction}；强度：{_cell(r.get('strength'))}；规则：{_cell(r.get('rule_version'))}。这是市场隐含预期，不是美联储承诺；过期快照仅作历史参考。")
    return '\n'.join(lines)


def multi_horizon_table(cross):
    matrix = cross.get('chart_windows', {}).get('multi_horizon') or {}
    if not matrix:
        return ''
    lines = ['**多窗口跨资产比较（UTC，共同已完成K线）**',
             '| 窗口 / 组 | 起止 | Gold | 2Y（bp） | 10Y（bp） | DXY | WTI / Brent | 状态 / 缺口 |',
             '|---|---|---:|---:|---:|---:|---|---|']
    names = {'15m': '15m', '1h': '1H', '4h': '4H', 'london_session': 'London session',
             'us_pre_market': 'US pre-market', 'since_prior_close': 'Since prior close',
             'since_fomc': 'Since FOMC', 'fomc_15m': 'FOMC后15m'}
    for row in matrix['rows']:
        if row['group'] not in {'energy', 'policy'}:
            continue
        values = {c['symbol']: c for c in row['changes']} if row['aligned_comparison_allowed'] else {}
        def change(symbol):
            c = values.get(symbol, {})
            return _number(c.get('change_bp')) if 'change_bp' in c else (_number(c['change_pct']) + '%' if 'change_pct' in c else '—')
        lines.append('| ' + ' | '.join([
            names[row['horizon']] + ' / ' + ('能源' if row['group'] == 'energy' else '利率与美元'), _cell(row['window_start']) + ' → ' + _cell(row['window_end']),
            change('XAUUSD'), change('US02Y'), change('US10Y'), change('DXY'),
            change('WTI') + ' / ' + change('BRENT'), _reason(row.get('reason') or row['status']),
        ]) + ' |')
    lines.extend(matrix['limitations'])
    return '\n'.join(lines)
