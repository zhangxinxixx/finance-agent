"""Synthetic dates, archives and model responses; actual Dagster and native chain."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from dagster import build_schedule_context, DefaultScheduleStatus
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from apps.worker.pipelines.gold_macro_daily_scheduled import run_scheduled_gold_macro_daily
from database.models.analysis import ensure_analysis_tables
from database.models.report import ensure_report_tables, ReportItem
from database.models.task import ensure_task_tables, TaskRun, TaskStep
from database.queries.analysis import upsert_analysis_snapshot
from dagster_finance.jobs.gold_macro_daily_job import gold_macro_daily_job
from dagster_finance.schedules.gold_macro_daily_schedule import gold_macro_daily_weekday_noon
from tests.analysis.test_input_validation import valid_snapshot
from tests.worker.test_gold_macro_daily_delivery import model_stub

NOON = datetime(2026, 10, 5, 4, tzinfo=timezone.utc)


def seed(db, root, *, age=1, received_after=False):
    data = valid_snapshot(root)
    delta = timedelta(hours=-2, minutes=-1-age)
    def shift(value):
        if isinstance(value, dict):
            return {k: shift(v) for k, v in value.items()}
        if isinstance(value, list):
            return [shift(v) for v in value]
        if isinstance(value, str) and value.startswith('2026-10-05T'):
            return (datetime.fromisoformat(value) + delta).isoformat()
        return value
    data = shift(data)
    data['run_id'] = data['snapshot_id'] = 'synthetic-noon-20261005'
    data['gold_workflow'].update(reader_report_version='gold_reader.v4', reader_presentation='gold_reader.research.v1')
    frame = data['daily_research']['execution_timeframes']['timeframes']['15m']
    (root/'raw/test.json').write_text(json.dumps({'bars': frame['bars']}))
    row = upsert_analysis_snapshot(db, {**data, 'payload': data}, str(root/'snapshot.json'))
    row.created_at = NOON + timedelta(minutes=1) if received_after else NOON-timedelta(seconds=10)
    db.commit()
    return data


@pytest.fixture
def setup(tmp_path, monkeypatch):
    from apps.llm.gateway import LLMGateway
    monkeypatch.setattr(LLMGateway, 'chat_sync', lambda *_a, **_k: pytest.fail('real model forbidden'))
    engine = create_engine('sqlite:///'+str(tmp_path/'registry.sqlite'))
    ensure_task_tables(engine)
    ensure_analysis_tables(engine)
    ensure_report_tables(engine)
    with Session(engine) as db:
        yield db, tmp_path
    engine.dispose()


def run(db, root, gateway, **kw):
    return run_scheduled_gold_macro_daily(db, scheduled_for=NOON.isoformat(), source_root=root,
        storage_root=root/'storage', prior_report_root=root, gateway=gateway, **kw)


def test_real_tick_job_prepares_reviews_saves_and_registers_once(setup, monkeypatch):
    db, root = setup
    seed(db, root)
    for key, value in {'STORAGE_ROOT': root/'storage', 'SOURCE_ROOT': root, 'PRIOR_REPORT_ROOT': root}.items():
        monkeypatch.setenv('FINANCE_AGENT_MACRO_DAILY_'+key, str(value))
    monkeypatch.delenv('FINANCE_AGENT_MACRO_DAILY_MODEL_AUTHORIZED', raising=False)
    tick = gold_macro_daily_weekday_noon.evaluate_tick(build_schedule_context(scheduled_execution_time=NOON))
    request, = tick.run_requests
    assert request.run_key == 'gold_macro_daily:noon:2026-10-05'
    assert gold_macro_daily_weekday_noon.default_status == DefaultScheduleStatus.STOPPED
    calls = []
    config = request.run_config
    config.pop('resources')  # explicitly inject a synthetic gateway, no env client
    resources = {'db_session': db, 'macro_daily_gateway': model_stub(calls)}
    first = gold_macro_daily_job.execute_in_process(run_config=config, resources=resources)
    result = first.output_for_node('gold_macro_daily_noon_op')
    assert first.success and result['status'] == 'generated' and len(calls) == 2
    directory = Path(result['directory'])
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    second = gold_macro_daily_job.execute_in_process(run_config=config, resources=resources)
    assert second.output_for_node('gold_macro_daily_noon_op')['reused'] is True
    assert len(calls) == 2 and {p.name:p.read_bytes() for p in directory.iterdir()} == before
    assert len(db.scalars(select(TaskRun)).all()) == len(db.scalars(select(ReportItem)).all()) == 1
    assert result['analysis_cutoff'] == '2026-10-05T03:59:00+00:00'


@pytest.mark.parametrize('age,late', [(61, False), (-1, False), (1, True)])
def test_stale_future_or_late_registered_input_never_calls_model(setup, age, late):
    db, root = setup
    seed(db, root, age=age, received_after=late)
    result = run(db, root, lambda **_: pytest.fail('must not call'))
    assert result['reason'] == 'no_timely_snapshot'
    assert not db.scalars(select(ReportItem)).all()
    assert not list(root.rglob('final_report.md'))


def test_model_unavailable_preserves_failure_and_recovery_does_not_spend(setup):
    db, root = setup
    seed(db, root)
    calls = []
    def unavailable(**kw):
        calls.append(kw)
        raise TimeoutError('synthetic unavailable provider')
    result = run(db, root, unavailable)
    assert result['reason'] == 'research_not_eligible' and len(calls) == 1
    assert run(db, root, unavailable, recover=True)['status'] == 'blocked'
    assert len(calls) == 1


def test_save_failure_recovers_from_checkpoint_without_model(setup, monkeypatch):
    db, root = setup
    seed(db, root)
    from apps.worker.pipelines import gold_macro_daily as pipeline
    writer = pipeline.complete_gold_macro_daily
    calls = []
    def interrupted(*a, **kw):
        raise OSError('synthetic interrupted storage')
    monkeypatch.setattr(pipeline, 'complete_gold_macro_daily', interrupted)
    first = run(db, root, model_stub(calls))
    assert first['reason'] == 'worker_OSError' and len(calls) == 2
    assert db.scalar(select(TaskStep)).artifact_refs
    monkeypatch.setattr(pipeline, 'complete_gold_macro_daily', writer)
    recovered = run(db, root, lambda **_: pytest.fail('no new inference'), recover=True)
    assert recovered['status'] == 'generated' and recovered['recovered'] is True
    assert len(calls) == 2


def test_no_authorization_and_uncertain_call_fail_closed(setup):
    db, root = setup
    seed(db, root)
    assert run(db, root, None)['reason'] == 'model_not_authorized'
    step = db.scalar(select(TaskStep))
    step.output_ref = 'model_attempt_started'
    db.commit()
    assert run(db, root, lambda **_: pytest.fail('uncertain attempt'), recover=True)['reason'] == 'model_attempt_uncertain_requires_audit'


def test_weekend_and_missing_directories_skip(monkeypatch):
    for key in ('STORAGE_ROOT', 'SOURCE_ROOT', 'PRIOR_REPORT_ROOT'):
        monkeypatch.delenv('FINANCE_AGENT_MACRO_DAILY_'+key, raising=False)
    assert not gold_macro_daily_weekday_noon.evaluate_tick(build_schedule_context(scheduled_execution_time=NOON)).run_requests
    weekend = datetime(2026, 10, 17, 4, tzinfo=timezone.utc)
    assert not gold_macro_daily_weekday_noon.evaluate_tick(build_schedule_context(scheduled_execution_time=weekend)).run_requests


def test_fresh_snapshot_does_not_requalify_stale_source(setup):
    from database.models.analysis import AnalysisSnapshot
    from database.queries.analysis import _sha256_hex
    db, root = setup
    data = seed(db, root)
    data['daily_research']['execution_timeframes']['timeframes']['15m']['status'] = 'stale'
    row = db.scalar(select(AnalysisSnapshot))
    row.payload = data
    row.payload_sha256 = _sha256_hex(data)
    db.commit()
    assert run(db, root, lambda **_: pytest.fail('stale source'))['reason'] == 'input_not_ready'


def test_definitions_register_stopped_schedule_and_disabled_gateway():
    from dagster import build_init_resource_context
    from dagster_finance.definitions import defs
    from dagster_finance.jobs.gold_macro_daily_job import macro_daily_gateway
    assert defs.get_job_def('gold_macro_daily_job').name == 'gold_macro_daily_job'
    assert defs.get_schedule_def('gold_macro_daily_weekday_noon').default_status == DefaultScheduleStatus.STOPPED
    assert macro_daily_gateway(build_init_resource_context(config={'enabled': False})) is None
