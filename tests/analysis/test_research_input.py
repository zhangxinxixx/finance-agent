from copy import deepcopy
import pytest
from apps.analysis.agents.research_input import (
    pack_evidence, leaf_sources, encode, ResearchInputTooLarge,
    project_history, project_cross_asset, project_macro, project_price_action,
    bounded_review, project_news_documents, project_options, project_workflow, final_input,
)


def test_reanalysis_findings_reach_synthesis_and_review_without_changing_facts():
    from types import SimpleNamespace
    finding = {'issue': 'window_mismatch', 'actual_horizon': 'us_pre_market',
               'actual_window_start': '2026-09-28T08:00:00Z',
               'actual_window_end': '2026-09-28T13:30:00Z',
               'unavailable_horizon': '4h', 'gold_change_pct': -0.32293}
    snapshot = {'gold_workflow': {}, 'reanalysis': {'review_findings': [finding]}}
    original = deepcopy(snapshot)
    projected = final_input(snapshot, SimpleNamespace(input_payload={}), catalog=[], assessment={})
    assert snapshot == original
    assert projected['prior_review_findings'] == [finding]
    review = bounded_review({'reader_narrative': 'review pending'}, projected, ['window'])
    assert finding['actual_window_start'] in encode(review)
    assert finding['actual_window_end'] in encode(review)
    assert '-0.32293' in encode(review)


def test_fedwatch_projection_prefers_unambiguous_fields_without_dropping_unknowns():
    from apps.analysis.agents.research_input import _compact_fedwatch_policy
    meeting = {"meeting_date": "2027-09-15", "bins": [],
               "hike_probability": .7, "prob_above_current_target": .7,
               "cut_probability": None, "prob_below_current_target": None,
               "expected_rate_pct": 4.05, "implied_target_midpoint_expected_rate": 4.05,
               "comparisons": {}}
    result = _compact_fedwatch_policy({"meetings": [meeting]})["meetings"][0]
    assert result["prob_above_current_target"] == .7
    assert result["prob_below_current_target"] is None
    assert result["implied_target_midpoint_expected_rate"] == 4.05
    assert "hike_probability" not in result and "cut_probability" not in result
    assert "expected_rate_pct" not in result
    assert result["comparisons"] == {}


def test_cme_projection_keeps_decision_facts_and_qualifications_without_grids():
    ref = {'source': 'cme', 'report_date': '2026-09-11', 'version_type': 'PRELIM'}
    options = {'status': 'available', 'data': {
        'trade_date': '2026-09-11',
        'data_source': {'status': 'PRELIM', 'report_date': '2026-09-11'},
        'selected_source_refs': [ref],
        'expiry_selection': {'selected_expiries': ['OCT26'], 'open_interest_coverage': .68,
                             'selection_policy': {'expiry_date_source': {'OCT26': 'estimated'}}},
        'parameters': {'model': 'black-76', 'f_source': 'parity_inferred', 'r': 0},
        'data_quality': {'warnings': ['expiry date estimated']},
        'gex_semantics': {'label': 'OI-Signed GEX Proxy', 'dealer_position_unknown': True,
                          'shape_proxy_included_in_usd_gex': False},
        'gex': {'gamma_flip': {'price': 4301, 'scope': 'selected_expiry_window'},
                'price_grid': [4000, 4100], 'net_gex_values': [-1, 2],
                'by_expiry': {'OCT26': {'summary': {'f_value': 4400, 'net_gex_signed': 42,
                                                   'put_gex_signed': -18},
                                         'gex_top': [{'strike': 9999}]}}},
        'oi_gamma_concentration_zone': {'levels': [{'expiry': 'OCT26', 'strike': 4350,
                                                   'open_interest': 900}]},
        'reconciliation': {'status': 'prelim_only', 'delta': {'comparison_available': False}},
        'roll_signals': [{'confidence': .001, 'from_expiry': 'OCT26'},
                         {'confidence': .7, 'from_expiry': 'OCT26', 'to_expiry': 'DEC26'}],
    }}
    before = deepcopy(options)
    projected = project_options(options)
    assert options == before
    assert projected['source']['status'] == 'PRELIM'
    assert projected['source']['source_refs'] == [ref]
    assert projected['expiry_window']['open_interest_coverage'] == .68
    assert projected['expiry_window']['expiry_date_source'] == {'OCT26': 'estimated'}
    assert projected['coordinate_policy']['forward_source'] == 'parity_inferred'
    assert projected['semantics']['dealer_position_unknown'] is True
    assert projected['aggregate_proxy_gamma_flip']['price'] == 4301
    assert projected['by_expiry']['OCT26']['oi_signed_gex_proxy']['put'] == -18
    assert projected['concentration']['levels'][0]['strike'] == 4350
    assert projected['reconciliation']['comparison_available'] is False
    assert len(projected['roll_signals']) == 1
    assert projected['omitted_low_confidence_roll_signal_count'] == 1
    for omitted in ('price_grid', 'net_gex_values', 'gex_top'):
        assert omitted not in encode(projected)
    legacy = deepcopy(options)
    summary = legacy['data']['gex']['by_expiry']['OCT26']['summary']
    summary.pop('put_gex_signed')
    summary['put_gex'] = 18
    exposure = project_options(legacy)['by_expiry']['OCT26']['oi_signed_gex_proxy']
    assert exposure['put'] is None
    assert exposure['legacy_put_absolute'] == 18


def test_workflow_projection_keeps_changes_and_fund_windows_without_repetition():
    zone = {'display_label': '4300–4325', 'role': 'Support', 'instrument': 'XAUUSD',
            'level_status': 'Active', 'eligible_for_target': True}
    flow = {'execution_zones': {'zones': [zone, dict(zone), dict(zone, level_status='Stale')]},
            'delta_vs_previous': {'rows': [
                {'symbol': 'XAU', 'current': 4350, 'previous': 4300, 'delta': 50},
                {'symbol': 'DFII10', 'current': 2.6, 'previous': 2.6, 'delta': 0,
                 'change_kind': 'unchanged'},
                {'symbol': 'MISSING', 'current': None, 'previous': None}]},
            'flow_diagnostics': {'window': {'start': '2026-09-01', 'end': '2026-09-08'},
                                 'reports': {'combined': {'duplicate': True}},
                                 'etf': {'weekly': {'shares': -1000000},
                                         'lineage_status': 'verified'}}}
    before = deepcopy(flow)
    projected = project_workflow(flow)
    assert flow == before
    assert projected['execution_zones']['zones'] == [zone]
    assert projected['execution_zones']['omitted_zone_count'] == 2
    delta = projected['delta_vs_previous']
    assert delta['changed_or_noncomparable_rows'][0]['delta'] == 50
    assert delta['unchanged_symbols'] == ['DFII10']
    assert delta['omitted_empty_symbols'] == ['MISSING']
    funds = projected['flow_diagnostics']
    assert funds['window']['end'] == '2026-09-08'
    assert funds['etf']['weekly']['shares'] == -1000000
    assert funds['etf']['lineage_status'] == 'verified'
    assert 'reports' not in funds


def test_compression_preserves_etf_endpoints_and_independent_zone_sources():
    zone = {'display_label': '4300–4325', 'role': 'Support', 'instrument': 'XAUUSD'}
    a, b = {'source': 'a'}, {'source': 'b'}
    flow = {'execution_zones': {'zones': [dict(zone, source_refs=[a]),
                                        dict(zone, source_refs=[b]),
                                        dict(zone, activation='requires reclaim', source_refs=[a])]},
            'flow_diagnostics': {'etf': {'weekly': {'shares': -1500000}}}}
    etf = {'shares_outstanding': 367200000, 'shares_reported_on': '2026-09-11',
           'shares_weekly_anchor_value': 368700000, 'shares_weekly_anchor_date': '2026-09-04'}
    projected = project_workflow(flow, official_etf=etf)
    zones = projected['execution_zones']['zones']
    assert len(zones) == 2
    assert zones[0]['source_refs'] == [a, b]
    assert zones[1]['activation'] == 'requires reclaim'
    window = projected['flow_diagnostics']['etf']['comparison_windows']['shares']
    assert window['current'] - window['weekly_anchor'] == -1500000
    assert (window['weekly_anchor_date'], window['current_date']) == ('2026-09-04', '2026-09-11')
    assert window['previous_date'] is None


def test_exact_facts_and_late_evidence_survive_without_mutating_archive():
    ref = {'source': 'treasury', 'source_url': 'https://example.com/rates',
           'observation_date': '2026-09-11', 'raw_path': '/archive/rates.json'}
    record = {'observations': [{'value': i, 'unit': '%', 'source_refs': [ref]} for i in range(65)],
              'last_fact': {'text': '证据' * 1000, 'value': 2.60001, 'source_refs': [ref]}}
    original = deepcopy(record)
    packed = pack_evidence(record, stage='test')
    assert record == original
    assert packed['observations'][-1]['value'] == 64
    assert packed['last_fact']['text'] == record['last_fact']['text']
    assert packed['last_fact']['value'] == 2.60001
    assert '[truncated]' not in encode(packed)
    assert len(packed['source_catalog']) == 1
    source = packed['source_catalog'][packed['last_fact']['source_ids'][0]]
    assert source['observation_date'] == '2026-09-11'
    assert packed['url_catalog'][source['source_url_id']] == ref['source_url']
    assert packed['input_contract']['omitted_archive_fields']['source_metadata:raw_path'] == 66


def test_unique_aggregate_sources_are_not_lost():
    a, b = {'source': 'a'}, {'source': 'b'}
    result = leaf_sources({'source_refs': [a, b], 'fact': {'source_refs': [a]}})
    assert result['source_refs'] == [b]
    assert result['fact']['source_refs'] == [a]


def test_oversized_context_fails_explicitly_instead_of_truncating():
    with pytest.raises(ResearchInputTooLarge):
        pack_evidence({'fact': 'important' * 1000}, stage='research', max_chars=100)
    with pytest.raises(ResearchInputTooLarge):
        bounded_review({'conclusion': 'x'*1000}, {}, [], max_chars=100)


def test_history_keeps_counterevidence_and_corrected_hypothesis_once():
    result = project_history({'rounds': [
        {'plan': {'hypothesis': 'ETF buying'}, 'collection': {'news': [{'title': 'ETF redemptions'}]}},
        {'plan': {'hypothesis': 'test dollar', 'evidence_assessment': 'ETF disproven'}}]})
    assert result['news'] == [{'title': 'ETF redemptions'}]
    assert result['decision_trail'][-1]['evidence_assessment'] == 'ETF disproven'


def test_history_keeps_agent_selected_evidence_and_unavailable_needs():
    request = {'provider': 'tradingview', 'key': 'CBOE:VIX', 'claim': '检验避险'}
    gap = {'data': 'OTC买方', 'materiality': 'decisive'}
    result = project_history({'schema_version': 'adaptive_research.v3',
        'unavailable_data_needs': [gap], 'rounds': [{
            'plan': {'driver_assessment': '避险与利率对冲', 'competing_hypotheses': ['仓位修复'],
                     'data_requests': [request], 'unavailable_data_needs': [gap]},
            'collection': {'market_observations': [{'ticker': 'CBOE:VIX', 'value': 28.0}]},
            'executed_requests': {'data_requests': [request]}, 'new_evidence_count': 1}]})
    assert result['market_observations'][0]['ticker'] == 'CBOE:VIX'
    assert result['decision_trail'][0]['requested_evidence'] == [request]
    assert result['decision_trail'][0]['competing_hypotheses'] == ['仓位修复']
    assert result['unavailable_data_needs'] == [gap]


def test_article_projection_keeps_late_corrections_and_split_attribution_verbatim():
    from hashlib import sha256

    blocks = [
        'Oil markets opened sharply higher after reports of a pipeline disruption.',
        'The initial report said the pipeline stopped 5 million bpd on September 17.',
        *[f'Background paragraph {index} describes regional market history and logistics.' for index in range(9)],
        'However, the operator denied an outage and said the system remained online.',
        'The 5 million bpd figure is capacity, not actual lost output, which remains uncertain.',
        'An earlier version corrected the date and removed an unsupported production estimate.',
        '"There is no verified physical loss at this stage."',
        'The operator spokesperson said in a statement released at 14:30 UTC.',
        '此消息未经证实。',
    ]
    document = {
        'document_id': 'a' * 32,
        'status': 'available',
        'evidence_scope': 'publisher_body',
        'published_at': '2026-09-17T14:30:00Z',
        'parsed_path': 'parsed/research_documents/a.json',
        'parsed_sha256': 'b' * 64,
        'part_index': 0,
        'part_count': 2,
        'detail_request_format': f"{'a' * 32}:<part_index>",
        'body_is_complete': False,
        'text_blocks': blocks,
    }
    projected = project_news_documents([document], focus_text='oil pipeline supply')[0]
    rows = projected['selected_blocks']['rows']
    selected = {row[0]: row[2] for row in rows}

    for index in (1, 11, 12, 13, 14, 15, 16):
        assert selected[index] == blocks[index]
    assert projected['omitted_block_count'] > 0
    assert projected['transmitted_body_complete'] is False
    assert projected['original_text_blocks_sha256'] == sha256(encode(blocks).encode()).hexdigest()
    assert projected['detail_request_format'].endswith(':<part_index>')
    assert projected['part_count'] == 2
    assert 'not the full article' in projected['archive_projection']
    assert project_news_documents([projected])[0] == projected


def test_article_exact_duplicates_keep_each_document_identity_without_repeating_text():
    shared = 'Reuters reported that officials had not verified the claimed supply loss.'
    documents = [
        {'document_id': char * 32, 'status': 'available', 'evidence_scope': 'publisher_body',
         'publisher': publisher, 'published_at': published,
         'text_blocks': [shared, f'{publisher} added a distinct dated fact for 2026-09-17.']}
        for char, publisher, published in (
            ('a', 'Publisher A', '2026-09-17T10:00:00Z'),
            ('b', 'Publisher B', '2026-09-17T11:00:00Z'),
        )
    ]
    first, second = project_news_documents(documents, focus_text='supply loss Reuters')
    assert first['publisher'] == 'Publisher A'
    assert second['publisher'] == 'Publisher B'
    assert first['published_at'] != second['published_at']
    assert first['selected_blocks']['rows'][0][2] == shared
    assert second['selected_blocks']['rows'][0][2].startswith('exact_duplicate:' + 'a' * 32)


def test_non_article_structured_detail_is_not_paragraph_sampled():
    document = {
        'document_id': 'c' * 32,
        'status': 'available',
        'evidence_scope': 'computed_snapshot_detail',
        'text_blocks': ['{"price_grid":[4000,4100]}'],
        'observations': [{'value': 100, 'observation_date': '2026-09-17'}],
    }
    projected = project_news_documents([document])[0]
    assert projected['text_blocks'] == document['text_blocks']
    assert projected['observations'] == document['observations']
    assert 'selected_blocks' not in projected


def test_sensitive_source_urls_and_failure_reasons_are_redacted_without_losing_locator():
    secret = 'do-not-print-this-secret'
    url = f'https://api.example.test/data?series=DGS10&api_key={secret}&format=json'
    packed = pack_evidence({
        'source_refs': [{'source': 'fixture', 'source_url': url,
                         'reason': 'collector failed at ' + url}],
        'errors': ['request failed: ' + url],
    }, stage='test')
    serialized = encode(packed)
    assert secret not in serialized
    assert '%5BREDACTED%5D' in serialized
    assert 'series=DGS10' in serialized
    assert packed['errors'][0].startswith('request failed: https://api.example.test/data')


def test_quote_semantics_survive_projection():
    observation = {'symbol': 'WTI', 'ticker': 'NYMEX:CL1!', 'display_value': 100.05,
                   'provider_change_pct': -2.37, 'change_basis': 'unknown_prior_time',
                   'quote_time_verified': False, 'continuous_contract': True,
                   'intraday_confirmation_allowed': False, 'unit': 'USD/bbl'}
    assert project_cross_asset({'observations': [observation]})['observations'][0] == observation


def test_cross_asset_and_history_project_chart_windows_without_raw_bars():
    ref = {'source': 'tradingview_chart', 'raw_path': 'raw/tv/chart.json'}
    bundle = {
        'schema_version': 'cross_asset_chart_windows.v1',
        'as_of': '2026-09-17T12:00:00+00:00',
        'series_health': [{
            'ticker': 'OANDA:XAUUSD', 'status': 'AVAILABLE', 'completed_bar_count': 64,
            'last_completed_bar_end': '2026-09-17T11:45:00+00:00',
            'bars': [{'time': '2026-09-17T11:30:00+00:00', 'close': 3700}],
            'source_refs': [ref],
        }],
        'windows': [{
            'group': 'gold_vs_CBOE:VIX', 'window_start': '2026-09-17T10:45:00+00:00',
            'window_end': '2026-09-17T11:45:00+00:00', 'horizon_minutes': 60,
            'status': 'AVAILABLE_DELAYED', 'aligned_comparison_allowed': True,
            'changes': [{'ticker': 'OANDA:XAUUSD', 'symbol': 'XAUUSD',
                         'start_close': 3690, 'end_close': 3700, 'change_pct': 0.271,
                         'delay_seconds': 600, 'source_refs': [ref],
                         'bars': [{'close': 3700}]}],
            'bars': [{'close': 3700}],
        }],
        'causal_attribution_allowed': False,
        'chart_series': [{'bars': [{'close': 3700}]}],
    }

    cross = project_cross_asset({'chart_windows': bundle, 'chart_series': bundle['chart_series']})
    history = project_history({'market_windows': [bundle], 'rounds': []})
    assert cross['chart_windows']['windows'][0]['changes'][0]['change_pct'] == 0.271
    assert history['market_windows'][0]['series_health'][0]['completed_bar_count'] == 64
    assert history['market_windows'][0]['causal_attribution_allowed'] is False
    assert 'bars' not in encode(cross)
    assert 'chart_series' not in encode(cross)
    assert 'bars' not in encode(history)


def test_final_synthesis_input_contains_compact_windows_without_raw_bars():
    from types import SimpleNamespace

    ref = {'source': 'tradingview_chart', 'raw_path': 'raw/tv/chart.json'}
    windows = [
        {'group': f'gold_vs_asset_{index}', 'horizon_minutes': 15 + index,
         'status': 'AVAILABLE_DELAYED', 'aligned_comparison_allowed': True,
         'changes': [
             {'ticker': 'OANDA:XAUUSD', 'start_close': 3690, 'end_close': 3700,
              'change_pct': None, 'source_refs': [ref], 'bars': [{'close': 3700}]},
             {'ticker': 'TVC:US10Y', 'start_close': 4.1, 'end_close': 4.12,
              'change_bp': 2.0, 'source_refs': [ref]},
         ]}
        for index in range(12)
    ]
    bundle = {
        'schema_version': 'cross_asset_chart_windows.v1',
        'as_of': '2026-09-17T12:00:00+00:00',
        'series_health': [{'ticker': 'OANDA:XAUUSD', 'status': 'AVAILABLE',
                           'completed_bar_count': 64, 'source_refs': [ref],
                           'bars': [{'time': '2026-09-17T11:30:00+00:00', 'close': 3700}]}],
        'windows': windows,
        'causal_attribution_allowed': False,
        'chart_series': [{'bars': [{'close': 3700}]}],
    }
    snapshot = {
        'snapshot_id': 'snapshot-1', 'trade_date': '2026-09-17',
        'snapshot_time': '2026-09-17T12:00:00+00:00',
        'gold_workflow': {'cross_asset_freshness': {
            'chart_windows': bundle, 'chart_series': bundle['chart_series'],
        }},
        'adaptive_research': {'market_windows': [bundle], 'rounds': []},
    }
    projected = final_input(
        snapshot, SimpleNamespace(input_payload={}), catalog={}, assessment={}
    )
    serialized = encode(projected)
    chart = projected['tradingview_cross_asset']['chart_windows']
    adaptive = projected['adaptive_research']['market_windows'][0]
    assert len(chart['windows_table']['rows']) == 12
    assert len(chart['changes_table']['rows']) == 24
    assert len(chart['series_health_table']['rows']) == 1
    assert len(adaptive['windows_table']['rows']) == 12
    assert 'windows' not in chart and 'series_health' not in chart
    change_columns = chart['changes_table']['columns']
    pct_index = change_columns.index('change_pct')
    assert chart['changes_table']['rows'][0][pct_index] is None
    assert pct_index not in chart['changes_table']['missing_by_row'].get('0', [])
    assert pct_index in chart['changes_table']['missing_by_row']['1']
    assert change_columns[0] == 'window_index'
    assert len(projected['source_catalog']) == 1
    assert serialized.count('"horizon_minutes"') == 2
    assert 'window_index' in projected['input_contract']['tabular_projection']
    assert 'bars' not in serialized
    assert 'chart_series' not in serialized


def test_macro_projection_omits_only_aggregate_source_plumbing():
    fact_ref = {'source': 'treasury', 'observation_date': '2026-09-11'}
    projected = project_macro({
        'source_refs': [{'source': 'aggregate'}],
        'input_snapshot_ids': {'macro': 'snapshot-id'},
        'layers': {'duplicate': True},
        'engines': {'treasury': {'real_yield': 2.6, 'source_refs': [fact_ref]}},
    })
    assert 'source_refs' not in projected
    assert 'input_snapshot_ids' not in projected
    assert 'layers' not in projected
    assert projected['engines']['treasury']['source_refs'] == [fact_ref]
    assert 'fact-level' in projected['projection_note']


def test_price_action_projection_keeps_state_and_declares_bounded_history():
    events = [{'type': 'CANDLE_REJECTION', 'time': str(i)} for i in range(12)]
    pivots = [{'label': 'HL', 'pivot_time': str(i)} for i in range(10)]
    projected = project_price_action({'schema_version': 'price_action.v1', 'timeframes': {
        '15m': {'status': 'available', 'structure_trend': 'bullish', 'trade_permission': True,
                'events': events, 'pivots': pivots, 'raw_path': 'archive.json'}}})
    frame = projected['timeframes']['15m']
    assert frame['status'] == 'available'
    assert frame['structure_trend'] == 'bullish'
    assert frame['event_count'] == 12
    assert frame['recent_events'] == events[-8:]
    assert frame['pivot_count'] == 10
    assert frame['recent_pivots'] == pivots[-6:]
    assert 'raw_path' not in frame
    assert 'complete ordered history' in frame['projection_note']


def test_non_object_sources_can_be_resolved():
    packed = pack_evidence({'source_refs': ['series:A', ['legacy', 1]]}, stage='test')
    assert len(packed['source_catalog']) == 2


def test_equal_sequence_values_are_not_deduplicated():
    assert pack_evidence({'returns': [1, 1, 2]}, stage='test')['returns'] == [1, 1, 2]


def test_reviewer_receives_the_same_full_evidence_not_only_macro():
    import json
    from types import SimpleNamespace
    from apps.analysis.agents.macro_causal_review import review_macro_thesis
    facts = pack_evidence({'macro_causal': {'real': 2.6},
                           'cme_options': {'version': 'PRELIM'},
                           'price_action': {'execution_timeframe': '15m'},
                           'cot_reports': {'report_date': '2026-09-08'}}, stage='synthesis')
    def gateway(**kw):
        context = json.loads(kw['messages'][1]['content'])
        assert context['evidence'] == facts
        return SimpleNamespace(content=json.dumps({'checks': [
            {'id': i, 'passed': True, 'reason': 'verified'} for i in range(14)]}))
    review = review_macro_thesis(gateway=gateway, analysis={'reader_narrative': 'test'},
                                evidence=facts, audit_context={})
    assert review['status'] == 'pass'
    assert review['input_metrics']['contract']['stage'] == 'review'


def test_unbound_oversize_workflow_cannot_bypass_input_gate_or_accept_state():
    from tests.analysis.test_research_synthesis import _output
    from apps.analysis.agents.research_synthesis import enrich_research_coordinator
    snapshot = {'gold_workflow': {'schema_version': 'gold_workflow.v2',
                                 'reader_report_version': 'gold_reader.v3',
                                 'macro_causal': {'oversize_fact': 'x'*200000}}}
    def forbidden(**kwargs):
        pytest.fail('oversize evidence must not reach model')
    before = _output()
    result = enrich_research_coordinator(snapshot, before, forbidden)
    assert result.input_payload['research_synthesis']['failure_reason'] == 'input_validation_blocked'
    assert result.bias.value == "unavailable"
    assert result.accepted_state_conclusion == before.accepted_state_conclusion


def test_source_qualifications_are_preserved():
    ref = {'source': 'news', 'source_url': 'https://example.com/story',
           'full_text_available': False, 'content_scope': 'headline_only',
           'verification_status': 'unconfirmed', 'reason': 'no primary confirmation',
           'vintage_date': '2026-09-11', 'report_type': 'combined', 'version_type': 'PRELIM'}
    packed = pack_evidence({'source_refs': [ref]}, stage='test')
    source = packed['source_catalog'][packed['source_ids'][0]]
    for key, value in ref.items():
        if key != 'source_url':
            assert source[key] == value


def test_pa_gate_excludes_weekend_proxy_from_frozen_snapshot_projection():
    from apps.analysis.agents.research_input import project_workflow
    from apps.features.research.price_action import gate_execution_frames
    execution = {'timeframe_features': [{'timeframe': '15m', 'status': 'available',
                  'trend': 'bearish', 'events': [{'type': 'failed_breakout_down', 'level': 4348.3}]}]}
    quality = {'timeframes': {'15m': {'status': 'unavailable', 'reason': 'market_session_CLOSED'}}}
    original = deepcopy(execution)
    for projected in (gate_execution_frames(execution, quality),
                      project_workflow({'execution': execution, 'price_action': quality})['execution']):
        assert projected['timeframe_features'][0]['events'] == []
        assert projected['timeframe_features'][0]['trend'] is None
        assert projected['status'] == 'unavailable'
        assert '4348.3' not in encode(projected)
    assert execution == original
    assert gate_execution_frames(execution, {'timeframes': {'15m': {'status': 'available'}}})['timeframe_features'] == execution['timeframe_features']


@pytest.mark.parametrize('second_review_passes', [True, False])
def test_v3_review_revision_is_bounded_and_preserves_accepted(second_review_passes):
    import json
    from tests.analysis.test_research_synthesis import _output
    from apps.analysis.agents.research_synthesis import enrich_research_coordinator
    fields = ('growth','inflation','labor','fed','treasury','term_premium','fiscal','dollar','liquidity','credit','oil')
    answer = {'dominant_factor': '条件性解释', 'counter_evidence': [], 'state_limitations': [],
              'convergence_transition': [], 'evidence_ids': ['macro_causal_v4'],
              'reader_narrative': '初稿：买盘类型仍待确认',
              'macro_answers': {k: '证据不足' for k in ('growth','inflation','reaction','policy','treasury','oil','response','residual')},
              'macro_narrative': {k: '证据不足' for k in fields},
              'dominant_shocks': {k: '证据不足' for k in ('primary','secondary','counter')}}
    calls=[]
    def gateway(**kw):
        calls.append(kw)
        if len(calls) in (2,4):
            passed = len(calls)==4 and second_review_passes
            content = {'checks': [{'id': i, 'passed': passed or i!=7, 'reason': '因果证据检查'} for i in range(14)]}
        else:
            content = {**answer, 'reader_narrative': '修订：保留候选，不确认买方' if len(calls)==3 else answer['reader_narrative']}
        return {'content': json.dumps(content)}
    from tests.analysis.test_input_validation import valid_snapshot
    snapshot = valid_snapshot()
    snapshot['gold_workflow'].update(reader_report_version='gold_reader.v3', macro_causal={'schema_version': 'gold_macro_causal.v4'})
    before=_output()
    result=enrich_research_coordinator(snapshot,before,gateway)
    assert len(calls)==4
    metadata=result.input_payload['research_synthesis']
    assert metadata['analysis']['reader_narrative'].startswith('修订')
    assert metadata['macro_review']['revision_attempts']==1
    assert metadata['macro_review']['prior_review']['status']=='needs_revision'
    assert metadata['macro_review']['status']==('pass' if second_review_passes else 'needs_revision')
    assert result.confidence==before.confidence*(1 if second_review_passes else .7)
    assert result.accepted_state_conclusion==before.accepted_state_conclusion


def test_revision_failure_keeps_valid_challenged_draft():
    from apps.analysis.agents.research_synthesis import _revise_after_review
    draft={'reader_narrative': '有依据的草稿'}
    review={'status': 'needs_revision', 'confidence_multiplier': .7, 'checks': [{'id': 7, 'passed': False}]}
    def unavailable(**kw):
        raise TimeoutError('provider timeout')
    result=_revise_after_review(gateway=unavailable,parsed=draft,raw_response='{}',response=None,
                               messages=[],review=review,prompt_payload={},audit_context={})
    assert result[0]==draft
    assert result[-1]['status']=='needs_revision'
    assert result[-1]['revision_error']=='TimeoutError'
    assert result[-1]['revision_attempts']==1


def _expand_table(table):
    if isinstance(table, list):
        return table
    rows = []
    for index, cells in enumerate(table['rows']):
        missing = table.get('missing_by_row', {}).get(str(index), [])
        row = deepcopy(table.get('shared_fields', {}))
        row.update({column: cell for i, (column, cell) in
                    enumerate(zip(table['columns'], cells)) if i not in missing})
        rows.append(row)
    return rows


def test_table_sharing_preserves_missing_null_order_and_counterevidence():
    from apps.analysis.agents.research_input import _rows_table, _share_table_fields

    qualification = 'Historical delayed observations; no causal attribution permitted.'
    rows = [
        {'symbol': 'GOLD', 'qualification': qualification, 'value': None,
         'date': '2026-09-17', 'confirmation': True},
        {'symbol': 'USD', 'qualification': qualification,
         'date': '2026-09-16', 'confirmation': 1},
        {'symbol': 'OIL', 'qualification': qualification, 'value': -1.5,
         'date': '2026-09-17', 'confirmation': False},
    ]
    table = _rows_table(rows, key_name='symbol')
    before = encode(table)
    _share_table_fields(table)
    assert len(encode(table)) < len(before)
    assert table['shared_fields'] == {'qualification': qualification}
    assert 'symbol' in table['columns']
    assert encode(_expand_table(table)) == encode(rows)
    assert _expand_table(table)[0]['value'] is None
    assert 'value' not in _expand_table(table)[1]
    packed_once = deepcopy(table)
    _share_table_fields(table)
    assert table == packed_once


def test_synthesis_shares_article_policy_without_losing_body_or_source_identity():
    from types import SimpleNamespace

    qualification = 'Operator denied production had resumed; the figure is capacity, not supply.'
    documents = [
        {'document_id': str(i) * 32, 'title': 'Supply report',
         'publisher': f'publisher_{i}', 'status': 'available',
         'published_at': f'2026-09-17T1{i}:00:00Z',
         'evidence_scope': 'publisher_body', 'text_blocks': [qualification],
         'source_refs': [{'source': f'publisher_{i}',
                          'source_url': f'https://example.test/{i}'}]}
        for i in range(4)
    ]
    snapshot = {'snapshot_id': 'transport-test', 'gold_workflow': {},
                'mainstream_news': {'documents': documents}}
    original = deepcopy(snapshot)
    packed = final_input(snapshot, SimpleNamespace(input_payload={}), catalog=[], assessment={})
    table = packed['mainstream_news']['documents_table']
    assert 'selection_policy' in table['shared_fields']
    assert 'archive_projection' in table['shared_fields']
    restored = _expand_table(table)
    assert [d['document_id'] for d in restored] == [d['document_id'] for d in documents]
    assert [d['published_at'] for d in restored] == [d['published_at'] for d in documents]
    assert restored[0]['selected_blocks']['rows'][0][2] == qualification
    for document in restored:
        assert 'not the full article' in document['archive_projection']
        source = packed['source_catalog'][document['source_ids'][0]]
        assert source['source'] == document['publisher']
        assert packed['url_catalog'][source['source_url_id']].startswith('https://example.test/')
    assert snapshot == original
    assert packed['input_contract']['decision_projection_version'] == 'decision_tables.v2'
    assert bounded_review({}, packed, [])['evidence'] == packed


def test_pa_transport_keeps_all_frames_events_and_distinct_zone_states():
    from types import SimpleNamespace

    frames = {
        tf: {'status': 'available', 'latest_bar_time': '2026-09-17T10:00:00Z',
             'structure_trend': trend, 'trade_permission': False,
             'events': [{'type': 'RECLAIM', 'time': '2026-09-17T10:00:00Z'}],
             'pivots': [{'price': 4300, 'label': 'HL'}],
             'zone_states': [{'low': 4290, 'high': 4310, 'state': state, 'events': []}]}
        for tf, trend, state in [('15m', 'bullish', 'RECLAIMED'),
                                  ('1h', 'bearish', 'BROKEN_PENDING'),
                                  ('4h', 'unconfirmed', 'WATCH')]
    }
    pa = {'timeframes': frames, 'five_minute_enabled': False}
    expected = project_price_action(pa)
    snapshot = {'gold_workflow': {'price_action': pa}}
    original = deepcopy(snapshot)
    result = final_input(snapshot, SimpleNamespace(input_payload={}), catalog=[], assessment={})
    for tf, frame in result['price_action']['timeframes'].items():
        for field in ('recent_events', 'recent_pivots', 'zone_states'):
            assert _expand_table(frame[field + '_table']) == expected['timeframes'][tf][field]
        assert frame['structure_trend'] == frames[tf]['structure_trend']
        assert frame['trade_permission'] is False
    assert snapshot == original


def test_review_budget_includes_its_transport_contract():
    analysis, evidence, questions = {'claim': 'x' * 100}, {}, []
    body_size = len(encode({'analysis': analysis, 'evidence': evidence, 'questions': questions}))
    with pytest.raises(ResearchInputTooLarge):
        bounded_review(analysis, evidence, questions, max_chars=body_size + 1)
    payload = bounded_review(analysis, evidence, questions, max_chars=1000)
    assert len(encode(payload)) <= payload['input_contract']['size_limit_chars']


def test_input_metrics_measures_each_domain_without_copying_evidence():
    from apps.analysis.agents.research_input import input_metrics

    payload = {'cme_options': {'status': 'PRELIM'}, 'mainstream_news': {'text': '新闻反证'}}
    metrics = input_metrics(payload)
    assert metrics['section_characters'] == {key: len(encode(value)) for key, value in payload.items()}
    assert metrics['characters'] == len(encode(payload))
    assert metrics['utf8_bytes'] > metrics['characters']
    assert '新闻反证' not in encode(metrics)
