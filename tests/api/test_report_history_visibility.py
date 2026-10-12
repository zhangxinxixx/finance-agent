"""Historical reading is independent of formal research eligibility and runtime data."""
from __future__ import annotations

import json
import os
import uuid
from datetime import date
from hashlib import sha256

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from apps.api.services import report_service as service
from apps.api.schemas.report import ReportDetail
from database.models.analysis import AnalysisSnapshot, FinalAnalysisResult, ensure_analysis_tables
from database.models.report import ReportArtifact, ReportItem, ensure_report_tables
from database.models.task import Base as TaskBase, TaskRun, TaskStatus

DAY = date(2026, 10, 6)
BODY = '# 历史综合报告\n原文、数字与结论保留。\n'
WARNING = 'historical-final-report-unverified'


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    engine = create_engine('sqlite://')
    ensure_report_tables(engine)
    ensure_analysis_tables(engine)
    TaskBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(service._storage, '_PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(service._jin10, '_JIN10_EXTERNAL_ROOT', tmp_path / 'external-jin10')
    monkeypatch.setattr(service._storage, '_try_db_session', factory)
    with factory() as db:
        yield tmp_path, db
    engine.dispose()


def body(root, run='old', day=DAY.isoformat()):
    path = root / f'storage/outputs/final_report/XAUUSD/{day}/{run}/final_report.md'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(BODY, encoding='utf-8')
    return path


def register(db, root, run='old', status='live', family='final_report_markdown', report_type='final_report'):
    path = body(root, run)
    item = ReportItem(report_id=f'registered:{run}', run_id=run, snapshot_id=f'snapshot:{run}',
                      asset='XAUUSD', trade_date=DAY, family=family, report_type=report_type,
                      title='Original title', data_status=status, lifecycle_status='generated',
                      source_refs=[{'source_type': 'report', 'source_id': 'original-source', 'source_name': 'original'}],
                      report_metadata={'original': {'value': 42}})
    item.artifacts = [ReportArtifact(artifact_id=f'{run}:md', artifact_type='analysis_md',
                                    file_path=str(path.relative_to(root)),
                                    sha256=sha256(path.read_bytes()).hexdigest(), is_primary=True)]
    db.add(item)
    db.commit()
    return item, path


def bind_snapshot(db, root, item, *, research=False):
    payload = {'run_id': item.run_id, 'snapshot_id': item.snapshot_id}
    if research:
        payload['daily_research'] = {'schema_version': 'daily_research.v1'}
    path = root / 'storage' / f'{item.run_id}-snapshot.json'
    path.write_text(json.dumps(payload), encoding='utf-8')
    db.add(TaskRun(id=uuid.UUID(item.run_id), name='premarket', status=TaskStatus.success,
                   snapshot_id=item.snapshot_id))
    db.add(AnalysisSnapshot(run_id=item.run_id, snapshot_id=item.snapshot_id, asset='XAUUSD',
                            trade_date=DAY, status='success', payload=payload,
                            payload_sha256=sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                            artifact_path=str(path.relative_to(root))))
    db.commit()


def finals():
    return [row for row in service.list_reports_index()['reports'] if row['type'] == 'final_report']


def assert_historical(row):
    assert row['available'] is True
    assert {k: row[k] for k in ('data_status', 'lifecycle_status', 'review_status', 'output_mode',
                               'authority', 'publish_allowed')} == {
        'data_status': 'partial', 'lifecycle_status': 'needs_review', 'review_status': 'needs_review',
        'output_mode': 'historical', 'authority': 'historical_only', 'publish_allowed': False,
    }


def assert_readable(db, report_id):
    detail = service.get_report_detail(db, report_id)
    assert detail.data_status == 'partial'
    assert detail.lifecycle_status == 'needs_review'
    assert detail.review_status == 'pending'
    assert json.loads(detail.model_dump_json())['review_status'] == 'pending'
    ReportDetail.model_validate_json(detail.model_dump_json())
    warnings = [w for w in detail.warnings if w.code == WARNING]
    assert len(warnings) == 1
    assert warnings[0].message == '历史综合报告仅供回看，未通过当前研究完整性与来源校验，不能作为当前正式结论或交易依据。'
    assert service.get_report_analysis(db, report_id)['content'] == BODY
    return detail


@pytest.mark.parametrize('status', ['live', 'partial'])
def test_registry_readable_and_deduplicated_with_legacy_and_filesystem(isolated, status):
    root, db = isolated
    item, path = register(db, root, status=status)
    db.add(FinalAnalysisResult(asset='XAUUSD', trade_date=DAY, run_id=item.run_id,
                               snapshot_id=item.snapshot_id, payload={}, payload_sha256='legacy',
                               final_report_path=str(path.relative_to(root))))
    db.commit()
    rows = finals()
    assert len(rows) == 1
    assert rows[0]['report_id'] == item.report_id
    assert_historical(rows[0])
    detail = assert_readable(db, item.report_id)
    assert detail.source_refs[0].source_id == 'original-source'
    assert detail.artifacts[0].sha256 == item.artifacts[0].sha256
    assert detail.title == item.title
    assert item.report_metadata == {'original': {'value': 42}}
    assert item.data_status == status  # Read projection never rewrites the registry.
    assert_readable(db, item.run_id)  # Legacy adapter preserves its warning.
    assert 'legacy-report-adapter' in {w.code for w in service.get_report_detail(db, item.run_id).warnings}


def test_empty_database_filesystem_detail_and_timestamp_sort(isolated):
    root, db = isolated
    older = body(root, 'z-older')
    newer = body(root, 'a-newer')
    body(root, 'prior-day', '2026-10-05')
    os.utime(older, (10, 10))
    os.utime(newer, (20, 20))
    rows = finals()
    assert [r['run_id'] for r in rows] == ['a-newer', 'z-older', 'prior-day']
    for row in rows:
        assert_historical(row)
        assert_readable(db, row['report_id'])
    assert service.get_report_detail(db, 'final_report:a-newer').run_id == 'a-newer'


@pytest.mark.parametrize('broken', ['no-session', 'old-schema', 'unavailable'])
def test_database_failure_does_not_block_files_or_other_reports(isolated, monkeypatch, broken):
    root, db = isolated
    body(root)
    macro = root / 'storage/outputs/macro/2026-10-06/macro-run/macro_full_report.md'
    macro.parent.mkdir(parents=True)
    macro.write_text('# macro', encoding='utf-8')
    if broken == 'no-session':
        monkeypatch.setattr(service._storage, '_try_db_session', lambda: None)
    elif broken == 'old-schema':
        db.execute(text('DROP TABLE report_items'))
        db.commit()
    else:
        db.execute(text('DROP TABLE report_items'))
        db.execute(text('DROP TABLE final_analysis_results'))
        db.commit()
    index = service.list_reports_index()['reports']
    assert_historical(next(r for r in index if r['type'] == 'final_report'))
    assert any(r['type'] == 'macro_report' for r in index)
    assert_readable(db, 'old')


@pytest.mark.parametrize('location', ['missing', 'body', 'run', 'date'])
def test_missing_body_and_symlink_escape_are_not_listed_or_read(isolated, location):
    root, db = isolated
    item, path = register(db, root, run='unsafe')
    outside = root / 'outside'
    outside.mkdir()
    if location == 'missing':
        path.unlink()
    elif location == 'body':
        target = outside / 'final_report.md'
        target.write_text(BODY, encoding='utf-8')
        path.unlink()
        path.symlink_to(target)
    else:
        import shutil
        directory = path.parent if location == 'run' else path.parent.parent
        target = outside / directory.name
        shutil.move(str(directory), target)
        directory.symlink_to(target, target_is_directory=True)
    empty = root / 'storage/outputs/final_report/XAUUSD/2026-10-06/no-body'
    empty.mkdir(parents=True, exist_ok=True)
    (empty / 'structured_report.json').write_text('{}', encoding='utf-8')
    assert finals() == []
    assert service.get_report_analysis(db, item.report_id) is None
    assert service.get_report_detail(db, 'unsafe') is None
    assert service.get_report_detail(db, 'no-body') is None
    assert service.get_report_detail(db, '../outside') is None


def test_current_verifier_accepts_valid_report_without_historical_downgrade(isolated):
    root, db = isolated
    item, path = register(db, root, run=str(uuid.uuid4()))
    structured = path.with_name('structured_report.json')
    structured.write_text('{"original":42}', encoding='utf-8')
    item.artifacts.append(ReportArtifact(artifact_id='structured', artifact_type='structured_json',
                                         file_path=str(structured.relative_to(root))))
    db.commit()
    bind_snapshot(db, root, item)
    assert service._verified_final_report(db, run_id=item.run_id, snapshot_id=item.snapshot_id,
                                          path=path, digest=item.artifacts[0].sha256)
    row, = finals()
    assert row['report_id'] == item.report_id
    assert row.get('authority') != 'historical_only'
    detail = service.get_report_detail(db, item.report_id)
    assert detail.data_status == 'live'
    assert detail.lifecycle_status == 'generated'
    assert WARNING not in {w.code for w in detail.warnings}
    assert detail.structured_payload == {'original': 42}


def test_new_research_contract_rejection_keeps_only_historical_reading(isolated):
    root, db = isolated
    item, path = register(db, root, run=str(uuid.uuid4()))
    bind_snapshot(db, root, item, research=True)
    assert not service._verified_final_report(db, run_id=item.run_id, snapshot_id=item.snapshot_id,
                                              path=path, digest=item.artifacts[0].sha256)
    row, = finals()
    assert_historical(row)
    assert_readable(db, item.report_id)


def test_observation_registry_and_files_are_not_promoted(isolated):
    root, db = isolated
    item, path = register(db, root, family='observation_report_markdown', report_type='observation_report')
    observation = root / 'storage/outputs/observation_report/XAUUSD/2026-10-06/old/final_report.md'
    observation.parent.mkdir(parents=True)
    path.rename(observation)
    item.artifacts[0].file_path = str(observation.relative_to(root))
    db.add(FinalAnalysisResult(asset='XAUUSD', trade_date=DAY, run_id=item.run_id, payload={},
                               payload_sha256='legacy', final_report_path=str(observation.relative_to(root))))
    db.commit()
    card = root / 'storage/outputs/observation_strategy_card/XAUUSD/2026-10-06/old/strategy_card.json'
    card.parent.mkdir(parents=True)
    card.write_text('{}', encoding='utf-8')
    assert service.list_reports_index()['reports'] == []
    detail = service.get_report_detail(db, item.report_id)
    assert WARNING not in {w.code for w in detail.warnings}
    assert detail.report_identity['authority'] == 'observation_only'
    assert service.get_report_analysis(db, item.report_id)['content'] == BODY


def test_registry_identity_wins_when_legacy_date_differs(isolated):
    root, db = isolated
    item, path = register(db, root)
    item.trade_date = date(2026, 10, 5)
    db.commit()
    row, = finals()
    assert row['report_id'] == item.report_id
    assert row['trade_date'] == '2026-10-05'
    assert_historical(row)


def test_verified_bindings_with_partial_registry_remain_historical(isolated):
    root, db = isolated
    item, path = register(db, root, run=str(uuid.uuid4()), status='partial')
    bind_snapshot(db, root, item)
    assert not service._verified_final_report(db, run_id=item.run_id, snapshot_id=item.snapshot_id,
                                              path=path, digest=item.artifacts[0].sha256)
    row, = finals()
    assert_historical(row)
    assert_readable(db, item.report_id)


def test_missing_verifier_table_does_not_remove_other_registered_reports(isolated):
    root, db = isolated
    item, path = register(db, root, run=str(uuid.uuid4()))
    db.add(ReportItem(report_id='other', family='other', report_type='other', title='Other report',
                      asset='XAUUSD', trade_date=DAY, artifacts=[ReportArtifact(
                          artifact_id='other:md', artifact_type='analysis_md', file_path=str(path.relative_to(root)))]))
    db.commit()
    db.execute(text('DROP TABLE task_runs'))
    db.commit()
    rows = service.list_reports_index()['reports']
    assert any(r['report_id'] == 'other' for r in rows)
    assert_historical(next(r for r in rows if r['report_id'] == item.report_id))
    assert_readable(db, item.report_id)


def test_storage_root_symlink_outside_project_is_rejected(isolated):
    root, db = isolated
    outside = root / 'outside'
    outside.mkdir()
    (root / 'storage').symlink_to(outside, target_is_directory=True)
    body(root)
    assert finals() == []
    assert service.get_report_detail(db, 'old') is None
