"""Synthetic coordinator integration checks; no market/model quality claims."""
from copy import deepcopy
import json

import pytest

from apps.analysis.agents import research_quality, research_synthesis
from apps.renderer.markdown.gold_reader import reader_sections, render_reader_report
from tests.analysis.test_gold_detailed_report import snapshot, response
from tests.analysis.test_research_synthesis import _output


def _gateway(calls, review_results):
    results = iter(review_results)

    def call(**kwargs):
        calls.append(kwargs)
        if kwargs['audit_context']['caller'] == 'macro_causal_reviewer':
            status = next(results)
            if status == 'unavailable':
                raise TimeoutError('synthetic reviewer timeout')
            evidence = json.loads(kwargs['messages'][1]['content'])
            assert len(evidence['questions']) == 17
            content = {'checks': [
                {'id': i, 'passed': status == 'pass' or i != 11,
                 'reason': 'Synthetic authority violation' if i == 11 else 'Synthetic check'}
                for i in range(17)]}
        else:
            content = response()
        return {'content': json.dumps(content), 'model': 'synthetic',
                'provider': 'fixture', 'audit_id': 'fixture-audit'}
    return call


def test_missing_macro_still_reviews_the_actual_detailed_coordinator():
    data, original, calls = snapshot(), _output(), []
    assert not data['gold_workflow'].get('macro_causal')
    before = deepcopy(data)
    result = research_synthesis.enrich_research_coordinator(data, original, _gateway(calls, ['pass']))
    assert len(calls) == 2
    meta = result.input_payload['research_synthesis']
    assert meta['generation_status'] == 'success'
    assert meta['review_status'] == 'pass' and meta['quality_eligible'] is True
    assert len(meta['macro_review']['checks']) == 17
    assert data == before and result.accepted_state_conclusion == original.accepted_state_conclusion


@pytest.mark.parametrize('reviews, count', [(['fail', 'fail'], 4), (['unavailable'], 2),
                                          (['fail', 'unavailable'], 4)])
def test_failed_or_unavailable_review_cannot_be_successful_research(reviews, count):
    data, original, calls = snapshot(), _output(), []
    result = research_synthesis.enrich_research_coordinator(data, original, _gateway(calls, reviews))
    meta = result.input_payload['research_synthesis']
    assert meta['status'] == 'quality_blocked'
    assert meta['generation_status'] == 'success' and meta['quality_eligible'] is False
    assert meta['review_status'] == ('unavailable' if reviews[-1] == 'unavailable' else 'needs_revision')
    assert meta['analysis'] and result.llm_raw_output
    assert len(calls) == count
    for field in ('summary', 'key_findings', 'watchlist', 'accepted_state_conclusion', 'status', 'bias'):
        assert getattr(result, field) == getattr(original, field)
    rendered = render_reader_report(data, reader_sections(data, {'coordinator': result}, {}))
    assert '研究质量未通过' in rendered
    assert response()['dominant_factor'] not in rendered


@pytest.mark.parametrize('missing', ['STANDARD_PATH', 'METHOD_PATH'])
def test_missing_quality_file_is_traceable_unavailable_before_gateway(monkeypatch, tmp_path, missing):
    monkeypatch.setattr(research_quality, missing, tmp_path/'absent.md')
    result = research_synthesis.enrich_research_coordinator(
        snapshot(), _output(), lambda **_: pytest.fail('must not call a model'))
    meta = result.input_payload['research_synthesis']
    assert meta['status'] == 'rule_fallback' and meta['quality_eligible'] is False
    assert meta['generation_status'] == 'unavailable' and meta['review_status'] == 'not_run'
    assert meta['failure_reason'] == ('quality_standard_unavailable' if missing == 'STANDARD_PATH'
                                      else 'quality_method_unavailable')
    assert meta['prompt_input_snapshot_id'] == result.snapshot_id
    assert meta['input_validation']['input_sha256']
    assert meta['quality_failure']['recovery_condition']


def test_frozen_request_with_drifted_method_is_rejected_by_coordinator(monkeypatch):
    frozen = research_synthesis._build_prompt_payload(snapshot(), _output())
    frozen['research_quality_standard']['method_sha256'] = '0' * 64
    before = deepcopy(frozen)
    monkeypatch.setattr(research_synthesis, '_build_prompt_payload', lambda *_: frozen)
    result = research_synthesis.enrich_research_coordinator(
        snapshot(), _output(), lambda **_: pytest.fail('must not call a model'))
    meta = result.input_payload['research_synthesis']
    assert meta['failure_reason'] == 'quality_method_fingerprint_mismatch'
    assert meta['quality_eligible'] is False and meta['review_status'] == 'not_run'
    assert meta['quality_failure']['requested_contract'] == before['research_quality_standard']
    assert meta['quality_failure']['available_contract'] == research_quality.quality_contract()
    assert frozen == before


def test_one_revision_can_pass_but_never_promotes_authority():
    data, original, calls = snapshot(), _output(), []
    before = deepcopy(data)
    result = research_synthesis.enrich_research_coordinator(data, original, _gateway(calls, ['fail', 'pass']))
    meta = result.input_payload['research_synthesis']
    assert len(calls) == 4 and meta['status'] == 'success' and meta['quality_eligible'] is True
    assert meta['macro_review']['revision_attempts'] == 1
    assert meta['macro_review']['prior_review']['status'] == 'needs_revision'
    assert meta['research_quality_standard']['benchmark_parity'] == 'not_evaluated'
    assert data == before and data['gold_workflow']['quality_gate']['publish_allowed'] is False
    assert result.accepted_state_conclusion == original.accepted_state_conclusion


def test_revision_exception_retains_draft_and_cannot_bypass_gate():
    calls = []
    base = _gateway(calls, ['fail'])

    def gateway(**kwargs):
        if kwargs['audit_context'].get('quality_revision_attempt'):
            raise TimeoutError('synthetic revision failure')
        return base(**kwargs)

    result = research_synthesis.enrich_research_coordinator(snapshot(), _output(), gateway)
    meta = result.input_payload['research_synthesis']
    assert meta['status'] == 'quality_blocked' and meta['quality_eligible'] is False
    assert meta['macro_review']['revision_error'] == 'TimeoutError'
    assert meta['macro_review']['revision_attempts'] == 1 and result.llm_raw_output


@pytest.mark.parametrize('presentation', [None, 'gold_reader.concise.v1', 'gold_reader.research.v1'])
def test_all_reader_presentations_label_blocked_drafts_and_keep_facts(presentation):
    data, calls = snapshot(), []
    result = research_synthesis.enrich_research_coordinator(data, _output(), _gateway(calls, ['unavailable']))
    data['gold_workflow']['reader_presentation'] = presentation
    before = result.model_dump(mode='json')
    md = render_reader_report(data, reader_sections(data, {'coordinator': result}, {}))
    assert '研究质量未通过' in md and '不可用' in md
    assert response()['dominant_factor'] not in md
    if presentation != 'gold_reader.research.v1':
        assert '5.24001' in md
    assert result.model_dump(mode='json') == before


def test_unqualified_draft_preserves_provenance_but_is_not_an_accepted_shadow_sample():
    from apps.analysis.research_shadow import _model_record, evaluate_shadow_readiness

    result = research_synthesis.enrich_research_coordinator(snapshot(), _output(), _gateway([], ['unavailable']))
    model = _model_record(result)
    assert model['provenance_complete'] is True
    assert model['generation_status'] == 'success' and model['quality_eligible'] is False
    record = {'task_status': 'success', 'analysis_time': '2026-10-14T12:10:43+08:00',
              'trade_date': '2026-10-14', 'session_quality': {'session_type': 'NORMAL'},
              'run_mode': 'live_shadow', 'artifacts_verified': True,
              'model': model, 'report_output': {'id': 'fixture'}, 'run_id': 'synthetic-blocked'}
    assert evaluate_shadow_readiness([record])['verified_trading_days'] == 0
    # Even a stale consumer's generic success label must not override the quality flag.
    record['model'] = {**model, 'status': 'success'}
    assert evaluate_shadow_readiness([record])['rejected_run_ids'] == ['synthetic-blocked']
    old = result.model_copy(deep=True)
    old_meta = old.input_payload['research_synthesis']
    for key in ('quality_gate_version', 'quality_eligible', 'review_status', 'generation_status'):
        old_meta.pop(key)
    old_meta['status'] = 'success'
    record['model'] = _model_record(old)
    assert record['model']['quality_review_required'] is True
    assert evaluate_shadow_readiness([record])['verified_trading_days'] == 0


def test_completed_blocked_artifact_does_not_silently_retry_or_rewrite():
    data = snapshot()
    result = research_synthesis.enrich_research_coordinator(data, _output(), _gateway([], ['unavailable']))
    before = result.model_dump(mode='json')
    again = research_synthesis.enrich_research_coordinator(
        data, result, lambda **_: pytest.fail('new attempts need a new request'))
    assert again.model_dump(mode='json') == before


def test_removing_required_quality_contract_cannot_disable_the_review(monkeypatch):
    frozen = research_synthesis._build_prompt_payload(snapshot(), _output())
    frozen.pop('research_quality_standard')
    monkeypatch.setattr(research_synthesis, '_build_prompt_payload', lambda *_: frozen)
    result = research_synthesis.enrich_research_coordinator(
        snapshot(), _output(), lambda **_: pytest.fail('missing contract must fail before a model call'))
    meta = result.input_payload['research_synthesis']
    assert meta['failure_reason'] == 'quality_contract_missing' and meta['quality_eligible'] is False


@pytest.mark.parametrize('review', ['pass', 'unavailable'])
def test_renderer_and_registry_gate_enforces_quality_independently_of_generation(review):
    from apps.analysis.snapshots.input_validation import research_report_rejection_reasons
    from apps.renderer.markdown.final_report import render_final_report_markdown, build_structured_report

    data = snapshot()
    data['gold_workflow']['quality_gate']['publish_allowed'] = True
    result = research_synthesis.enrich_research_coordinator(data, _output(), _gateway([], [review]))
    reasons = research_report_rejection_reasons(data, result)
    assert 'research_generation_failed' not in reasons
    if review == 'pass':
        assert not reasons
    else:
        assert 'research_quality_not_eligible' in reasons and 'research_review_not_accepted' in reasons
        for render in (render_final_report_markdown, build_structured_report):
            with pytest.raises(ValueError, match='research_quality_not_eligible'):
                render(snapshot=data, coordinator_output=result, macro_output=None,
                       options_output=None, risk_output=None)


def test_contract_with_missing_quality_verdict_cannot_register_as_success():
    from apps.analysis.snapshots.input_validation import research_report_rejection_reasons

    data = snapshot()
    result = research_synthesis.enrich_research_coordinator(data, _output(), _gateway([], ['pass']))
    meta = result.input_payload['research_synthesis']
    # Models archived before this gate must not acquire the new verdict by default.
    for key in ('quality_gate_version', 'quality_eligible', 'review_status', 'generation_status'):
        meta.pop(key)
    assert 'research_quality_not_eligible' in research_report_rejection_reasons(data, result)


def test_method_drift_after_generation_blocks_review_and_preserves_recovery(monkeypatch, tmp_path):
    path = tmp_path/'method.md'
    path.write_bytes(research_quality.METHOD_PATH.read_bytes())
    monkeypatch.setattr(research_quality, 'METHOD_PATH', path)
    calls = []
    def gateway(**kwargs):
        calls.append(kwargs)
        path.write_text('Changed method after generation; synthetic test only')
        return {'content': json.dumps(response())}
    result = research_synthesis.enrich_research_coordinator(snapshot(), _output(), gateway)
    meta = result.input_payload['research_synthesis']
    assert len(calls) == 1 and meta['status'] == 'quality_blocked'
    assert meta['macro_review']['reason'] == 'quality_method_fingerprint_mismatch'
    assert meta['quality_failure']['recovery_condition']
    assert meta['generation_status'] == 'success' and meta['review_status'] == 'unavailable'
