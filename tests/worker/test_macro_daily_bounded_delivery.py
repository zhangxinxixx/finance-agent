"""Synthetic responses only; exercise the real macro entry and its consumers."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from apps.worker.pipelines.gold_macro_daily import generate_gold_macro_daily
from apps.renderer.markdown.gold_reader import endpoint_window_sections, research_sections, render_reader_report
from tests.worker.test_gold_macro_daily_delivery import candidate, model_stub


def test_bounded_entry_keeps_native_binding_and_messages(tmp_path):
    prepared = candidate(tmp_path)
    before = deepcopy(prepared)
    calls = []
    result = generate_gold_macro_daily(prepared, source_root=tmp_path,
                                      storage_root=tmp_path/'output', gateway=model_stub(calls))
    assert result['status'] == 'generated'
    assert len(calls) == 2 and calls[0]['messages'] == prepared['messages']
    synthesis = result['coordinator']['input_payload']['research_synthesis']
    assert synthesis['input_validation'] == prepared['snapshot']['input_validation']
    assert all(c['max_retries'] == 0 for c in calls)
    assert prepared == before


@pytest.mark.parametrize('failure', ['bad_json', 'generation_timeout', 'review_rejected', 'review_timeout'])
def test_bounded_entry_never_repairs_or_retries(tmp_path, failure):
    prepared, calls = candidate(tmp_path), []
    original = model_stub([], review='fail' if failure == 'review_rejected' else 'pass')
    def invoke(**kwargs):
        calls.append(kwargs)
        review = kwargs['audit_context']['caller'] == 'macro_causal_reviewer'
        if not review and failure == 'bad_json':
            return {'content': 'not valid json', 'model': 'synthetic-only'}
        if (not review and failure == 'generation_timeout') or (review and failure == 'review_timeout'):
            raise TimeoutError('synthetic timeout')
        return original(**kwargs)
    result = generate_gold_macro_daily(prepared, source_root=tmp_path,
                                      storage_root=tmp_path/'output', gateway=invoke)
    assert result['status'] == 'blocked'
    assert len(calls) == (2 if failure.startswith('review_') else 1)
    assert not list((tmp_path/'output').rglob('final_report.md'))
    assert result['coordinator']['input_payload']['research_synthesis']['quality_eligible'] is False


def test_macro_refuses_gateway_with_paid_or_other_provider_fallback(tmp_path):
    gateway = SimpleNamespace(config=SimpleNamespace(fallback_providers=('other',)),
                              chat_sync=lambda **_: pytest.fail('must stop before gateway'))
    with pytest.raises(ValueError, match='without_fallback'):
        generate_gold_macro_daily(candidate(tmp_path), source_root=tmp_path,
                                  storage_root=tmp_path/'output', gateway=gateway)


def test_four_hour_endpoint_note_is_scoped_and_does_not_rewrite_model():
    row = {'horizon':'4h','group':'gold_vs_TVC:DXY','aligned_comparison_allowed':True,
           'comparison_scope':'BOUNDED_WINDOW','bar_resolution_seconds':900,
           'window_start':'2026-10-16T06:00:00+00:00','window_end':'2026-10-16T10:00:00+00:00',
           'changes':[{'symbol':'XAUUSD','source_refs':[{'source':'synthetic-xau'}]},
                      {'symbol':'DXY','source_refs':[{'source':'synthetic-dxy'}]}]}
    flow = {'cross_asset_freshness':{'chart_windows':{'multi_horizon':{'rows':[row]}}}}
    synthesis = {'status':'success','analysis':{'reader_narrative':'合成正文：4H黄金美元比较；黄金原生4H结构另看。'}}
    original = deepcopy(synthesis)
    sections = research_sections({'gold_workflow':flow}, synthesis)
    note = sections[0]['endpoint_window_basis'][0]
    assert '四小时长度的端点窗口' in note['body'] and '15分钟完整K线' in note['body']
    assert '不表示取得合格原生DXY 4H' in note['body']
    assert note['source_refs'] == [{'source':'synthetic-xau'},{'source':'synthetic-dxy'}]
    assert next(s for s in sections if s['section_id']=='model_research')['body'] == synthesis['analysis']['reader_narrative']
    assert synthesis == original
    narrative = ('## 一句话结论\n\n合成市场判断。\n\n'
                 '| 实际窗口 | 黄金 | DXY |\n|---|---|---|\n'
                 '| 2026-10-16 06:00—10:00，4H | 1 | -1 |\n'
                 '| 2026-10-16 09:00—10:00，1H | 0 | 0 |\n\n'
                 '## PA\n\n原生4H结构未确认。')
    snapshot = {'trade_date': '2026-10-16', 'snapshot_time': '2026-10-16T10:14:00+00:00',
                'report_kind': 'gold_macro_daily',
                'gold_workflow': {**flow, 'reader_presentation': 'gold_reader.research.v1'}}
    synthesis['analysis']['reader_narrative'] = narrative
    rendered = render_reader_report(snapshot, research_sections(snapshot, synthesis))
    assert '06:00—10:00，4小时端点窗口' in rendered
    assert rendered.index('一句话结论') < rendered.index('实际窗口') < rendered.index('> 注：') < rendered.index('## PA')
    assert '原生4H结构未确认' in rendered
    assert synthesis['analysis']['reader_narrative'] == narrative
    for change in ({'aligned_comparison_allowed':False},{'bar_resolution_seconds':14400},
                   {'window_end':'2026-10-16T09:00:00+00:00'},{'comparison_scope':'UNKNOWN'}):
        changed = deepcopy(flow)
        changed['cross_asset_freshness']['chart_windows']['multi_horizon']['rows'][0].update(change)
        assert endpoint_window_sections(changed) == []
