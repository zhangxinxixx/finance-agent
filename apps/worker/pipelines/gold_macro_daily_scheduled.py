"""One noon slot through existing snapshot, research, task and report facilities.

Upstream collectors own ingestion. This worker selects an already persisted,
timely snapshot; it never relabels stale inputs or invokes the premarket graph.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import uuid
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from apps.analysis.agents.schemas import AgentOutput
from apps.worker.pipelines.gold_macro_daily import (
    complete_gold_macro_daily, generate_gold_macro_daily, prepare_gold_macro_daily,
)
from apps.worker.report_registry_sink import register_gold_macro_daily_bundle
from apps.runtime.immutable_artifact import immutable_json_item, write_immutable_artifact_bundle
from database.models.analysis import AnalysisSnapshot
from database.models.task import TaskRun, TaskStatus, TaskStep, StepStatus
from database.queries.analysis import _sha256_hex


def noon_slot(value):
    stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('scheduled_time_requires_timezone')
    local = stamp.astimezone(ZoneInfo('Asia/Shanghai'))
    if local.weekday() >= 5 or (local.hour, local.minute, local.second, local.microsecond) != (12, 0, 0, 0):
        raise ValueError('not_a_weekday_noon_slot')
    return stamp.astimezone(timezone.utc), f'gold_macro_daily:noon:{local.date().isoformat()}'


def _utc(value):
    # SQLAlchemy SQLite drops UTC offsets; these registry columns are UTC.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def run_scheduled_gold_macro_daily(db, *, scheduled_for, source_root, storage_root,
                                   prior_report_root, gateway=None, recover=False):
    cutoff, slot = noon_slot(scheduled_for)
    task_id = uuid.uuid5(uuid.NAMESPACE_URL, slot)
    binding = {'scheduled_for': cutoff.isoformat(), 'source_root': str(Path(source_root).resolve()),
               'storage_root': str(Path(storage_root).resolve()),
               'prior_report_root': str(Path(prior_report_root).resolve())}
    task = db.get(TaskRun, task_id)
    if task is not None:
        step = db.scalar(select(TaskStep).where(TaskStep.task_run_id == task_id, TaskStep.name == 'macro_daily_noon'))
        if step is None or json.loads(step.input_json) != binding:
            raise ValueError('noon_slot_binding_conflict')
        if task.status == TaskStatus.success:
            # Re-verify the same files/registration; never manufacture a new ID.
            saved = json.loads(step.output_json)
            register_gold_macro_daily_bundle(db, directory=Path(saved['directory']), storage_root=Path(storage_root))
            return {**saved, 'reused': True, 'new_model_calls': 0}
        if not recover:
            return {'status': 'blocked', 'reason': 'existing_slot_requires_explicit_recovery', 'task_id': str(task_id)}
        # Conditional claim prevents two recovery workers from spending at once.
        from sqlalchemy import update
        claimed = db.execute(update(TaskRun).where(
            TaskRun.id == task_id, TaskRun.status.in_([TaskStatus.blocked, TaskStatus.failed]),
        ).values(status=TaskStatus.running))
        db.commit()
        if claimed.rowcount != 1:
            return {'status': 'blocked', 'reason': 'slot_running_or_uncertain', 'task_id': str(task_id)}
    else:
        task = TaskRun(id=task_id, name=slot, task_type='gold_macro_daily_noon', status=TaskStatus.running,
                       trade_date=cutoff.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat(),
                       started_at=datetime.now(timezone.utc), current_stage='prepare')
        step = TaskStep(task_run_id=task_id, name='macro_daily_noon', stage='prepare', status=StepStatus.running,
                        input_json=json.dumps(binding), retryable=False, retry_count=0)
        db.add_all([task, step])
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return {'status': 'blocked', 'reason': 'slot_already_claimed', 'task_id': str(task_id)}

    def finish(status, reason, **extra):
        result = {'status': status, 'reason': reason, 'task_id': str(task_id),
                  'scheduled_for': cutoff.isoformat(), 'publish_allowed': False, 'execution_ready': False, **extra}
        task.status = TaskStatus.success if status == 'generated' else TaskStatus.blocked
        task.current_stage = step.stage = status
        task.ended_at = step.finished_at = datetime.now(timezone.utc)
        task.error_summary = None if status == 'generated' else reason
        step.status = StepStatus.success if status == 'generated' else StepStatus.blocked
        step.output_json = json.dumps(result, ensure_ascii=False)
        db.commit()
        return result

    try:
        checkpoint = json.loads(step.artifact_refs)[0] if step.artifact_refs else None
        if checkpoint:
            path = Path(checkpoint['file_path']).resolve()
            expected = Path(storage_root).resolve()/'outputs'/'gold_macro_daily_checkpoints'/str(task_id)/'checkpoint.json'
            if path != expected:
                return finish('blocked', 'checkpoint_path_mismatch')
            content = path.read_bytes()
            if sha256(content).hexdigest() != checkpoint['sha256']:
                return finish('blocked', 'checkpoint_hash_mismatch')
            saved = json.loads(content)
            if saved['binding'] != binding:
                return finish('blocked', 'checkpoint_binding_mismatch')
            prepared = saved['prepared']
            current = prepare_gold_macro_daily(prepared['snapshot'], source_root=Path(source_root),
                                              prior_report_root=Path(prior_report_root))
            if (current.get('messages') != prepared['messages']
                    or current['snapshot']['input_validation'] != prepared['snapshot']['input_validation']):
                return finish('blocked', 'checkpoint_input_no_longer_verified')
            result = complete_gold_macro_daily(prepared, AgentOutput.model_validate(saved['coordinator']),
                                              storage_root=Path(storage_root))
        else:
            if step.output_ref == 'model_attempt_started':
                return finish('blocked', 'model_attempt_uncertain_requires_audit')
            lower = cutoff - timedelta(minutes=60)
            rows = db.scalars(select(AnalysisSnapshot).where(
                AnalysisSnapshot.asset == 'XAUUSD', AnalysisSnapshot.trade_date == task.trade_date,
                AnalysisSnapshot.status.in_(['success', 'partial']),
                AnalysisSnapshot.snapshot_time <= cutoff, AnalysisSnapshot.snapshot_time >= lower,
                AnalysisSnapshot.created_at <= cutoff,
            ).order_by(AnalysisSnapshot.snapshot_time.desc(), AnalysisSnapshot.snapshot_id.asc())).all()
            row = next((r for r in rows if r.payload.get('gold_workflow', {}).get('reader_report_version') == 'gold_reader.v4'
                        and r.payload.get('gold_workflow', {}).get('reader_presentation') == 'gold_reader.research.v1'), None)
            if row is None:
                return finish('blocked', 'no_timely_snapshot', new_model_calls=0)
            snapshot = row.payload
            if (row.payload_sha256 != _sha256_hex(snapshot)
                    or any(snapshot.get(k) != getattr(row, k) for k in ('snapshot_id', 'run_id', 'asset'))
                    or str(snapshot.get('trade_date')) != row.trade_date.isoformat()
                    or datetime.fromisoformat(snapshot['snapshot_time'].replace('Z', '+00:00')) != _utc(row.snapshot_time)):
                return finish('blocked', 'snapshot_registry_identity_mismatch', new_model_calls=0)
            prepared = prepare_gold_macro_daily(snapshot, source_root=Path(source_root), db_session=db,
                                              prior_report_root=Path(prior_report_root))
            task.snapshot_id = snapshot['snapshot_id']
            if prepared['status'] != 'prepared':
                return finish('blocked', 'input_not_ready', new_model_calls=0)
            # A fresh wrapper is insufficient: the frozen input must retain at
            # least one independently qualified domain after native freshness checks.
            domains = prepared['snapshot']['input_validation']['domains']
            if not any(v.get('status') in {'available', 'partial'} for v in domains.values() if isinstance(v, dict)):
                return finish('blocked', 'no_qualified_evidence', new_model_calls=0)
            if gateway is None:
                return finish('blocked', 'model_not_authorized', new_model_calls=0)
            task.current_stage = step.stage = 'research'
            step.input_hash = prepared['messages_sha256']
            step.output_ref = 'model_attempt_started'
            db.commit()  # An uncertain call may not be repeated automatically.

            def checkpoint_result(current, output):
                path = Path(storage_root).resolve()/'outputs'/'gold_macro_daily_checkpoints'/str(task_id)/'checkpoint.json'
                content = {'binding': binding, 'prepared': current, 'coordinator': output.model_dump(mode='json')}
                write_immutable_artifact_bundle([immutable_json_item(path, content)], storage_root=storage_root)
                step.artifact_refs = json.dumps([{'artifact_type': 'research_checkpoint', 'file_path': str(path),
                                                 'sha256': sha256(path.read_bytes()).hexdigest()}])
                task.current_stage = step.stage = 'save'
                db.commit()  # Recover saving/registration without new inference.

            result = generate_gold_macro_daily(prepared, source_root=Path(source_root), storage_root=Path(storage_root),
                prior_report_root=Path(prior_report_root), gateway=gateway, on_research_result=checkpoint_result)
        if result['status'] != 'generated':
            return finish('blocked', 'research_not_eligible', quality_reasons=result.get('reasons', []))
        directory = Path(result['bundle']['paths'][0]).parent
        registration = register_gold_macro_daily_bundle(db, directory=directory, storage_root=Path(storage_root))
        task.final_result_id = registration['report_id']
        coordinator = result['coordinator']
        review = coordinator['input_payload']['research_synthesis'].get('macro_review') or {}
        return finish('generated', None, report_id=registration['report_id'], directory=str(directory),
                      analysis_cutoff=prepared['snapshot']['snapshot_time'], recovered=bool(checkpoint),
                      data_coverage=prepared['snapshot']['input_validation']['domains'],
                      model={'provider': coordinator.get('llm_provider'), 'model': coordinator.get('llm_model'),
                             'generation_audit_id': coordinator.get('llm_audit_id'),
                             'generation_usage': coordinator.get('llm_usage'), 'review_audit_id': review.get('audit_id'),
                             'cost_usd': None, 'cost_status': 'read_from_gateway_audit_not_estimated'})
    except Exception as exc:
        db.rollback()
        return finish('blocked', 'worker_' + type(exc).__name__)
