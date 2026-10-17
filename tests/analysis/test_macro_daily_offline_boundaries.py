"""Synthetic boundary cases; no live market, collector or model calls."""
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace

import pytest

from apps.analysis.agents.research_synthesis import _build_prompt_payload
from apps.analysis.snapshots.report_continuity import prior_report_context_model_input
from apps.features.macro.fedwatch_policy import project_fedwatch_policy
from apps.features.macro.release_evidence import build_release_evidence
from apps.features.research.macro_causal import build_macro_causal
from apps.features.research.price_action import qualify_price_action_evidence
from apps.renderer.markdown.gold_reader import reader_audit_details, research_sections
from tests.analysis.test_gold_detailed_report import snapshot as detailed_snapshot, response
from tests.analysis.test_gold_macro_daily import context_payload
from tests.analysis.test_research_synthesis import _output
from tests.analysis.test_research_input import _expand_table
from tests.features.test_fedwatch import snapshot as fedwatch_snapshot, NOW


def test_collector_archive_reaches_real_synthesis_as_historical_distribution():
    raw = fedwatch_snapshot()
    before = deepcopy(raw)
    data = detailed_snapshot()
    data.update(snapshot_time='2026-09-28T20:00:00+00:00', snapshot_id='synthetic-stale')
    data.setdefault('macro', {}).setdefault('data', {})['fedwatch'] = raw
    data['gold_workflow']['macro_causal'] = build_macro_causal(data)
    policy = data['gold_workflow']['macro_causal']['engines']['policy']
    assert len(policy['meetings']) == 4
    assert policy['distribution_scope'] == 'historical_snapshot_only'
    assert policy['current_repricing_eligible'] is False
    assert policy['repricing']['status'] == 'unavailable'
    assert all(m['repricing_1d_bp'] is None for m in policy['meetings'])
    payload = _build_prompt_payload(data, _output())
    projected = payload['macro_causal']['engines']['policy']
    table = projected['meetings']['policy_columns_table']
    assert table['column_values'][table['columns'].index('meeting_date')] == [m['meeting_date'] for m in policy['meetings']]
    assert projected['source_health']['status'] == 'stale'
    assert raw == before


def test_collector_archive_future_receipt_and_unknown_shape_fail_closed():
    raw = fedwatch_snapshot()
    raw['collected_at'] = '2026-09-29T00:00:00Z'
    policy = project_fedwatch_policy(raw, as_of=NOW)
    assert policy['meetings'] == []
    assert policy['reason'] == 'collected_at_in_future'
    assert project_fedwatch_policy({}, as_of=NOW)['reason'] == 'fedwatch_view_contract_missing'


def test_saved_fresh_view_does_not_keep_freshness_at_later_cutoff():
    from apps.features.macro.fedwatch import build_fedwatch_view
    view = build_fedwatch_view(fedwatch_snapshot(), as_of=NOW)
    before = deepcopy(view)
    policy = project_fedwatch_policy(view, as_of='2026-09-28T20:00:00Z')
    assert len(policy['meetings']) == 4
    assert policy['source_health']['status'] == 'stale'
    assert policy['repricing']['direction'] is None
    assert policy['current_repricing_eligible'] is False
    assert view == before


def test_fresh_distribution_without_comparison_is_not_repricing():
    raw = fedwatch_snapshot()
    raw['rows'] = [r for r in raw['rows'] if r['comparison_window'] == 'current']
    policy = project_fedwatch_policy(raw, as_of=NOW)
    assert len(policy['meetings']) == 4
    assert policy['distribution_scope'] == 'current_snapshot'
    assert policy['current_repricing_eligible'] is False


def test_native_audit_survives_unavailable_cftc_and_partial_labor():
    data = detailed_snapshot()
    data['gold_workflow']['reader_presentation'] = 'gold_reader.research.v1'
    data.setdefault('daily_research', {})['cot_reports'] = {'status': 'unavailable', 'reason': 'not_collected'}
    data['daily_research']['supplemental_sources'] = {
        'UNRATE': {'status': 'available', 'value': 4.0, 'source_refs': [{'source': 'synthetic_fred'}]}}
    data['input_validation'] = {'status': 'partial', 'domains': {'employment': {'status': 'unavailable'}}}
    synthesis = {'status': 'success', 'analysis': {**response(), 'reader_narrative': '## 一句话结论\n\n合成正文。'},
                 'macro_review': {'status': 'pass'}}
    outputs = {'coordinator': SimpleNamespace(input_payload={'research_synthesis': synthesis})}
    audit = reader_audit_details(data, outputs)
    assert 'not_collected' in audit
    sections = research_sections(data, synthesis)
    assert '部分历史就业与工资序列仍可用：UNRATE' in sections[-1]['body']
    assert '就业领域完整发布与审计材料' in sections[-1]['body']
    assert sections[0]['body'] == synthesis['analysis']['reader_narrative']


def pa_fixture():
    return {'timeframes': {'15m': {'status': 'available', 'ticker': 'OANDA:XAUUSD',
        'source_refs': [{'source': 'synthetic', 'retrieved_at': '2026-10-16T04:55:00Z'}],
        'pivots': [{'side': 'high', 'price': 4179.875, 'pivot_time': '2026-10-16T03:00:00Z',
                    'confirmed_at': '2026-10-16T03:30:00Z'},
                   {'side': 'low', 'price': 4163.265, 'pivot_time': '2026-10-16T03:45:00Z',
                    'confirmed_at': '2026-10-16T04:15:00Z'}],
        'events': [{'type': 'BOS', 'direction': 'bullish', 'price': 4179.875,
                    'time': '2026-10-16T04:00:00Z', 'pivot_time': '2026-10-16T03:00:00Z',
                    'pivot_confirmed_at': '2026-10-16T03:30:00Z'}]}}}


def test_pa_receipt_is_not_confirmation_and_event_matches_exact_pivot():
    raw = pa_fixture()
    before = deepcopy(raw)
    result = qualify_price_action_evidence(raw, as_of='2026-10-16T04:57:00Z')['timeframes']['15m']
    low = result['pivots'][1]
    assert low['pivot_confirmed_at'] == '2026-10-16T04:15:00Z'
    assert low['available_at'] == '2026-10-16T04:55:00+00:00'
    assert low['decision_eligible_at_cutoff'] is True
    assert result['events'][0]['pivot_id'] == result['pivots'][0]['pivot_id']
    assert raw == before
    earlier = qualify_price_action_evidence(raw, as_of='2026-10-16T04:00:00Z')['timeframes']['15m']
    assert not earlier['pivots'][1]['decision_eligible_at_cutoff']
    assert not earlier['events'][0]['decision_eligible_at_cutoff']
    raw['timeframes']['15m']['events'][0]['price'] = 4186.385
    wrong = qualify_price_action_evidence(raw, as_of='2026-10-16T04:57:00Z')['timeframes']['15m']['events'][0]
    assert wrong['pivot_id'] is None and not wrong['decision_eligible_at_cutoff']


@pytest.mark.parametrize('receipt', [None, '2026-10-16T03:00:00Z', '2026-10-16T05:00:00Z'])
def test_missing_early_or_future_receipt_never_grants_current_pa_eligibility(receipt):
    raw = pa_fixture()
    raw['timeframes']['15m']['source_refs'][0]['retrieved_at'] = receipt
    result = qualify_price_action_evidence(raw, as_of='2026-10-16T04:57:00Z')['timeframes']['15m']
    assert not result['pivots'][1]['decision_eligible_at_cutoff']
    assert not result['events'][0]['decision_eligible_at_cutoff']


def release_snapshot():
    def observation(value, at, kind):
        return {'status': 'available', 'indicator': 'PPI', 'reference_period': '2026-09',
                'measure': 'mom_sa', 'unit': 'percent', 'value': value, 'observation_date': '2026-10-15',
                'published_at': at, 'retrieved_at': at, 'evidence_kind': kind,
                'source_refs': [{'source': 'synthetic_release', 'source_url': 'https://example.test/release',
                                 'raw_path': 'synthetic.json', 'retrieved_at': at, 'source_type': 'official'}]}
    return {'snapshot_time': '2026-10-16T04:57:00Z', 'macro': {'data': {'release_events': [
        {'event_id': 'synthetic-ppi', 'actual': observation(1.3, '2026-10-15T12:30:00Z', 'official_release_value'),
         'consensus': observation(0.6, '2026-10-15T12:00:00Z', 'pre_release_consensus')}]}}, 'snapshot_id': 'synthetic'}


def test_release_surprise_computed_only_from_matching_pre_release_evidence():
    data = release_snapshot()
    before = deepcopy(data)
    feature = build_macro_causal(data)['engines']['releases']
    assert feature['events'][0]['surprise']['value'] == pytest.approx(0.7)
    assert feature['events'][0]['market_response']['status'] == 'unavailable'
    assert feature['policy_response']['status'] == 'unverified'
    assert data == before


def test_existing_formal_event_response_reaches_synthesis_without_inventing_surprise():
    from apps.features.news.formal_events import build_official_event_snapshot
    from tests.features.news.test_formal_events import _candidate, _reaction, AS_OF
    formal = build_official_event_snapshot(candidates=[_candidate()], reactions=[_reaction()], as_of=AS_OF)
    data = detailed_snapshot()
    data['snapshot_time'] = AS_OF.isoformat()
    data['official_events'] = {'status': 'available', 'data': formal.model_dump(mode='json')}
    data['gold_workflow']['macro_causal'] = build_macro_causal(data)
    payload = _build_prompt_payload(data, _output())
    events = _expand_table(payload['macro_causal']['engines']['releases']['events_table'])
    assert events[0]['market_response']['status'] == 'confirmed'
    assert events[0]['market_response']['return_pct'] == 0.42
    assert events[0]['surprise']['value'] is None
    assert events[0]['actual']['status'] == 'unavailable'


@pytest.mark.parametrize('reverse', [False, True])
def test_duplicate_official_feeds_reach_messages_once_with_both_sources(reverse):
    """Synthetic duplicate feeds; no real market or model evaluation."""
    from apps.features.news.formal_events import build_official_event_snapshot
    from tests.features.news.test_formal_events import _candidate, AS_OF
    first = _candidate()
    second = deepcopy(first)
    second['source_refs'][0]['raw_path'] = 'raw/official/synthetic-second-feed.json'
    rows = [first, first, second]
    if reverse:
        rows.reverse()
    formal = build_official_event_snapshot(candidates=rows, reactions=[], as_of=AS_OF)
    data = detailed_snapshot()
    data['snapshot_time'] = AS_OF.isoformat()
    data['official_events'] = {'status': 'available', 'data': formal.model_dump(mode='json')}
    before = deepcopy(data)
    feature = build_macro_causal(data)
    assert data == before
    merged = feature['engines']['releases']['events']
    assert len(merged) == 1
    assert {ref['raw_path'] for ref in merged[0]['source_refs']} == {
        first['source_refs'][0]['raw_path'], second['source_refs'][0]['raw_path']}
    assert len(merged[0]['source_refs']) == 2
    data['gold_workflow']['macro_causal'] = feature
    events = _expand_table(_build_prompt_payload(data, _output())['macro_causal']['engines']['releases']['events_table'])
    assert len(events) == 1
    assert events[0]['actual']['status'] == 'unavailable'
    assert events[0]['consensus']['status'] == 'unavailable'
    assert events[0]['surprise']['value'] is None


def test_same_official_identity_at_different_times_is_not_coalesced():
    from apps.features.news.formal_events import build_official_event_snapshot
    from tests.features.news.test_formal_events import _candidate, AS_OF
    first = _candidate()
    second = _candidate(event_time='2026-07-29T12:10:00+00:00')
    formal = build_official_event_snapshot(candidates=[first, second], reactions=[], as_of=AS_OF)
    result = build_release_evidence({'snapshot_time': AS_OF.isoformat(),
        'official_events': {'status': 'available', 'data': formal.model_dump(mode='json')}})
    assert len(result['events']) == 2
    assert {row['published_at'] for row in result['events']} == {
        first['event_time'], second['event_time']}


def test_archive_hash_gate_rejects_consensus_without_erasing_actual(tmp_path):
    import hashlib
    from tests.analysis.test_input_validation import valid_snapshot
    from apps.analysis.snapshots.input_validation import prepare_analysis_inputs
    data = valid_snapshot(tmp_path)
    data.update(snapshot_time='2026-10-16T04:57:00Z', trade_date='2026-10-16')
    data.setdefault('gold_workflow', {})['production_shadow'] = True
    release = release_snapshot()['macro']['data']['release_events'][0]
    for role in ('actual', 'consensus'):
        filename = role + '.json'
        (tmp_path/filename).write_text('{"fixture":"synthetic"}')
        ref = release[role]['source_refs'][0]
        ref.update(raw_path=filename, raw_sha256=hashlib.sha256((tmp_path/filename).read_bytes()).hexdigest())
    release['consensus']['source_refs'][0]['raw_sha256'] = '0' * 64
    data.setdefault('macro', {}).setdefault('data', {})['release_events'] = [release]
    prepared = prepare_analysis_inputs(data, storage_root=tmp_path)
    events = prepared['gold_workflow']['macro_causal']['engines']['releases']['events']
    assert events[0]['actual']['value'] == 1.3
    assert events[0]['consensus']['status'] == 'unavailable'
    assert events[0]['surprise']['value'] is None


def test_native_bar_table_encoding_is_lossless_including_missing_and_zero():
    from apps.analysis.agents.research_input import _project_packed_tables
    from tests.analysis.test_research_input import _expand_table
    bars = [{'time': '2026-10-16T04:00:00Z', 'open': 1, 'high': 2, 'low': 0, 'close': 1, 'volume': 0},
            {'time': '2026-10-16T04:15:00Z', 'open': 1, 'high': 3, 'low': 1, 'close': 2, 'volume': None},
            {'time': '2026-10-16T04:30:00Z', 'open': 2, 'high': 3, 'low': 1, 'close': 2}]
    payload = {'technical_daily': {'data': {'execution_timeframes': {'15m': {'bars': deepcopy(bars)}}}}}
    _project_packed_tables(payload)
    table = payload['technical_daily']['data']['execution_timeframes']['15m']['bars_table']
    assert _expand_table(table) == bars


@pytest.mark.parametrize('change,reason', [
    ({'retrieved_at': '2026-10-15T12:31:00Z'}, 'consensus_not_received_before_release'),
    ({'measure': 'yoy'}, 'consensus_metric_mismatch'),
    ({'reference_period': '2026-08'}, 'consensus_metric_mismatch'),
    ({'unit': 'index'}, 'consensus_metric_mismatch'),
    ({'value': float('nan')}, 'value_invalid'),
])
def test_missing_or_late_consensus_does_not_erase_release_actual(change, reason):
    data = release_snapshot()
    data['macro']['data']['release_events'][0]['consensus'].update(change)
    event = build_release_evidence(data)['events'][0]
    assert event['actual']['value'] == 1.3
    assert event['surprise']['value'] is None
    assert event['surprise']['reason'] == reason


def test_new_reader_rejects_previous_body_without_receipt_identity():
    data = detailed_snapshot()
    data.update(snapshot_time='2026-10-07T01:30:00Z', asset='XAUUSD')
    data['prior_report_contexts'] = context_payload(data)
    prior = data['prior_report_contexts']['contexts']['daily']
    prior.pop('available_at')
    checked = prior_report_context_model_input(data)['contexts']['daily']
    assert checked['reason_code'] == 'context_availability_not_verified_before_cutoff'
    assert 'body' not in checked


def test_registry_imported_after_cutoff_is_not_historical_availability(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from database.models.report import ensure_report_tables
    from tests.analysis.test_report_continuity import register, snapshot
    from apps.analysis.snapshots.report_continuity import load_prior_report_contexts
    engine = create_engine('sqlite://')
    ensure_report_tables(engine)
    with Session(engine) as db:
        item, _, _ = register(db, tmp_path, name='late-import', trade_date='2026-10-06',
                              generated_at=datetime.fromisoformat('2026-10-06T04:00:00+00:00'))
        item.created_at = item.updated_at = datetime.fromisoformat('2026-10-08T04:00:00+00:00')
        db.flush()
        result = load_prior_report_contexts(db, storage_root=tmp_path, snapshot=snapshot())
        daily = result['contexts']['daily']
        assert daily['status'] == 'unavailable'
        assert daily['details']['rejected_reason_counts']['registry_revision_not_available_before_cutoff'] == 1
    engine.dispose()
