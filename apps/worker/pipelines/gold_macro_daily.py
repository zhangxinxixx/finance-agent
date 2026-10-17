"""Independent macro daily delivery using the existing research/output chain.

Acquisition, model authorization, task ownership and DB commit remain with the
caller. Preparation performs no inference. Generation requires an explicit
gateway and never instantiates a default model client.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from apps.analysis.agents.coordinator import coordinate_agent_outputs
from apps.analysis.agents.research_input import RESEARCH_PRESENTATION_VERSION, ResearchInputTooLarge, encode, input_metrics
from apps.analysis.agents.research_synthesis import (
    _build_messages, _build_prompt_payload, enrich_research_coordinator,
)
from apps.analysis.agents.schemas import AgentOutput
from apps.analysis.snapshots.input_validation import prepare_analysis_inputs, research_report_rejection_reasons
from apps.output.final_report import _safe_artifact_dir, write_final_report
from apps.renderer.markdown.gold_reader import reader_audit_details, reader_sections, render_reader_report


def prepare_gold_macro_daily(
    snapshot: dict, *, source_root: Path, archive_refs=(), db_session=None,
    prior_report_root: Path | None = None,
) -> dict[str, Any]:
    """Read selected existing archives/registry and freeze messages, with no model.

    Registry session and archive selection are explicit; generation only rechecks
    the resulting frozen input and never reloads today's registry into history.
    """
    candidate = deepcopy(snapshot)
    flow = candidate.get('gold_workflow') or {}
    if (candidate.get('asset') != 'XAUUSD'
            or flow.get('reader_report_version') != 'gold_reader.v4'
            or flow.get('reader_presentation') != RESEARCH_PRESENTATION_VERSION):
        raise ValueError('macro_daily_requires_verified_v4_research_contract')
    candidate['report_kind'] = 'gold_macro_daily'
    from apps.worker.macro_daily_inputs import attach_macro_daily_inputs
    candidate = attach_macro_daily_inputs(candidate, source_root=source_root,
                                          archive_refs=archive_refs, db_session=db_session,
                                          prior_report_root=prior_report_root)
    prepared = prepare_analysis_inputs(candidate, storage_root=source_root, prior_report_root=prior_report_root)
    coordinator = coordinate_agent_outputs(
        prepared, macro_output=None, options_output=None, risk_output=None,
        created_at=datetime.fromisoformat(prepared['snapshot_time'].replace('Z', '+00:00')),
    )
    result = {'status': 'blocked', 'snapshot': prepared,
              'coordinator': coordinator.model_dump(mode='json'),
              'model_calls': 0, 'execution_ready': False,
              'source_roots': {'raw': str(source_root.resolve()),
                               'prior_reports': str((prior_report_root or source_root).resolve())}}
    if not prepared['input_validation']['can_analyze']:
        return result
    try:
        payload = _build_prompt_payload(prepared, coordinator)
        messages = _build_messages(payload)
    except ResearchInputTooLarge as exc:
        result.update(reason='research_input_budget_exceeded', detail=str(exc), truncation=False)
        return result
    result.update(status='prepared', model_input=payload, messages=messages,
                  input_metrics=input_metrics(payload),
                  message_characters=sum(len(m['content']) for m in messages),
                  messages_sha256=sha256(encode(messages).encode()).hexdigest())
    return result


def generate_gold_macro_daily(
    prepared: dict, *, source_root: Path, storage_root: Path, gateway: Any,
    prior_report_root: Path | None = None,
    on_research_result=None,
) -> dict[str, Any]:
    """Generate/review one candidate; rejected drafts never produce a report bundle.

    No collection, scheduler, implicit DB or publication occurs here. The caller
    supplies its authorized, bounded gateway and retains task_steps/call audit.
    Format/quality repair is disabled here: at most one generation and one
    reviewer invocation traverse the normal input-binding chain.
    Existing output directories stop before inference to avoid paid reruns.
    """
    if gateway is None or not callable(getattr(gateway, 'chat_sync', gateway)):
        raise ValueError('explicit_authorized_gateway_required')
    if getattr(getattr(gateway, 'config', None), 'fallback_providers', ()):
        raise ValueError('macro_daily_requires_gateway_without_fallback')
    snapshot = prepared['snapshot']
    target = _safe_artifact_dir(storage_root, artifact_type='gold_macro_daily', asset='XAUUSD',
                               trade_date=snapshot['trade_date'], run_id=snapshot['run_id'])
    if target.exists():
        raise FileExistsError('macro daily run already has artifacts; read the existing bundle')
    # Recheck raw hashes, the complete projection and method files before billing.
    current = prepare_gold_macro_daily(snapshot, source_root=source_root, prior_report_root=prior_report_root)
    if prepared.get('source_roots', current['source_roots']) != current['source_roots']:
        raise ValueError('frozen_macro_daily_source_roots_changed')
    if current['status'] != 'prepared':
        return {'status': 'blocked', 'reason': 'input_validation_blocked', 'model_calls': 0}
    if (current['model_input'] != prepared.get('model_input')
            or current['messages'] != prepared.get('messages')
            or current['snapshot']['input_validation'] != snapshot['input_validation']):
        raise ValueError('frozen_macro_daily_input_changed')
    output = enrich_research_coordinator(
        current['snapshot'], AgentOutput.model_validate(current['coordinator']), gateway=gateway,
        allow_repairs=False,
    )
    if on_research_result is not None:
        on_research_result(current, output)
    return complete_gold_macro_daily(current, output, storage_root=storage_root)


def complete_gold_macro_daily(prepared: dict, output: AgentOutput, *, storage_root: Path) -> dict[str, Any]:
    """Persist a matching reviewed result with the original immutable writer."""
    snapshot = prepared['snapshot']
    reasons = research_report_rejection_reasons(snapshot, output)
    if output.snapshot_id != snapshot['snapshot_id']:
        reasons.append('coordinator_snapshot_mismatch')
    if reasons:
        return {'status': 'blocked', 'reasons': sorted(set(reasons)),
                'coordinator': output.model_dump(mode='json'), 'execution_ready': False}
    sections = reader_sections(snapshot, {'coordinator': output}, {})
    markdown = render_reader_report(snapshot, sections)
    audit = reader_audit_details(snapshot, {'coordinator': output})
    synthesis = output.input_payload['research_synthesis']
    structured = {
        'schema_version': 'gold_macro_daily_bundle.v1',
        'rendering_version': 'gold_macro_daily.rendering.v1.2',
        'report_type': 'gold_macro_daily',
        'snapshot_id': snapshot['snapshot_id'], 'run_id': snapshot['run_id'],
        'asset': snapshot['asset'], 'trade_date': snapshot['trade_date'],
        'analysis_cutoff': snapshot['snapshot_time'],
        'input_sha256': snapshot['input_validation']['input_sha256'],
        'model_input_sha256': prepared['input_metrics']['sha256'],
        'messages_sha256': prepared['messages_sha256'],
        'generation_status': synthesis['generation_status'],
        'review_status': synthesis['review_status'], 'quality_eligible': synthesis['quality_eligible'],
        'research_quality': 'not_evaluated', 'publish_allowed': False,
        'output_mode': 'candidate', 'execution_ready': False,
        'input_snapshot_ids': snapshot['input_snapshot_ids'], 'source_refs': snapshot['source_refs'],
        'content_sha256': {'final_report.md': sha256(markdown.encode()).hexdigest(),
                           'audit_report.md': sha256(audit.encode()).hexdigest()},
        'sections': sections, 'analysis_input': snapshot,
        'coordinator': output.model_dump(mode='json'),
    }
    bundle = write_final_report(
        storage_root=storage_root, artifact_type='gold_macro_daily', asset='XAUUSD',
        trade_date=snapshot['trade_date'], run_id=snapshot['run_id'], markdown=markdown,
        audit_markdown=audit, structured_report=structured,
    )
    return {'status': 'generated', 'report_id': f"gold_macro_daily:{snapshot['run_id']}",
            'bundle': bundle, 'execution_ready': False, 'publish_allowed': False,
            'coordinator': output.model_dump(mode='json')}
