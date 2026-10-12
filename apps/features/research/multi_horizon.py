"""A fixed, sign-independent comparison matrix from validated chart series."""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo


def snapshot_window_anchors(snapshot):
    """Use an archived official FOMC publication clock, never infer a clock from its date."""
    from copy import deepcopy
    from apps.features.research.cross_asset import _time

    anchors = deepcopy(snapshot.get('cross_asset_window_anchors') or {})
    cutoff = _time(snapshot.get('snapshot_time'))
    candidates = []
    for event in snapshot.get('official_events', {}).get('data', {}).get('events', []):
        stamp = _time(event.get('occurred_at'))
        refs = [r for r in event.get('source_refs', []) if r.get('source') == 'fed_rss'
                and r.get('source_type') == 'official' and r.get('raw_path') and r.get('reference')]
        if event.get('title') == 'fomc_statement' and cutoff and stamp and stamp <= cutoff and refs:
            candidates.append((stamp, refs))
    if candidates:
        stamp, refs = max(candidates, key=lambda x: x[0])
        anchors['since_fomc'] = {'timestamp': stamp.isoformat(), 'published_at': stamp.isoformat(),
                                 'verified': True, 'source_refs': deepcopy(refs)}
    return anchors


def _anchor(key, end, anchors, now):
    if key in {'15m', '1h', '4h'}:
        minutes = {'15m': 15, '1h': 60, '4h': 240}[key]
        return end - timedelta(minutes=minutes), end, [], None
    if key in {'london_session', 'us_pre_market'}:
        zone, opening, closing = (('Europe/London', time(8), time(16, 30))
                                  if key == 'london_session' else ('America/New_York', time(4), time(9, 30)))
        local = end.astimezone(ZoneInfo(zone))
        start = datetime.combine(local.date(), opening, ZoneInfo(zone)).astimezone(UTC)
        stop = datetime.combine(local.date(), closing, ZoneInfo(zone)).astimezone(UTC)
        return start, min(end, stop), [], 'SESSION_NOT_STARTED' if start >= end or local.weekday() > 4 else None
    # Prior close differs by instrument/venue; an arbitrary midnight is not a close.
    entry = anchors.get('since_fomc' if key == 'fomc_15m' else key, {})
    try:
        stamp = datetime.fromisoformat(entry['timestamp'].replace('Z', '+00:00'))
        published = datetime.fromisoformat(entry['published_at'].replace('Z', '+00:00'))
        if (stamp.tzinfo is None or published.tzinfo is None or not entry.get('source_refs')
                or entry.get('verified') is not True or published > now or not stamp < end):
            raise ValueError('unverified or future anchor')
        stop = stamp + timedelta(minutes=15) if key == 'fomc_15m' else end
        if stop > end:
            raise ValueError('event window is not complete')
        return stamp.astimezone(UTC), stop.astimezone(UTC), entry['source_refs'], None
    except (KeyError, ValueError, TypeError, AttributeError):
        return None, end, [], 'VERIFIED_ANCHOR_MISSING_OR_INVALID'


def build_multi_horizon(healthy, *, groups, now, session, anchors=None):
    """healthy contains the original series plus already validated completed closes."""
    from apps.features.research.cross_asset import _time
    from apps.parsers.market.tradingview import ALL_INSTRUMENTS

    horizons = ('15m', '1h', '4h', 'london_session', 'us_pre_market', 'since_prior_close', 'since_fomc', 'fomc_15m')
    rows = []
    core = set().union(*map(set, groups.values()))
    global_end = None
    if core <= healthy.keys() and len({healthy[t][0]['resolution_seconds'] for t in core}) == 1:
        common = set.intersection(*(set(healthy[t][1]) for t in core))
        global_end = max(common) if common else None
    closed = session['state'] in {'CLOSED', 'HOLIDAY', 'EARLY_CLOSE', 'MAINTENANCE'}
    for group, tickers in groups.items():
        missing = sorted(set(tickers) - healthy.keys())
        selected = [healthy[t] for t in tickers if t in healthy]
        intervals = {r['resolution_seconds'] for r, _ in selected}
        common = set.intersection(*(set(b) for _, b in selected)) if selected else set()
        end = global_end or (max(common) if common else None)
        interval = next(iter(intervals)) if len(intervals) == 1 else None
        delay = max((r['delay_seconds'] for r, _ in selected), default=0)
        effective_delay = max((healthy[t][0]['delay_seconds'] for t in core), default=delay) if global_end else delay
        for key in horizons:
            row = {'group': group, 'horizon': key, 'status': 'UNAVAILABLE',
                   'aligned_comparison_allowed': False, 'changes': [], 'reason': None,
                   'window_start': None, 'window_end': end.isoformat() if end else None,
                   'alignment_endpoint': end.isoformat() if end else None,
                   'bar_resolution_seconds': interval, 'max_delay_seconds': delay,
                   'alignment_delay_seconds': effective_delay,
                   'comparison_scope': 'LAST_AVAILABLE_SESSION' if closed else 'BOUNDED_WINDOW',
                   'anchor_source_refs': [], 'causal_attribution_allowed': False}
            rows.append(row)
            if missing or not end or not interval or not now:
                row.update(reason='MISSING_SERIES_OR_COMMON_RESOLUTION', missing_tickers=missing)
                continue
            start, stop, refs, error = _anchor(key, end, anchors or {}, now)
            row.update(window_start=start.isoformat() if start else None, window_end=stop.isoformat(), anchor_source_refs=refs)
            if error:
                row['reason'] = error
                continue
            duration = (stop - start).total_seconds()
            if duration <= 0 or duration % interval or duration / interval > 2048:
                row['reason'] = 'ANCHOR_NOT_ON_BAR_GRID_OR_HISTORY_LIMIT'
                continue
            # Fixed session windows may end before the latest bar; freshness is
            # based on the live common series endpoint, not session closing time.
            limit = 96 * 3600 if closed else effective_delay + 2 * interval
            if not 0 <= (now - end).total_seconds() <= limit or session['state'] == 'UNKNOWN':
                row['reason'] = 'STALE_OR_UNKNOWN_SESSION'
                continue
            required = {start + timedelta(seconds=i * interval) for i in range(int(duration / interval) + 1)}
            if any(not required <= bars.keys() for _, bars in selected):
                row['reason'] = 'MISSING_ENDPOINT_OR_INTERIOR_BAR'
                continue
            if start.date() != stop.date():
                # A single current front-contract label cannot certify history.
                # Require a stable contract on every used futures bar.
                invalid_roll = False
                for raw, _ in selected:
                    if ALL_INSTRUMENTS[raw['ticker']][1] != 'futures':
                        continue
                    contracts = {b.get('front_contract') for b in raw.get('bars', [])
                                 if _time(b.get('time')) and _time(b['time']) + timedelta(seconds=interval) in required}
                    if len(contracts) != 1 or None in contracts or '' in contracts:
                        invalid_roll = True
                if invalid_roll:
                    row['reason'] = 'CROSS_DATE_CONTRACT_CONTINUITY_UNVERIFIED'
                    continue
            row.update(status='AVAILABLE_DELAYED' if effective_delay else 'AVAILABLE', aligned_comparison_allowed=True)
            for raw, bars in selected:
                symbol, instrument, unit, _ = ALL_INSTRUMENTS[raw['ticker']]
                change = {'ticker': raw['ticker'], 'symbol': symbol, 'unit': unit,
                          'start_close': bars[start], 'end_close': bars[stop],
                          'source_refs': raw.get('source_refs', [])}
                if instrument == 'bond':
                    change['change_bp'] = round((bars[stop] - bars[start]) * 100, 4)
                else:
                    change['change_pct'] = round((bars[stop] / bars[start] - 1) * 100, 5)
                row['changes'].append(change)
    return {'schema_version': 'cross_asset_multi_horizon.v1', 'rows': rows,
            'selection_policy': 'fixed_horizons_independent_of_return_sign',
            'causal_attribution_allowed': False,
            'limitations': ['局部窗口不能代表全天；所有可用及缺失窗口同时保留。',
                            '共同涨跌是观察性证据，不是已识别因果。',
                            '不支持广泛风险厌恶主导，不等于排除地缘对冲、OTC或实物需求。',
                            'London按08:00–16:30当地时间、US pre-market按04:00–09:30纽约时间定义；不是所有标的统一交易所时段。']}
