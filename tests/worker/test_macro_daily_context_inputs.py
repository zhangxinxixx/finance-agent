"""Synthetic intake/registry cases through actual research message preparation."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from apps.worker.pipelines.gold_macro_daily import prepare_gold_macro_daily, generate_gold_macro_daily
from database.models.report import ReportItem, ensure_report_tables
from tests.analysis.test_input_validation import valid_snapshot
from tests.analysis.test_report_continuity import register
from tests.analysis.test_research_input import _expand_table
from tests.features.test_fedwatch import snapshot as fedwatch_fixture


def seed(root):
    data = valid_snapshot(root)
    data['gold_workflow'].update(reader_report_version='gold_reader.v4', reader_presentation='gold_reader.research.v1',
                                 production_shadow=True)
    return data


def archive(root, kind, payload, name=None):
    path = root/(name or kind+'.json')
    path.write_text(json.dumps(payload))
    return {'kind': kind, 'path': str(path), 'sha256': sha256(path.read_bytes()).hexdigest()}


def release(root, *, late=False):
    rows = {}
    for role, value, at, kind in [
        ('actual', 1.3, '2026-10-04T12:30:00+00:00', 'official_release_value'),
        ('consensus', 0.6, '2026-10-04T12:00:00+00:00', 'pre_release_consensus')]:
        p = root/(role+'.json')
        p.write_text(json.dumps({'fixture': 'synthetic', 'value': value}))
        receipt = '2026-10-04T12:31:00+00:00' if late and role == 'consensus' else at
        rows[role] = {'status': 'available', 'indicator': 'PPI', 'reference_period': '2026-09',
            'measure': 'mom_sa', 'unit': 'percent', 'value': value, 'observation_date': '2026-10-04',
            'evidence_kind': kind, 'published_at': at, 'retrieved_at': receipt,
            'source_refs': [{'source': 'synthetic_'+role, 'source_type': 'official' if role == 'actual' else 'survey',
                'source_url': 'https://example.test/'+role, 'raw_path': p.name,
                'sha256': sha256(p.read_bytes()).hexdigest(), 'retrieved_at': receipt}]}
    return {'event_id': 'synthetic-ppi', **rows}


@pytest.fixture
def registry(tmp_path):
    engine = create_engine('sqlite:///'+str(tmp_path/'registry.sqlite'))
    ensure_report_tables(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def test_archived_release_and_registered_prior_reach_full_messages(tmp_path, registry):
    original = seed(tmp_path)
    before = deepcopy(original)
    row = release(tmp_path)
    ref = archive(tmp_path, 'macro_release_events', {'release_events': [row]})
    _, _, body = register(registry, tmp_path, name='synthetic-prior', trade_date='2026-10-04',
                         generated_at=datetime(2026, 10, 4, 13, tzinfo=timezone.utc),
                         body='# Synthetic prior\nOld thesis: gold failed to retain a break.\n')
    registry.commit()
    writes = []
    def guard(_conn, _cursor, sql, *_):
        if sql.lstrip().upper().startswith(('INSERT','UPDATE','DELETE','CREATE','ALTER')):
            writes.append(sql)
    event.listen(registry.get_bind(), 'before_cursor_execute', guard)
    pending = ReportItem(report_id='pending-unsaved')
    registry.add(pending)
    result = prepare_gold_macro_daily(original, source_root=tmp_path, archive_refs=[ref], db_session=registry)
    assert not writes
    assert pending in registry.new
    registry.expunge(pending)
    assert result['status'] == 'prepared' and original == before
    events = _expand_table(result['model_input']['macro_causal']['engines']['releases']['events_table'])
    assert events[0]['actual']['value'] == 1.3
    assert events[0]['surprise']['value'] == pytest.approx(0.7)
    prior = result['model_input']['prior_report_contexts']['contexts']['daily']
    assert prior['body'] == body and prior['available_at'] < original['snapshot_time']
    actual_request = '\n'.join(m['content'] for m in result['messages'])
    assert 'Old thesis: gold failed to retain a break.' in actual_request
    assert 'synthetic-ppi' in actual_request
    again = prepare_gold_macro_daily(result['snapshot'], source_root=tmp_path)
    assert again['messages'] == result['messages']
    assert result['model_calls'] == 0 and result['execution_ready'] is False


def test_late_consensus_and_late_registry_revision_do_not_erase_other_evidence(tmp_path, registry):
    data = seed(tmp_path)
    data['macro'] = {'status': 'unavailable', 'data': None}
    ref = archive(tmp_path, 'macro_release_events', {'release_events': [release(tmp_path, late=True)]})
    item, _, _ = register(registry, tmp_path, name='late', trade_date='2026-10-04',
                          generated_at=datetime(2026, 10, 4, 13, tzinfo=timezone.utc))
    item.updated_at = datetime(2026, 10, 5, 7, tzinfo=timezone.utc)
    registry.commit()
    result = prepare_gold_macro_daily(data, source_root=tmp_path, archive_refs=[ref], db_session=registry)
    assert result['status'] == 'prepared'
    releases = result['model_input']['macro_causal']['engines']['releases']
    events = _expand_table(releases['events_table'])
    assert events[0]['actual']['value'] == 1.3
    assert events[0]['surprise']['value'] is None
    assert events[0]['consensus']['reason'] == 'consensus_not_received_before_release'
    prior = result['snapshot']['prior_report_contexts']['contexts']['daily']
    assert prior['status'] == 'unavailable'
    assert prior['details']['rejected_reason_counts']['registry_revision_not_available_before_cutoff'] == 1


def test_fred_index_is_not_a_release_and_no_registry_remains_explicit(tmp_path):
    data = seed(tmp_path)
    ref = archive(tmp_path, 'macro_release_events', {'as_of': '2026-10-04',
                   'rows': [{'symbol': 'PPIFIS', 'value': 1.34}]})
    result = prepare_gold_macro_daily(data, source_root=tmp_path, archive_refs=[ref])
    assert result['status'] == 'prepared'
    assert result['model_input']['macro_causal']['engines']['releases']['events_table'] == []
    assert result['snapshot']['macro_daily_context_intake'][0]['reason'] == 'structured_release_events_absent'
    assert result['snapshot']['prior_report_contexts']['contexts']['daily']['reason_code'] == 'report_registry_session_not_supplied'


def test_changed_archive_blocks_before_any_model_call(tmp_path):
    data = seed(tmp_path)
    ref = archive(tmp_path, 'macro_release_events', {'release_events': [release(tmp_path)]})
    prepared = prepare_gold_macro_daily(data, source_root=tmp_path, archive_refs=[ref])
    from pathlib import Path
    Path(ref['path']).write_text('{}')
    with pytest.raises(ValueError, match='frozen_macro_context_archive_changed'):
        generate_gold_macro_daily(prepared, source_root=tmp_path, storage_root=tmp_path/'output',
                                  gateway=lambda **_: pytest.fail('model must not be called'))


@pytest.mark.parametrize('change', ['future', 'stale', 'fresh_no_comparison'])
def test_fedwatch_archive_reaches_messages_with_its_actual_time_eligibility(tmp_path, change):
    data = seed(tmp_path)
    raw = fedwatch_fixture()
    current = '2026-10-04T12:00:00+00:00' if change == 'stale' else '2026-10-05T05:59:00+00:00'
    shift = datetime.fromisoformat(current) - datetime.fromisoformat(raw['as_of'].replace('Z', '+00:00'))
    for row in raw['rows']:
        row['as_of'] = (datetime.fromisoformat(row['as_of'].replace('Z', '+00:00')) + shift).isoformat()
    raw.update(as_of=current, collected_at='2026-10-05T06:00:00+00:00')
    if change == 'future':
        raw['collected_at'] = '2026-10-05T07:00:00+00:00'
    if change == 'fresh_no_comparison':
        raw['rows'] = [r for r in raw['rows'] if r['comparison_window'] == 'current']
    p = tmp_path/'raw/synthetic.json'
    p.write_text('{"fixture":"synthetic FedWatch"}')
    raw['content_hash'] = sha256(p.read_bytes()).hexdigest()
    raw['source_refs'][0].update(source_url='https://example.test/fedwatch',
        retrieved_at=raw['collected_at'], sha256=raw['content_hash'])
    ref = archive(tmp_path, 'fedwatch', {'job': 'fedwatch', 'result': raw})
    result = prepare_gold_macro_daily(data, source_root=tmp_path, archive_refs=[ref])
    assert result['status'] == 'prepared'
    policy = result['model_input']['macro_causal']['engines']['policy']
    assert policy['current_repricing_eligible'] is False
    if change == 'future':
        assert not policy['meetings']
    else:
        assert policy['meetings']
        assert policy['distribution_scope'] == ('current_snapshot' if change == 'fresh_no_comparison' else 'historical_snapshot_only')


def test_full_priors_over_budget_are_blocked_without_truncation(tmp_path, registry):
    data = seed(tmp_path)
    for cadence in ['daily', 'weekly']:
        register(registry, tmp_path, name=cadence, trade_date='2026-10-04', cadence=cadence,
                 generated_at=datetime(2026, 10, 4, 13, tzinfo=timezone.utc), body='x'*99_000)
    registry.commit()
    result = prepare_gold_macro_daily(data, source_root=tmp_path, db_session=registry)
    assert result['status'] == 'blocked' and result['reason'] == 'research_input_budget_exceeded'
    assert result['truncation'] is False and result['model_calls'] == 0
    assert all(len(v['body']) == 99_000 for v in result['snapshot']['prior_report_contexts']['contexts'].values())


def test_report_storage_stays_explicit_and_is_rechecked_before_inference(tmp_path, registry):
    raw_root, report_root = tmp_path/'input', tmp_path/'prior-reports'
    data = seed(raw_root)
    _, path, body = register(registry, report_root, name='separate-root', trade_date='2026-10-04',
                            generated_at=datetime(2026, 10, 4, 13, tzinfo=timezone.utc))
    registry.commit()
    prepared = prepare_gold_macro_daily(data, source_root=raw_root, db_session=registry,
                                         prior_report_root=report_root)
    assert prepared['model_input']['prior_report_contexts']['contexts']['daily']['body'] == body
    again = prepare_gold_macro_daily(prepared['snapshot'], source_root=raw_root, prior_report_root=report_root)
    assert again['messages'] == prepared['messages']
    path.write_text(body+'changed')
    with pytest.raises(ValueError, match='frozen_macro_daily_input_changed'):
        generate_gold_macro_daily(prepared, source_root=raw_root, prior_report_root=report_root,
                                  storage_root=tmp_path/'output', gateway=lambda **_: pytest.fail('no model'))


def test_existing_official_event_archive_enters_messages_without_numeric_invention(tmp_path):
    from apps.features.news.formal_events import build_official_event_snapshot
    from tests.features.news.test_formal_events import _candidate
    data = seed(tmp_path)
    at = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)
    event = _candidate(event_id='synthetic-official-event', event_time=at.isoformat())
    event['source_refs'][0].update(retrieved_at=at.isoformat(), raw_path='raw/official-event.json')
    (tmp_path/'raw/official-event.json').write_text('{"fixture":"synthetic event"}')
    formal = build_official_event_snapshot(candidates=[event], reactions=[], as_of=at)
    ref = archive(tmp_path, 'official_events', formal.model_dump(mode='json'))
    prepared = prepare_gold_macro_daily(data, source_root=tmp_path, archive_refs=[ref])
    events = _expand_table(prepared['model_input']['macro_causal']['engines']['releases']['events_table'])
    assert events[0]['event_id'] == 'synthetic-official-event'
    assert events[0]['actual']['status'] == events[0]['consensus']['status'] == 'unavailable'
    assert events[0]['surprise']['value'] is None
