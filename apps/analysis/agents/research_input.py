"""Evidence projection shared by research, synthesis and review.

No character slicing: observations and qualifications are kept whole. Archive
plumbing is omitted explicitly; repeated sources are referenced once.
"""
import json
import re
from copy import deepcopy
from collections import Counter
from hashlib import sha256
from datetime import date, datetime
from math import isfinite
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


RESEARCH_INPUT_CONTRACT_VERSION = 'research_input.v3'
SYNTHESIS_INPUT_MAX_CHARS = 200000

# Additive opt-in contract: old projections and frozen readers remain unchanged.
DETAILED_PROFILE_VERSION = 'gold_reader.v4'
RESEARCH_PRESENTATION_VERSION = 'gold_reader.research.v1'
DETAILED_TOPICS = {
    'market_evolution': '行情演化与事件先后',
    'growth_inflation': '增长、通胀与政策约束',
    'labor': '就业、工资与修订',
    'real_rates': '实际利率与盈亏平衡通胀率',
    'curve_policy': '曲线、政策与期限溢价',
    'dollar': '美元与计价压力',
    'liquidity': '流动性数量与融资价格',
    'credit': '信用与风险偏好',
    'oil': '原油与地缘传导',
    'flows': 'ETF配置与CFTC杠杆仓位',
    'options': 'GC期权结构与到期生命周期',
    'treasury_turn': '美债拐点的支持、反对与升级',
    'gold_response': '黄金响应：定性背离与统计残差',
    'state': '研究候选与正式状态',
    'levels': '关键位生命周期',
    'scenarios': '主、上行、下行条件路径',
    'calendar': '下一阶段事件日历',
    'observation': '4H/1H/15m观察卡',
    'risks': '风险与证据缺口',
    'continuity': '跨报告接续与来源归属',
}
DETAILED_REASONING_FIELDS = ('facts', 'transmission', 'response', 'alternatives',
                             'judgment', 'falsification')


def detailed_source_refs(value):
    """Collect only references beneath this evidence scope, without mutation."""
    result = {}

    def walk(item):
        if isinstance(item, dict):
            for key, child in item.items():
                if key == 'source_ref' and isinstance(child, dict):
                    result[encode(child)] = deepcopy(child)
                elif key == 'source_refs':
                    refs = child.values() if isinstance(child, dict) else child if isinstance(child, list) else []
                    for ref in refs:
                        if isinstance(ref, dict):
                            result[encode(ref)] = deepcopy(ref)
                else:
                    walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)
    walk(value)
    return list(result.values())


def _detailed_date(value):
    try:
        if not isinstance(value, str):
            return None
        return datetime.fromisoformat(value.replace('Z', '+00:00')).date() if 'T' in value else date.fromisoformat(value)
    except ValueError:
        return None


def _detailed_numeric(value):
    return type(value) in (int, float) and isfinite(value)


def detailed_comparison(row, *, cutoff, weekly=True):
    """Validate supplied endpoints, never compute a return or reconstruct one."""
    left_date = row.get('weekly_anchor_date' if weekly else 'previous_date')
    left = row.get('weekly_anchor_value' if weekly else 'previous_value')
    change = row.get('weekly_change' if weekly else 'change')
    start, end, upper = map(_detailed_date, (left_date, row.get('observation_date'), cutoff))
    reasons = []
    if start is None or end is None or upper is None:
        reasons.append('missing_or_invalid_dates')
    elif not start < end <= upper:
        reasons.append('unordered_or_future_endpoints')
    if not all(_detailed_numeric(x) for x in (left, row.get('value'), change)):
        reasons.append('missing_or_invalid_numeric_endpoint_or_change')
    if row.get('status') in {'unavailable', 'invalid', 'blocked', 'failed'} or row.get('lineage_status') != 'verified':
        reasons.append('unverified_observation_or_lineage')
    if not row.get('source_refs'):
        reasons.append('missing_source_refs')
    for ref in row.get('source_refs') or []:
        if not isinstance(ref, dict):
            reasons.append('invalid_source_ref')
            break
        explicit_date = ref.get('observation_date') or ref.get('date')
        if explicit_date is not None and _detailed_date(explicit_date) != end:
            reasons.append('source_observation_date_mismatch')
            break
    current_source = row.get('current_source')
    anchor_source = row.get('weekly_anchor_source' if weekly else 'previous_source')
    if current_source is not None or anchor_source is not None:
        if not isinstance(current_source, dict) or not isinstance(anchor_source, dict):
            reasons.append('endpoint_source_missing')
        elif any(current_source.get(k) != anchor_source.get(k) for k in
                 ('source', 'source_url', 'symbol', 'instrument_type', 'contract_code', 'unit')):
            reasons.append('endpoint_source_or_contract_changed')
    # Component windows must match; asynchronous rate decompositions fail closed.
    for component in row.get('components') or []:
        if not isinstance(component, dict) or any(
            component.get(key) != row.get(key)
            for key in ('observation_date', 'weekly_anchor_date' if weekly else 'previous_date')
        ):
            reasons.append('component_window_not_verified')
            break
    return {'start_date': left_date, 'start_value': left,
            'end_date': row.get('observation_date'), 'end_value': row.get('value'),
            'supplied_change': change, 'unit': row.get('unit'),
            'change_unit': row.get('change_unit') or row.get('unit'),
            'comparison_allowed': not reasons, 'constraints': reasons,
            'source_refs': deepcopy(row.get('source_refs') or [])}


def _detailed_clean(value):
    """Drop transport/audit duplication, preserving whole observations and prose."""
    if isinstance(value, list):
        return [_detailed_clean(v) for v in value]
    if not isinstance(value, dict):
        return value
    return {k: _detailed_clean(v) for k, v in value.items()
            if k not in ARCHIVE_KEYS | {'source_refs', 'source_ref', 'raw_scenarios'}}


def _detailed_refs(value):
    # Source identity and dates remain local; archive hashes/HTTP plumbing are audit-only.
    refs = [{k: v for k, v in ref.items() if k in SOURCE_KEYS}
            for ref in detailed_source_refs(value)]
    return list({encode(ref): ref for ref in refs if ref}.values())


def _detailed_levels(flow):
    keys = {'price', 'instrument', 'coordinate', 'role', 'previous_role', 'source_date',
            'source_type', 'status', 'level_status', 'expiry', 'expiry_date', 'expiry_estimated',
            'activation', 'invalidation', 'eligible_for_target', 'verification_status'}
    return [{k: v for k, v in row.items() if k in keys}
            for row in flow.get('key_levels') or [] if isinstance(row, dict)]


def _detailed_walls(data):
    """Select saved OI observations for display, without calculating new walls."""
    result = {}
    keys = {'strike', 'expiry', 'side', 'oi', 'open_interest', 'oi_change', 'delta_oi',
            'delta', 'volume', 'block', 'pnt', 'settlement', 'wall_type', 'gex', 'net_gex'}
    for name, rows in (data.get('walls') or {}).items():
        if not isinstance(rows, list):
            continue
        if name == 'block_pnt_walls':
            selected = rows
        else:
            # The stored wall candidates are ordered by strike, so taking the
            # first eight hides the largest positions. Show four supplied OI
            # observations per expiry; this is display selection, not a new
            # metric, dealer-position estimate, or price-target calculation.
            by_expiry = {}
            for row in rows:
                by_expiry.setdefault(row.get('expiry'), []).append(row)
            def saved_oi(row):
                value = row.get('open_interest', row.get('oi'))
                return value if _detailed_numeric(value) else float('-inf')
            selected = [row for group in by_expiry.values()
                        for row in sorted(group, key=saved_oi, reverse=True)[:4]]
        result[name] = [{k: v for k, v in row.items() if k in keys} for row in selected]
        result[name + '_omitted_count'] = len(rows) - len(selected)
    result['projection_note'] = ('仅在已保存的各侧墙候选中按OI展示每到期月前四条，'
                                 '不代表完整期权链中最大的四个持仓。仅为展示筛选，'
                                 '不重新计算墙、期权指标或价格目标。Block/PNT保留已提供记录；'
                                 '其余完整链与原始输入见审计附件。')
    return result


def _detailed_strikes(data):
    rows = data.get('strike_metrics') or []
    if not isinstance(rows, list):
        return {'status': 'unsupported_shape', 'audit_ref': 'audit_report.md'}
    fields = {'strike', 'expiry', 'expiry_date', 'side', 'open_interest', 'oi', 'oi_change',
              'delta_oi', 'delta', 'settlement', 'volume', 'block', 'pnt', 'trade_date'}
    return {'rows': [{k: v for k, v in r.items() if k in fields} for r in rows[:16] if isinstance(r, dict)],
            'omitted_count': max(0, len(rows) - 16),
            'projection_note': 'First sixteen supplied strike metrics; remaining chain in audit_report.md.'}


def detailed_report_profile(snapshot):
    """Read-only, dated evidence projection. Availability is not analytic quality."""
    flow = snapshot.get('gold_workflow') or {}
    research = snapshot.get('daily_research') or {}
    passport = [{**_detailed_clean(row), 'source_refs': _detailed_refs(row)}
                for row in research.get('passport') or []]
    cutoff = snapshot.get('snapshot_time')
    rows = {row.get('symbol'): row for row in passport}
    macro = project_macro(flow.get('macro_causal') or {})
    engines = macro.get('engines') or {}
    workflow = project_workflow(flow, official_etf=research.get('official_etf'))

    def selected(*symbols):
        return [rows[s] for s in symbols if s in rows]

    technical = snapshot.get('technical') or {}
    technical = technical.get('data', technical)
    options = snapshot.get('options') or {}
    option_data = options.get('data') or {}
    news = (snapshot.get('news') or {}).get('data') or {}
    execution = deepcopy(flow.get('execution') or {})
    if 'timeframe_features' in execution:
        execution['timeframe_features'] = [r for r in execution['timeframe_features'] if r.get('timeframe') in {'4H', '1H', '15m'}]
    pa = project_price_action(flow.get('price_action') or {})
    if 'timeframes' in pa:
        pa['timeframes'] = {k: v for k, v in pa['timeframes'].items() if k in {'4H', '1H', '15m'}}
    evidence = {
        'market_evolution': {'technical': technical, 'price_anchor': flow.get('price_anchor'),
                             'completed_windows': project_cross_asset(flow.get('cross_asset_freshness') or {}).get('chart_windows')},
        'growth_inflation': {'growth': engines.get('growth'), 'inflation': engines.get('inflation')},
        'labor': {'employment': research.get('employment'), 'labor': macro.get('labor')},
        'real_rates': {'observations': selected('US10Y', 'REAL10Y', 'BREAKEVEN_10Y'), 'treasury': engines.get('treasury')},
        'curve_policy': {'observations': selected('US02Y', 'US10Y', 'US30Y', 'YIELD_SPREAD_10Y_2Y', 'YIELD_SPREAD_2Y_3M'),
                         'policy': engines.get('policy'), 'treasury': engines.get('treasury')},
        'dollar': {'observations': selected('DXY', 'BROAD_DOLLAR'), 'dollar': engines.get('dollar')},
        'liquidity': {'observations': selected('RESERVES', 'TGA', 'TGA_WEEKLY_AVERAGE', 'ON_RRP_USAGE', 'SOFR', 'EFFR', 'IORB'), 'liquidity': engines.get('liquidity')},
        'credit': {'observations': selected('HY_OAS', 'VIX'), 'credit': engines.get('credit')},
        'oil': {'observations': selected('WTI_SPOT', 'BRENT_SPOT', 'WTI_FUTURES_PROXY', 'BRENT_FUTURES_PROXY'), 'energy': flow.get('energy_channels')},
        'flows': {'diagnostics': workflow.get('flow_diagnostics') if flow.get('flow_diagnostics') else None, 'official_etf': research.get('official_etf'), 'cot_reports': research.get('cot_reports')},
        'options': {'projection': project_options(options), 'walls': _detailed_walls(option_data) if option_data else None,
                    'strike_metrics': _detailed_strikes(option_data) if option_data.get('strike_metrics') else None},
        'treasury_turn': {'treasury': engines.get('treasury'), 'turning_evidence': engines.get('turning_point')},
        'gold_response': {'response': engines.get('response'), 'residual': engines.get('residual')},
        'state': {'state_record': {**workflow.get('state_record', {}), **{k: v for k, v in (flow.get('state_record') or {}).items() if k in {'schema_version', 'calculation_version', 'namespace', 'current_state', 'source_snapshot_id', 'state_id', 'predecessor_id', 'as_of'}}}},
        'levels': {'key_levels': _detailed_levels(flow), 'execution_zones': workflow.get('execution_zones')},
        'scenarios': {'scenario_display': flow.get('scenario_display'), 'scenario_engine': {k: v for k, v in (flow.get('scenario_engine') or {}).items() if k in {'main_scenario_id', 'semantics', 'constraints', 'coverage', 'signal_status'}}},
        'calendar': {'official_calendar': news.get('official_calendar'), 'supplemental_sources': research.get('supplemental_sources')},
        'observation': {'execution': execution, 'price_action': pa, 'market_session': research.get('market_session')},
        'risks': {'source_health': workflow.get('core_source_health'), 'quality_gate': flow.get('quality_gate')},
        'continuity': {'delta_vs_previous': workflow.get('delta_vs_previous')},
    }
    boundaries = {
        'market_evolution': '休市只禁止新确认，不抹去已收盘历史；事件归因须有正文与同步窗口。',
        'growth_inflation': '月频不能当周变化；区分发布值、可追溯预期与修订；PPI不一比一外推PCE。',
        'labor': '就业、工资和修订分别看；持仓或新闻摘要不能替代官方发布与价格响应。',
        'real_rates': '名义/TIPS/BE只能同日同窗口分解，不与期限溢价分解重复相加。',
        'curve_policy': '政策概率、2Y同族；期限溢价与拍卖未提供时仅作候选解释。',
        'dollar': 'DXY不替代正式广义美元；实际日期与日/周窗口分开。',
        'liquidity': '周均与每日点位分开；不重复扣减生成精确净流动性。',
        'credit': '披露滞后不代表今日信用风险已确认或不存在。',
        'oil': '连续期货与现货分列；换月不可硬比，运输损失需独立证据。',
        'flows': 'GLD不代表全球；AUM不是申赎；CFTC不同口径不相减。',
        'options': 'PRELIM不删除有效OI事实；Block/PNT缺失不是零；dealer方向未知，GC无基差不映射XAU。',
        'treasury_turn': '无历史与拍卖证据不固定No Turn或评分；分别给支持、反对、升级和失效。',
        'gold_response': '定性渠道背离不是拟合回报残差，无回归输出不报残差百分数或强度分。',
        'state': 'state_record是权威；Accepted空值保持空；样本S4/S5语义不可移植。',
        'levels': '现货与GC坐标分列，保留Watch/Stale/Retired及确认/失效，不替文字补验证。',
        'scenarios': '主/上/下均须条件、区域、失效和观察窗口；缺区域写待形成，不改规则权重。',
        'calendar': '未核验时区/DST/时刻/预期不补造；日期精度不等于具体发布时间。',
        'observation': '仅4H/1H/15m条件观察，无5m；二次入场/楔形未实现，休市无新信号。',
        'risks': '局部缺口仅限制依赖结论；生成、正文覆盖、因果审阅、发布门禁分别报告。',
        'continuity': '前报告身份须核验；同源修订不叫新成交，不反推前报告数值。',
    }
    modules = {}
    for key, value in evidence.items():
        refs = _detailed_refs(value)
        if key == 'levels':
            # Legacy levels carry aggregate source lists: only a known CME
            # coordinate can be narrowed safely. Unresolved spot lineage stays audit-only.
            refs = [r for r in _detailed_refs(flow.get('key_levels') or [])
                    if r.get('source') == 'cme_daily_bulletin']
        # Scope presence is conservative: even complete-looking objects do not
        # prove that every causal link was observed or that prose is correct.
        present = any(v not in (None, {}, []) for v in value.values())
        if key == 'options':
            present = bool(option_data)
        if key == 'flows':
            diagnostics = value.get('diagnostics') or {}
            etf = value.get('official_etf') or {}
            cot = value.get('cot_reports') or {}
            present = (diagnostics.get('status') not in {None, 'unavailable', 'failed'}
                       or bool(etf.get('source_refs')) and any(etf.get(k) is not None for k in
                           ('shares_outstanding', 'gold_holdings_tonnes'))
                       or any(isinstance(report, dict) and report.get('source_refs')
                              and report.get('status', report.get('readiness')) not in {'unavailable', 'failed'}
                              for report in cot.values()))
        if key == 'observation':
            present = bool(execution or flow.get('price_action'))
        modules[key] = {'title': DETAILED_TOPICS[key], 'availability': 'partial' if present else 'missing',
                        'evidence': _detailed_clean(value), 'source_refs': refs,
                        'constraints': [boundaries[key]], 'evidence_id': 'detailed:' + key}
    return {'version': DETAILED_PROFILE_VERSION, 'reasoning_fields': list(DETAILED_REASONING_FIELDS),
            'passport': passport, 'cutoff': cutoff, 'modules': modules,
            'weekly_comparisons': [dict(symbol=r.get('symbol'), **detailed_comparison(r, cutoff=cutoff)) for r in passport],
            'daily_comparisons': [dict(symbol=r.get('symbol'), **detailed_comparison(r, cutoff=cutoff, weekly=False)) for r in passport],
            'coverage_semantics': 'Substantive structured prose is required; partial evidence remains partial. Presence of headings or valid schema is not proof of analytic quality.'}
CME_ROLL_SIGNAL_MIN_CONFIDENCE = 0.05


class ResearchInputTooLarge(ValueError):
    pass


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


ARCHIVE_KEYS = {
    'raw_path', 'parsed_path', 'input_snapshot_ids', 'raw_levels', 'raw_scenarios',
    'raw_level', '_identity', 'decision_ref', 'evidence_ref', 'previous_decision_ref',
    'payload_hash', 'sha256', 'request_messages', 'llm_raw_output', 'input_metrics', 'audit_id',
}
SOURCE_KEYS = {'source', 'source_url', 'url', 'reference', 'symbol', 'date', 'observation_date',
               'observation_month', 'release_date', 'published_at', 'retrieved_at', 'vintage_status',
               'evidence_scope', 'source_ref', 'source_tier', 'snapshot_id', 'artifact_ref',
               'status', 'reason', 'reason_code', 'warning', 'verification_status',
               'qualification_reason', 'vintage_date', 'observation_cutoff_date',
               'observation_cutoff_month', 'report_date', 'report_type', 'version_type',
               'full_text_available', 'content_scope', 'release_datetime', 'release_timezone',
               'release_status', 'release_date_kind', 'time_precision', 'unit',
               'provider_observation_time', 'instrument_type', 'contract_code', 'source_kind'}
_CREDENTIAL_QUERY_KEYS = {
    'api_key', 'apikey', 'access_token', 'token', 'auth_token', 'authorization',
    'client_secret', 'secret', 'password', 'passwd',
}
_SENSITIVE_TEXT_KEYS = {
    'reason', 'reason_code', 'warning', 'warnings', 'error', 'errors', 'message',
    'detail', 'qualification_reason',
}
_URL_RE = re.compile(r'https?://[^\s\"\'<>]+')
_INLINE_CREDENTIAL_RE = re.compile(
    r'(?i)\b(api[_-]?key|apikey|access[_-]?token|auth[_-]?token|token|client[_-]?secret|secret|password|passwd)=([^&\s\"\'<>]+)'
)


def _redact_url_credentials(value):
    """Remove credential values without destroying the source locator."""
    if not isinstance(value, str):
        return value
    try:
        parts = urlsplit(value)
    except ValueError:
        return value
    if parts.scheme not in {'http', 'https'} or not parts.netloc:
        return value
    changed = False
    query = []
    for key, item in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() in _CREDENTIAL_QUERY_KEYS:
            item = '[REDACTED]'
            changed = True
        query.append((key, item))
    if not changed:
        return value
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _redact_sensitive_text(value):
    if not isinstance(value, str):
        return value
    value = _URL_RE.sub(lambda match: _redact_url_credentials(match.group(0)), value)
    return _INLINE_CREDENTIAL_RE.sub(lambda match: f'{match.group(1)}=[REDACTED]', value)


def pack_evidence(value, *, stage, max_chars=200000, packed_projection=None):
    sources, source_ids, omissions, urls = {}, {}, Counter(), {}

    def source(ref):
        if not isinstance(ref, dict):
            ref = {'reference': ref}
        for key in ref:
            if key not in SOURCE_KEYS:
                omissions['source_metadata:' + key] += 1
        selected = {
            k: (_redact_url_credentials(v) if k in {'source_url', 'url'}
                else _redact_sensitive_text(v) if k in _SENSITIVE_TEXT_KEYS
                else v)
            for k, v in ref.items() if k in SOURCE_KEYS
        }
        if not selected:
            selected = {'opaque_reference_sha256': sha256(encode(ref).encode()).hexdigest(),
                        'status': 'unresolved_source_contract_not_independent_evidence'}
        for field in ('source_url', 'url'):
            if isinstance(selected.get(field), str):
                url = selected.pop(field)
                url_id = 'url_' + sha256(url.encode()).hexdigest()[:12]
                urls[url_id] = url
                selected[field + '_id'] = url_id
        key = encode(selected)
        if key not in source_ids:
            identifier = 'src_' + sha256(key.encode()).hexdigest()[:16]
            source_ids[key] = identifier
            sources[identifier] = selected
        return source_ids[key]

    def walk(v, *, parent_key=None):
        if isinstance(v, dict):
            result = {}
            for k, item in v.items():
                if k in ARCHIVE_KEYS:
                    omissions[k] += 1
                    continue
                if k in {'current_source', 'previous_source', 'weekly_anchor_source', 'yoy_source'} and isinstance(item, dict):
                    result[k + '_id'] = source(item)
                elif (k == 'source_ref' or k.endswith('_source_ref')) and isinstance(item, dict):
                    result[k.replace('source_ref', 'source_id')] = source(item)
                elif k == 'source_refs' or k.endswith('_source_refs'):
                    refs = ([item] if SOURCE_KEYS.intersection(item) else list(item.values())) if isinstance(item, dict) else item
                    if isinstance(refs, list):
                        result[k.replace('source_refs', 'source_ids')] = list(dict.fromkeys(source(r) for r in refs))
                    else:
                        result[k] = item
                else:
                    result[k] = walk(item, parent_key=k)
            return result
        if isinstance(v, (list, tuple)):
            # Sequence multiplicity and order may encode observations/windows.
            return [walk(item, parent_key=parent_key) for item in v]
        if isinstance(v, str):
            if parent_key in {'url', 'source_url'}:
                return _redact_url_credentials(v)
            if parent_key in _SENSITIVE_TEXT_KEYS or (parent_key or '').endswith('_reason'):
                return _redact_sensitive_text(v)
        return v

    result = walk(value)
    if packed_projection is not None:
        packed_projection(result)
    result['source_catalog'] = sources
    result['url_catalog'] = urls
    result['input_contract'] = {
        'version': RESEARCH_INPUT_CONTRACT_VERSION, 'stage': stage,
        'omitted_archive_fields': dict(omissions),
        'truncation': False,
        'source_resolution': 'source_ids resolve in source_catalog; url_id/source_url_id resolve in url_catalog; full archive retained outside request',
        'size_limit_chars': max_chars,
    }
    size = len(encode(result))
    if size > max_chars:
        raise ResearchInputTooLarge(f'{stage}: {size} characters exceeds {max_chars}; no evidence was silently truncated')
    return result


def project_workflow(flow, *, official_etf=None):
    keys = ('schema_version', 'reader_report_version', 'reader_presentation', 'analysis_time', 'price_anchor', 'real_rate',
            'method_boundaries', 'quality_gate', 'scenario_display', 'execution')
    result = {k: flow[k] for k in keys if k in flow}
    from apps.features.research.price_action import gate_execution_frames
    result['execution'] = gate_execution_frames(flow.get('execution', {}), flow.get('price_action', {}))
    zones = flow.get('execution_zones', {})
    zone_keys = {'display_label', 'display_lower', 'display_upper', 'price', 'instrument', 'role',
                 'source_date', 'source_type', 'source_refs', 'activation', 'invalidation',
                 'level_status', 'zone_status', 'eligible_for_target'}
    if zones:
        raw_zones = list(zones.get('zones', []))
        active_zones = []
        seen_zones = {}
        for zone in raw_zones:
            if (zone.get('level_status') == 'Stale'
                    or zone.get('zone_status') == 'unavailable'
                    or zone.get('eligible_for_target') is False):
                continue
            projected = {k: v for k, v in zone.items() if k in zone_keys}
            identity = encode({k: v for k, v in projected.items() if k != 'source_refs'})
            if identity in seen_zones:
                existing = seen_zones[identity]
                refs = [*existing.get('source_refs', []), *projected.get('source_refs', [])]
                if refs:
                    existing['source_refs'] = list({encode(ref): ref for ref in refs}.values())
                continue
            seen_zones[identity] = projected
            active_zones.append(projected)
        result['execution_zones'] = {
            'status': zones.get('status'), 'missing_inputs': zones.get('missing_inputs'),
            'zones': active_zones,
            'omitted_zone_count': len(raw_zones) - len(active_zones),
            'projection_note': 'Only active, execution-eligible, deduplicated spot zones are supplied; stale and inactive zones remain in the frozen snapshot.',
        }
    diagnostics = flow.get('flow_diagnostics', {})
    result['flow_diagnostics'] = _project_flow_diagnostics(diagnostics, official_etf=official_etf)
    state = flow.get('state_record', {})
    state_keys = {'accepted_state', 'previous_state', 'candidate_state', 'transition_status',
                  'transition_confirmed', 'accepted_at', 'confirmed_conditions', 'missing_conditions',
                  'invalidation_conditions', 'trigger_conditions', 'candidate_label', 'rule_validation'}
    result['state_record'] = {k: v for k, v in state.items() if k in state_keys}
    delta = flow.get('delta_vs_previous', {})
    delta_keys = {'symbol', 'previous', 'current', 'delta', 'unit', 'previous_date', 'current_date',
                  'change_kind', 'status', 'reason', 'source_refs'}
    raw_delta_rows = list(delta.get('rows', []))
    changed_rows = []
    unchanged_symbols = []
    omitted_empty_symbols = []
    for row in raw_delta_rows:
        if row.get('change_kind') == 'unchanged':
            if row.get('symbol'):
                unchanged_symbols.append(row['symbol'])
            continue
        if row.get('current') is None and row.get('previous') is None and row.get('delta') is None:
            if row.get('symbol'):
                omitted_empty_symbols.append(row['symbol'])
            continue
        changed_rows.append({k: v for k, v in row.items() if k in delta_keys})
    result['delta_vs_previous'] = {
        'status': delta.get('status'), 'previous_snapshot_id': delta.get('previous_snapshot_id'),
        'previous_analysis_time': delta.get('previous_analysis_time'),
        'changed_or_noncomparable_rows': changed_rows,
        'unchanged_symbols': unchanged_symbols,
        'omitted_empty_symbols': omitted_empty_symbols,
        'projection_note': 'Unchanged observations are represented by symbol only; current levels remain in domain evidence.',
    }
    health_keys = {'source_key', 'source_health', 'reason', 'actual_latest_date', 'expected_release_time'}
    result['core_source_health'] = {'items': [{k: v for k, v in r.items() if k in health_keys}
                                            for r in flow.get('core_source_health', {}).get('items', [])]}
    return result


def _project_flow_diagnostics(diagnostics, *, official_etf=None):
    """Keep fund conclusions once; detailed CFTC reports are supplied separately."""
    if not isinstance(diagnostics, dict):
        return diagnostics
    etf = diagnostics.get('etf') or {}
    auxiliary = etf.get('auxiliary') or {}
    compact_etf = {
        'status': etf.get('status'),
        'lineage_status': etf.get('lineage_status'),
        'missing_data': etf.get('missing_data', []),
        'primary_fund': etf.get('primary_fund'),
        'daily': etf.get('daily'),
        'weekly': etf.get('weekly'),
        'daily_vs_weekly': etf.get('daily_vs_weekly'),
        'levels': etf.get('levels'),
        'reported_on': etf.get('reported_on'),
        'auxiliary': {
            key: {field: value.get(field) for field in ('status', 'reason', 'source_refs') if field in value}
            for key, value in auxiliary.items() if isinstance(value, dict)
        },
        'limitations': etf.get('limitations', []),
        'source_refs': etf.get('source_refs', []),
    }
    if official_etf:
        # Exact comparison endpoints are evidence, even when the headline
        # daily/weekly changes have already been summarized by the flow engine.
        compact_etf['comparison_windows'] = {
            metric: {key: official_etf.get(field) for key, field in (
                ('current', current_field),
                ('current_date', prefix + '_reported_on'),
                ('previous', prefix + '_previous_value'),
                ('previous_date', prefix + '_previous_reported_on'),
                ('weekly_anchor', prefix + '_weekly_anchor_value'),
                ('weekly_anchor_date', prefix + '_weekly_anchor_date'),
            )}
            for metric, prefix, current_field in (
                ('shares', 'shares', 'shares_outstanding'),
                ('holdings_tonnes', 'gold_holdings_tonnes', 'gold_holdings_tonnes'),
            )
        }
    return {
        'schema_version': diagnostics.get('schema_version'),
        'status': diagnostics.get('status'),
        'classification': diagnostics.get('classification'),
        'classification_status': diagnostics.get('classification_status'),
        'classifications': diagnostics.get('classifications'),
        'primary_report_type': diagnostics.get('primary_report_type'),
        'report_date': diagnostics.get('report_date'),
        'window': diagnostics.get('window'),
        'position_contraction': diagnostics.get('position_contraction'),
        'etf': compact_etf,
        'event_attribution': diagnostics.get('event_attribution'),
        'limitations': diagnostics.get('limitations', []),
        'projection_note': 'Detailed current, previous and delta CFTC rows are supplied once in cot_reports; duplicate report payloads are omitted here.',
    }


def leaf_sources(value):
    """Remove only aggregate refs exactly represented by descendants."""
    def refs(v):
        if isinstance(v, dict):
            result = set()
            for k, item in v.items():
                if k == 'source_refs' and isinstance(item, list):
                    result.update(encode(r) for r in item)
                else:
                    result.update(refs(item))
            return result
        if isinstance(v, list):
            return set().union(*(refs(x) for x in v))
        return set()
    if isinstance(value, dict):
        result = {k: leaf_sources(v) for k, v in value.items()}
        descendants = refs({k: v for k, v in result.items() if k != 'source_refs'})
        if isinstance(result.get('source_refs'), list):
            result['source_refs'] = [r for r in result['source_refs'] if encode(r) not in descendants]
        return result
    if isinstance(value, list):
        return [leaf_sources(v) for v in value]
    return value


def _project_market_windows(value):
    """Keep deterministic window changes while excluding every raw chart bar."""
    if isinstance(value, list):
        return [_project_market_windows(item) for item in value if isinstance(item, dict)]
    if not isinstance(value, dict):
        return value
    health_keys = {
        'ticker', 'symbol', 'status', 'reason', 'delay_seconds', 'resolution_seconds',
        'completed_bar_count', 'retrieved_at', 'last_completed_bar_end', 'front_contract', 'source_refs',
    }
    window_keys = {
        'group', 'window_start', 'window_end', 'horizon_minutes', 'bar_resolution_seconds',
        'window_lag_seconds', 'max_delay_seconds', 'comparison_scope', 'status',
        'alignment_delay_seconds', 'common_anchor_end',
        'aligned_comparison_allowed', 'reason', 'missing_tickers',
    }
    change_keys = {
        'ticker', 'symbol', 'unit', 'start_close', 'end_close', 'change_pct', 'change_bp',
        'delay_seconds', 'front_contract', 'source_refs',
    }
    projected = {
        key: value[key] for key in (
            'schema_version', 'as_of', 'causal_attribution_allowed', 'limitations', 'alignment_reference_tickers'
        ) if key in value
    }
    projected['series_health'] = [
        {key: item[key] for key in health_keys if key in item}
        for item in value.get('series_health', []) if isinstance(item, dict)
    ]
    projected['windows'] = []
    for window in value.get('windows', []):
        if not isinstance(window, dict):
            continue
        item = {key: window[key] for key in window_keys if key in window}
        item['changes'] = [
            {key: change[key] for key in change_keys if key in change}
            for change in window.get('changes', []) if isinstance(change, dict)
        ]
        projected['windows'].append(item)
    projected['projection_note'] = (
        'Only compact completed-bar window changes and series health are supplied. '
        'Raw OHLC arrays and chart-series payloads remain outside the model input.'
    )
    if value.get('multi_horizon'):
        # This contract contains only derived changes and lineage, never OHLC.
        projected['multi_horizon'] = deepcopy(value['multi_horizon'])
    return projected


def project_history(record, *, news_focus=None, seen_article_blocks=None):
    if not isinstance(record, dict):
        return record
    keys = ('schema_version', 'status', 'stop_reason', 'observations', 'documents',
            'market_observations', 'market_windows', 'news', 'errors', 'unavailable_data_needs')
    result = {k: record[k] for k in keys if k in record}
    final_assessment = record.get('final_assessment')
    if isinstance(final_assessment, dict):
        final_keys = {
            'action', 'question', 'hypothesis', 'driver_assessment', 'competing_hypotheses',
            'falsifier', 'evidence_assessment', 'finish_reason', 'finish_reason_normalized_from',
            'unavailable_data_needs', 'why_these_requests',
        }
        projected_final = {
            key: value for key, value in final_assessment.items() if key in final_keys
        }
        if projected_final.get('unavailable_data_needs') == result.get('unavailable_data_needs'):
            projected_final.pop('unavailable_data_needs')
        result['final_assessment'] = projected_final
    for field in ('observations', 'market_observations', 'market_windows', 'news', 'documents', 'errors'):
        if field not in result:
            result[field] = [item for r in record.get('rounds', [])
                             for item in (r.get('collection') or {}).get(field, [])]
    result['market_windows'] = _project_market_windows(result.get('market_windows', []))
    result['documents'] = project_news_documents(
        result.get('documents', []),
        focus_text=news_focus,
        seen_blocks=seen_article_blocks,
    )
    rounds = list(record.get('rounds', []))
    result['decision_trail'] = [
        {'decision_index': r.get('decision_index'),
         'question': r.get('plan', {}).get('question'),
         'hypothesis': r.get('plan', {}).get('hypothesis'),
         **({
             'driver_assessment': r.get('plan', {}).get('driver_assessment'),
             'competing_hypotheses': r.get('plan', {}).get('competing_hypotheses', []),
             'falsifier': r.get('plan', {}).get('falsifier'),
         } if final_assessment is None else {}),
         'requested_evidence': [
             {key: request.get(key) for key in (
                 'request_id', 'provider', 'key', 'claim', 'decision_impact',
                 'freshness_need', 'priority', 'resolution') if key in request}
             for request in r.get('plan', {}).get('data_requests', [])
         ],
         'evidence_assessment': (
             None if r is rounds[-1] and final_assessment is not None
             else r.get('plan', {}).get('evidence_assessment')
         ),
         'new_evidence_count': r.get('new_evidence_count')}
        for r in rounds]
    result['decision_trail_projection'] = (
        'Each round keeps its question, hypothesis, requested evidence and evidence assessment. '
        'Repeated driver/alternative/falsifier planning prose is represented by final_assessment; '
        'collected evidence, failures and unavailable needs remain above, and full plans remain in the frozen snapshot.'
    )
    return result


_NEWS_NEGATION_RE = re.compile(
    r'(?i)(?:\b(?:correct(?:ed|ion)?|revis(?:ed|ion)?|clarif(?:y|ied|ication)|'
    r'den(?:y|ied|ial)|not|no|without|uncertain|unlikely|unconfirmed|unverified|unsubstantiated|disputed|however|although|'
    r'despite|rather\s+than|capacity|estimate|preliminary)\b|'
    r'\b(?:may|might|could)\s+(?:not|have|be|reflect|indicate|suggest|mean|remain)\b|'
    r'更正|修正|澄清|否认|未经证实|无法证实|并非|不是|没有|尚未|未能|不确定|可能|估算|初步|但|不过|尽管)'
)
_NEWS_NUMBER_OR_DATE_RE = re.compile(
    r'(?i)(?:\b\d+(?:[.,]\d+)?(?:%|\s*(?:bpd|mbpd|million|billion|basis\s+points?|bps|'
    r'tonnes?|barrels?|dollars?))?\b|\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|'
    r'may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b)'
)
_NEWS_ATTRIBUTION_RE = re.compile(
    r'(?i)(?:\b(?:said|says|according\s+to|reported|statement|spokes(?:man|woman|person)|'
    r'officials?|analysts?|operator|Reuters|Associated\s+Press|AP)\b|表示|称|据|声明|官员|运营商)'
)
_NEWS_CAUSAL_RE = re.compile(
    r'(?i)(?:\b(?:gold|oil|dollar|yield|rates?|inflation|fed|treasury|pipeline|supply|demand|'
    r'outage|attack|sanction|tariff|shipping|production|inventory|employment|prices?)\b|'
    r'黄金|原油|美元|收益率|利率|通胀|美联储|供应|需求|中断|制裁|关税|库存|就业|价格)'
)
_NEWS_TOKEN_RE = re.compile(r'[A-Za-z][A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,}')
_NEWS_STOPWORDS = {
    'the', 'and', 'for', 'with', 'from', 'that', 'this', 'was', 'were', 'have', 'has',
    'will', 'would', 'could', 'may', 'said', 'says', 'news', 'after', 'before', 'into',
}


def _news_focus_tokens(*values):
    text = ' '.join(str(value or '') for value in values)
    return {
        token.lower() for token in _NEWS_TOKEN_RE.findall(text)
        if token.lower() not in _NEWS_STOPWORDS
    }


def _project_article_blocks(document, *, focus_text=None, seen_blocks=None):
    blocks = list(document.get('text_blocks') or [])
    if not blocks or not all(isinstance(block, str) for block in blocks):
        return {'text_blocks': blocks}
    normalized = [re.sub(r'\s+', ' ', block).strip() for block in blocks]
    substantive = [
        index for index, block in enumerate(normalized)
        if len(block) >= 24 or (block and _NEWS_NEGATION_RE.search(block))
    ]
    focus_tokens = _news_focus_tokens(document.get('title'), focus_text)
    reasons = {index: set() for index in range(len(blocks))}
    selected = set(substantive[:2])
    for index in substantive[:2]:
        reasons[index].add('article_lead')

    scores = []
    qualifier_indexes = []
    attribution_indexes = []
    numeric_indexes = []
    for index in substantive:
        block = normalized[index]
        tokens = _news_focus_tokens(block)
        relevance = len(tokens & focus_tokens)
        qualifier = bool(_NEWS_NEGATION_RE.search(block))
        numeric = bool(_NEWS_NUMBER_OR_DATE_RE.search(block))
        attribution = bool(_NEWS_ATTRIBUTION_RE.search(block))
        causal = bool(_NEWS_CAUSAL_RE.search(block))
        score = relevance * 4 + numeric * 3 + attribution * 2 + causal * 2 + qualifier * 5
        score += 2 if index < 5 else 0
        scores.append((score, index))
        if qualifier:
            selected.add(index)
            qualifier_indexes.append(index)
            reasons[index].add('correction_negation_or_uncertainty')
        if numeric:
            numeric_indexes.append(index)
        if attribution:
            attribution_indexes.append(index)
        if relevance:
            reasons[index].add('title_or_research_question_relevance')

    for label, indexes, count in (
        ('numeric', numeric_indexes, 4),
        ('attribution', attribution_indexes, 3),
    ):
        for index in sorted(indexes, key=lambda item: next(score for score, idx in scores if idx == item), reverse=True)[:count]:
            selected.add(index)
            reasons[index].add(label)
    for _, index in sorted(scores, reverse=True)[:8]:
        selected.add(index)
        reasons[index].add('ranked')

    # Corrections and split quotations need their neighboring attribution or
    # subject sentence. Keep whole paragraphs rather than slicing strings.
    for index in sorted(qualifier_indexes):
        previous = index - 1
        if previous in substantive:
            selected.add(previous)
            reasons[previous].add('qualifier_context')
    for index in sorted(selected):
        if any(mark in normalized[index] for mark in ('"', '“', '”')):
            for neighbor in (index - 1, index + 1):
                if neighbor in substantive and _NEWS_ATTRIBUTION_RE.search(normalized[neighbor]):
                    selected.add(neighbor)
                    reasons[neighbor].add('quote_attribution_context')

    seen_blocks = seen_blocks if seen_blocks is not None else {}
    selected_rows = []
    reason_counts = Counter()
    for index in sorted(selected):
        original = blocks[index]
        block_hash = sha256(original.encode()).hexdigest()
        block_id = f"p{document.get('part_index', 0)}:b{index}"
        reason_counts.update(reasons[index] or {'context'})
        duplicate = seen_blocks.get(block_hash)
        if duplicate is None:
            text_or_ref = original
            seen_blocks[block_hash] = {
                'document_id': document.get('document_id'),
                'block_id': block_id,
            }
        else:
            text_or_ref = 'exact_duplicate:' + str(duplicate.get('document_id')) + ':' + duplicate['block_id']
            reason_counts['exact_duplicate'] += 1
        selected_rows.append([index, block_id, text_or_ref])
    return {
        'selected_blocks': {
            'columns': ['original_index', 'block_id', 'text_or_exact_duplicate_ref'],
            'rows': selected_rows,
        },
        'original_block_count': len(blocks),
        'selected_block_count': len(selected_rows),
        'omitted_block_count': len(blocks) - len(selected_rows),
        'selection_reason_counts': dict(reason_counts),
        'original_text_blocks_sha256': sha256(encode(blocks).encode()).hexdigest(),
        'transmitted_body_complete': len(selected_rows) == len(blocks)
                                     and all(not row[2].startswith('exact_duplicate:') for row in selected_rows),
        'projection_scope': 'traceable_extractive_selection_not_full_article',
        'selection_policy': (
            'selected_blocks rows are [original_index, block_id, verbatim_text_or_exact_duplicate_ref]. '
            'Whole source paragraphs only: lead, question relevance, core dated/numeric facts, '
            'attribution, and every detected correction/negation/uncertainty paragraph. '
            'Context neighbors are retained for corrections and split quotations. Omitted paragraphs '
            'remain in the hash-verified archive; omission is not evidence that no counterexample exists.'
        ),
    }


def project_news_documents(documents, *, focus_text=None, seen_blocks=None):
    """Project article prose extractively while retaining archive traceability."""
    seen_blocks = seen_blocks if seen_blocks is not None else {}
    keep = {
        'document_id', 'title', 'publisher', 'origin_publisher', 'published_at', 'updated_at',
        'retrieved_at', 'requested_at', 'completed_at', 'observed_at', 'observation_date',
        'release_date', 'as_of',
        'status', 'evidence_scope', 'body_is_complete', 'body_verified', 'body_extraction',
        'eligible_current_news', 'article_body_chars', 'freshness', 'text_blocks',
        'observations', 'links', 'source_refs', 'source_ids', 'parsed_sha256',
        'reason', 'reason_code', 'error', 'errors', 'warning', 'warnings',
        'critical_gaps', 'limitations',
        'parsed_path', 'detail_request_format', 'part_index', 'part_count',
        'omitted_link_count', 'instruction_boundary',
    }
    projected = []
    for document in documents or []:
        if not isinstance(document, dict):
            projected.append(document)
            continue
        if document.get('projection_scope') == 'traceable_extractive_selection_not_full_article':
            projected.append(dict(document))
            continue
        is_article = (
            document.get('evidence_scope') == 'publisher_body'
            and not document.get('observations')
            and isinstance(document.get('text_blocks'), list)
        )
        if is_article:
            item = {key: value for key, value in document.items() if key in keep}
            item.pop('text_blocks', None)
            item.update(_project_article_blocks(
                document,
                focus_text=focus_text,
                seen_blocks=seen_blocks,
            ))
            item['archive_projection'] = (
                'The coordinator receives a traceable extractive paragraph selection, not the full article. '
                'document_id:part_index can be expanded only by the research loop before final freeze; '
                'the final coordinator has no archive tool and must not claim it read omitted paragraphs.'
            )
        else:
            item = dict(document)
            item['archive_projection'] = (
                'Non-article evidence is not paragraph-sampled. Fetch keys and duplicate feed metadata '
                'are omitted; structured observations and supplied text_blocks remain complete.'
            )
        projected.append(item)
    return projected


def project_cross_asset(cross):
    keys = {'symbol', 'ticker', 'display_value', 'unit', 'minute_bar_time', 'retrieved_at',
            'delay_seconds', 'freshness', 'intraday_confirmation_allowed', 'source_refs',
            'change', 'change_percent', 'price_time', 'observation_date', 'status',
            'provider_change_abs', 'provider_change_pct', 'change_basis', 'provider_bar_time',
            'quote_time', 'quote_time_verified', 'instrument_type', 'continuous_contract', 'value_kind'}
    result = {'observations': [{k: v for k, v in row.items() if k in keys}
                               for row in cross.get('observations', [])],
              'curves': cross.get('curves', []), 'analysis_capability': cross.get('analysis_capability'),
              'critical_freshness_failures': cross.get('critical_freshness_failures', []),
              'market_session': cross.get('market_session'),
              'synchronous_event_attribution_allowed': cross.get('synchronous_event_attribution_allowed'),
              'alignment_note': cross.get('alignment_note')}
    if cross.get('chart_windows'):
        result['chart_windows'] = _project_market_windows(cross['chart_windows'])
    return result


def project_macro(macro, *, energy_channels=None, cross_asset=None):
    result = {k: v for k, v in macro.items()
              if k not in {'layers', 'questions', 'validation_layer', 'deduplication',
                           'source_refs', 'input_snapshot_ids'}}
    engines = dict(result.get('engines') or {})
    if (engines.get('policy') or {}).get('schema_version') == 'fedwatch_policy_projection.v1':
        engines['policy'] = _compact_fedwatch_policy(engines['policy'])
    growth = dict(engines.get('growth') or {})
    details = dict(growth.get('official_details') or {})
    if details:
        facts = [fact for fact in growth.get('facts', []) if isinstance(fact, dict)]
        metric_status = {}
        metric_source_refs = []
        supplemental_metrics = {}
        for name, metric in (details.get('metrics') or {}).items():
            if not isinstance(metric, dict):
                continue
            source_ref = metric.get('source_ref')
            if isinstance(source_ref, dict):
                metric_source_refs.append(source_ref)
            metric_status[name] = {
                key: metric.get(key) for key in (
                    'symbol', 'status', 'reason', 'reference_period', 'observation_date',
                    'release_date', 'release_time',
                ) if key in metric
            }
            comparable_keys = (
                'symbol', 'status', 'value', 'unit', 'previous_value', 'change',
                'observation_date', 'reference_period', 'release_date', 'release_time',
            )
            covered_by_fact = any(
                all(key not in metric or fact.get(key) == metric.get(key) for key in comparable_keys)
                for fact in facts
            )
            if not covered_by_fact:
                supplemental_metrics[name] = {
                    key: value for key, value in metric.items()
                    if key not in {'source_ref', 'source_key'}
                }
        growth['official_details'] = {
            key: details.get(key) for key in (
                'status', 'as_of', 'unavailable_symbols', 'warnings'
            ) if key in details
        }
        growth['official_details'].update({
            'metric_status_and_timing': metric_status,
            'supplemental_metrics_not_in_facts': supplemental_metrics,
            'source_refs': metric_source_refs,
            'projection_note': (
                'Current/previous values and changes already present in facts are not repeated. '
                'Status, reasons, release timing, unique metrics and source lineage remain.'
            ),
        })
        engines['growth'] = growth
    treasury_windows = (engines.get('treasury') or {}).get('windows')
    response = dict(engines.get('response') or {})
    if treasury_windows and response.get('rates') == treasury_windows:
        response.pop('rates')
        response['rates_evidence_ref'] = 'macro_causal.engines.treasury.windows'
        engines['response'] = response
    chains = []
    for chain in result.get('transmission_chains') or []:
        if isinstance(chain, dict) and treasury_windows and chain.get('observed') == treasury_windows:
            chain = dict(chain)
            chain.pop('observed')
            chain['observed_evidence_ref'] = 'macro_causal.engines.treasury.windows'
        chains.append(chain)
    if chains:
        result['transmission_chains'] = chains
    energy_observations = (energy_channels or {}).get('observations') if isinstance(energy_channels, dict) else None
    oil = engines.get('oil') or {}
    if energy_observations and oil.get('facts') == energy_observations:
        engines['oil'] = {
            'type': oil.get('type'),
            'facts_evidence_ref': 'energy_channels.observations',
            'projection_note': 'Identical oil facts are supplied once in energy_channels.',
        }
    if engines:
        result['engines'] = engines
    if ('market_session' in result and isinstance(cross_asset, dict)
            and result.get('market_session') == cross_asset.get('market_session')):
        result.pop('market_session')
        result['market_session_evidence_ref'] = 'tradingview_cross_asset.market_session'
    result['projection_note'] = (
        'Top-level aggregate source lists and snapshot plumbing are omitted; '
        'fact-level and engine-level source references remain attached.'
    )
    return result


def project_price_action(price_action):
    """Keep the current deterministic PA state without replaying every swing.

    The model interprets the computed structure; it does not recompute BOS or
    CHoCH from the full pivot history.  Counts make the bounded projection
    explicit, while the immutable snapshot retains every event and pivot.
    """
    result = {k: v for k, v in price_action.items() if k != 'timeframes'}
    timeframes = {}
    for timeframe, raw in (price_action.get('timeframes') or {}).items():
        if not isinstance(raw, dict):
            continue
        events = list(raw.get('events') or [])
        pivots = list(raw.get('pivots') or [])
        zone_states = []
        for zone in raw.get('zone_states') or []:
            if not isinstance(zone, dict):
                zone_states.append(zone)
                continue
            zone_events = list(zone.get('events') or [])
            event_types = Counter(
                str(event.get('type') or 'unknown') for event in zone_events if isinstance(event, dict)
            )
            projected_zone = {key: value for key, value in zone.items() if key != 'events'}
            projected_zone.update({
                'event_count': len(zone_events),
                'event_type_counts': dict(event_types),
                'first_event_time': next((event.get('time') for event in zone_events
                                          if isinstance(event, dict) and event.get('time')), None),
                'latest_event': next((event for event in reversed(zone_events)
                                      if isinstance(event, dict)), None),
                'event_projection_note': (
                    'Current zone state, transition counts, first timestamp and latest event are supplied; '
                    'the complete deterministic event replay remains in the frozen snapshot.'
                ),
            })
            zone_states.append(projected_zone)
        timeframes[timeframe] = {
            k: v for k, v in raw.items()
            if k not in {'events', 'pivots', 'zone_states', 'raw_path'}
        }
        timeframes[timeframe].update({
            'event_count': len(events),
            'recent_events': events[-8:],
            'pivot_count': len(pivots),
            'recent_pivots': pivots[-6:],
            'zone_states': zone_states,
            'projection_note': (
                'Recent deterministic events/pivots plus current structure are supplied; '
                'the complete ordered history remains in the frozen snapshot.'
            ),
        })
    result['timeframes'] = timeframes
    return result


def _prior_report_contexts(snapshot):
    """Validate and project each historical body exactly once for model input."""
    from apps.analysis.snapshots.report_continuity import prior_report_context_model_input

    return prior_report_context_model_input(snapshot)


def final_input(snapshot, output, *, catalog, assessment):
    flow = snapshot['gold_workflow']
    energy_channels = flow.get('energy_channels', {})
    cross_asset = flow.get('cross_asset_freshness', {})
    news_focus = snapshot.get('news', {}).get('data', {}).get('daily_market_brief', {}).get('report_inputs', {}).get('research_focus', [])
    adaptive_record = snapshot.get('adaptive_research', {})
    focus_context = encode({
        'research_focus': news_focus,
        'assessment_domain_notes': assessment.get('domain_notes') if isinstance(assessment, dict) else None,
        'adaptive_final_assessment': adaptive_record.get('final_assessment'),
    })
    seen_article_blocks = {}
    mainstream_news = {
        k: (project_news_documents(
            v,
            focus_text=focus_context,
            seen_blocks=seen_article_blocks,
        ) if k == 'documents' else v)
        for k, v in snapshot.get('mainstream_news', {}).items() if k != 'candidates'
    }
    adaptive_research = project_history(
        adaptive_record,
        news_focus=focus_context,
        seen_article_blocks=seen_article_blocks,
    )
    payload = {
        'schema_version': 'research_synthesis.v2', 'snapshot_id': snapshot.get('snapshot_id'),
        'trade_date': snapshot.get('trade_date'), 'cutoff': snapshot.get('snapshot_time'),
        'gold_workflow': project_workflow(
            flow, official_etf=snapshot.get('daily_research', {}).get('official_etf')),
        'macro_causal': project_macro(
            flow.get('macro_causal', {}),
            energy_channels=energy_channels,
            cross_asset=cross_asset,
        ),
        'price_action': project_price_action(flow.get('price_action', {})),
        'technical_daily': snapshot.get('technical', {}),
        'cme_options': project_options(snapshot.get('options', {})),
        'cot_reports': snapshot.get('daily_research', {}).get('cot_reports', {}),
        'supplemental_source_features': snapshot.get('daily_research', {}).get('supplemental_sources', {}),
        'energy_channels': energy_channels,
        'news_focus': news_focus,
        'mainstream_news': mainstream_news,
        'tradingview_cross_asset': project_cross_asset(cross_asset),
        'adaptive_research': adaptive_research,
        'prior_report_contexts': _prior_report_contexts(snapshot),
        'evidence_catalog': catalog,
        'input_scope': ('Current facts, alternatives and rule references; no requirement to agree with rule bias. '
                        'Prior report bodies are historical opinion only and every old hypothesis must be '
                        'rechecked against current evidence.'),
    }
    if flow.get('reader_report_version') == DETAILED_PROFILE_VERSION:
        from apps.analysis.agents.research_quality import quality_contract
        payload['research_quality_standard'] = quality_contract()
        profile = detailed_report_profile(snapshot)
        # Resolve reviewed evidence once, rather than copying it into each module.
        paths = {
            'market_evolution': ['technical_daily', 'gold_workflow.price_anchor', 'tradingview_cross_asset.chart_windows'],
            'growth_inflation': ['macro_causal.engines.growth', 'macro_causal.engines.inflation'],
            'labor': ['macro_causal.labor'], 'real_rates': ['macro_causal.engines.treasury'],
            'curve_policy': ['macro_causal.engines.policy', 'macro_causal.engines.treasury'],
            'flows': ['gold_workflow.flow_diagnostics', 'cot_reports'],
            'treasury_turn': ['macro_causal.engines.treasury'],
            'gold_response': ['macro_causal.engines.response', 'macro_causal.engines.residual'],
            'state': ['gold_workflow.state_record'], 'scenarios': ['gold_workflow.scenario_display'],
            'observation': ['gold_workflow.execution', 'price_action'],
            'risks': ['gold_workflow.core_source_health', 'gold_workflow.quality_gate'],
            'continuity': ['gold_workflow.delta_vs_previous'],
        }
        for key, module in profile['modules'].items():
            if key in paths:
                module['evidence_paths'] = paths[key]
                module['source_refs'] = []  # local sources resolve at evidence_paths
                module['evidence'] = ({'official_etf': module['evidence'].get('official_etf')}
                                      if key == 'flows' else {})
            elif key == 'options':
                module['evidence_paths'] = ['cme_options']
                module['evidence'].pop('projection', None)
            elif key == 'levels':
                module['evidence_paths'] = ['gold_workflow.execution_zones']
                module['evidence'].pop('execution_zones', None)
        for module in profile['modules'].values():
            observations = module['evidence'].pop('observations', None)
            if observations is not None:
                module['passport_symbols'] = [r.get('symbol') for r in observations]
        for field in ('weekly_comparisons', 'daily_comparisons'):
            for row in profile[field]:
                row.pop('source_refs', None)  # resolve by symbol in passport
        profile['projection_note'] = ('evidence_paths resolve from this input root; facts are supplied once. '
                                      'Detailed archive/omitted option chain remain in audit_report.md.')
        payload['report_profile'] = profile
        if not flow.get('macro_causal'):
            payload['macro_causal'] = {}
        payload['evidence_catalog'] = [*catalog, *[
            {'evidence_id': module['evidence_id'], 'family': key,
             'evidence_path': 'report_profile.modules.' + key,
             'availability': module['availability']}
            for key, module in profile['modules'].items()]]
    # Reanalysis carries explicit review evidence separately from market facts.
    # Preserve it for both synthesis and the reviewer; old research summaries
    # must not silently override a verified correction to their window labels.
    findings = snapshot.get('reanalysis', {}).get('review_findings')
    if findings:
        payload['prior_review_findings'] = deepcopy(findings)
    # Keep domain challenges, not recursively nested snapshots or a second
    # copy of every fact. Immutable hard fields are enforced outside prose.
    domains = (output.input_payload or {}).get('domain_analyses', [])
    domain_keys = {'agent_name', 'module', 'summary', 'risk_points', 'data_gaps',
                   'limitations', 'invalid_conditions', 'status'}
    payload['domain_analyses'] = [{k: v for k, v in d.items() if k in domain_keys}
                                for d in domains if isinstance(d, dict)]
    payload['analytical_counter_evidence'] = {k: assessment[k] for k in ('limitations', 'domain_notes') if k in assessment}
    payload['projection_notes'] = 'Repeated aggregate source lists omitted; source references remain attached to individual facts. Full records remain in snapshot.'
    packed = pack_evidence(
        leaf_sources(payload),
        stage='synthesis',
        max_chars=SYNTHESIS_INPUT_MAX_CHARS,
        packed_projection=_project_packed_tables,
    )
    packed['input_contract']['tabular_projection'] = (
        'Decision evidence tables use columns plus ordered rows. missing_by_row records '
        'fields that were absent rather than explicitly null; full row objects remain in the frozen snapshot. '
        'Chart-window series health and window metadata use separate tables; one changes_table uses '
        'window_index to resolve each change to its windows_table row. '
        'shared_fields belong to EVERY row of that table and are written once; '
        'they retain the exact original values, including dates, units and qualifications.'
    )
    packed['input_contract']['decision_projection_version'] = 'decision_tables.v2'
    size = len(encode(packed))
    if size > SYNTHESIS_INPUT_MAX_CHARS:
        raise ResearchInputTooLarge(
            f'synthesis: {size} characters exceeds {SYNTHESIS_INPUT_MAX_CHARS}; '
            'no evidence was silently truncated'
        )
    return packed


def _rows_table(rows, *, key_name=None):
    """Losslessly encode repeated object keys once for model transport."""
    if not isinstance(rows, (list, tuple)) or not rows or not all(isinstance(row, dict) for row in rows):
        return rows
    columns = list(dict.fromkeys(key for row in rows for key in row))
    encoded_rows = [[row.get(column) for column in columns] for row in rows]
    missing_by_row = {
        str(index): [column_index for column_index, column in enumerate(columns) if column not in row]
        for index, row in enumerate(rows)
        if any(column not in row for column in columns)
    }
    result = {'columns': columns, 'rows': encoded_rows}
    if key_name:
        result['key_column'] = key_name
    if missing_by_row:
        result['missing_by_row'] = missing_by_row
    return result


def _indexed_records_table(records, *, key_name):
    if not isinstance(records, dict) or not records or not all(isinstance(row, dict) for row in records.values()):
        return records
    return _rows_table([{key_name: key, **row} for key, row in records.items()], key_name=key_name)


def _share_table_fields(value):
    """Factor exact common cells, without sampling rows or dropping nulls.

    Only explicitly projected transport tables are changed. Source dictionaries
    and arbitrary model facts keep their original shape. A missing field must
    never become a shared field, even when all materialized cells look null.
    """
    if isinstance(value, list):
        for item in value:
            _share_table_fields(item)
        return
    if not isinstance(value, dict):
        return
    for item in list(value.values()):
        _share_table_fields(item)
    columns, rows = value.get('columns'), value.get('rows')
    if (not isinstance(columns, list) or not columns
            or not all(isinstance(column, str) for column in columns)
            or len(set(columns)) != len(columns)
            or not isinstance(rows, list) or len(rows) < 3
            or not all(isinstance(row, list) and len(row) == len(columns) for row in rows)
            or set(value) - {'columns', 'rows', 'missing_by_row', 'key_column', 'shared_fields'}):
        return
    missing = value.get('missing_by_row', {})
    shared = {}
    indexes = []
    for index, column in enumerate(columns):
        if column == value.get('key_column') or any(index in cells for cells in missing.values()):
            continue
        cell = rows[0][index]
        # Exact serialized equality distinguishes booleans, integers and floats.
        encoded = encode(cell)
        if (len(encoded) >= 24 and (len(rows) - 1) * len(encoded) > 80
                and all(encode(row[index]) == encoded for row in rows[1:])):
            shared[column] = cell
            indexes.append(index)
    if not shared:
        return
    kept = [i for i in range(len(columns)) if i not in indexes]
    remap = {old: new for new, old in enumerate(kept)}
    value['columns'] = [columns[i] for i in kept]
    value['rows'] = [[row[i] for i in kept] for row in rows]
    value.setdefault('shared_fields', {}).update(shared)
    if missing:
        value['missing_by_row'] = {
            row: [remap[i] for i in cells] for row, cells in missing.items()
        }


def _project_chart_window_tables(bundle):
    """Encode repeated window keys once without changing the frozen projection."""
    if not isinstance(bundle, dict):
        return
    if 'series_health' in bundle:
        bundle['series_health_table'] = _rows_table(bundle.pop('series_health'))
    if 'windows' not in bundle:
        return
    windows = bundle.pop('windows')
    window_rows, change_rows = [], []
    for window_index, window in enumerate(windows):
        if not isinstance(window, dict):
            window_rows.append(window)
            continue
        compact = dict(window)
        changes = compact.pop('changes', [])
        window_rows.append(compact)
        for change in changes:
            if isinstance(change, dict):
                change_rows.append({'window_index': window_index, **change})
            else:
                change_rows.append({'window_index': window_index, 'value': change})
    bundle['windows_table'] = _rows_table(window_rows)
    bundle['changes_table'] = _rows_table(change_rows, key_name='window_index')
    matrix = bundle.get('multi_horizon') or {}
    if 'rows' in matrix:
        matrix_rows, matrix_changes = [], []
        for row_index, row in enumerate(matrix.pop('rows')):
            compact = dict(row)
            for change in compact.pop('changes', []):
                matrix_changes.append({'row_index': row_index, **change})
            matrix_rows.append(compact)
        matrix['rows_table'] = _rows_table(matrix_rows)
        matrix['changes_table'] = _rows_table(matrix_changes, key_name='row_index')
        matrix['table_projection'] = 'changes_table.row_index resolves to zero-based rows_table; all horizons and missing reasons retained.'
    bundle['table_projection'] = (
        'changes_table.window_index resolves to the zero-based row in windows_table. '
        'missing_by_row distinguishes absent fields from explicit null values.'
    )


def _project_packed_tables(payload):
    """Apply lossless row encoding only to the final LLM evidence payload."""
    profile = payload.get('report_profile')
    if profile:
        for key in ('passport', 'weekly_comparisons', 'daily_comparisons'):
            profile[key] = _rows_table(profile[key], key_name='symbol')
            _share_table_fields(profile[key])

    workflow = payload.get('gold_workflow') or {}
    delta = workflow.get('delta_vs_previous') or {}
    if 'changed_or_noncomparable_rows' in delta:
        delta['changed_or_noncomparable_table'] = _rows_table(delta.pop('changed_or_noncomparable_rows'))
    zones = workflow.get('execution_zones') or {}
    if 'zones' in zones:
        zones['zones_table'] = _rows_table(zones.pop('zones'))
    source_health = workflow.get('core_source_health') or {}
    if 'items' in source_health:
        source_health['items_table'] = _rows_table(source_health.pop('items'))

    cross = payload.get('tradingview_cross_asset') or {}
    if 'observations' in cross:
        cross['observations_table'] = _rows_table(cross.pop('observations'))
    _project_chart_window_tables(cross.get('chart_windows'))
    energy = payload.get('energy_channels') or {}
    for field in ('observations', 'tradingview_intraday'):
        if field in energy:
            energy[field + '_table'] = _rows_table(energy.pop(field))

    macro = payload.get('macro_causal') or {}
    if 'liquidity_credit' in macro:
        macro['liquidity_credit_table'] = _rows_table(macro.pop('liquidity_credit'))
    engines = macro.get('engines') or {}
    inflation = engines.get('inflation') or {}
    if 'series' in inflation:
        inflation['series_table'] = _indexed_records_table(inflation.pop('series'), key_name='series_name')
    labor_details = (macro.get('labor') or {}).get('official_details') or {}
    for field in ('metrics', 'industry_employment'):
        if field in labor_details:
            labor_details[field + '_table'] = _indexed_records_table(
                labor_details.pop(field), key_name='series_id_key'
            )

    # Keep all PA observations but stop repeating their field names per candle,
    # pivot and zone. The timeframe still owns its status/clock/permission.
    for frame in (payload.get('price_action') or {}).get('timeframes', {}).values():
        for field in ('recent_events', 'recent_pivots', 'zone_states'):
            if field in frame:
                frame[field + '_table'] = _rows_table(frame.pop(field))
    for domain in (engines.get('growth') or {}, macro.get('labor') or {}):
        if 'facts' in domain:
            domain['facts_table'] = _rows_table(domain.pop('facts'))

    # Full selected paragraphs, publisher identities and every qualification
    # remain present. Common extraction policies now occur once per table.
    mainstream = payload.get('mainstream_news') or {}
    if 'documents' in mainstream:
        mainstream['documents_table'] = _rows_table(mainstream.pop('documents'))

    # The planner calls its accumulated evidence `history`; synthesis calls
    # the same evidence `adaptive_research`. Both need the lossless projection.
    for field in ('adaptive_research', 'history'):
        adaptive = payload.get(field) or {}
        if 'market_observations' in adaptive:
            adaptive['market_observations_table'] = _rows_table(adaptive.pop('market_observations'))
        for bundle in adaptive.get('market_windows') or []:
            _project_chart_window_tables(bundle)
    if isinstance(payload.get('news_focus'), list):
        payload['news_focus_table'] = _rows_table(payload.pop('news_focus'))
    policy = engines.get('policy')
    if isinstance(policy, dict):
        engines['policy'] = _share_policy_records(policy)
    _share_table_fields(payload)
    bundles = [cross.get('chart_windows')]
    for field in ('adaptive_research', 'history'):
        bundles.extend((payload.get(field) or {}).get('market_windows') or [])
    for bundle in bundles:
        matrix = (bundle or {}).get('multi_horizon') or {}
        table = matrix.get('rows_table')
        if isinstance(table, dict) and _encode_column_runs(table):
            matrix['table_projection'] = (
                'changes_table.row_index resolves to the zero-based row in rows_table. '
                'rows_table.columns[i] names column_values[i]; a value_runs object expands '
                'ordered [value, repeat_count] pairs. shared_fields belong to every row. '
                'missing_by_row distinguishes absent fields from null. All rows, horizons, '
                'times, values and missing reasons are retained exactly.'
            )
    # Source and URL catalogs are appended afterward and also consume budget.
    if len(encode(payload)) > 150000:
        def compact_tables(value):
            changed = False
            if isinstance(value, dict):
                for child in list(value.values()):
                    changed = compact_tables(child) or changed
                changed = _encode_column_runs(value) or changed
            elif isinstance(value, list):
                for child in value:
                    changed = compact_tables(child) or changed
            return changed

        if compact_tables(payload):
            payload['table_encoding'] = (
                'A table may use column_values instead of rows. columns[i] names column_values[i]; '
                'value_runs expands ordered [value, repeat_count] pairs. shared_fields apply to '
                'every row; missing_by_row preserves absent fields separately from null. '
                'Row order, types, values and source references are unchanged.'
            )


def _encode_column_runs(table):
    """Encode repeated horizon metadata without omitting any missing window."""
    rows, columns = table.get('rows'), table.get('columns')
    if (not rows or not columns or not isinstance(rows, list) or not isinstance(columns, list)
            or not all(isinstance(column, str) for column in columns)
            or not all(isinstance(row, list) and len(row) == len(columns) for row in rows)):
        return False
    vectors = []
    for index in range(len(columns)):
        values = [row[index] for row in rows]
        runs = []
        for value in values:
            if runs and encode(runs[-1][0]) == encode(value):
                runs[-1][1] += 1
            else:
                runs.append([value, 1])
        packed = {'value_runs': runs}
        vectors.append(packed if len(encode(packed)) < len(encode(values)) else values)
    candidate = {key: value for key, value in table.items() if key != 'rows'}
    candidate['column_values'] = vectors
    if len(encode(table)) - len(encode(candidate)) < 256:
        return False
    table.clear()
    table.update(candidate)
    return True


def _compact_fedwatch_policy(policy):
    """Keep decision evidence, with meetings stored once and exact zeros omitted.

    This is a model-input projection only. Raw, normalized and API distributions
    retain all buckets; no threshold discards small but nonzero probabilities.
    """
    meetings = {m['meeting_date']: m for m in policy.get('meetings', [])}

    def compact(value, *, canonical=False):
        if isinstance(value, list):
            return [compact(child) for child in value]
        if not isinstance(value, dict):
            return value
        meeting = meetings.get(value.get('meeting_date'))
        if (not canonical and 'bins' in value and meeting is not None
                and all(key in meeting and meeting[key] == child for key, child in value.items())):
            return {'meeting_ref': value['meeting_date']}
        result = {}
        for key, child in value.items():
            aliases = {"cut_probability": "prob_below_current_target",
                       "hold_probability": "prob_at_current_target",
                       "hike_probability": "prob_above_current_target",
                       "expected_rate_pct": "implied_target_midpoint_expected_rate"}
            aliases.update({old + "_delta_pp": new + "_delta_pp" for old, new in list(aliases.items())
                            if old.endswith("probability")})
            if key in aliases and aliases[key] in value and value[aliases[key]] == child:
                continue  # API compatibility aliases add no model evidence.
            field = {'bins': 'probability', 'bin_probability_deltas_pp': 'delta_pp'}.get(key)
            if field and isinstance(child, list):
                kept = [row for row in child if not (
                    isinstance(row, dict) and type(row.get(field)) in (int, float) and row[field] == 0)]
                result[key] = compact(kept)
                if len(kept) != len(child):
                    result[key + '_omitted_exact_zero_count'] = len(child) - len(kept)
            else:
                result[key] = compact(child)
        return result

    result = compact({key: value for key, value in policy.items() if key != 'meetings'})
    result['meetings'] = [compact(meeting, canonical=True) for meeting in meetings.values()]
    result['decision_evidence_note'] = (
        'meeting_ref resolves by meeting_date in meetings. Only explicitly observed exact-zero '
        'probability/delta buckets are omitted and counted; nonzero tails, nulls and missing '
        'history remain distinct. Absence is never evidence of zero. Full grids remain in '
        'the source snapshot; all policy expectations and comparisons were computed before projection.'
    )
    return result


def _share_policy_records(policy):
    """Losslessly share repeated meeting/distribution objects after source packing.

    Policy horizons and comparisons frequently contain the same complete
    meeting. Keep every distinct value; references form an acyclic graph.
    This runs after source resolution so source_ids keep their normal meaning.
    """
    def column_table(rows):
        table = _rows_table(rows)
        vectors = [[row[i] for row in table['rows']] for i in range(len(table['columns']))]
        encoded = []
        for values in vectors:
            runs = []
            for cell in values:
                if runs and encode(runs[-1][0]) == encode(cell):
                    runs[-1][1] += 1
                else:
                    runs.append([cell, 1])
            packed = {'value_runs': runs}
            encoded.append(packed if len(encode(packed)) < len(encode(values)) else values)
        return {**{k: v for k, v in table.items() if k != 'rows'}, 'column_values': encoded}

    def tables(value):
        if isinstance(value, dict):
            children = {key: tables(child) for key, child in value.items()}
            # Comparisons such as 1d/1w/1m are keyed records, not lists.
            # Preserve their keys while sharing repeated statistical columns.
            if (len(children) >= 3
                    and all(isinstance(child, dict) and child for child in children.values())):
                common = set.intersection(*(set(child) for child in children.values()))
                if len(common) >= 2:
                    candidate = {'policy_mapping_table': {
                        'keys': list(children), **column_table(list(children.values()))}}
                    if len(encode(children)) - len(encode(candidate)) >= 256:
                        return candidate
            return children
        if isinstance(value, list):
            children = [tables(child) for child in value]
            if (len(children) >= 3 and all(isinstance(child, dict) for child in children)
                    and any(children)):
                return {'policy_columns_table': column_table(children)}
            return children
        return value

    policy = tables(policy)
    counts = Counter()

    def count(value):
        if not isinstance(value, (dict, list, str)):
            return
        serialized = encode(value)
        if len(serialized) >= 128:
            counts[serialized] += 1
        if isinstance(value, str):
            return
        for child in (value.values() if isinstance(value, dict) else value):
            count(child)

    count(policy)
    records = {}
    identifiers = {}

    def project(value, *, share=True):
        if not isinstance(value, (dict, list, str)):
            return value
        serialized = encode(value)
        if share and counts[serialized] > 1:
            # Local references need no repeated content hash; the complete
            # request already has an audited hash and exact value comparison.
            identifier = identifiers.setdefault(serialized, f'p{len(identifiers)}')
            if identifier not in records:
                records[identifier] = project(value, share=False)
            return {'policy_ref': identifier}
        if isinstance(value, dict):
            return {key: project(child) for key, child in value.items()}
        if isinstance(value, str):
            return value
        return [project(child) for child in value]

    result = project(policy, share=False)
    result['shared_policy_records'] = records
    result['policy_projection'] = (
            'policy_ref resolves within shared_policy_records in this policy engine, recursively. '
            'policy_columns_table encodes an ordered object list: columns[i] names column_values[i]; '
            'policy_mapping_table uses the same columns plus keys: row i is the object at keys[i]; '
            'value_runs contains ordered [value, repeat_count] pairs, including explicit zeros/nulls; '
            'missing_by_row marks absent column indexes, not null values. '
            'All meeting distributions, dates, comparisons and qualifications are retained exactly; '
            'only identical repeated objects are stored once. source_ids still resolve in source_catalog.'
    )
    return result


def project_options(options):
    """Project only CME facts that can change the final research judgment.

    Full strike grids, repeated selection/semantics blocks and low-confidence
    roll candidates remain in the immutable options artifact.
    """
    data = options.get('data') or {}
    source = data.get('data_source') or {}
    selection = data.get('expiry_selection') or source.get('expiry_selection') or {}
    gex = data.get('gex') or {}
    semantics = data.get('gex_semantics') or gex.get('semantics') or {}
    parameters = data.get('parameters') or {}
    reconciliation = data.get('reconciliation') or source.get('reconciliation') or {}
    concentration = data.get('oi_gamma_concentration_zone') or gex.get('oi_gamma_concentration_zone') or {}
    selected_expiries = list(selection.get('selected_expiries') or source.get('expiries') or semantics.get('selected_expiries') or [])

    by_expiry = {}
    for expiry, expiry_data in (gex.get('by_expiry') or {}).items():
        if selected_expiries and expiry not in selected_expiries:
            continue
        summary = expiry_data.get('summary') or {}
        skew = expiry_data.get('iv_skew') or {}
        by_expiry[expiry] = {
            'f_value': summary.get('f_value'),
            'structure': summary.get('structure'),
            'proxy_gamma_flip': {
                'price': summary.get('gamma_zero'),
                'method': summary.get('gamma_zero_method'),
            },
            'oi_signed_gex_proxy': {
                'net': summary.get('net_gex_signed', summary.get('net_gex')),
                'call': summary.get('call_gex_signed', summary.get('call_gex')),
                'put': summary.get('put_gex_signed'),
                'legacy_put_absolute': summary.get('put_gex') if 'put_gex_signed' not in summary else None,
                'total_absolute': summary.get('total_gex'),
            },
            'iv_skew': {
                key: skew.get(key) for key in (
                    'atm_iv', 'skew_25d', 'tail_skew_10d', 'interpretation'
                ) if key in skew
            },
        }

    all_expiries = selection.get('all_expiries') or selection.get('eligible_expiries') or []
    selection_policy = selection.get('selection_policy') or {}
    coverage = selection.get('coverage') or {}
    flip = gex.get('gamma_flip') or {}
    concentration_levels = [
        {key: level.get(key) for key in (
            'expiry', 'strike', 'open_interest', 'absolute_gamma_exposure', 'net_gex'
        ) if key in level}
        for level in list(concentration.get('levels') or [])[:5]
    ]
    roll_signals = [
        signal for signal in data.get('roll_signals', [])
        if isinstance(signal.get('confidence'), (int, float))
        and signal['confidence'] >= CME_ROLL_SIGNAL_MIN_CONFIDENCE
    ]
    reconciliation_delta = reconciliation.get('delta') or {}
    data_quality = data.get('data_quality') or {}
    quality_categories = data_quality.get('categories') or {}

    return {
        'schema_version': 'cme_research_projection.v2',
        'status': options.get('status'),
        'reason': options.get('reason'),
        'trade_date': data.get('trade_date') or source.get('report_date'),
        'source': {
            'status': source.get('status'),
            'version': source.get('version'),
            'report_date': source.get('report_date'),
            'product': source.get('product'),
            'feature_revision': source.get('feature_revision'),
            'analysis_row_count': source.get('row_count'),
            'source_refs': data.get('selected_source_refs') or source.get('source_refs') or [],
        },
        'data_quality': {
            'warnings': data_quality.get('warnings', []),
            'rows_missing_delta': quality_categories.get('rows_missing_delta'),
            'proxy_strikes': quality_categories.get('proxy_strikes'),
            'prelim_rows': quality_categories.get('prelim_data'),
        },
        'expiry_window': {
            'selected_expiries': selected_expiries,
            'selected_row_count': selection.get('selected_row_count'),
            'available_expiry_count': len(all_expiries),
            'selected_open_interest': selection.get('selected_open_interest'),
            'eligible_open_interest': selection.get('eligible_open_interest'),
            'open_interest_coverage': selection.get('open_interest_coverage', coverage.get('open_interest')),
            'row_coverage': selection.get('row_coverage', coverage.get('rows')),
            'expiry_date_source': {
                expiry: selection_policy.get('expiry_date_source', {}).get(expiry)
                for expiry in selected_expiries
            },
            'front_active_option_expiry': selection_policy.get('front_active_option_expiry'),
            'front_active_future_status': selection_policy.get('front_active_future_status'),
            'selected_is_full_chain': selection_policy.get('selected_is_full_chain'),
        },
        'semantics': {
            key: semantics.get(key) for key in (
                'label', 'method', 'scope', 'dealer_position_unknown',
                'settlement_implied_black76_gamma_available', 'position_sign_inference',
                'black76_gex_unit', 'gamma_proxy_row_count', 'shape_proxy_included_in_usd_gex',
                'shape_proxy_included_in_gamma_flip', 'interpretation'
            ) if key in semantics
        },
        'coordinate_policy': {
            'instrument': 'GC futures options',
            'xauusd_mapping': 'unavailable_without_verified_basis',
            'model': parameters.get('model'),
            'forward_source': parameters.get('f_source'),
            'risk_free_rate': parameters.get('r'),
            'analysis_range': parameters.get('analysis_range'),
            'live_price_anchor_available': parameters.get('live_p0') is not None,
        },
        'aggregate_proxy_gamma_flip': {
            key: flip.get(key) for key in (
                'label', 'price', 'method', 'scope', 'dealer_position_unknown'
            ) if key in flip
        },
        'by_expiry': by_expiry,
        'concentration': {
            'label': concentration.get('label'),
            'scope': concentration.get('scope'),
            'selected_expiries': concentration.get('selected_expiries'),
            'levels': concentration_levels,
            'omitted_level_count': max(0, len(concentration.get('levels') or []) - len(concentration_levels)),
            'limitations': concentration.get('limitations', []),
        },
        'reconciliation': {
            'status': reconciliation.get('status'),
            'current_selection': reconciliation.get('current_selection'),
            'report_date': reconciliation.get('report_date'),
            'comparison_available': reconciliation_delta.get('comparison_available'),
            'changed': reconciliation_delta.get('changed'),
            'added_in_final': reconciliation_delta.get('added_in_final'),
            'removed_from_final': reconciliation_delta.get('removed_from_final'),
            'source_refs': reconciliation.get('source_refs', []),
        },
        'roll_signals': roll_signals,
        'omitted_low_confidence_roll_signal_count': len(data.get('roll_signals', [])) - len(roll_signals),
        'roll_display_min_confidence': CME_ROLL_SIGNAL_MIN_CONFIDENCE,
        'projection_note': 'Full strike chain, price grid, repeated blocks, raw wall candidates and low-confidence roll signals remain in the immutable CME artifact; snapshot_detail can expand selected expiry or gamma_grid during research, before final freeze.',
    }


def input_metrics(payload):
    serialized = encode(payload)
    return {'characters': len(serialized), 'utf8_bytes': len(serialized.encode()),
            'sha256': sha256(serialized.encode()).hexdigest(),
            'contract': payload.get('input_contract'), 'unit': 'characters_not_tokens',
            'section_characters': {key: len(encode(value)) for key, value in payload.items()}}


def bounded_review(analysis, evidence, questions, *, max_chars=240000):
    payload = {'questions': questions, 'analysis': analysis, 'evidence': evidence}
    payload['input_contract'] = {'version': RESEARCH_INPUT_CONTRACT_VERSION, 'stage': 'review',
                                  'truncation': False, 'size_limit_chars': max_chars}
    if len(encode(payload)) > max_chars:
        raise ResearchInputTooLarge('review: input budget exceeded; no silent truncation')
    return payload
