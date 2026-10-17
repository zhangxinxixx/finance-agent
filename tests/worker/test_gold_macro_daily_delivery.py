"""Synthetic model responses; native preparation/review/Bundle/registry/API chain."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.worker.pipelines.gold_macro_daily import (
    prepare_gold_macro_daily, generate_gold_macro_daily, complete_gold_macro_daily,
)
from apps.worker.report_registry_sink import register_gold_macro_daily_bundle
from apps.analysis.agents.schemas import AgentOutput
from database.models.report import ReportItem, ensure_report_tables
from tests.analysis.test_input_validation import valid_snapshot
from tests.analysis.test_gold_detailed_report import response


def candidate(tmp_path):
    data = valid_snapshot(tmp_path)
    data['gold_workflow'].update(reader_report_version='gold_reader.v4', reader_presentation='gold_reader.research.v1')
    return prepare_gold_macro_daily(data, source_root=tmp_path)


def model_stub(calls, *, review='pass'):
    def invoke(**kwargs):
        calls.append(kwargs)
        if kwargs['audit_context']['caller'] == 'macro_causal_reviewer':
            if review == 'unavailable':
                raise TimeoutError('synthetic unavailable reviewer')
            result = {'checks': [{'id': i, 'passed': review == 'pass', 'reason': 'Synthetic check'} for i in range(17)]}
        else:
            result = response()
            result['reader_narrative'] = '## 一句话结论\n\n合成测试正文：已有信息仅支持条件观察，不构成真实市场判断。\n\n## 等待条件\n\n待合格完整收盘确认后重验原假设。'
        return {'content': json.dumps(result, ensure_ascii=False), 'model': 'synthetic-test-only',
                'provider': 'fixture', 'audit_id': 'synthetic-audit'}
    return invoke


@pytest.fixture
def db():
    from database.models.analysis import ensure_analysis_tables
    from database.models.task import ensure_task_tables
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    ensure_report_tables(engine)
    ensure_analysis_tables(engine)
    ensure_task_tables(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_macro_without_cme_events_or_priors_traverses_real_chain_and_api(tmp_path, monkeypatch, db):
    prepared = candidate(tmp_path)
    original = deepcopy(prepared)
    calls = []
    result = generate_gold_macro_daily(prepared, source_root=tmp_path, storage_root=tmp_path/'storage', gateway=model_stub(calls))
    assert result['status'] == 'generated'
    assert len(calls) == 2
    assert {c['audit_context']['caller'] for c in calls} == {'research_synthesis.enrich_research_coordinator', 'macro_causal_reviewer'}
    assert prepared == original
    directory = Path(result['bundle']['paths'][0]).parent
    text = (directory/'final_report.md').read_text()
    assert text.startswith('# 2026-10-05 黄金宏观日报') and '合成测试正文' in text
    assert not list((tmp_path/'storage').rglob('strategy_card.json'))
    record = register_gold_macro_daily_bundle(db, directory=directory, storage_root=tmp_path/'storage')
    db.commit()
    item = db.get(ReportItem, record['report_id'])
    before = item.updated_at
    assert register_gold_macro_daily_bundle(db, directory=directory, storage_root=tmp_path/'storage')['created'] is False
    assert item.updated_at == before
    retry = complete_gold_macro_daily(prepared, AgentOutput.model_validate(result['coordinator']), storage_root=tmp_path/'storage')
    assert retry['bundle']['skipped']
    with pytest.raises(FileExistsError):
        generate_gold_macro_daily(prepared, source_root=tmp_path, storage_root=tmp_path/'storage', gateway=lambda **_: pytest.fail('no paid repeat'))

    from apps.api.routes.reports_routes import router
    from apps.api.services.page_data_boundary import PageDataBoundaryMiddleware, sanitize_page_payload
    from database.models.engine import get_db
    from apps.api.services.report_reading import detail
    monkeypatch.setattr(detail._storage, '_PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(detail._storage, '_try_db_session', lambda: Session(db.bind))
    monkeypatch.setenv('STORAGE_ROOT', str(tmp_path/'storage'))
    app = FastAPI()
    app.add_middleware(PageDataBoundaryMiddleware)
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        from apps.api.services.report_index_service import list_reports_index
        index = list_reports_index()['reports']
        selected = next(row for row in index if row['report_id'] == record['report_id'])
        assert selected['type'] == 'gold_macro_daily'
        assert selected['publish_allowed'] is False and selected['output_mode'] == 'candidate'
        assert selected['analysis_cutoff'] == prepared['snapshot']['snapshot_time']
        actual = client.get(f"/api/reports/{record['report_id']}")
        assert actual.status_code == 200, actual.text
        body = actual.json()
        assert body['report_identity']['quality_eligible'] is True
        assert body['report_identity']['publish_allowed'] is False
        assert body['report_identity']['execution_ready'] is False
        assert body['report_identity']['research_quality'] == 'not_evaluated'
        assert body['report_identity']['model_review_status'] == 'pass'
        assert body['report_identity']['review_status'] == body['review_status'] == 'pending'
        assert body['research_identity']['data_as_of'] == prepared['snapshot']['snapshot_time']
        assert body['research_identity']['snapshot_id'] == prepared['snapshot']['snapshot_id']
        assert selected['research_identity']['data_as_of'] == body['research_identity']['data_as_of']
        md = client.get(f"/api/reports/{record['report_id']}/analysis")
        assert md.status_code == 200 and md.json()['content'] == text
        evidence = client.get(f"/api/reports/{record['report_id']}/evidence")
        assert evidence.status_code == 200
        assert evidence.json()['content'] == sanitize_page_payload(json.loads((directory/'structured_report.json').read_text()))
        assert not any(w['code'] == 'report-artifacts-partial' for w in body['warnings'])
        (directory/'final_report.md').write_text(text + '\n篡改')
        assert client.get(f"/api/reports/{record['report_id']}/analysis").status_code == 404
        assert not any(row['report_id'] == record['report_id'] for row in list_reports_index()['reports'])


@pytest.mark.parametrize('review', ['fail', 'unavailable'])
def test_rejected_review_retains_draft_without_bundle(tmp_path, review):
    prepared = candidate(tmp_path)
    result = generate_gold_macro_daily(prepared, source_root=tmp_path, storage_root=tmp_path/'storage', gateway=model_stub([], review=review))
    assert result['status'] == 'blocked'
    assert result['coordinator']['input_payload']['research_synthesis']['analysis']
    assert not list((tmp_path/'storage').rglob('final_report.md'))


def test_changed_archive_or_messages_stop_before_model(tmp_path):
    prepared = candidate(tmp_path)
    bad = deepcopy(prepared)
    bad['messages'][-1]['content'] += 'changed'
    with pytest.raises(ValueError, match='frozen_macro_daily_input_changed'):
        generate_gold_macro_daily(bad, source_root=tmp_path, storage_root=tmp_path/'storage', gateway=lambda **_: pytest.fail('must not call'))
    (tmp_path/'raw/test.json').write_text('{}')
    # Bind a known digest before changing raw bytes; native archive validation
    # must reject it rather than dropping the last good source then proceeding.
    saved = deepcopy(prepared['snapshot'])
    frame = saved['daily_research']['execution_timeframes']['timeframes']['15m']
    frame['source_refs'][0]['sha256'] = sha256(b'original').hexdigest()
    saved.pop('input_validation', None)
    checked = prepare_gold_macro_daily(saved, source_root=tmp_path)
    assert checked['status'] == 'blocked' and checked['model_calls'] == 0


def test_gateway_is_never_implicit(tmp_path):
    prepared = candidate(tmp_path)
    with pytest.raises(ValueError, match='explicit_authorized_gateway_required'):
        generate_gold_macro_daily(prepared, source_root=tmp_path, storage_root=tmp_path/'storage', gateway=None)


def test_old_model_cannot_be_rebound_and_registry_rejects_tamper(tmp_path, db):
    prepared = candidate(tmp_path)
    result = generate_gold_macro_daily(prepared, source_root=tmp_path, storage_root=tmp_path/'storage', gateway=model_stub([]))
    changed = deepcopy(prepared)
    changed['snapshot']['snapshot_id'] += '-new'
    rejected = complete_gold_macro_daily(changed, AgentOutput.model_validate(result['coordinator']), storage_root=tmp_path/'new-storage')
    assert rejected['status'] == 'blocked'
    directory = Path(result['bundle']['paths'][0]).parent
    (directory/'audit_report.md').write_text('tampered')
    with pytest.raises(ValueError, match='content_hash'):
        register_gold_macro_daily_bundle(db, directory=directory, storage_root=tmp_path/'storage')
    assert db.get(ReportItem, result['report_id']) is None


def test_unavailable_query_lineage_registers_without_rewriting_frozen_bundle(tmp_path, db):
    snapshot = candidate(tmp_path)['snapshot']
    missing = {'source': 'cot_snapshot_query', 'reference': 'query://COT_GOLD/noncomm_net',
               'raw_path': None, 'retrieved_at': snapshot['snapshot_time'],
               'qualification_reason': 'no_eligible_cot_candidate'}
    snapshot['source_refs'].append(missing)
    prepared = prepare_gold_macro_daily(snapshot, source_root=tmp_path)
    result = generate_gold_macro_daily(prepared, source_root=tmp_path,
                                      storage_root=tmp_path/'storage', gateway=model_stub([]))
    directory = Path(result['bundle']['paths'][0]).parent
    frozen = {p.name: p.read_bytes() for p in directory.iterdir()}
    record = register_gold_macro_daily_bundle(db, directory=directory, storage_root=tmp_path/'storage')
    db.commit()
    item = db.get(ReportItem, record['report_id'])
    projected = next(ref for ref in item.source_refs if ref.get('source') == missing['source'])
    assert projected == {**missing, 'source_ref': 'cot_snapshot_query'}
    assert all(artifact.source_refs == item.source_refs for artifact in item.artifacts)
    assert {p.name: p.read_bytes() for p in directory.iterdir()} == frozen
    assert missing in json.loads(frozen['structured_report.json'])['source_refs']


def test_window_transport_fingerprint_is_stable_across_process_hash_seeds():
    import os
    import subprocess
    import sys

    script = '''
import json
from apps.analysis.agents.research_input import _project_market_windows, _project_chart_window_tables
data = {'series_health': [{'ticker': 'OANDA:XAUUSD', 'symbol': 'XAUUSD', 'status': 'available'}],
        'windows': [{'group': 'gold_dxy', 'window_start': '2026-10-16T04:00:00Z',
                     'window_end': '2026-10-16T04:15:00Z', 'status': 'available',
                     'changes': [{'ticker': 'OANDA:XAUUSD', 'symbol': 'XAUUSD',
                                  'start_close': 4100.0, 'end_close': 4101.0,
                                  'change_pct': 0.02439, 'unit': 'USD/oz'}]}]}
projected = _project_market_windows(data)
_project_chart_window_tables(projected)
table = projected['changes_table']
assert dict(zip(table['columns'], table['rows'][0]))['end_close'] == 4101.0
print(json.dumps(projected, sort_keys=True))
'''
    results = [subprocess.check_output([sys.executable, '-c', script],
               env={**os.environ, 'PYTHONHASHSEED': seed}) for seed in ('1', '9876')]
    assert results[0] == results[1]
