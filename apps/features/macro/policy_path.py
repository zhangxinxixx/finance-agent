"""Fixed policy horizons and comparable SEP evidence, without extrapolation."""

from calendar import monthrange
from copy import deepcopy
from datetime import date
from math import isfinite

from apps.features.macro.policy_expectations import _time, build_policy_expectations


def bind_policy_target(distribution, reference):
    """Attach a separately sourced effective target; never use EFFR as target."""
    result = deepcopy(distribution)
    if not reference or not result:
        return result
    try:
        low, high = float(reference['lower']), float(reference['upper'])
        observed = _time(result['observed_at'])
        if (reference.get('rate_unit') != 'percent' or not reference.get('source_refs')
                or not all(isfinite(v) for v in (low, high)) or low >= high
                or _time(reference['effective_at']) > observed
                or _time(reference['published_at']) > observed):
            raise ValueError('invalid target reference')
        midpoint = (low + high) / 2
        if result.get('current_target_midpoint') not in (None, midpoint):
            raise ValueError('target reference conflict')
        result['current_target_midpoint'] = midpoint
        result['current_target_reference'] = deepcopy(reference)
        result['source_refs'] = result.get('source_refs', []) + deepcopy(reference['source_refs'])
    except (KeyError, TypeError, ValueError, OverflowError):
        result['current_target_midpoint'] = None
        result['target_reference_error'] = 'invalid_or_conflicting_current_target_reference'
    return result


def _add_months(day, months):
    year, month = divmod(day.year * 12 + day.month - 1 + months, 12)
    month += 1
    return date(year, month, min(day.day, monthrange(year, month)[1]))


def build_policy_path(source, *, as_of, target_reference=None, sep=None):
    source = bind_policy_target(source, target_reference)
    result = build_policy_expectations(source, as_of=as_of)
    # A caller may have no current observations: still return all requested rows.
    day = _time(as_of).date()
    meetings = result['meetings']
    requests = [('next_meeting', None), ('year_end', date(day.year, 12, 31))]
    requests += [(f'{n}m', _add_months(day, n)) for n in (3, 6, 12)]
    rows = []
    for key, target in requests:
        available = [m for m in meetings if target is None or date.fromisoformat(m['meeting_date']) <= target]
        chosen = (available[0] if key == 'next_meeting' else available[-1]) if available else None
        if chosen and target:
            meeting_day = date.fromisoformat(chosen['meeting_date'])
            if (target - meeting_day).days > 62 or (key == 'year_end' and meeting_day.month != 12):
                chosen = None
        reason = None if chosen else result.get('reason') or 'meeting_coverage_missing'
        rows.append({
            'horizon': key, 'target_date': target.isoformat() if target else None,
            'meeting_date': chosen['meeting_date'] if chosen else None,
            'status': 'available' if chosen else 'unavailable', 'reason': reason,
            'expected_target_midpoint_pct': chosen['expected_target_midpoint_pct'] if chosen else None,
            'repricing_1d_bp': chosen['repricing_1d_bp'] if chosen else None,
            'repricing_1w_bp': chosen['repricing_1w_bp'] if chosen else None,
            'comparison_1d_status': 'available' if chosen and chosen['repricing_1d_bp'] is not None else 'comparable_history_missing',
            'comparison_1w_status': 'available' if chosen and chosen['repricing_1w_bp'] is not None else 'comparable_history_missing',
            'observed_at': result.get('observed_at'), 'source_refs': deepcopy(result['source_refs']),
            'basis': 'last_covered_meeting_on_or_before_horizon_not_interpolated',
        })
    result['policy_path'] = {
        'schema_version': 'fed_policy_path.v1', 'rows': rows,
        'status': 'complete' if all(r['status'] == 'available' for r in rows) else 'partial' if meetings else 'unavailable',
        'missing_horizons': [r['horizon'] for r in rows if r['status'] != 'available'],
        'market_vs_sep': _compare_sep(rows[1], sep, as_of=as_of),
        'limitations': ['期限采用目标日之前最近已覆盖会议，不插值；缺失不是零变化。',
                        'SEP是官员适当政策中位数，不是市场概率或政策承诺；差值不是意外指数。'],
    }
    return result


def _compare_sep(year_end, sep, *, as_of):
    empty = {'status': 'unavailable', 'reason': 'verified_year_end_sep_missing',
             'market_minus_sep_bp': None, 'source_refs': []}
    if not sep:
        return empty
    try:
        median = float(sep['median_target_midpoint_pct'])
        if (sep['rate_unit'] != 'percent' or sep['statistic'] != 'median'
                or sep['horizon'] != 'year_end' or not sep.get('source_refs')
                or not isfinite(median) or _time(sep['published_at']) > _time(as_of)
                or str(sep['year']) != year_end['target_date'][:4]):
            raise ValueError('incompatible SEP')
        result = {**empty, 'year': sep['year'], 'sep_median_pct': median,
                  'sep_published_at': sep['published_at'], 'source_refs': deepcopy(sep['source_refs'])}
        if year_end['status'] != 'available':
            return {**result, 'reason': 'market_year_end_distribution_missing'}
        if _time(sep['published_at']) > _time(year_end['observed_at']):
            return {**result, 'reason': 'market_observation_precedes_sep'}
        return {**result, 'status': 'available', 'reason': None,
                'market_observed_at': year_end['observed_at'],
                'market_minus_sep_bp': (year_end['expected_target_midpoint_pct'] - median) * 100,
                'source_refs': result['source_refs'] + deepcopy(year_end['source_refs'])}
    except (KeyError, TypeError, ValueError, OverflowError):
        return {**empty, 'reason': 'invalid_or_incompatible_sep'}
