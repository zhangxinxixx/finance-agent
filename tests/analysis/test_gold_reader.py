from types import SimpleNamespace

import pytest

from apps.features.research.workflow import build_gold_workflow
from apps.output.final_report import write_final_report
from apps.renderer.markdown.gold_reader import reader_sections, render_reader_report
from tests.analysis.test_daily_research import _snapshot


def test_reader_preserves_model_selected_subject_without_fixed_topic_sections():
    snapshot = _snapshot()
    snapshot['gold_workflow'] = build_gold_workflow(snapshot)
    narrative = '### 今天先研究美元\n\n美元解释更符合当前证据，但缺少同窗口变化，仍可被推翻。'
    coordinator = SimpleNamespace(input_payload={'research_synthesis': {'analysis': {
        'reader_narrative': narrative, 'independent_assessment': '当前无法确认单一主因。'}}})
    sections = reader_sections(snapshot, {'coordinator': coordinator}, {})
    assert [s['section_id'] for s in sections] == ['research_summary', 'market_snapshot', 'model_research', 'sources']
    md = render_reader_report(snapshot, sections)
    assert narrative in md
    assert 'audit_report.md' in md
    assert '三、原油' not in md


def test_reader_and_audit_are_one_immutable_bundle(tmp_path):
    kwargs = dict(storage_root=tmp_path, trade_date='2026-09-10', run_id='reader-test',
                  markdown='# 研究正文', audit_markdown='# 完整溯源', structured_report={'sections': []})
    first = write_final_report(**kwargs)
    assert len(first['paths']) == 3
    assert write_final_report(**kwargs)['skipped']
    with pytest.raises(FileExistsError):
        write_final_report(**{**kwargs, 'audit_markdown': '# conflicting'})


def test_v2_cards_preserve_narrative_and_do_not_invent_accepted_or_previous():
    from copy import deepcopy
    from apps.features.research.production_shadow import apply_production_shadow_features
    from apps.features.research.state import build_state_proposal

    snapshot = _snapshot()
    flow = apply_production_shadow_features(snapshot, build_gold_workflow(snapshot))
    flow['reader_report_version'] = 'gold_reader.v2'  # frozen legacy reader contract
    flow['state_record'] = build_state_proposal(snapshot, flow)
    snapshot['gold_workflow'] = flow
    before = deepcopy(snapshot)
    narrative = '本轮先研究资金，暂不接受规则的多空排序。'
    coordinator = SimpleNamespace(input_payload={'research_synthesis': {'analysis': {
        'reader_narrative': narrative, 'independent_assessment': '观察资金变化。'}}})
    sections = reader_sections(snapshot, {'coordinator': coordinator}, {})
    cards = {s['section_id']: s['body'] for s in sections}
    assert cards['model_research'] == narrative
    assert set(cards) >= {'reader_delta', 'reader_state', 'reader_scenarios', 'reader_execution', 'reader_health'}
    assert '不生成报告间Delta' in cards['reader_delta']
    assert 'INITIALIZATION_REQUIRED' in cards['reader_state']
    assert 'Accepted尚未初始化' in cards['reader_state']
    assert all(x in cards['reader_execution'] for x in ('空仓', '已有多单', '已有空单'))
    assert snapshot == before


def test_cards_show_pending_and_bear_main_without_rewriting_priority():
    from apps.renderer.markdown.gold_decision_cards import decision_cards

    snapshot = _snapshot()
    flow = build_gold_workflow(snapshot)
    flow['state_record'] = {'previous_state': 'S6', 'accepted_state': 'S5', 'candidate_state': 'S4',
                            'transition_status': 'PENDING', 'transition_confirmed': False}
    flow['scenario_engine']['main_scenario_id'] = 'bear'
    flow['scenario_display'] = {'scenarios': [dict(r, display_weight_pct=50 if r['id'] == 'bear' else 25)
                                             for r in flow['scenario_engine']['scenarios']]}
    flow['delta_vs_previous'] = {'status': 'available', 'previous_snapshot_id': 'verified-research',
        'previous_analysis_time': '2026-09-09T12:00:00Z', 'rows': [
        {'symbol': 'REAL10Y', 'previous': 2.43, 'current': 2.43, 'delta': 0,
         'unit': '%', 'change_kind': 'unchanged', 'previous_date': '2026-09-09', 'current_date': '2026-09-09'}]}
    flow['core_source_health'] = {'items': [{'source_key': 'oil', 'source_health': 'FAILED',
        'reason': 'DELAYED_CLOCK_UNVERIFIED', 'collector_status': 'success'}]}
    snapshot['gold_workflow'] = flow
    cards = {s['section_id']: s['body'] for s in decision_cards(snapshot)}
    assert '| Current Accepted State | S5 |' in cards['reader_state']
    assert '| Transition Confirmed | 否 |' in cards['reader_state']
    assert 'Accepted尚未初始化' not in cards['reader_state']
    assert 'Bear 空头路径 / Main 主路径' in cards['reader_scenarios']
    assert '区间路径 / Main' not in cards['reader_scenarios']
    assert '| 0 % | 无新增变化 |' in cards['reader_delta']
    assert '不是上一份Accepted正式报告' in cards['reader_delta']
    assert 'FAILED / DELAYED_CLOCK_UNVERIFIED' in cards['reader_health']


def test_cards_missing_scenario_does_not_fabricate_zone_or_weight():
    from apps.renderer.markdown.gold_decision_cards import decision_cards
    snapshot = _snapshot()
    snapshot['gold_workflow'] = build_gold_workflow(snapshot)
    body = next(s['body'] for s in decision_cards(snapshot) if s['section_id'] == 'reader_scenarios')
    assert body.count('数据不足，路径未生成') == 3
    assert '50%' not in body


def test_v3_moves_internal_contracts_to_audit_and_closes_weekend_quote():
    from copy import deepcopy
    from apps.features.research.production_shadow import apply_production_shadow_features
    from apps.renderer.markdown.gold_reader import reader_audit_details

    s = _snapshot()
    s['gold_workflow'] = apply_production_shadow_features(s, build_gold_workflow(s))
    s['daily_research']['market_session'] = {'state': 'CLOSED', 'new_intraday_confirmation_allowed': False}
    s['gold_workflow']['price_anchor'].update(price=99999, price_time='weekend_refresh')
    model = SimpleNamespace(input_payload={'research_synthesis': {'status': 'success',
        'analysis': {'reader_narrative': '### 为什么涨\n\n反弹有承接，但实际利率没有改善。',
                     'independent_assessment': '内部修订：不把技术修复完全删除。'},
        'macro_review': {'status': 'needs_revision', 'confidence_multiplier': 0.7, 'checks': []}}})
    original = deepcopy(s)
    sections = reader_sections(s, {'coordinator': model}, {})
    body = render_reader_report(s, sections)
    assert [r['section_id'] for r in sections] == ['model_research', 'market_snapshot', 'policy_and_windows', 'sources']
    assert 'Fed Policy Path' in body and 'Market vs Fed SEP' in body
    assert '— 表示缺失，不是零' in body
    assert '为什么涨' in body and '可信度已下调' in body
    assert '内部修订' not in body and '完全删除' not in body
    assert '99999' not in body and 'weekend_refresh' not in body
    assert 'Reviewer' not in body and 'INITIALIZATION_REQUIRED' not in body
    audit = reader_audit_details(s, {'coordinator': model})
    assert 'Reviewer：needs_revision' in audit and 'Accepted' in audit
    assert s == original


def test_v3_does_not_present_failed_synthesis_as_complete():
    from apps.features.research.production_shadow import apply_production_shadow_features
    s = _snapshot()
    s['gold_workflow'] = apply_production_shadow_features(s, build_gold_workflow(s))
    model = SimpleNamespace(input_payload={'research_synthesis': {'status': 'rule_fallback',
        'analysis': {'reader_narrative': '不应展示的未通过正文'}}})
    body = render_reader_report(s, reader_sections(s, {'coordinator': model}, {}))
    assert '完整分析尚未生成' in body
    assert '不应展示的未通过正文' not in body


def test_reader_terminology_keeps_values_and_uncertainty():
    from apps.renderer.markdown.gold_reader import reader_prose
    raw = '一、期权\n\nSelected Expiry Window Proxy Gamma Flip约4239.7，PRELIM；方向未知。'
    value = reader_prose(raw)
    assert '### 一、期权' in value
    assert '4239.7' in value and '方向未知' in value
    assert '初步版' in value and '所选到期窗口' in value
    assert 'Selected Expiry' not in value
