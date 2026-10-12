import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from apps.worker.adaptive_research import enrich_research_snapshot, plan_research
from apps.collectors.fred.collector import collect_fred_series_from_payload


@pytest.fixture(autouse=True)
def _dwd_session(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from database.models.analysis import AnalysisBase
    from database.models.execution import ExecutionBase
    from tests.helpers.warehouse import create_collection_schema
    engine = create_engine('sqlite://')
    create_collection_schema(engine)
    AnalysisBase.metadata.create_all(engine)
    ExecutionBase.metadata.create_all(engine)
    original = enrich_research_snapshot
    with Session(engine) as session:
        def enrich_with_dwd(*args, **kwargs):
            kwargs.setdefault('db_session', session)
            return original(*args, **kwargs)
        monkeypatch.setitem(globals(), 'enrich_research_snapshot', enrich_with_dwd)
        yield
    engine.dispose()


def snapshot():
    return {'snapshot_id': 'snap', 'trade_date': '2026-09-10', 'run_id': 'run',
            'snapshot_time': '2026-09-10T00:00:00+00:00', 'source_refs': [],
            'input_snapshot_ids': {}, 'daily_research': {'passport': []}}


def gateway(**changes):
    plan = dict(question='为何价格与利率背离？', hypothesis='美元主导', falsifier='同窗口美元转强',
                why_these_requests='先验证美元解释', fred_series=[], news_queries=[])
    plan.update(changes)
    plan.setdefault('action', 'continue' if plan['fred_series'] or plan['news_queries'] else 'finish')
    plan.setdefault('finish_reason', 'evidence_sufficient')
    plan.setdefault('evidence_assessment', '比较新增证据后再判断。')
    return lambda **kwargs: SimpleNamespace(content=json.dumps(plan), audit_id='audit', model='fixture')


def structured_gateway(*, requests=None, action=None, gaps=None, **changes):
    requests = requests or []
    plan = dict(
        action=action or ('continue' if requests else 'finish'),
        question='哪条链解释当前金价偏离？',
        hypothesis='风险厌恶抵消实际利率压力',
        driver_assessment='宏观机会成本偏空，但实际金价跌幅不足',
        competing_hypotheses=['美元回落', '仓位修复'],
        falsifier='VIX不升且股指上涨',
        why_these_requests='用同窗口交叉资产区分避险和仓位修复',
        evidence_assessment='现有证据不能区分两条解释。',
        data_requests=requests,
        unavailable_data_needs=gaps or [],
        finish_reason='evidence_sufficient',
    )
    plan.update(changes)
    return lambda **kwargs: SimpleNamespace(content=json.dumps(plan), audit_id='audit-v2', model='fixture')


def request(provider, key, *, request_id='r1', freshness='intraday', resolution=None):
    item = {'request_id': request_id, 'provider': provider, 'key': key,
            'claim': '该观测可区分风险厌恶与仓位修复',
            'decision_impact': '改变主导驱动和情景排序',
            'freshness_need': freshness, 'priority': 'high'}
    if resolution is not None:
        item['resolution'] = resolution
    return item


def test_model_can_choose_no_additional_collection(tmp_path):
    before = snapshot()
    untouched = deepcopy(before)
    def forbidden(**kwargs):
        pytest.fail('model did not request collection')
    result = enrich_research_snapshot(before, storage_root=tmp_path, gateway=gateway(),
                                     fred_collector=forbidden, news_collector=forbidden)
    assert before == untouched
    assert result['adaptive_research']['status'] == 'completed'
    assert result['adaptive_research']['plan']['hypothesis'] == '美元主导'
    assert (tmp_path / result['input_snapshot_ids']['adaptive_research']).is_file()


def test_missing_mandatory_fresh_news_cannot_pass_on_model_sufficiency(tmp_path):
    data = snapshot()
    data['mainstream_news'] = {'documents': [], 'critical_gaps': ['FRESH_REUTERS_BODY']}
    result = enrich_research_snapshot(data, storage_root=tmp_path, gateway=gateway())
    assert result['adaptive_research']['stop_reason'] == 'evidence_unavailable'
    assert result['adaptive_research']['status'] == 'partial'
    assert result['adaptive_research']['unavailable_data_needs'][-1]['materiality'] == 'decisive'


def test_baseline_news_document_can_be_expanded_without_refetch(tmp_path):
    import httpx
    from apps.collectors.research.public_evidence import collect_public_document, project_document
    body = '<article><h1>Gold report</h1>' + ''.join('<p>'+str(i)+'x'*1500+'</p>' for i in range(10)) + '</article>'
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=body))) as client:
        document = collect_public_document(key='https://www.reuters.com/business/test', retrieved_date='2026-09-15',
                                           storage_root=tmp_path, client=client)
    data = snapshot()
    data['mainstream_news'] = {'documents': [project_document(document)]}
    plans = [structured_gateway(requests=[request('evidence_detail', document['document_id']+':1')]), structured_gateway()]
    result = enrich_research_snapshot(data, storage_root=tmp_path, gateway=lambda **kw: plans.pop(0)(**kw))
    expanded = result['adaptive_research']['documents'][0]
    assert expanded['part_index'] == 1
    assert expanded['text_blocks'] == document['parts'][1]


def test_research_planner_receives_compact_cme_with_source_limits():
    data = snapshot()
    data['options'] = {'status': 'available', 'data': {
        'data_source': {'status': 'PRELIM', 'report_date': '2026-09-11'},
        'gex_semantics': {'dealer_position_unknown': True},
        'gex': {'price_grid': [4000, 4100], 'net_gex_values': [-1, 2],
                'gamma_flip': {'price': 4050, 'scope': 'selected_expiry_window'}},
    }}
    def model(**kwargs):
        payload = json.loads(kwargs['messages'][1]['content'])
        cme = payload['domain_evidence']['options']
        assert cme['schema_version'] == 'cme_research_projection.v2'
        assert cme['source']['status'] == 'PRELIM'
        assert cme['semantics']['dealer_position_unknown'] is True
        assert cme['aggregate_proxy_gamma_flip']['price'] == 4050
        assert 'price_grid' not in json.dumps(cme)
        return gateway()(**kwargs)
    assert plan_research(data, model)['action'] == 'finish'


def test_research_planner_receives_traceable_article_extract_not_full_body():
    data = snapshot()
    blocks = [
        'Gold rose after a pipeline report raised concern about oil supply.',
        *[f'Background paragraph {index} repeats regional history and logistics.' for index in range(14)],
        'However, the operator denied an outage and said capacity was not actual lost output.',
        'The clarification was published at 14:30 UTC on September 17.',
    ]
    data['news'] = {'data': {'daily_market_brief': {'report_inputs': {
        'research_focus': [{'question': 'Does an oil supply loss explain gold?'}]
    }}}}
    data['mainstream_news'] = {'documents': [{
        'document_id': 'a' * 32,
        'status': 'available',
        'evidence_scope': 'publisher_body',
        'published_at': '2026-09-17T14:30:00Z',
        'parsed_path': 'parsed/research_documents/a.json',
        'parsed_sha256': 'b' * 64,
        'part_index': 0,
        'part_count': 2,
        'detail_request_format': f"{'a' * 32}:<part_index>",
        'text_blocks': blocks,
    }]}

    def model(**kwargs):
        payload = json.loads(kwargs['messages'][1]['content'])
        document = payload['domain_evidence']['mainstream_news']['documents'][0]
        rows = document['selected_blocks']['rows']
        selected = {row[0]: row[2] for row in rows}
        assert document['projection_scope'] == 'traceable_extractive_selection_not_full_article'
        assert document['omitted_block_count'] > 0
        assert selected[15] == blocks[15]
        assert selected[16] == blocks[16]
        assert document['detail_request_format'].endswith(':<part_index>')
        assert document['part_count'] == 2
        assert 'text_blocks' not in document
        return structured_gateway()(**kwargs)

    assert plan_research(data, model)['action'] == 'finish'


def test_planner_timeout_configuration_is_capped_by_remaining_total_budget(tmp_path):
    observed = []

    def model(**kwargs):
        observed.append(kwargs['request_timeout'])
        return structured_gateway()(**kwargs)

    result = enrich_research_snapshot(
        snapshot(),
        storage_root=tmp_path,
        gateway=model,
        max_elapsed_seconds=45,
        planner_request_timeout_seconds=180,
    )
    assert len(observed) == 1
    assert 44 < observed[0] <= 45
    assert result['adaptive_research']['budget']['planner_request_timeout_seconds'] == 180


def test_planner_timeout_configuration_rejects_nonpositive_values(tmp_path):
    with pytest.raises(ValueError, match='invalid research budget'):
        enrich_research_snapshot(
            snapshot(),
            storage_root=tmp_path,
            gateway=structured_gateway(),
            planner_request_timeout_seconds=0,
        )


@pytest.mark.parametrize('transient_error', [
    RuntimeError('All LLM providers failed. Tried: cockpit, jojocode. Last error: Connection error.'),
    RuntimeError('All LLM providers failed. Tried: cockpit. Last error: Error code: 408.'),
    type('HTTP408Error', (Exception,), {'status_code': 408})('request timed out'),
])
def test_planner_retries_one_transient_failure_and_keeps_sanitized_audit(tmp_path, transient_error):
    calls = []

    def model(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise transient_error
        return structured_gateway()(**kwargs)

    record = enrich_research_snapshot(snapshot(), storage_root=tmp_path, gateway=model)['adaptive_research']

    assert record['status'] == 'completed'
    assert record['stop_reason'] == 'evidence_sufficient'
    assert [call['audit_context']['planner_attempt'] for call in calls] == [1, 2]
    assert record['budget_used']['planner_retries'] == 1
    assert record['budget']['planner_retry_limit_per_decision'] == 1
    assert record['planner_attempt_errors'] == [{
        'decision_index': 1,
        'role': 'planner',
        'attempt': 1,
        'error_type': type(transient_error).__name__,
        'retryable': True,
        'retry_scheduled': True,
    }]
    assert str(transient_error) not in json.dumps(record)


def test_planner_does_not_retry_contract_or_parse_failure(tmp_path):
    calls = 0

    def model(**kwargs):
        nonlocal calls
        calls += 1
        raise ValueError('invalid private response')

    record = enrich_research_snapshot(snapshot(), storage_root=tmp_path, gateway=model)['adaptive_research']

    assert calls == 1
    assert record['stop_reason'] == 'model_failure'
    assert record['status'] == 'unavailable'
    assert record['errors'] == ['research_plan_failed:ValueError']
    assert record['planner_attempt_errors'][0]['retryable'] is False
    assert 'invalid private response' not in json.dumps(record)


def test_planner_retry_exhaustion_preserves_prior_evidence_and_never_claims_sufficiency(tmp_path):
    calls = 0
    first_plan = structured_gateway(requests=[request('tradingview', 'CBOE:VIX')])

    def model(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return first_plan(**kwargs)
        raise RuntimeError('All LLM providers failed. Tried: cockpit. Last error: Connection error.')

    def market(**kwargs):
        return {'retrieved_at': '2026-09-10T15:53:00+00:00', 'source_refs': [],
                'observations': [{'ticker': 'CBOE:VIX', 'symbol': 'VIX', 'instrument_type': 'index',
                    'unit': 'index', 'status': 'available', 'value': 28.0,
                    'retrieved_at': '2026-09-10T15:53:00+00:00',
                    'minute_bar_time': '2026-09-10T15:52:00+00:00',
                    'provider_bar_time': '2026-09-10T00:00:00+00:00', 'delay_seconds': 0,
                    'value_kind': 'latest_completed_1m_close',
                    'source_refs': [{'source': 'tradingview_cross_asset', 'raw_path': 'raw/scanner.json',
                                     'retrieved_at': '2026-09-10T15:53:00+00:00'}]}]}

    record = enrich_research_snapshot(
        snapshot(), storage_root=tmp_path, gateway=model, market_collector=market,
    )['adaptive_research']

    assert calls == 3
    assert record['stop_reason'] == 'model_failure'
    assert record['stop_reason'] != 'evidence_sufficient'
    assert record['status'] == 'partial'
    assert record['market_observations'][0]['ticker'] == 'CBOE:VIX'
    assert record['rounds'][0]['new_evidence_count'] == 1
    assert record['budget_used']['planner_retries'] == 1
    assert [error['attempt'] for error in record['planner_attempt_errors']] == [1, 2]
    assert record['errors'] == ['research_plan_failed:RuntimeError']


def test_planner_skips_retry_when_transient_failure_consumes_remaining_budget(tmp_path):
    moments = iter([0, 0, 0, 10, 10])
    calls = 0

    def clock():
        return next(moments, 10)

    def model(**kwargs):
        nonlocal calls
        calls += 1
        raise TimeoutError('request timed out')

    record = enrich_research_snapshot(
        snapshot(), storage_root=tmp_path, gateway=model,
        max_elapsed_seconds=10, planner_request_timeout_seconds=180, clock=clock,
    )['adaptive_research']

    assert calls == 1
    assert record['stop_reason'] == 'time_budget_exhausted'
    assert record['status'] == 'unavailable'
    assert record['budget_used']['planner_retries'] == 0
    assert record['planner_attempt_errors'][0]['retry_skipped'] == 'time_budget_exhausted'
    assert record['planner_attempt_errors'][0]['retry_scheduled'] is False


def test_cme_detail_is_only_expanded_on_request_and_returns_to_planner(tmp_path):
    data = snapshot()
    data['options'] = {'status': 'available', 'data': {
        'data_source': {'status': 'PRELIM', 'report_date': '2026-09-09'},
        'gex_semantics': {'dealer_position_unknown': True},
        'gex': {'price_grid': [4000, 4100], 'net_gex_values': [-1, 2]},
    }}
    plans = [structured_gateway(requests=[request('snapshot_detail', 'cme:gamma_grid')]), structured_gateway()]
    def model(**kwargs):
        if len(plans) == 1:
            context = json.loads(kwargs['messages'][1]['content'])
            doc = context['history']['documents'][0]
            assert json.loads(doc['text_blocks'][0])['price_grid'] == [4000, 4100]
            assert doc['qualifications']['semantics']['dealer_position_unknown'] is True
        return plans.pop(0)(**kwargs)
    result = enrich_research_snapshot(data, storage_root=tmp_path, gateway=model)
    assert result['adaptive_research']['status'] == 'completed'
    assert result['adaptive_research']['budget_used']['document_requests'] == 1


def test_reviewer_failure_preserves_draft_and_never_claims_sufficiency(tmp_path):
    count = 0
    def model(**kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise RuntimeError('unavailable')
        return structured_gateway()(**kwargs)
    result = enrich_research_snapshot(snapshot(), storage_root=tmp_path, gateway=model, evidence_review_enabled=True)
    assert result['adaptive_research']['stop_reason'] == 'review_failure'
    assert result['adaptive_research']['status'] == 'partial'
    assert (tmp_path/result['research_revision']['parent_snapshot_ref']['path']).exists()


def test_web_search_alternative_returns_to_researcher_and_frozen_evidence(tmp_path):
    plans = [structured_gateway(requests=[request('web_search', 'Saudi pipeline September 2026')]), structured_gateway()]
    def model(**kwargs):
        if len(plans) == 1:
            context = json.loads(kwargs['messages'][1]['content'])
            assert context['history']['news'][0]['evidence_scope'] == 'search_metadata_only'
        return plans.pop(0)(**kwargs)
    result = enrich_research_snapshot(snapshot(), storage_root=tmp_path, gateway=model,
        web_search_collector=lambda **kw: {'news': [{'title': 'Pipeline status', 'url': 'https://apnews.com/article/a',
                                                    'evidence_scope': 'search_metadata_only'}],
                                           'errors': [], 'source_refs': [{'source': 'public_rss'}]})
    assert result['adaptive_research']['status'] == 'completed'
    assert result['adaptive_research']['news'][0]['evidence_scope'] == 'search_metadata_only'


def test_reviewer_requests_one_collection_before_new_immutable_snapshot(tmp_path):
    initial = snapshot()
    initial['gold_workflow'] = {'state_record': {'accepted_state': 'S5'}}
    before = deepcopy(initial)
    plans = [structured_gateway(),
             structured_gateway(requests=[request('public_document', 'IAU')]),
             structured_gateway(hypothesis='IAU只有持仓水平，不能确认当日净买盘')]
    roles = []
    def model(**kwargs):
        roles.append(kwargs['audit_context']['caller'])
        if len(plans) == 1:
            context = json.loads(kwargs['messages'][1]['content'])
            assert context['history']['documents'][0]['observations'][0]['value'] == 100
        return plans.pop(0)(**kwargs)
    def collect(**kwargs):
        return {'document_id': '1'*32, 'key': 'IAU', 'status': 'available', 'parts': [],
                'source_refs': [{'source': 'ishares'}],
                'observations': [{'symbol': 'IAU_SHARES', 'value': 100, 'unit': 'shares',
                                  'observation_date': '2026-09-10', 'source_refs': [{'source': 'ishares'}]}]}
    result = enrich_research_snapshot(initial, storage_root=tmp_path, gateway=model,
                                      document_collector=collect, evidence_review_enabled=True)
    assert initial == before
    assert len(roles) == 3
    assert roles[1] == 'adaptive_research.evidence_reviewer'
    revision = result['research_revision']
    assert revision['supplemental_collection_rounds'] == 1
    parent = json.loads((tmp_path/revision['parent_snapshot_ref']['path']).read_text())
    assert parent['snapshot_id'] != result['snapshot_id']
    assert parent['adaptive_research']['documents'] == []
    child = json.loads((tmp_path/result['input_snapshot_ids']['research_revision']['path']).read_text())
    assert len(child['adaptive_research']['documents']) == 1
    assert child['gold_workflow']['state_record']['accepted_state'] == 'S5'
    from apps.analysis.agents.research_input import final_input
    payload = final_input(result, SimpleNamespace(input_payload={}), catalog={}, assessment={})
    series = payload['supplemental_source_features']['IAU']['series']['IAU_SHARES']
    assert series['current']['value'] == 100
    assert series['delta'] is None
    assert payload['adaptive_research']['documents'][0]['observations'][0]['value'] == 100


def test_document_budget_is_checked_before_network(tmp_path):
    def forbidden(**kwargs):
        pytest.fail('budget must be enforced')
    result = enrich_research_snapshot(snapshot(), storage_root=tmp_path,
        gateway=structured_gateway(requests=[request('public_document', 'IAU')]),
        document_collector=forbidden, max_document_requests=0)
    assert result['adaptive_research']['stop_reason'] == 'request_budget_exhausted'


@pytest.mark.parametrize('changes', [dict(fred_series=['FAKE']), dict(news_queries=['x'] * 3), dict(fred_series=['SOFR'] * 5)])
def test_request_scope_is_validated(changes):
    with pytest.raises(ValueError):
        plan_research(snapshot(), gateway(**changes))


def test_structured_plan_exposes_capabilities_and_preserves_selection_reason():
    selected = request('tradingview', 'CBOE:VIX')
    inspected = []

    def model(**kwargs):
        context = json.loads(kwargs['messages'][1]['content'])
        inspected.append(context)
        assert context['collection_capabilities']['collection_policy']['mandatory_baseline'] == 'deterministic and outside model control'
        assert 'TVC:SILVER' in context['collection_capabilities']['providers']['tradingview']['capabilities']
        return structured_gateway(requests=[selected])(**kwargs)

    plan = plan_research(snapshot(), model)
    assert inspected
    assert plan['schema_version'] == 'research_plan.v2'
    assert plan['market_symbols'] == ['CBOE:VIX']
    assert plan['market_requests'] == [{'ticker': 'CBOE:VIX', 'resolution': '15'}]
    assert plan['data_requests'][0]['resolution'] == '15'
    assert plan['data_requests'][0]['decision_impact'] == '改变主导驱动和情景排序'


@pytest.mark.parametrize('bad_request', [
    request('made_up_provider', 'anything'),
    request('tradingview', 'BROKER:USOIL'),
    request('tradingview', 'CBOE:VIX', resolution='5'),
    request('fred', 'NOT_A_SERIES', freshness='latest_release'),
    [request('fred', 'DGS2', request_id='one', freshness='latest_available'),
     request('fred', 'DGS2', request_id='two', freshness='latest_available')],
])
def test_structured_request_is_rejected_before_collection(bad_request):
    requests = bad_request if isinstance(bad_request, list) else [bad_request]
    with pytest.raises(ValueError):
        plan_research(snapshot(), structured_gateway(requests=requests))


def test_same_ticker_different_resolutions_are_distinct_budgeted_requests():
    requests = [request('tradingview', 'CBOE:VIX', request_id='m15'),
                request('tradingview', 'CBOE:VIX', request_id='m1', resolution='1')]
    plan = plan_research(snapshot(), structured_gateway(requests=requests))
    assert plan['market_requests'] == [
        {'ticker': 'CBOE:VIX', 'resolution': '15'},
        {'ticker': 'CBOE:VIX', 'resolution': '1'},
    ]


def test_agent_can_select_different_evidence_for_different_market_question():
    def model(**kwargs):
        context = json.loads(kwargs['messages'][1]['content'])
        change = context['spot_anchor']['change']
        selected = (request('tradingview', 'CBOE:VIX') if change > 0 else
                    request('fred', 'DDFUELUSGULF', freshness='latest_available'))
        return structured_gateway(requests=[selected])(**kwargs)

    up = snapshot()
    up['daily_research']['spot_anchor'] = {'change': 1.0}
    down = snapshot()
    down['daily_research']['spot_anchor'] = {'change': -1.0}
    assert plan_research(up, model)['market_symbols'] == ['CBOE:VIX']
    assert plan_research(down, model)['fred_series'] == ['DDFUELUSGULF']


def test_optional_series_is_archived_and_dated(tmp_path):
    def collector(**kwargs):
        assert kwargs['symbols'] == ('DDFUELUSGULF',)
        return collect_fred_series_from_payload(symbol='DDFUELUSGULF',
            payload={'observations': [{'date': '2026-09-09', 'value': '4.2'}]},
            retrieved_date='2026-09-10', retrieved_at='2026-09-10T00:00:00+00:00',
            storage_root=tmp_path, source_url='https://fred.stlouisfed.org/series/DDFUELUSGULF')
    result = enrich_research_snapshot(snapshot(), storage_root=tmp_path,
        gateway=gateway(fred_series=['DDFUELUSGULF']), fred_collector=collector)
    record = result['adaptive_research']
    assert record['errors'] == []
    row = next(r for r in record['observations'] if r['symbol'] == 'DIESEL_GULF_SPOT')
    assert row['value'] == 4.2
    assert row['unit'] == 'USD/gal'
    assert row['observation_date'] == '2026-09-09'
    assert (tmp_path / row['source_refs'][0]['raw_path']).is_file()


def test_selected_market_observation_returns_to_next_agent_decision(tmp_path):
    plans = [
        structured_gateway(requests=[request('tradingview', 'TVC:SILVER')]),
        structured_gateway(hypothesis='白银没有确认黄金反弹', action='finish',
                           evidence_assessment='新增白银观测已用于反证。'),
    ]

    def model(**kwargs):
        context = json.loads(kwargs['messages'][1]['content'])
        if len(plans) == 1:
            table = context['history']['market_observations_table']
            assert table['rows'][0][table['columns'].index('ticker')] == 'TVC:SILVER'
        return plans.pop(0)(**kwargs)

    def market_collector(**kwargs):
        assert kwargs['symbols'] == ('TVC:SILVER',)
        return {'retrieved_at': '2026-09-10T15:53:00+00:00', 'source_refs': [],
                'observations': [{'ticker': 'TVC:SILVER', 'symbol': 'SILVER_SPOT_PROXY',
                    'instrument_type': 'commodity', 'unit': 'USD/oz', 'status': 'available',
                    'value': 51.2, 'retrieved_at': '2026-09-10T15:53:00+00:00',
                    'minute_bar_time': '2026-09-10T15:52:00+00:00',
                    'provider_bar_time': '2026-09-10T00:00:00+00:00', 'delay_seconds': 0,
                    'value_kind': 'latest_completed_1m_close',
                    'source_refs': [{'source': 'tradingview_cross_asset', 'raw_path': 'raw/scanner.json',
                                     'retrieved_at': '2026-09-10T15:53:00+00:00'}]}]}

    record = enrich_research_snapshot(snapshot(), storage_root=tmp_path, gateway=model,
        market_collector=market_collector)['adaptive_research']
    assert record['status'] == 'completed'
    assert record['budget_used']['market_requests'] == 1
    assert record['market_observations'][0]['display_value'] == 51.2
    assert record['rounds'][0]['executed_requests']['data_requests'][0]['claim']


def test_chart_windows_return_to_planner_without_raw_bars_and_resolution_budget_is_distinct(tmp_path):
    requested = [request('tradingview', 'CBOE:VIX', request_id='vix-15'),
                 request('tradingview', 'CBOE:VIX', request_id='vix-1', resolution='1')]
    plans = [structured_gateway(requests=requested), structured_gateway(action='finish')]
    calls = []

    def model(**kwargs):
        context = json.loads(kwargs['messages'][1]['content'])
        if len(plans) == 1:
            windows = context['history']['market_windows'][0]
            table = windows['changes_table']
            assert table['rows'][0][table['columns'].index('ticker')] == 'OANDA:XAUUSD'
            assert table['rows'][0][table['columns'].index('window_index')] == 0
            assert windows['causal_attribution_allowed'] is False
            assert 'bars' not in json.dumps(context)
            assert 'chart_series' not in json.dumps(context)
        return plans.pop(0)(**kwargs)

    def market_collector(**kwargs):
        calls.append(kwargs)
        base = {'retrieved_at': '2026-09-10T15:53:00+00:00',
                'source_refs': [], 'observations': []}
        if kwargs.get('resolution') == '1':
            return base
        base['observations'] = [{
            'ticker': 'CBOE:VIX', 'symbol': 'VIX', 'instrument_type': 'index',
            'unit': 'index', 'status': 'missing', 'value': None,
            'retrieved_at': base['retrieved_at'], 'minute_bar_time': None,
            'provider_bar_time': None, 'delay_seconds': 600, 'source_refs': [], 'value_kind': 'scanner_close',
        }]
        bars = [
            {'time': f'2026-09-10T{hour:02d}:{minute:02d}:00+00:00', 'close': close}
            for (hour, minute), close in zip(
                [(13, 15), (13, 30), (13, 45), (14, 0), (14, 15),
                 (14, 30), (14, 45), (15, 0), (15, 15)],
                range(100, 109), strict=True)
        ]
        ref = {'source': 'tradingview_chart', 'raw_path': 'raw/tv.json'}
        base['chart_series'] = [
            {'ticker': ticker, 'status': 'available', 'delay_seconds': 600,
             'resolution_seconds': 900, 'retrieved_at': base['retrieved_at'],
             'bars': [dict(bar, open=bar['close'] * multiplier, high=bar['close'] * multiplier,
                           low=bar['close'] * multiplier, close=bar['close'] * multiplier) for bar in bars],
             'metadata': {'exchange': ticker.split(':')[0], 'instrument_type': 'commodity' if ticker == 'OANDA:XAUUSD' else 'index',
                          'currency': 'USD' if ticker == 'OANDA:XAUUSD' else None, 'series_completed': True},
             'source_refs': [dict(ref, ticker=ticker, retrieved_at=base['retrieved_at'])]}
            for ticker, multiplier in [('OANDA:XAUUSD', 20), ('CBOE:VIX', 0.2)]
        ]
        return base

    record = enrich_research_snapshot(
        snapshot(), storage_root=tmp_path,
        gateway=model, market_collector=market_collector,
    )['adaptive_research']

    assert record['status'] == 'completed'
    assert record['errors'] == []
    assert record['market_observations'][0]['freshness'] == 'MISSING'
    assert record['budget_used']['market_requests'] == 2
    assert len(calls) == 2
    assert 'resolution' not in calls[0]
    assert calls[1]['resolution'] == '1'
    assert record['market_windows'][0]['windows']
    final_window = record['market_windows'][0]['windows'][0]
    assert final_window['status'] == 'STALE'
    assert final_window['aligned_comparison_allowed'] is False
    assert final_window['changes'][0]['change_pct'] is not None
    frozen_round = json.loads((tmp_path / record['rounds'][0]['evidence_ref']['path']).read_text())
    assert frozen_round['collection']['market_windows'][0]['windows'][0]['status'] == 'AVAILABLE_DELAYED'
    assert frozen_round['collection']['market_windows'][0]['windows'][0]['aligned_comparison_allowed'] is True
    assert 'bars' not in json.dumps(record['market_windows'])


def test_decisive_unavailable_need_is_preserved_and_downgrades_completion(tmp_path):
    gap = {'data': '全球OTC买方身份', 'reason': '当前能力目录无买方分类',
           'decision_impact': '无法确认非利率需求来源', 'materiality': 'decisive'}
    record = enrich_research_snapshot(snapshot(), storage_root=tmp_path,
        gateway=structured_gateway(gaps=[gap]))['adaptive_research']
    assert record['status'] == 'partial'
    assert record['stop_reason'] == 'evidence_unavailable'
    assert record['final_assessment']['finish_reason_normalized_from'] == 'evidence_sufficient'
    assert record['unavailable_data_needs'] == [gap]


def test_gap_resolved_by_later_assessment_is_not_left_outstanding(tmp_path):
    gap = {'data': '同窗口风险观测', 'reason': '首轮缺失',
           'decision_impact': '区分避险和技术修复', 'materiality': 'decisive'}
    plans = [structured_gateway(requests=[request('tradingview', 'CBOE:VIX')], gaps=[gap]),
             structured_gateway(action='finish', evidence_assessment='新增证据已经解决首轮缺口')]
    def market(**kwargs):
        return {'retrieved_at': '2026-09-10T15:53:00+00:00', 'source_refs': [],
                'observations': [{'ticker': 'CBOE:VIX', 'symbol': 'VIX', 'instrument_type': 'index',
                    'unit': 'index', 'status': 'available', 'value': 28.0,
                    'retrieved_at': '2026-09-10T15:53:00+00:00',
                    'minute_bar_time': '2026-09-10T15:52:00+00:00',
                    'provider_bar_time': '2026-09-10T00:00:00+00:00', 'delay_seconds': 0,
                    'value_kind': 'latest_completed_1m_close',
                    'source_refs': [{'source': 'tradingview_cross_asset', 'raw_path': 'raw/scanner.json',
                                     'retrieved_at': '2026-09-10T15:53:00+00:00'}]}]}
    record = enrich_research_snapshot(snapshot(), storage_root=tmp_path,
        gateway=lambda **kwargs: plans.pop(0)(**kwargs), market_collector=market)['adaptive_research']
    assert record['status'] == 'completed'
    assert record['unavailable_data_needs'] == []
    assert record['rounds'][0]['plan']['unavailable_data_needs'] == [gap]


def test_failed_collection_preserves_hypothesis_as_unconfirmed(tmp_path):
    def failed(**kwargs):
        raise TimeoutError('private detail')
    result = enrich_research_snapshot(snapshot(), storage_root=tmp_path,
        gateway=gateway(news_queries=['gold dollar']), news_collector=failed)
    assert result['adaptive_research']['status'] == 'partial'
    assert result['adaptive_research']['news'] == []
    assert 'private detail' not in json.dumps(result)


def test_counterevidence_drives_second_round_then_model_finishes(tmp_path):
    from apps.collectors.news.base import NewsCollectionResult, RawNewsItem
    requests = []
    decisions = [gateway(news_queries=['gold ETF flows'], hypothesis='ETF流入驱动'),
                 gateway(news_queries=['gold dollar reaction'], hypothesis='改为检验美元解释', evidence_assessment='首轮未找到ETF证据，换方向'),
                 gateway(hypothesis='美元解释仍待同步价格确认', finish_reason='evidence_unavailable')]
    def model(**kwargs):
        context = json.loads(kwargs['messages'][1]['content'])
        if len(requests) == 1:
            assert context['history']['news'][0]['title'] == 'ETF evidence absent'
        return decisions.pop(0)(**kwargs)
    def news(**kwargs):
        query = next(iter(kwargs['query_groups'].values()))
        requests.append(query)
        title = 'ETF evidence absent' if len(requests) == 1 else 'Dollar weakens'
        item = RawNewsItem(source_key='fixture', source_name='fixture', source_type='news', feed_key='fixture',
                           title=title, url=f'https://example.com/{len(requests)}', domain='example.com',
                           published_at='2026-09-10T01:00:00Z', fetched_at='2026-09-10T02:00:00Z')
        return NewsCollectionResult(source_key='fixture', status='success', items=[item], source_refs=[])
    result = enrich_research_snapshot(snapshot(), storage_root=tmp_path, gateway=model, news_collector=news)
    record = result['adaptive_research']
    assert len(requests) == 2 and len(record['rounds']) == 3
    assert record['stop_reason'] == 'evidence_unavailable'
    assert record['status'] == 'partial'
    assert record['plan']['hypothesis'] == 'ETF流入驱动'
    assert record['final_assessment']['hypothesis'] == '美元解释仍待同步价格确认'
    assert all((tmp_path / r['decision_ref']['path']).exists() for r in record['rounds'])
    assert record['rounds'][1]['previous_decision_ref'] == record['rounds'][0]['decision_ref']


def test_repeated_requests_do_not_recollect(tmp_path):
    from apps.collectors.news.base import NewsCollectionResult
    calls = []
    def news(**kwargs):
        calls.append(kwargs)
        return NewsCollectionResult('fixture', 'partial', [], [])
    record = enrich_research_snapshot(snapshot(), storage_root=tmp_path,
        gateway=gateway(news_queries=['gold dollar']), news_collector=news)['adaptive_research']
    assert len(calls) == 1
    assert record['stop_reason'] == 'repeated_requests'
    assert record['status'] == 'partial'


def test_budget_stops_before_unapproved_extra_collection(tmp_path):
    def forbidden(**kwargs):
        pytest.fail('budget exhausted')
    record = enrich_research_snapshot(snapshot(), storage_root=tmp_path, max_news_queries=0,
        gateway=gateway(news_queries=['gold dollar']), news_collector=forbidden)['adaptive_research']
    assert record['stop_reason'] == 'request_budget_exhausted'
    assert record['status'] == 'partial'
    record = enrich_research_snapshot({**snapshot(), 'run_id': 'timed'}, storage_root=tmp_path,
        gateway=forbidden, max_elapsed_seconds=0)['adaptive_research']
    assert record['stop_reason'] == 'time_budget_exhausted'


def test_round_limit_returns_results_for_final_assessment(tmp_path):
    from apps.collectors.news.base import NewsCollectionResult
    decisions = [gateway(news_queries=['first']), gateway(news_queries=['different'])]
    record = enrich_research_snapshot(snapshot(), storage_root=tmp_path, max_rounds=1,
        gateway=lambda **kwargs: decisions.pop(0)(**kwargs),
        news_collector=lambda **kwargs: NewsCollectionResult('fixture', 'partial', [], []))['adaptive_research']
    assert record['stop_reason'] == 'round_budget_exhausted'
    assert record['budget_used']['collection_rounds'] == 1
    assert len(record['rounds']) == 2


def test_model_failure_after_collection_keeps_completed_evidence(tmp_path):
    from apps.collectors.news.base import NewsCollectionResult
    called = []
    def model(**kwargs):
        called.append(True)
        if len(called) > 1:
            raise TimeoutError('secret endpoint detail')
        return gateway(news_queries=['test'])(**kwargs)
    record = enrich_research_snapshot(snapshot(), storage_root=tmp_path, gateway=model,
        news_collector=lambda **kwargs: NewsCollectionResult('fixture', 'partial', [], []))['adaptive_research']
    assert record['stop_reason'] == 'model_failure'
    assert record['status'] == 'partial'
    assert (tmp_path / record['rounds'][0]['evidence_ref']['path']).exists()
    assert 'secret endpoint detail' not in json.dumps(record)


def test_no_progress_gets_final_review_without_third_collection(tmp_path):
    from apps.collectors.news.base import NewsCollectionResult
    decisions = [gateway(news_queries=[x]) for x in ['one', 'two', 'three']]
    collected = []
    def model(**kwargs):
        context = json.loads(kwargs['messages'][1]['content'])
        if len(collected) == 2:
            assert context['remaining_budget']['collection_block_reason'] == 'no_new_evidence'
            assert len(context['history']['decision_trail']) == 2
        return decisions.pop(0)(**kwargs)
    def news(**kwargs):
        collected.append(True)
        return NewsCollectionResult('fixture', 'partial', [], [])
    record = enrich_research_snapshot(snapshot(), storage_root=tmp_path, gateway=model, news_collector=news)['adaptive_research']
    assert record['stop_reason'] == 'no_new_evidence'
    assert len(collected) == 2
    assert len(record['rounds']) == 3
