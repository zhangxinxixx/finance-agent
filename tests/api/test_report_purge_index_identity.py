"""Actual purge anchors, index service and HTTP responses in isolated SQLite."""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import MetaData, create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.services import report_index_service as index_service
from database.models.analysis import AgentOutput, AnalysisBase, FinalAnalysisResult, ensure_analysis_tables
from database.models.report import ReportArtifact, ReportItem, ensure_report_tables
from tests.api.test_gold_policy_report_delivery_api import _client_with_session, _make_session_factory
from tests.api.test_purged_output_reading import _marker, _upsert_final, _write


def _identities(prefix):
    return {key: prefix + '-' + key for key in ('report_id', 'run_id', 'snapshot_id')}


@pytest.mark.parametrize('report_type', ['final_report', 'strategy_card'])
def test_unrelated_reports_with_missing_snapshot_never_match(report_type):
    item = {'type': report_type, 'report_id': 'keep-B', 'run_id': 'run-B', 'snapshot_id': None}
    anchor = {'report_id': 'purged-A', 'run_id': 'run-A', 'snapshot_id': None}
    assert index_service._purged_index_identity(item, [anchor]) is False


@pytest.mark.parametrize('key', ['report_id', 'run_id', 'snapshot_id'])
@pytest.mark.parametrize('missing', ['missing-key', None, '', ' \t\n'])
def test_missing_identity_values_are_not_equal(key, missing):
    item, anchor = {'type': 'final_report', **_identities('keep')}, _identities('purged')
    if missing == 'missing-key':
        item.pop(key)
        anchor.pop(key)
    else:
        item[key] = anchor[key] = missing
    assert index_service._purged_index_identity(item, [anchor]) is False


@pytest.mark.parametrize('identity', [' padded-id', 'padded-id '])
def test_nonblank_ids_are_opaque_and_are_not_trimmed_into_another_id(identity):
    item, anchor = {'type': 'final_report', **_identities('keep')}, _identities('purged')
    item['run_id'], anchor['run_id'] = identity, 'padded-id'
    assert index_service._purged_index_identity(item, [anchor]) is False


@pytest.mark.parametrize('key', ['report_id', 'run_id', 'snapshot_id'])
@pytest.mark.parametrize('identity', ['real-id', 'None', 'null', 'undefined', '0', 'nan'])
def test_real_same_field_id_is_not_rejected_by_a_string_blacklist(key, identity):
    item, anchor = {'type': 'strategy_card', **_identities('keep')}, _identities('purged')
    item[key] = anchor[key] = identity
    assert index_service._purged_index_identity(item, [anchor]) is True


@pytest.mark.parametrize('item_key,anchor_key', [
    ('report_id', 'run_id'), ('report_id', 'snapshot_id'),
    ('run_id', 'report_id'), ('run_id', 'snapshot_id'),
    ('snapshot_id', 'report_id'), ('snapshot_id', 'run_id'),
])
def test_unrelated_cross_field_collisions_are_not_aliases(item_key, anchor_key):
    item, anchor = {'type': 'final_report', **_identities('keep')}, _identities('purged')
    item[item_key] = anchor[anchor_key] = 'coincidence'
    assert index_service._purged_index_identity(item, [anchor]) is False


@pytest.mark.parametrize('item,anchor', [
    ({'report_id': 'final_report:run-a'}, {'run_id': 'run-a'}),
    ({'report_id': 'strategy_card:run-a'}, {'report_id': 'final_report:run-a'}),
    ({'report_id': 'run-a', 'run_id': 'run-a'}, {'report_id': 'final_report:run-a'}),
    ({'report_id': 'final_report:snapshot-a'}, {'snapshot_id': 'snapshot-a'}),
    ({'report_id': 'snapshot-a', 'snapshot_id': 'snapshot-a'}, {'snapshot_id': 'snapshot-a'}),
])
def test_supported_typed_run_and_snapshot_aliases_remain_fenced(item, anchor):
    assert index_service._purged_index_identity({'type': 'final_report', **item}, [anchor]) is True


@pytest.mark.parametrize('item,anchors', [
    ({'report_id': 'run-long', 'run_id': 'run-long'}, [{'run_id': 'run'}]),
    ({'report_id': 'final_report:run-long'}, [{'report_id': 'final_report:run'}]),
    ({'report_id': 'keep'}, [{}]),
    ({'report_id': 'keep'}, []),
])
def test_empty_anchor_and_similar_short_ids_do_not_match(item, anchors):
    assert index_service._purged_index_identity({'type': 'final_report', **item}, anchors) is False


@pytest.mark.parametrize('report_type', ['gold_policy_daily', 'options_report', 'observation_report'])
def test_fence_still_only_applies_to_final_and_strategy(report_type):
    assert index_service._purged_index_identity({'type': report_type, 'run_id': 'run'}, [{'run_id': 'run'}]) is False


@pytest.fixture
def isolated_index(tmp_path, monkeypatch):
    factory = _make_session_factory()
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')
    monkeypatch.setattr('apps.api.services._storage._PROJECT_ROOT', tmp_path)
    monkeypatch.setattr('apps.api.data_service._PROJECT_ROOT', tmp_path)
    monkeypatch.setattr('apps.api.services._storage._try_db_session', factory)
    monkeypatch.setattr('apps.api.data_service._try_db_session', factory)
    return {'root': tmp_path, 'factory': factory}


def _files(env, run_id):
    root, day = env['root'], '2026-10-11'
    final = _write(root, f'storage/outputs/final_report/XAUUSD/{day}/{run_id}/final_report.md', '# Body')
    _write(root, f'storage/outputs/strategy_card/XAUUSD/{day}/{run_id}/strategy_card.json', '{}')
    return final


def _registered(db, env, report_id, run_id, *, snapshot_id=None, asset='XAUUSD'):
    path = _files(env, run_id or report_id)
    item = ReportItem(report_id=report_id, report_type='final_report', family='final_report_markdown',
                      title=report_id, asset=asset, trade_date=date(2026, 10, 11), run_id=run_id,
                      snapshot_id=snapshot_id, data_status='live', lifecycle_status='generated')
    db.add(item)
    db.flush()
    db.add(ReportArtifact(artifact_id=report_id + ':body', report_id=report_id, artifact_type='analysis_md',
                          file_path=str(path.relative_to(env['root'])), is_primary=True))
    return item


def _agent(db, run_id, snapshot_id, marker):
    db.add(AgentOutput(run_id=run_id, snapshot_id=snapshot_id, asset='XAUUSD', trade_date=date(2026, 10, 11),
                       agent_name='coordinator_agent', module='coordinator', status='unavailable',
                       bias='unavailable', confidence=0.0, summary='',
                       payload={'output_cleanup': marker}, payload_sha256='a' * 64))


def _read_index(env, case):
    direct = index_service.list_reports_index()
    with env['factory']() as db:
        client = _client_with_session(db)
        try:
            response = client.get('/api/reports/index')
        finally:
            from apps.api.main import app
            app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == direct
    evidence = os.environ.get('FINANCE_AGENT_REPORT_CONTRACT_EVIDENCE')
    if evidence:
        root = Path(evidence)
        root.mkdir(parents=True, exist_ok=True)
        (root / f'{case}.json').write_text(json.dumps({'status': response.status_code, 'body': response.json()}, indent=2) + '\n')
    return response.json()['reports']


@pytest.mark.parametrize('source', ['report-lifecycle', 'report-marker', 'report-artifact', 'final', 'agent'])
def test_db_anchors_and_index_api_keep_normal_reports_and_block_real_purges(isolated_index, source):
    env = isolated_index
    with env['factory']() as db:
        _registered(db, env, 'keep-B', 'run-B')
        if source.startswith('report'):
            item = _registered(db, env, 'final_report:run-A', 'run-A')
            if source == 'report-lifecycle':
                item.lifecycle_status = 'purged'
            elif source == 'report-marker':
                item.report_metadata = {'output_cleanup': _marker(run_id='run-A')}
            else:
                db.flush()
                db.get(ReportArtifact, 'final_report:run-A:body').status = 'purged'
        elif source == 'final':
            _upsert_final(db, trade_date='2026-10-11', run_id='run-A', payload={'output_cleanup': _marker(run_id='run-A')})
        else:
            _agent(db, 'run-A', '', _marker(run_id='run-A'))
        db.commit()
    _files(env, 'run-A')  # Residual final AND strategy files still physically exist.
    anchors = index_service._collect_purged_report_anchors('XAUUSD')
    assert any(anchor['run_id'] == 'run-A' for anchor in anchors)
    assert not any(anchor['run_id'] == 'run-B' for anchor in anchors)
    rows = _read_index(env, 'mixed-' + source)
    assert {row['type'] for row in rows if row.get('run_id') == 'run-B'} == {'final_report', 'strategy_card'}
    assert not any(row.get('run_id') == 'run-A' for row in rows)
    assert (env['root'] / 'storage/outputs/final_report/XAUUSD/2026-10-11/run-A/final_report.md').exists()
    with env['factory']() as db:
        assert db.get(ReportItem, 'keep-B').lifecycle_status == 'generated'


@pytest.mark.parametrize('alias', ['typed-id', 'artifact-marker', 'artifact-path'])
def test_purged_alias_only_registration_fences_residual_files_without_hiding_other_runs(isolated_index, alias):
    env = isolated_index
    _files(env, 'legacy-purged')
    _files(env, 'history-keep')
    with env['factory']() as db:
        report_id = 'final_report:legacy-purged' if alias == 'typed-id' else 'registered-parent'
        db.add(ReportItem(report_id=report_id, family='final_report_markdown', report_type='final_report',
                          title='purged', asset='XAUUSD', trade_date=date(2026, 10, 11),
                          run_id=None, snapshot_id=None, lifecycle_status='purged' if alias == 'typed-id' else 'generated'))
        db.flush()
        if alias != 'typed-id':
            path = 'purged://cleanup-token' if alias == 'artifact-marker' else 'storage/outputs/final_report/XAUUSD/2026-10-11/legacy-purged/final_report.md'
            metadata = {'output_cleanup': _marker(run_id='legacy-purged')} if alias == 'artifact-marker' else {}
            db.add(ReportArtifact(artifact_id='purged-body', report_id=report_id, artifact_type='analysis_md',
                                  file_path=path, status='purged', artifact_metadata=metadata))
        db.commit()
    rows = _read_index(env, 'alias-' + alias)
    assert {row['type'] for row in rows if row.get('run_id') == 'history-keep'} == {'final_report', 'strategy_card'}
    assert not any(row.get('run_id') == 'legacy-purged' for row in rows)


def test_same_snapshot_still_fences_registered_and_legacy_database_index(isolated_index):
    env = isolated_index
    with env['factory']() as db:
        db.add(ReportItem(report_id='purged-parent', family='final_report_markdown', title='purged', asset='XAUUSD',
                          lifecycle_status='purged', run_id='purged-run', snapshot_id='snapshot-purged'))
        for report_id, snapshot in [('snapshot-linked', 'snapshot-purged'), ('snapshot-unrelated', 'snapshot-keep')]:
            item = _registered(db, env, report_id, report_id, snapshot_id=snapshot)
            artifact = db.get(ReportArtifact, report_id + ':body')
            path = _write(env['root'], f'storage/reports/{report_id}/final_report.md', '# Body')
            artifact.file_path = str(path.relative_to(env['root']))
            # Keep this case on the registry path, outside the filesystem scanner.
            for suffix in ['final_report/XAUUSD/2026-10-11/' + item.run_id + '/final_report.md',
                           'strategy_card/XAUUSD/2026-10-11/' + item.run_id + '/strategy_card.json']:
                (env['root'] / 'storage/outputs' / suffix).unlink()
        legacy = _upsert_final(db, trade_date='2026-10-11', run_id='legacy-snapshot-linked', payload={})
        legacy.snapshot_id = 'snapshot-purged'
        legacy.final_report_path = str(_write(env['root'], 'storage/reports/legacy/final_report.md', '# Legacy'))
        legacy.strategy_card = None
        db.commit()
    rows = _read_index(env, 'same-snapshot')
    assert [row['report_id'] for row in rows] == ['snapshot-unrelated']


def test_cross_asset_tombstone_does_not_fence_xau_history(isolated_index):
    env = isolated_index
    _files(env, 'shared-run')
    with env['factory']() as db:
        db.add(ReportItem(report_id='other-asset', family='final_report_markdown', title='other', asset='BTCUSD',
                          run_id='shared-run', snapshot_id=None, lifecycle_status='purged'))
        db.commit()
    assert index_service._collect_purged_report_anchors('XAUUSD') == []
    rows = _read_index(env, 'cross-asset')
    assert {row['type'] for row in rows} == {'final_report', 'strategy_card'}


@pytest.mark.parametrize('source', ['final', 'agent'])
@pytest.mark.parametrize('raw_run', [None, '', ' \t'])
def test_legacy_nullable_run_is_normalized_before_string_conversion(isolated_index, source, raw_run, monkeypatch):
    env = isolated_index
    # Clone table metadata for an old nullable schema without modifying ORM models.
    metadata = MetaData()
    for table in AnalysisBase.metadata.tables.values():
        table.to_metadata(metadata)
    metadata.tables['final_analysis_results'].c.run_id.nullable = True
    metadata.tables['agent_outputs'].c.run_id.nullable = True
    metadata.tables['agent_outputs'].c.snapshot_id.nullable = True
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    metadata.create_all(engine)
    ensure_report_tables(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    env = {**env, 'factory': factory}
    monkeypatch.setattr('apps.api.services._storage._try_db_session', factory)
    monkeypatch.setattr('apps.api.data_service._try_db_session', factory)
    with factory() as db:
        marker = _marker(run_id='marker-purged')
        if source == 'final':
            db.add(FinalAnalysisResult(asset='XAUUSD', trade_date=date(2026, 10, 11),
                                       run_id=raw_run, snapshot_id=None, payload={'output_cleanup': marker},
                                       payload_sha256='b' * 64))
        else:
            _agent(db, raw_run, None, marker)
        db.commit()
    _files(env, 'None')  # Literal string ID is legal and MUST NOT be blacklisted.
    _files(env, 'marker-purged')
    anchors = index_service._collect_purged_report_anchors('XAUUSD')
    assert len(anchors) == 1
    assert anchors[0]['run_id'] == anchors[0]['report_id'] == 'marker-purged'
    assert anchors[0]['snapshot_id'] is None
    missing_case = [None, '', ' \t'].index(raw_run)
    rows = _read_index(env, f'legacy-{source}-{missing_case}')
    assert {row['type'] for row in rows if row.get('run_id') == 'None'} == {'final_report', 'strategy_card'}
    assert not any(row.get('run_id') == 'marker-purged' for row in rows)


@pytest.mark.parametrize('purged', [False, True])
def test_pure_normal_and_pure_purged_inputs_use_the_actual_index_api(isolated_index, purged):
    env = isolated_index
    _files(env, 'only-run')
    with env['factory']() as db:
        _upsert_final(db, trade_date='2026-10-11', run_id='only-run',
                      payload={'output_cleanup': _marker(run_id='only-run')} if purged else {})
        db.commit()
    rows = _read_index(env, 'pure-' + str(purged))
    if purged:
        assert rows == []
    else:
        assert {row['type'] for row in rows} == {'final_report', 'strategy_card'}


@pytest.mark.parametrize('collision', ['report-vs-run', 'run-vs-report'])
def test_api_does_not_hide_a_different_report_for_an_unrelated_cross_field_collision(isolated_index, collision):
    env = isolated_index
    report_id, run_id = ('coincidence', 'keep-run') if collision == 'report-vs-run' else ('keep-report', 'coincidence')
    anchor_id, anchor_run = ('purged-report', 'coincidence') if collision == 'report-vs-run' else ('coincidence', 'purged-run')
    with env['factory']() as db:
        _registered(db, env, report_id, run_id, snapshot_id='keep-snapshot')
        db.add(ReportItem(report_id=anchor_id, family='final_report_markdown', title='purged', asset='XAUUSD',
                          run_id=anchor_run, snapshot_id='purged-snapshot', lifecycle_status='purged'))
        db.commit()
    rows = _read_index(env, 'cross-field-' + collision)
    assert any(row['report_id'] == report_id and row['run_id'] == run_id for row in rows)


def test_legacy_artifact_table_without_path_retains_the_existing_marker_fence(isolated_index, monkeypatch):
    env = isolated_index
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    ensure_analysis_tables(engine)
    ReportItem.__table__.create(engine)
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE report_artifacts (artifact_id TEXT PRIMARY KEY, report_id TEXT, status TEXT, metadata JSON)'))
        connection.execute(text('INSERT INTO report_artifacts VALUES (:id, :report, :status, :metadata)'),
                           {'id': 'old-artifact', 'report': 'final_report:old-purged', 'status': 'purged',
                            'metadata': json.dumps({'output_cleanup': _marker(run_id='old-purged')})})
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    env = {**env, 'factory': factory}
    monkeypatch.setattr('apps.api.services._storage._try_db_session', factory)
    monkeypatch.setattr('apps.api.data_service._try_db_session', factory)
    with factory() as db:
        db.add(ReportItem(report_id='final_report:old-purged', family='final_report_markdown', title='old',
                          asset='XAUUSD', run_id='old-purged', lifecycle_status='generated'))
        db.commit()
    _files(env, 'old-purged')
    _files(env, 'history-keep')
    anchors = index_service._collect_purged_report_anchors('XAUUSD')
    assert any(row['run_id'] == 'old-purged' for row in anchors)
    rows = _read_index(env, 'legacy-artifact-no-path')
    assert {row['type'] for row in rows if row.get('run_id') == 'history-keep'} == {'final_report', 'strategy_card'}
    assert not any(row.get('run_id') == 'old-purged' for row in rows)
