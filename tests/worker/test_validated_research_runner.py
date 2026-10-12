"""Full worker orchestration with modern sourced inputs and isolated persistence."""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from database.models.analysis import AnalysisBase, AgentOutput, AnalysisSnapshot, FinalAnalysisResult
from database.models.execution import ensure_execution_tables
from database.models.report import ReportItem, ensure_report_tables
from database.models.task import Base, StepStatus, TaskRun, TaskStatus, TaskStep
from tests.analysis.test_input_validation import valid_snapshot


@pytest.mark.parametrize('mode', ['success', 'model_failure', 'missing_spot'])
def test_worker_modern_research_gate_and_database_payload(tmp_path, monkeypatch, mode):
    import apps.worker.runner as runner

    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    AnalysisBase.metadata.create_all(engine)
    ensure_execution_tables(engine)
    ensure_report_tables(engine)
    with Session(engine) as db:
        task = TaskRun(name='premarket', task_type='premarket', status=TaskStatus.pending)
        db.add(task)
        db.flush()
        db.add_all([TaskStep(task_run_id=task.id, name=name, status=StepStatus.pending)
                    for name in ('macro_collect', 'macro_feature', 'report_render')])
        db.commit()
        source = valid_snapshot(tmp_path)
        source.update(run_id=str(task.id), snapshot_id=f'XAUUSD:2026-10-05:{task.id}')
        if mode == 'missing_spot':
            source['daily_research']['execution_timeframes'] = {}

        def macro_step(name, state, **kwargs):
            state.snapshot_dict = {'as_of': source['trade_date'], 'indicators': {}}
            return {'step': name, 'status': 'success'}

        calls = []
        def gateway(gateway, **kwargs):
            calls.append(kwargs)
            if mode == 'missing_spot':
                pytest.fail('Invalid input must be stopped before models')
            if mode == 'model_failure':
                raise RuntimeError('offline fixture model failure')
            catalog = kwargs['audit_context']['input_payload']['evidence_catalog']
            return {'content': json.dumps({
                'dominant_factor': '仅已收盘现货可用，宏观因果保持待确认。',
                'counter_evidence': [], 'state_limitations': ['缺少宏观数据'],
                'convergence_transition': [], 'evidence_ids': [catalog[0]['evidence_id']],
            })}

        monkeypatch.setattr('apps.worker.pipelines.macro.run_macro_step', macro_step)
        monkeypatch.setattr(runner, 'build_analysis_snapshot', lambda **kwargs: source)
        monkeypatch.setattr('apps.api.services.source_service.get_data_source_status_index', lambda: {})
        monkeypatch.setattr(runner, '_evaluate_premarket_readiness', lambda **kwargs: {'decision': 'allow'})
        monkeypatch.setattr('apps.analysis.agents.research_synthesis._call_gateway', gateway)
        result = runner.run_premarket(db, task.id, storage_root=tmp_path)
        stored = db.query(AnalysisSnapshot).one()
        assert stored.payload['input_validation']['can_analyze'] is (mode != 'missing_spot')
        if mode == 'success':
            assert result in {TaskStatus.success, TaskStatus.partial_success}
            assert calls and list(tmp_path.rglob('final_report.md'))
            render = db.query(AgentOutput).filter(AgentOutput.agent_name == 'report_render_agent').one()
            structured = render.payload['input_payload']['structured_report']
            assert structured['sections'] and structured['version']['run_id'] == str(task.id)
            assert db.query(ReportItem).count() == 2
        else:
            assert result == TaskStatus.blocked
            assert not list(tmp_path.rglob('final_report.md'))
            assert db.query(FinalAnalysisResult).count() == 0
            assert db.query(ReportItem).count() == 0
            render_step = db.query(TaskStep).filter(TaskStep.name == 'report_render').one()
            assert render_step.status == StepStatus.blocked
            assert json.loads(render_step.output_json)['status'] == 'blocked'
            assert render_step.finished_at >= render_step.started_at
            assert bool(calls) is (mode == 'model_failure')
            assert task.error_summary
    engine.dispose()
