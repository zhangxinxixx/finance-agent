"""Model transport must preserve nonzero tails, missing history and provenance."""
from copy import deepcopy

import pytest

from apps.analysis.agents.research_input import project_macro, final_input, encode
from apps.features.macro.fedwatch_policy import project_fedwatch_policy
from apps.worker.fedwatch import fedwatch_view
from tests.features.test_fedwatch import NOW, TARGET, snapshot


def policy_fixture():
    source = snapshot()
    source['target_reference'] = TARGET
    return project_fedwatch_policy(fedwatch_view(source, as_of=NOW), as_of=NOW)


@pytest.mark.parametrize('legacy_rate_delta', [0.0, 0.125])
def test_projection_preserves_tails_missing_history_timing_and_original(legacy_rate_delta):
    policy = policy_fixture()
    meeting = policy['meetings'][0]
    canonical_expected_rate = meeting['implied_target_midpoint_expected_rate']
    meeting['expected_rate_pct'] = canonical_expected_rate + legacy_rate_delta
    meeting['bins'] += [
        {'target_low': 6, 'target_high': 6.25, 'probability': 0.0},
        {'target_low': 6.25, 'target_high': 6.5, 'probability': 1e-10},
        {'target_low': 6.5, 'target_high': 6.75, 'probability': None},
    ]
    meeting['comparisons'].pop('1m')
    before = deepcopy(policy)
    projected = project_macro({'engines': {'policy': policy}})['engines']['policy']
    current = projected['meetings'][0]
    assert current['bins_omitted_exact_zero_count'] == 1
    assert current['bins'][-2:]== meeting['bins'][-2:]
    assert '1m' not in current['comparisons']
    for key in ('source_as_of', 'implied_target_midpoint_expected_rate', 'comparisons'):
        # Comparison rows may have only explicit zero deltas removed.
        if key != 'comparisons':
            assert current[key] == meeting[key]
    if legacy_rate_delta == 0:
        assert 'expected_rate_pct' not in current
    else:
        assert current['expected_rate_pct'] == meeting['expected_rate_pct']
    assert current['comparisons']['1d']['comparison_source_as_of'] == meeting['comparisons']['1d']['comparison_source_as_of']
    assert policy == before
    # A disagreeing copy is retained, never replaced just because dates match.
    assert 'bins' in projected['market_implied_path']['next_meeting']


def test_full_synthesis_uses_compact_policy_with_resolvable_meetings():
    from types import SimpleNamespace
    policy = policy_fixture()
    projected = project_macro({'engines': {'policy': policy}})['engines']['policy']
    assert projected['market_implied_path']['next_meeting'] == {'meeting_ref': policy['meetings'][0]['meeting_date']}
    snapshot_input = {'gold_workflow': {'macro_causal': {'engines': {'policy': policy}}},
                      'snapshot_time': NOW, 'snapshot_id': 'synthetic'}
    result = final_input(snapshot_input, SimpleNamespace(input_payload={}), catalog={}, assessment={})
    text = encode(result)
    assert 'meeting_ref' in text and 'Only explicitly observed exact-zero' in text
    assert 'source_catalog' in result and result['input_contract']['truncation'] is False
    assert policy['snapshot_id'] in text
    assert len(text) < len(encode(policy))


def test_horizon_uses_meeting_observation_time_not_envelope_cutoff():
    source = snapshot()
    source['target_reference'] = TARGET
    view = fedwatch_view(source, as_of=NOW)
    view['as_of'] = '2026-09-28T11:55:05Z'
    policy = project_fedwatch_policy(view, as_of=NOW)
    assert policy['policy_path']['rows'][0]['observed_at'] == policy['meetings'][0]['source_as_of']
    assert policy['policy_path']['rows'][0]['observed_at'] != view['as_of']
