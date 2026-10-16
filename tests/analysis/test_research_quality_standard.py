"""Offline method/flow checks; no model quality or market-performance claims."""
from copy import deepcopy
from hashlib import sha256
import json

import pytest

from apps.analysis.agents.macro_causal_review import review_macro_thesis
from apps.analysis.agents.research_quality import METHOD_PATH, quality_contract
from apps.analysis.agents.research_synthesis import _build_messages, _build_prompt_payload
from apps.analysis.research_shadow import SKILLS, archive_research_versions
from tests.analysis.test_gold_detailed_report import snapshot
from tests.analysis.test_research_synthesis import _output


def test_same_quality_method_and_complete_evidence_reach_synthesis_and_reviewer():
    source = snapshot()
    before = deepcopy(source)
    payload = _build_prompt_payload(source, _output())
    method = METHOD_PATH.read_text()
    assert payload['research_quality_standard'] == quality_contract()
    assert method in _build_messages(payload)[0]['content']
    seen = []

    def gateway(**kwargs):
        seen.append(kwargs)
        packed = json.loads(kwargs['messages'][1]['content'])
        assert packed['evidence'] == payload
        assert method in kwargs['messages'][0]['content']
        assert len(packed['questions']) == 17
        return {'content': json.dumps({'checks': [
            {'id': i, 'passed': True, 'reason': 'Test substitute: protocol only, not semantic evaluation'}
            for i in range(17)]})}

    review = review_macro_thesis(gateway=gateway, analysis={'reader_narrative': 'synthetic protocol example'},
                                evidence=payload, audit_context={})
    assert len(seen) == 1
    assert review['status'] == 'pass'
    assert review['research_quality_standard']['benchmark_parity'] == 'not_evaluated'
    assert review['is_probability'] is False
    assert source == before


@pytest.mark.parametrize('missing_or_failed', ['missing_new_checks', 14, 15, 16])
def test_old_passes_cannot_hide_unreviewed_or_failed_quality_dimensions(missing_or_failed):
    payload = _build_prompt_payload(snapshot(), _output())
    checks = [{'id': i, 'passed': i != missing_or_failed, 'reason': 'Synthetic reviewer response'}
              for i in range(14 if missing_or_failed == 'missing_new_checks' else 17)]
    result = review_macro_thesis(gateway=lambda **_: {'content': json.dumps({'checks': checks})},
                                analysis={}, evidence=payload, audit_context={})
    assert result['status'] == ('unavailable' if missing_or_failed == 'missing_new_checks' else 'needs_revision')
    assert result['confidence_multiplier'] == .7


def test_changed_method_cannot_silently_replay_a_frozen_request():
    payload = _build_prompt_payload(snapshot(), _output())
    payload['research_quality_standard']['method_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='fingerprint mismatch'):
        _build_messages(payload)

    def never_call(**kwargs):
        pytest.fail('invalid method binding must be rejected before a gateway request')

    result = review_macro_thesis(gateway=never_call, analysis={}, evidence=payload, audit_context={})
    assert result['status'] == 'unavailable'


def test_quality_standard_is_in_immutable_research_version_archive(tmp_path):
    root, storage = tmp_path/'repo', tmp_path/'storage'
    for name in SKILLS:
        path = root/'.agents/skills'/name/'SKILL.md'
        path.parent.mkdir(parents=True)
        path.write_text('Local test method, no market assertions')
    standard = root/'docs/evals/gold-research-quality-v1.md'
    standard.parent.mkdir(parents=True)
    standard.write_text('Test standard revision one')
    first = archive_research_versions(storage, repo_root=root)
    manifest = json.loads((storage/first['artifact_ref']).read_text())
    entry = manifest['files']['docs/evals/gold-research-quality-v1.md']
    assert entry['sha256'] == sha256(standard.read_bytes()).hexdigest()
    old = (storage/entry['artifact_ref']).read_bytes()
    standard.write_text('Test standard revision two')
    second = archive_research_versions(storage, repo_root=root)
    assert second['manifest_id'] != first['manifest_id']
    assert (storage/entry['artifact_ref']).read_bytes() == old
