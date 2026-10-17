"""Replay recorded real responses through the native macro daily chain offline.

No gateway, collection, scheduler or production DB is opened. Output is an
explicit new directory, with its own registry and task records. Subsequent runs
may only resume that same identity and reuse the immutable verified Bundle.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import uuid


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', required=True, type=Path)
    parser.add_argument('--recorded-calls', required=True, type=Path)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--prior-report-root', required=True, type=Path)
    parser.add_argument('--output-root', required=True, type=Path)
    args = parser.parse_args(argv)
    root, prepared_path, calls_path = args.output_root.resolve(), args.prepared.resolve(), args.recorded_calls.resolve()
    if prepared_path.is_relative_to(root) or calls_path.is_relative_to(root) or root.is_relative_to(calls_path):
        parser.error('output must be separate from recorded inputs')
    prepared = json.loads(prepared_path.read_text())
    recorded = []
    for number in (1, 2):
        request_path = calls_path/f'{number:02d}-http-request.json'
        response_path = calls_path/f'{number:02d}-full-response.txt'
        audit_path = calls_path/f'{number:02d}-gateway-audit.json'
        request = json.loads(request_path.read_text())['request']
        audit = json.loads(audit_path.read_text())
        raw = response_path.read_text()
        if (audit['status'] != 'success' or audit['response_text'] != raw
                or audit['request_messages'] != request['messages']):
            raise ValueError('recorded_call_evidence_mismatch')
        recorded.append((request, audit, raw))
    identity = {'prepared_sha256': digest(prepared_path),
                'source_root': str(args.source_root.resolve()),
                'prior_report_root': str(args.prior_report_root.resolve()),
                'recorded_files': {p.name:digest(p) for p in sorted(calls_path.iterdir())
                                   if p.is_file() and p.name.startswith(('01-', '02-'))}}
    marker = root/'REPLAY_INPUT.json'
    if root.exists() and any(root.iterdir()):
        if not marker.is_file() or json.loads(marker.read_text()) != identity:
            parser.error('nonempty output directory does not belong to this replay')
    root.mkdir(parents=True, exist_ok=True)
    if not marker.exists():
        marker.write_text(json.dumps(identity, ensure_ascii=False, indent=2)+'\n')
    storage = root/'storage'
    database = root/'registry.sqlite'
    os.environ.update(DATABASE_URL='sqlite:///'+str(database), STORAGE_ROOT=str(storage),
                      FINANCE_AGENT_DISABLE_BACKGROUND_JOBS='1', FINANCE_AGENT_DISABLE_JIN10='1')
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    def forbidden(*_, **__):
        raise RuntimeError('offline replay forbids network and model calls')
    def guard(event, arguments):
        if event in {'socket.connect', 'subprocess.Popen', 'os.system', 'os.posix_spawn'}:
            forbidden()
    sys.addaudithook(guard)
    from apps.llm.gateway import LLMGateway
    LLMGateway.chat_sync = forbidden
    LLMGateway.chat = forbidden
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from database.models.task import TaskRun, TaskStep, TaskStatus, StepStatus, ensure_task_tables
    from database.models.report import ensure_report_tables
    from database.models.analysis import ensure_analysis_tables
    from apps.worker.pipelines.gold_macro_daily import generate_gold_macro_daily
    from apps.worker.report_registry_sink import register_gold_macro_daily_bundle
    from apps.output.final_report import _safe_artifact_dir, verify_gold_macro_daily_bundle
    engine = create_engine('sqlite:///'+str(database))
    ensure_task_tables(engine)
    ensure_analysis_tables(engine)
    ensure_report_tables(engine)
    task_id = uuid.uuid4()
    replayed = []
    def recorded_gateway(**kwargs):
        number = len(replayed)
        if number >= 2 or kwargs['messages'] != recorded[number][0]['messages']:
            raise ValueError('recorded_messages_mismatch_or_extra_call')
        _, audit, raw = recorded[number]
        replayed.append({'actual_call_id': audit['call_id'], 'messages_exactly_equal': True,
                         'response_sha256': sha256(raw.encode()).hexdigest()})
        return SimpleNamespace(content=raw, model=audit['model_resolved'], provider=audit['provider_resolved'],
            usage=audit['usage'], latency_ms=audit['latency_ms'], audit_id=audit['call_id'])
    snapshot = prepared['snapshot']
    directory = _safe_artifact_dir(storage, artifact_type='gold_macro_daily', asset='XAUUSD',
                                   trade_date=snapshot['trade_date'], run_id=snapshot['run_id'])
    with Session(engine) as db:
        db.add(TaskRun(
            id=task_id, name=snapshot['run_id'], task_type='gold_macro_daily_replay', status=TaskStatus.running,
            current_stage='recorded_response_replay', started_at=datetime.now(timezone.utc),
            snapshot_id=snapshot['snapshot_id'], trade_date=snapshot['trade_date']))
        db.commit()
    try:
        reused = directory.exists()
        if reused:
            bundle = verify_gold_macro_daily_bundle(directory)
            if (bundle['input_sha256'] != snapshot['input_validation']['input_sha256']
                    or bundle['messages_sha256'] != prepared['messages_sha256']):
                raise ValueError('existing_bundle_input_mismatch')
            result = {'status':'generated', 'bundle':{'paths':[str(directory/'final_report.md')]},
                      'coordinator':bundle['coordinator']}
        else:
            result = generate_gold_macro_daily(prepared, source_root=args.source_root.resolve(),
                prior_report_root=args.prior_report_root.resolve(), storage_root=storage, gateway=recorded_gateway)
        with Session(engine) as db:
            registration = (register_gold_macro_daily_bundle(db, directory=directory, storage_root=storage)
                            if result['status'] == 'generated' else None)
            task = db.get(TaskRun, task_id)
            task.status = TaskStatus.success if registration else TaskStatus.blocked
            task.current_stage = result['status']
            task.ended_at = datetime.now(timezone.utc)
            for name in ('recorded_response_replay', 'bundle_and_registry'):
                db.add(TaskStep(task_run_id=task_id, name=name, stage=name, status=StepStatus.success if registration else StepStatus.blocked,
                    retryable=False, retry_count=0, finished_at=datetime.now(timezone.utc),
                    input_refs=json.dumps(identity), output_refs=json.dumps(registration)))
            db.commit()
        output = {'status':result['status'], 'task_id':str(task_id), 'new_model_calls':0, 'new_http_requests':0,
                  'replayed':replayed, 'bundle_reused':reused, 'registration':registration,
                  'final_report':str(directory/'final_report.md') if registration else None,
                  'execution_ready':False, 'publish_allowed':False, 'pipeline':result}
        target = root/f'replay-{task_id}.json'
        target.write_text(json.dumps(output, ensure_ascii=False, indent=2)+'\n')
        print(json.dumps({k:v for k,v in output.items() if k!='pipeline'}, ensure_ascii=False))
        return 0 if registration else 1
    except Exception as exc:
        with Session(engine) as db:
            task = db.get(TaskRun, task_id)
            task.status=TaskStatus.failed
            task.current_stage='offline_replay_failed'
            task.ended_at=datetime.now(timezone.utc)
            db.add(TaskStep(task_run_id=task_id, name='offline_replay_failed', stage='output', status=StepStatus.failed,
                error_type=type(exc).__name__, retryable=False, finished_at=datetime.now(timezone.utc)))
            db.commit()
        raise
    finally:
        engine.dispose()


if __name__ == '__main__':
    raise SystemExit(main())
