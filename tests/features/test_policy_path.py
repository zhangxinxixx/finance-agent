from copy import deepcopy

import pytest

from apps.features.macro.policy_path import bind_policy_target, build_policy_path


def source():
    return {'provider': 'cme', 'observed_at': '2026-09-18T12:00:00Z',
            'probability_unit': 'fraction', 'rate_unit': 'percent', 'current_target_midpoint': 3.875,
            'source_refs': [{'raw_path': 'raw/cme.json', 'sha256': 'source-hash'}],
            'meetings': [{'meeting_date': d, 'bins': [{'lower': 3.75, 'upper': 4, 'probability': .5},
                                                    {'lower': 4, 'upper': 4.25, 'probability': .5}]}
                         for d in ['2026-10-28', '2026-12-09', '2027-03-17', '2027-09-15']]}


def test_fixed_horizons_and_matching_history_keep_lineage():
    data = source()
    old = deepcopy(data)
    old['observed_at'] = '2026-09-17T12:00:00Z'
    for m in old['meetings']:
        m['bins'][0]['probability'], m['bins'][1]['probability'] = 1, 0
    data['comparisons'] = {'1d': old}
    before = deepcopy(data)
    path = build_policy_path(data, as_of=data['observed_at'])['policy_path']
    assert path['status'] == 'complete'
    assert [r['horizon'] for r in path['rows']] == ['next_meeting', 'year_end', '3m', '6m', '12m']
    assert all(r['expected_target_midpoint_pct'] == 4 for r in path['rows'])
    assert all(r['repricing_1d_bp'] == pytest.approx(12.5) for r in path['rows'])
    assert all(r['repricing_1w_bp'] is None for r in path['rows'])
    assert data == before


def test_no_distribution_still_has_five_explicit_missing_rows():
    path = build_policy_path({}, as_of='2026-09-18T12:00:00Z')['policy_path']
    assert len(path['rows']) == 5 and path['status'] == 'unavailable'
    assert all(r['expected_target_midpoint_pct'] is None and r['reason'] for r in path['rows'])


def test_missing_december_does_not_extrapolate_october_to_year_end():
    data = source()
    data['meetings'] = data['meetings'][:1]
    path = build_policy_path(data, as_of=data['observed_at'])['policy_path']
    assert path['status'] == 'partial'
    assert path['rows'][1]['expected_target_midpoint_pct'] is None
    assert path['rows'][4]['status'] == 'unavailable'


def sep():
    return {'year': 2026, 'horizon': 'year_end', 'statistic': 'median', 'rate_unit': 'percent',
            'published_at': '2026-09-16T18:00:00Z', 'median_target_midpoint_pct': 4.1,
            'source_refs': [{'source': 'Federal Reserve SEP', 'raw_path': 'raw/sep.html'}]}


def test_sep_is_same_year_published_before_market_and_units_match():
    data = source()
    result = build_policy_path(data, as_of=data['observed_at'], sep=sep())['policy_path']['market_vs_sep']
    assert result['status'] == 'available'
    assert result['market_minus_sep_bp'] == pytest.approx(-10)
    for field, value in [('year', 2027), ('rate_unit', 'bp'), ('statistic', 'mean'), ('published_at', '2026-09-19T00:00:00Z')]:
        bad = {**sep(), field: value}
        result = build_policy_path(data, as_of=data['observed_at'], sep=bad)['policy_path']['market_vs_sep']
        assert result['status'] == 'unavailable' and result['market_minus_sep_bp'] is None


def test_target_reference_cannot_be_effr_or_future_or_conflicting():
    data = source()
    data['current_target_midpoint'] = None
    ref = {'lower': 3.75, 'upper': 4, 'rate_unit': 'percent', 'effective_at': '2026-09-17T00:00:00Z',
           'published_at': '2026-09-16T18:00:00Z', 'source_refs': [{'source': 'Fed statement'}]}
    assert bind_policy_target(data, ref)['current_target_midpoint'] == 3.875
    assert bind_policy_target(data, {**ref, 'effective_at': '2026-09-19T00:00:00Z'})['current_target_midpoint'] is None
    assert bind_policy_target({**data, 'current_target_midpoint': 4.5}, ref)['current_target_midpoint'] is None


def test_future_meeting_timestamp_and_unbounded_sla_are_rejected():
    data = source()
    data['meetings'][0]['observed_at'] = '2026-09-19T00:00:00Z'
    assert build_policy_path(data, as_of=data['observed_at'])['status'] == 'unavailable'
    data = source()
    data['max_age_seconds'] = float('inf')
    assert build_policy_path(data, as_of=data['observed_at'])['status'] == 'unavailable'


def test_bad_history_does_not_erase_valid_current_distribution():
    data = source()
    data['comparisons'] = {'1d': {'provider': 'cme', 'observed_at': 'invalid'}}
    result = build_policy_path(data, as_of=data['observed_at'])
    assert result['status'] == 'available'
    assert all(r['repricing_1d_bp'] is None for r in result['policy_path']['rows'])
