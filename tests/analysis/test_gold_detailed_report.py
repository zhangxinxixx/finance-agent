"""Detailed reader contracts using independent frozen-shaped test data."""
from copy import deepcopy
from types import SimpleNamespace
import json

import pytest

from apps.analysis.agents.research_input import (
    detailed_report_profile, detailed_comparison, DETAILED_TOPICS,
    ResearchInputTooLarge,
)
from apps.analysis.agents.research_synthesis import (
    _build_prompt_payload, _parse_and_validate, enrich_research_coordinator,
)
from apps.renderer.markdown.gold_reader import reader_sections, render_reader_report
from tests.analysis.test_research_synthesis import _output
from tests.analysis.test_daily_research import _snapshot as legacy_snapshot
from apps.features.research.workflow import build_gold_workflow


def archived_snapshot():
    ref = {'source': 'treasury_rates', 'source_url': 'https://home.treasury.gov/fixture',
           'observation_date': '2026-10-01', 'retrieved_at': '2026-10-04T07:00:00Z'}
    return {'snapshot_id': 'detailed-fixture', 'trade_date': '2026-10-04',
            'snapshot_time': '2026-10-04T07:12:00Z',
            'daily_research': {'passport': [
                {'symbol': 'US10Y', 'label': '10Y', 'unit': '%', 'value': 5.24001,
                 'observation_date': '2026-10-01', 'previous_value': 5.2,
                 'previous_date': '2026-09-30', 'change': .04001,
                 'weekly_anchor_date': '2026-09-24', 'weekly_anchor_value': 5.1,
                 'weekly_change': .14001, 'status': 'fresh', 'lineage_status': 'verified',
                 'source_refs': [ref]}],
                 'market_session': {'new_intraday_confirmation_allowed': False}},
            'technical': {'price': 4100.12345, 'as_of': '2026-10-02', 'source_refs': [{'source': 'OTC', 'source_url': 'https://example.org/history'}]},
            'options': {'status': 'available', 'data': {'trade_date': '2026-10-02',
                'data_source': {'version': 'PRELIM', 'source_refs': [{'source': 'CME', 'report_date': '2026-10-02'}]},
                'walls': {'block_pnt_walls': [{'strike': 4300, 'expiry': 'NOV26', 'open_interest': 200, 'delta_oi': 0, 'block': 0}]}}},
            'gold_workflow': {'schema_version': 'gold_workflow.v2', 'reader_report_version': 'gold_reader.v4',
                'quality_gate': {'data_quality': 'Partial', 'publish_allowed': False},
                'price_anchor': {'daily_close': 4100.12345, 'daily_close_date': '2026-10-02', 'status': 'historical'},
                'state_record': {'accepted_state': None, 'candidate_state': 'S4', 'transition_confirmed': False},
                'key_levels': [{'instrument': 'XAUUSD spot', 'price': 4100, 'source_date': '2026-10-02', 'status': 'Watch'},
                               {'instrument': 'GC futures', 'price': 4300, 'source_date': '2026-10-02', 'status': 'Retired'}],
                'execution': {'timeframe_features': [{'timeframe': '5m', 'close': 111}, {'timeframe': '15m', 'status': 'unavailable'}]}}}


def snapshot():
    data = archived_snapshot()
    data['daily_research']['passport'].append({
        'symbol': 'XAUUSD_DAILY', 'value': 4100.12345, 'unit': 'USD/oz',
        'status': 'fresh', 'lineage_status': 'verified', 'frequency': 'daily',
        'observation_date': '2026-10-02', 'source_refs': [{
            'source': 'twelvedata_xauusd_daily', 'symbol': 'XAUUSD', 'instrument_type': 'spot',
            'source_url': 'https://example.test/xauusd', 'raw_path': 'raw/spot-fixture.json',
            'retrieved_at': '2026-10-04T07:00:00Z'}]})
    return data


def response():
    texts = {
        'facts': '本范围记录了明确的观察窗口，判断只引用输入保存事实，不从其他报告借入数字。',
        'transmission': '压力可能通过折现与资金配置渠道影响黄金，因果强度仍取决于同窗口证据的完整性。',
        'response': '已收盘历史可以用于复盘，但没有同步事件价格材料时不能确认新的响应或实时信号。',
        'alternatives': '需要比较政策预期、仓位调整与其他风险渠道，现有材料不足以识别唯一交易主体。',
        'judgment': '当前保留条件式研究判断，对局部有效证据展开解释，不将候选解释升级为正式状态。',
        'falsification': '若后续同步窗口表现与此判断相反，且原始来源通过核验，应重新评估主导解释。',
    }
    modules = {key: {**texts, 'evidence_ids': ['detailed:' + key],
                     'pending': ['仍缺同步价格或完整发布窗口，不能确认本模块因果链的全部环节。']}
               for key in DETAILED_TOPICS}
    modules['scenarios']['paths'] = {name: {key: '等待同窗口原始证据补齐后再确认该条件。' for key in
        ('macro', 'funds', 'price', 'region', 'trigger', 'invalidation', 'window')} for name in ('main', 'up', 'down')}
    modules['observation']['cards'] = {name: {key: '休市无新确认，待已收盘结构与区域核验。' for key in
        ('4H', '1H', '15m', 'invalidation')} for name in ('flat', 'long', 'short')}
    return {'dominant_factor': '保留条件研究判断', 'counter_evidence': [],
            'state_limitations': [], 'convergence_transition': [],
            'evidence_ids': ['detailed:real_rates'], 'report_sections': modules}


def test_rich_profile_and_reader_preserve_exact_observations_and_dates():
    data = snapshot()
    before = deepcopy(data)
    payload = _build_prompt_payload(data, _output())
    assert payload['report_profile']['version'] == 'gold_reader.v4'
    passport = payload['report_profile']['passport']
    assert passport['rows'][0][passport['columns'].index('value')] == 5.24001
    parsed = _parse_and_validate(json.dumps(response(), ensure_ascii=False), payload)
    synthesis = {'status': 'success', 'analysis': parsed, 'evidence_ids': response()['evidence_ids']}
    sections = reader_sections(data, {'coordinator': SimpleNamespace(input_payload={'research_synthesis': synthesis})}, {})
    md = render_reader_report(data, sections)
    assert '5.24001' in md and '2026-09-24 / 5.1' in md
    assert '2026-10-01 / 5.24001' in md
    assert '2026-10-02 / 5.24001' not in md
    assert 'Accepted尚未初始化' in md
    assert 'Retired' in md and 'Watch' in md
    assert '主路径' in md and '上行路径' in md and '下行路径' in md
    assert '已有多单' in md and '已有空单' in md and '空仓' in md
    assert len([s for s in sections if s['section_id'].startswith('detailed_')]) == len(DETAILED_TOPICS) + 5
    assert data == before
    rate = next(s for s in sections if s['section_id'] == 'detailed_real_rates')
    assert all(r['source'] == 'treasury_rates' for r in rate['source_refs'])
    assert 'OTC' not in str(rate['source_refs'])


def test_actual_passport_symbols_reach_each_detailed_topic():
    data = snapshot()
    for symbol in ('BROAD_DOLLAR', 'ON_RRP_USAGE', 'WTI_SPOT', 'BRENT_SPOT'):
        data['daily_research']['passport'].append({'symbol': symbol, 'value': 1,
            'source_refs': [{'source': 'fixture', 'symbol': symbol}]})
    modules = detailed_report_profile(data)['modules']
    expected = {'dollar': {'BROAD_DOLLAR'}, 'liquidity': {'ON_RRP_USAGE'},
                'oil': {'WTI_SPOT', 'BRENT_SPOT'}}
    for topic, symbols in expected.items():
        supplied = {r['symbol'] for r in modules[topic]['evidence']['observations']}
    assert symbols <= supplied


def test_concise_reader_keeps_exact_facts_and_full_audit_reasoning():
    from apps.renderer.markdown.gold_reader import reader_audit_details

    data = snapshot()
    data['gold_workflow']['reader_presentation'] = 'gold_reader.concise.v1'
    data['input_validation'] = {'status': 'partial', 'domains': {'options': {'status': 'unavailable'}}}
    synthesis = {'status': 'success', 'analysis': response(), 'evidence_ids': response()['evidence_ids'],
                 'macro_review': {'status': 'pass'}}
    outputs = {'coordinator': SimpleNamespace(input_payload={'research_synthesis': synthesis})}
    before = deepcopy(data)
    concise = render_reader_report(data, reader_sections(data, outputs, {}))
    audit = reader_audit_details(data, outputs)
    assert '5.24001' in concise and '2026-10-01' in concise
    assert '未通过' in concise and '尚未初始化' in concise and '期权' in concise
    assert '上行' in concise and '下行' in concise and 'audit_report.md' in concise
    assert len(concise) < len(audit) / 3
    assert response()['report_sections']['labor']['transmission'] in audit
    assert '2026-09-24 / 5.1' in audit
    assert data == before


def test_oi_display_does_not_hide_large_positions_behind_strike_order():
    from apps.analysis.agents.research_input import _detailed_walls
    from apps.renderer.markdown.gold_detailed import record_table

    rows = [{'expiry': expiry, 'strike': i, 'oi': i + 1, 'block': 0, 'pnt': None}
            for expiry in ('NOV26', 'DEC26') for i in range(12)]
    before = deepcopy(rows)
    projection = _detailed_walls({'walls': {'call_oi_walls': rows}})
    selected = projection['call_oi_walls']
    assert len(selected) == 8
    assert {r['oi'] for r in selected} == {9, 10, 11, 12}
    assert projection['call_oi_walls_omitted_count'] == 16
    table = record_table(selected, ('strike', 'oi', 'block', 'pnt'))
    assert '缺失不视为零' in table and '| 0 |' in table
    assert rows == before


@pytest.mark.parametrize('field,value,reason', [
    ('weekly_anchor_date', '2026-02-30', 'missing_or_invalid_dates'),
    ('observation_date', '2026-10-05', 'unordered_or_future_endpoints'),
    ('weekly_anchor_date', '2026-10-01', 'unordered_or_future_endpoints'),
    ('weekly_anchor_value', None, 'missing_or_invalid_numeric_endpoint_or_change'),
    ('value', True, 'missing_or_invalid_numeric_endpoint_or_change'),
    ('weekly_change', float('inf'), 'missing_or_invalid_numeric_endpoint_or_change'),
    ('lineage_status', 'unverified', 'unverified_observation_or_lineage'),
    ('source_refs', [], 'missing_source_refs'),
])
def test_invalid_comparisons_fail_closed_without_reconstructing_endpoints(field, value, reason):
    row = snapshot()['daily_research']['passport'][0]
    row[field] = value
    result = detailed_comparison(row, cutoff='2026-10-04')
    assert not result['comparison_allowed'] and reason in result['constraints']
    assert result['start_value'] == row['weekly_anchor_value']


def test_zero_change_and_nonfriday_window_are_valid_but_async_components_are_not():
    row = snapshot()['daily_research']['passport'][0]
    row['weekly_change'] = 0
    row['weekly_anchor_value'] = row['value']
    assert detailed_comparison(row, cutoff='2026-10-04')['comparison_allowed']
    row['components'] = [{'observation_date': '2026-09-30', 'weekly_anchor_date': '2026-09-24'}]
    assert not detailed_comparison(row, cutoff='2026-10-04')['comparison_allowed']


def test_weekend_preserves_history_and_prelim_oi_without_missing_pnt_zero():
    profile = detailed_report_profile(snapshot())
    assert profile['modules']['market_evolution']['evidence']['technical']['as_of'] == '2026-10-02'
    walls = profile['modules']['options']['evidence']['walls']['block_pnt_walls']
    assert walls[0]['open_interest'] == 200 and walls[0]['block'] == 0
    assert 'pnt' not in walls[0]
    assert profile['modules']['options']['evidence']['projection']['source']['version'] == 'PRELIM'
    assert '111' not in str(profile['modules']['observation'])


def test_partial_missing_sources_and_model_fallback_do_not_claim_complete_report():
    data = snapshot()
    data['options'] = {}
    profile = detailed_report_profile(data)
    assert profile['modules']['options']['availability'] == 'missing'
    sections = reader_sections(data, {}, {})
    assert '待完成' in sections[0]['body']
    assert not any('**研究判断**' in s['body'] for s in sections)


@pytest.mark.parametrize('mutation', ['empty', 'unknown', 'missing_topic', 'paths', 'pending', 'authority', 'too_long'])
def test_v4_model_contract_rejects_incomplete_or_unauthorized_outputs(mutation):
    data, result = snapshot(), response()
    if mutation == 'empty':
        result['report_sections']['oil']['judgment'] = '不可用'
    elif mutation == 'unknown':
        result['report_sections']['oil']['evidence_ids'] = ['made_up']
    elif mutation == 'missing_topic':
        del result['report_sections']['credit']
    elif mutation == 'paths':
        del result['report_sections']['scenarios']['paths']['down']
    elif mutation == 'pending':
        result['report_sections']['flows']['pending'] = []
    elif mutation == 'authority':
        result['accepted_state'] = 'S5'
    else:
        result['report_sections']['oil']['facts'] = '数' * 4001
    with pytest.raises(ValueError):
        _parse_and_validate(json.dumps(result), _build_prompt_payload(data, _output()))


def test_single_repair_and_v4_token_budget_leave_hard_fields_unchanged():
    data, original = snapshot(), _output()
    before = deepcopy(data)
    calls = []
    def gateway(**kwargs):
        calls.append(kwargs)
        return {'content': json.dumps({'wrong': 'output'} if len(calls) == 1 else response())}
    result = enrich_research_coordinator(data, original, gateway)
    meta = result.input_payload['research_synthesis']
    assert len(calls) == 2 and all(c['max_tokens'] == 32000 for c in calls)
    assert meta['status'] == 'success' and meta['report_coverage']['prose_contract'] == 'complete'
    assert meta['report_coverage']['financial_evidence']['flows'] == 'missing'
    for field in ('bias', 'status', 'accepted_state_conclusion'):
        assert getattr(result, field) == getattr(original, field)
    assert data == before


def test_invalid_twice_falls_back_and_never_retries_endlessly():
    calls = []
    def gateway(**kwargs):
        calls.append(kwargs)
        return {'content': '{"wrong":"output"}'}
    result = enrich_research_coordinator(snapshot(), _output(), gateway)
    assert len(calls) == 2
    assert result.input_payload['research_synthesis']['status'] == 'rule_fallback'


def test_input_overflow_is_explicit_no_gateway_or_silent_truncation():
    data = snapshot()
    data['technical']['explanation'] = '原始材料' * 60000
    with pytest.raises(ResearchInputTooLarge):
        _build_prompt_payload(data, _output())
    result = enrich_research_coordinator(data, _output(), lambda **k: pytest.fail('must not call gateway'))
    assert result.input_payload['research_synthesis']['failure_reason'] == 'ResearchInputTooLarge'


def test_legacy_versions_retain_existing_rendering_and_do_not_receive_profile():
    for version in ('gold_reader.v1', 'gold_reader.v2', 'gold_reader.v3'):
        data = legacy_snapshot()
        data['gold_workflow'] = build_gold_workflow(data)
        data['gold_workflow']['reader_report_version'] = version
        payload = _build_prompt_payload(data, _output())
        assert 'report_profile' not in payload
        coordinator = SimpleNamespace(input_payload={'research_synthesis': {'status': 'success', 'analysis': {'reader_narrative': '旧版完整正文。'}}})
        sections = reader_sections(data, {'coordinator': coordinator}, {})
        assert all(not s['section_id'].startswith('detailed_') for s in sections)
        assert '旧版完整正文。' in render_reader_report(data, sections)


def test_endpoint_contract_change_and_false_source_date_fail_closed():
    row = snapshot()['daily_research']['passport'][0]
    row['current_source'] = {'source': 'CME', 'contract_code': 'GCZ26'}
    row['weekly_anchor_source'] = {'source': 'CME', 'contract_code': 'GCV26'}
    assert 'endpoint_source_or_contract_changed' in detailed_comparison(row, cutoff='2026-10-04')['constraints']
    row.pop('current_source')
    row.pop('weekly_anchor_source')
    row['source_refs'][0]['observation_date'] = '2026-10-02'
    assert 'source_observation_date_mismatch' in detailed_comparison(row, cutoff='2026-10-04')['constraints']


def test_v4_macro_review_revision_is_bounded_and_keeps_original_state():
    data = snapshot()
    data['gold_workflow']['macro_causal'] = {'schema_version': 'gold_macro_causal.v4'}
    body = response()
    body.update({
        'macro_answers': {k: '局部证据允许条件推演，缺失环节仍待核验。' for k in
                          ('growth', 'inflation', 'reaction', 'policy', 'treasury', 'oil', 'response', 'residual')},
        'macro_narrative': {k: '证据不足，候选解释不能升级为确定因果。' for k in
                           ('growth', 'inflation', 'labor', 'fed', 'treasury', 'term_premium', 'fiscal', 'dollar', 'liquidity', 'credit', 'oil')},
        'dominant_shocks': {k: '暂无充分同步证据。' for k in ('primary', 'secondary', 'counter')},
    })
    original = _output()
    before = deepcopy(data)
    calls = []
    def gateway(**kwargs):
        calls.append(kwargs)
        if kwargs['audit_context']['caller'] == 'macro_causal_reviewer':
            count = len(json.loads(kwargs['messages'][1]['content'])['questions'])
            content = {'checks': [{'id': i, 'passed': i != 0, 'reason': '仍缺独立因果证据'} for i in range(count)]}
        else:
            content = body
        return {'content': json.dumps(content)}
    result = enrich_research_coordinator(data, original, gateway)
    meta = result.input_payload['research_synthesis']
    assert len(calls) == 4  # synthesis, review, one revision, second review
    assert meta['status'] == 'success' and meta['macro_review']['revision_attempts'] == 1
    assert meta['macro_review']['status'] == 'needs_revision'
    assert result.confidence == original.confidence * .7
    assert result.accepted_state_conclusion == original.accepted_state_conclusion
    assert data == before


def test_v4_missing_optional_research_is_renderable_and_fixture_artifact_is_separate(tmp_path):
    data = snapshot()
    del data['daily_research']
    sections = reader_sections(data, {}, {})
    report = render_reader_report(data, sections)
    assert '契约未通过' in report and 'Accepted尚未初始化' in report
    # Temporary artifact is explicitly a test fixture, never a real market report.
    target = tmp_path / 'fixture_gold_reader_v4.md'
    target.write_text('# TEST FIXTURE ONLY\n\n' + report, encoding='utf-8')
    assert target.stat().st_size > 0
    assert target.read_text(encoding='utf-8').startswith('# TEST FIXTURE ONLY')


def test_large_chain_and_repeated_audit_are_explicitly_projected_not_dumped():
    from apps.analysis.agents.research_input import encode
    data = snapshot()
    wall = {'strike': 4300.12345, 'expiry': 'NOV26', 'oi': 200, 'oi_change': 0,
            'block': 0, 'volume': 14, 'side': 'Call', 'wall_type': 'Static'}
    data['options']['data']['walls']['call_oi_walls'] = [deepcopy(wall) for _ in range(4000)]
    audit = {'source': 'cme_daily_bulletin', 'report_date': '2026-10-02',
             'source_url': 'https://www.cmegroup.com/fixture', 'raw_path': 'AUDIT_ONLY_MARKER' * 500}
    for level in data['gold_workflow']['key_levels']:
        level['source_refs'] = [deepcopy(audit) for _ in range(40)]
        level['raw_level'] = {'nested_chain': [deepcopy(wall) for _ in range(1000)]}
    data['gold_workflow']['state_record']['source_refs'] = [deepcopy(audit) for _ in range(40)]
    before = deepcopy(data)
    profile = detailed_report_profile(data)
    walls = profile['modules']['options']['evidence']['walls']
    assert walls['call_oi_walls_omitted_count'] == 3996
    assert len(walls['call_oi_walls']) == 4
    assert walls['call_oi_walls'][0] == wall
    assert 'pnt' not in walls['call_oi_walls'][0]
    payload = _build_prompt_payload(data, _output())
    assert len(encode(payload)) < 200000
    report = render_reader_report(data, reader_sections(data, {}, {}))
    assert len(report) < 120000
    assert '4300.12345' in report and '3996' in report
    assert 'AUDIT_ONLY_MARKER' not in report and 'nested_chain' not in report
    assert data == before


def test_curated_cot_calendar_and_source_tables_use_actual_snapshot_fields():
    data = snapshot()
    data['daily_research']['cot_reports'] = {'futures_only': {
        'report_type': 'futures_only', 'report_date': '2026-09-29', 'previous_report_date': '2026-09-22',
        'managed_money': {'latest': {'long': 131711, 'short': 11393, 'net': 120318, 'unit': 'contracts'},
                          'previous': {'long': 135699, 'short': 8310, 'net': 127389},
                          'delta': {'long': -3988, 'short': 3083, 'net': -7071}},
        'open_interest': {'value': 406456, 'previous': 412800, 'delta': -6344, 'unit': 'contracts'}}}
    data['news'] = {'data': {'official_calendar': {'time_precision': 'day', 'events': [
        {'title': 'CPI release', 'start_date': '2026-10-14', 'end_date': '2026-10-14',
         'time_precision': 'day', 'time_status': 'unavailable', 'verification_status': 'official_confirmed'}]}}}
    sections = reader_sections(data, {}, {})
    flows = next(r['body'] for r in sections if r['section_id'] == 'detailed_flows')
    assert all(str(v) in flows for v in (131711, 11393, -3988, 406456, -6344))
    calendar = next(r['body'] for r in sections if r['section_id'] == 'detailed_calendar')
    assert '2026-10-14' in calendar and 'day' in calendar and 'unavailable' in calendar
    assert '08:30' not in calendar


def test_real_shape_acceptance_budget_and_immutable_reader_when_supplied():
    import os
    from pathlib import Path
    from apps.analysis.agents.research_input import encode, bounded_review
    path = os.environ.get('GOLD_DETAILED_ACCEPTANCE_SNAPSHOT')
    if not path:
        pytest.skip('Independent real snapshot is supplied by acceptance environment only')
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    data['gold_workflow']['reader_report_version'] = 'gold_reader.v4'
    before = deepcopy(data)
    payload = _build_prompt_payload(data, _output())
    report = render_reader_report(data, reader_sections(data, {}, {}))
    assert len(encode(payload)) <= 200000
    assert len(report) < 120000
    assert len(payload['report_profile']['modules']) == 20
    assert '5.24' in report and '2026-10-01' in report
    assert '541982' in report and '2026-09-29' in report
    assert 'PRELIM' in report and 'GC期货' in report
    assert 'Accepted尚未初始化' in report
    assert '2026-10-14' in report
    review = bounded_review(response(), payload, ['test'])
    assert len(encode(review)) <= 240000
    assert data == before
    body = response()
    body.update({
        'macro_answers': {k: '局部证据允许条件推演，缺失环节仍待核验。' for k in
                          ('growth', 'inflation', 'reaction', 'policy', 'treasury', 'oil', 'response', 'residual')},
        'macro_narrative': {k: '证据不足，候选解释不能升级为确定因果。' for k in
                           ('growth', 'inflation', 'labor', 'fed', 'treasury', 'term_premium', 'fiscal', 'dollar', 'liquidity', 'credit', 'oil')},
        'dominant_shocks': {k: '暂无充分同步证据。' for k in ('primary', 'secondary', 'counter')},
    })
    calls = []
    def gateway(**kwargs):
        calls.append(kwargs)
        content = ({'checks': [{'id': i, 'passed': True, 'reason': '测试审阅'}
                               for i in range(len(json.loads(kwargs['messages'][1]['content'])['questions']))]}
                   if kwargs['audit_context']['caller'] == 'macro_causal_reviewer' else body)
        return {'content': json.dumps(content)}
    result = enrich_research_coordinator(data, _output(), gateway)
    assert result.input_payload['research_synthesis']['status'] == 'success'
    assert len(calls) == 2
    assert calls[0]['max_tokens'] == 32000
    assert len(encode(calls[0]['audit_context']['input_payload'])) <= 200000
    assert data == before


def test_reader_unknown_claim_id_is_not_authorized_by_claim_itself():
    data, body = snapshot(), response()
    body['report_sections']['oil']['evidence_ids'].append('fabricated_source')
    synthesis = {'status': 'success', 'analysis': body, 'evidence_ids': ['fabricated_source']}
    coordinator = SimpleNamespace(input_payload={'research_synthesis': synthesis})
    sections = reader_sections(data, {'coordinator': coordinator}, {})
    assert '待完成' in sections[0]['body']
    assert all('**研究判断**' not in s['body'] for s in sections)


def test_pending_text_counts_toward_total_prose_budget():
    result = response()
    for section in result['report_sections'].values():
        section['pending'] = ['待核验' * 500] * 4
    with pytest.raises(ValueError, match='total prose budget'):
        _parse_and_validate(json.dumps(result), _build_prompt_payload(snapshot(), _output()))


def test_supplied_strike_delta_and_settlement_remain_exact_without_dealer_inference():
    data = snapshot()
    row = {'strike': 4100, 'expiry': 'NOV26', 'side': 'Put', 'open_interest': 2183,
           'delta_oi': 223, 'delta': -.37261234, 'settlement': 98.1234, 'block': 200}
    data['options']['data']['strike_metrics'] = [deepcopy(row) for _ in range(100)]
    profile = detailed_report_profile(data)
    metrics = profile['modules']['options']['evidence']['strike_metrics']
    assert metrics['rows'][0] == row and metrics['omitted_count'] == 84
    assert 'pnt' not in metrics['rows'][0]
    report = render_reader_report(data, reader_sections(data, {}, {}))
    assert '-0.37261234' in report and '98.1234' in report and '84' in report
    assert 'dealer方向未知' in report


def test_reader_preserves_concentration_separately_from_filtered_wall_candidates():
    data = snapshot()
    data['options']['data']['oi_gamma_concentration_zone'] = {
        'scope': 'selected_expiry_window', 'selected_expiries': ['DEC26'],
        'levels': [{'expiry': 'DEC26', 'strike': 5000, 'open_interest': 12656,
                    'absolute_gamma_exposure': 43132907.0896, 'net_gex': 39673774.7377}],
        'limitations': ['公开持仓集中不识别dealer方向'],
    }
    data['options']['data']['walls']['call_oi_walls'] = [
        {'strike': 5150, 'expiry': 'DEC26', 'side': 'CALL', 'oi': 986, 'oi_change': 0}]
    report = render_reader_report(data, reader_sections(data, {}, {}))
    assert '所选窗口OI/Gamma集中记录（独立于墙候选）' in report
    assert '12656' in report and '43132907.0896' in report and '39673774.7377' in report
    assert '不代表完整期权链中最大的四个持仓' in report
    assert '本组未保存：OI持仓' not in report
    assert '本组未保存：OI变化' not in report
