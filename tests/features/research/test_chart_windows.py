from copy import deepcopy
from datetime import datetime, timedelta

from apps.features.research.chart_windows import build_chart_windows, refresh_chart_windows
from apps.features.research.cross_asset import build_cross_asset_features

NOW = '2026-09-17T12:10:00+00:00'


def series(ticker, delay=0, value=100):
    start = datetime.fromisoformat('2026-09-17T08:00:00+00:00')
    return {'ticker': ticker, 'status': 'available', 'delay_seconds': delay, 'resolution_seconds': 900,
            'retrieved_at': NOW, 'front_contract': 'CLV2026' if ticker == 'NYMEX:CL1!' else None,
            'source_refs': [{'source': 'tradingview_chart', 'raw_path': f'raw/{ticker}.json'}],
            'bars': [{'time': (start + timedelta(minutes=15*i)).isoformat(), 'close': value+i}
                     for i in range(17)]}


def energy():
    return [series('OANDA:XAUUSD', value=4300), series('NYMEX:CL1!', 600), series('ICEEUR:BRN1!', 600)]


def find(result, group='energy', horizon=60):
    return next(w for w in result['windows'] if w['group'] == group and w.get('horizon_minutes') == horizon)


def test_delayed_window_uses_same_completed_closes_and_does_not_mutate():
    data = energy()
    before = deepcopy(data)
    result = build_chart_windows(data, as_of=NOW)
    window = find(result)
    assert window['window_end'] == '2026-09-17T12:00:00+00:00'
    assert window['window_start'] == '2026-09-17T11:00:00+00:00'
    assert window['status'] == 'AVAILABLE_DELAYED'
    assert window['aligned_comparison_allowed']
    assert window['changes'][1]['change_pct'] == round((115/111-1)*100, 5)
    assert all(r['end_close'] != 116 for r in window['changes'])
    assert not result['causal_attribution_allowed']
    assert 'bars' not in str(result)
    assert data == before


def test_yield_change_is_basis_points_not_percentage_return():
    data = [series('OANDA:XAUUSD'), series('TVC:DXY'), series('TVC:US02Y'), series('TVC:US10Y')]
    for row in data[2:]:
        for i, bar in enumerate(row['bars']):
            bar['close'] = 4 + i / 100
    window = find(build_chart_windows(data, as_of=NOW), 'policy')
    assert window['changes'][2]['change_bp'] == 4
    assert 'change_pct' not in window['changes'][2]


def test_missing_interior_bar_is_not_forward_filled():
    data = energy()
    del data[1]['bars'][13]
    result = build_chart_windows(data, as_of=NOW)
    assert find(result)['reason'] == 'MISSING_ENDPOINT_OR_INTERIOR_BAR'
    assert not find(result)['aligned_comparison_allowed']
    assert find(result, horizon=15)['aligned_comparison_allowed']


def test_unverified_delay_and_duplicate_series_fail_closed():
    data = energy()
    data[1]['delay_seconds'] = None
    result = build_chart_windows(data, as_of=NOW)
    assert result['series_health'][1]['status'] == 'DELAY_UNVERIFIED'
    assert result['windows'][0]['missing_tickers'] == ['NYMEX:CL1!']
    data = energy()
    data.extend([deepcopy(data[1]), deepcopy(data[1])])
    result = build_chart_windows(data, as_of=NOW)
    assert result['windows'][0]['missing_tickers'] == ['NYMEX:CL1!']


def test_stale_common_window_is_not_rescued_by_new_capture_time():
    data = energy()
    for row in data:
        row['bars'] = row['bars'][:9]
    window = find(build_chart_windows(data, as_of=NOW))
    assert window['status'] == 'STALE'
    assert not window['aligned_comparison_allowed']


def test_frozen_window_survives_feature_rebuild_then_expires():
    first = build_cross_asset_features({'observations': [], 'chart_series': energy()}, as_of=NOW)
    assert first['analysis_capability']['energy_window_comparison'] == 'DELAYED'
    second = build_cross_asset_features(first, as_of=NOW)
    assert second['chart_windows'] == first['chart_windows']
    expired = refresh_chart_windows(first['chart_windows'], as_of='2026-09-17T13:10:00+00:00')
    assert find(expired)['status'] == 'STALE'
    assert not find(expired)['aligned_comparison_allowed']


def test_weekend_last_session_not_realtime_and_ancient_data_not_usable():
    data = energy()
    for row in data:
        row['retrieved_at'] = '2026-09-19T12:10:00+00:00'
    result = build_chart_windows(data, as_of='2026-09-19T12:10:00+00:00')
    assert find(result)['comparison_scope'] == 'LAST_AVAILABLE_SESSION'
    assert find(result)['aligned_comparison_allowed']
    for row in data:
        row['retrieved_at'] = '2026-09-26T12:10:00+00:00'
    result = build_chart_windows(data, as_of='2026-09-26T12:10:00+00:00')
    assert not find(result)['aligned_comparison_allowed']


def test_scanner_clock_gap_does_not_hide_verified_chart_window():
    from apps.features.research.source_health import build_core_source_health
    from apps.renderer.markdown.gold_reader import cross_asset_table
    observed = {'observations': [{'symbol': 'WTI', 'ticker': 'NYMEX:CL1!', 'status': 'available',
                                 'value': 115, 'unit': 'USD/bbl', 'retrieved_at': NOW,
                                 'delay_seconds': 600, 'source_refs': []}], 'chart_series': energy()}
    cross = build_cross_asset_features(observed, as_of=NOW)
    health = build_core_source_health({'snapshot_time': NOW, 'tradingview_cross_asset': cross})
    oil = next(r for r in health['items'] if r['source_key'] == 'tv_wti')
    assert oil['source_health'] == 'HEALTHY'
    assert oil['aligned_window_available']
    assert not oil['realtime_confirmation_available']
    assert not oil['alert_required']
    assert oil['access_method'] == 'tradingview_scanner_and_chart'
    text = cross_asset_table(cross)
    assert '2026-09-17T11:00:00+00:00' in text
    assert '2026-09-17T12:00:00+00:00' in text
    assert '600秒' in text and '共同已完成K线窗口' in text
    assert 'ENERGY_INTRADAY' in text


def test_minute_event_research_has_aligned_windows_but_no_five_minute_strategy():
    data = [series('OANDA:XAUUSD'), series('NYMEX:CL1!', 600)]
    start = datetime.fromisoformat('2026-09-17T09:00:00+00:00')
    for row in data:
        row['resolution_seconds'] = 60
        row['bars'] = [{'time': (start + timedelta(minutes=i)).isoformat(), 'close': 100 + i / 100}
                       for i in range(190)]
    result = build_chart_windows(data, as_of=NOW)
    window = find(result, 'gold_vs_NYMEX:CL1!', 30)
    assert window['window_end'] == '2026-09-17T12:00:00+00:00'
    assert window['aligned_comparison_allowed']
    assert {w.get('horizon_minutes') for w in result['windows']} == {None, 1, 30, 120}


def test_mixed_resolution_does_not_claim_comparable_returns():
    data = energy()
    data[0]['resolution_seconds'] = 3600
    result = build_chart_windows(data, as_of=NOW)
    assert result['windows'][0]['reason'] == 'NO_COMMON_RESOLUTION_OR_ENDPOINT'


def test_cross_date_window_is_excluded():
    data = energy()
    for row in data:
        row['retrieved_at'] = '2026-09-17T00:40:00+00:00'
        start = datetime.fromisoformat('2026-09-16T20:00:00+00:00')
        row['bars'] = [{'time': (start + timedelta(minutes=15*i)).isoformat(), 'close': 100 + i}
                       for i in range(18)]
    result = build_chart_windows(data, as_of='2026-09-17T00:40:00+00:00')
    assert find(result)['reason'] == 'CROSS_DATE_WINDOW_EXCLUDED'


def test_oil_and_policy_groups_share_the_same_end_despite_delay():
    data = energy() + [series(t) for t in ('TVC:DXY', 'TVC:US02Y', 'TVC:US10Y')]
    # At 12:20, non-delayed 12:15 closes exist; delayed oil has only 12:00.
    for row in data:
        row['retrieved_at'] = '2026-09-17T12:20:00+00:00'
    result = build_chart_windows(data, as_of='2026-09-17T12:20:00+00:00')
    energy_window, policy_window = find(result), find(result, 'policy')
    assert energy_window['window_end'] == policy_window['window_end'] == '2026-09-17T12:00:00+00:00'
    assert policy_window['alignment_delay_seconds'] == 600
    assert policy_window['max_delay_seconds'] == 0
    assert policy_window['aligned_comparison_allowed']


def matrix_row(result, horizon, group='policy'):
    return next(r for r in result['multi_horizon']['rows'] if r['horizon'] == horizon and r['group'] == group)


def long_policy(now=NOW, start='2026-09-17T06:00:00+00:00'):
    rows = [series(t) for t in ('OANDA:XAUUSD', 'TVC:DXY', 'TVC:US02Y', 'TVC:US10Y')]
    a, stop = datetime.fromisoformat(start), datetime.fromisoformat(now)
    count = int((stop - a).total_seconds() // 900)
    for row in rows:
        row.update(retrieved_at=now)
        row['bars'] = [{'time': (a + timedelta(minutes=i*15)).isoformat(), 'close': 100 + i} for i in range(count)]
    return rows


def test_multi_horizon_keeps_conflicting_one_and_four_hour_signs():
    data = long_policy()
    # Four-hour rise but final hour falls. No sign-dependent selection.
    for row in data:
        for i in range(-4, 0):
            row['bars'][i]['close'] = row['bars'][-5]['close'] - (i+5)
    result = build_chart_windows(data, as_of=NOW)
    one, four = matrix_row(result, '1h'), matrix_row(result, '4h')
    assert one['aligned_comparison_allowed'] and four['aligned_comparison_allowed']
    assert one['changes'][0]['change_pct'] < 0 < four['changes'][0]['change_pct']
    assert matrix_row(result, 'since_fomc')['reason'] == 'VERIFIED_ANCHOR_MISSING_OR_INVALID'
    assert result['multi_horizon']['causal_attribution_allowed'] is False


def test_named_sessions_use_dst_and_do_not_imply_all_day():
    for now, start, london, us in [('2026-09-17T12:10:00+00:00', '2026-09-17T06:00:00+00:00', '07:00', '08:00'),
                                    ('2026-11-18T14:10:00+00:00', '2026-11-18T07:00:00+00:00', '08:00', '09:00')]:
        result = build_chart_windows(long_policy(now, start), as_of=now)
        assert matrix_row(result, 'london_session')['window_start'][11:16] == london
        assert matrix_row(result, 'us_pre_market')['window_start'][11:16] == us
        assert matrix_row(result, 'us_pre_market')['aligned_comparison_allowed']


def test_event_anchor_requires_source_cutoff_and_contiguous_history():
    data = long_policy()
    anchor = {'timestamp': '2026-09-17T09:00:00Z', 'published_at': '2026-09-17T08:00:00Z',
              'verified': True, 'source_refs': [{'source': 'official event clock'}]}
    result = build_chart_windows(data, as_of=NOW, anchors={'since_fomc': anchor})
    assert matrix_row(result, 'since_fomc')['aligned_comparison_allowed']
    event = matrix_row(result, 'fomc_15m')
    assert event['aligned_comparison_allowed']
    assert event['window_end'] == '2026-09-17T09:15:00+00:00'
    result = build_chart_windows(data, as_of=NOW, anchors={'since_fomc': {**anchor, 'published_at': '2026-09-18T12:00:00Z'}})
    assert not matrix_row(result, 'since_fomc')['aligned_comparison_allowed']
    del data[0]['bars'][-3]
    result = build_chart_windows(data, as_of=NOW, anchors={'since_fomc': anchor})
    assert matrix_row(result, 'since_fomc')['reason'] == 'MISSING_ENDPOINT_OR_INTERIOR_BAR'


def test_matrix_survives_model_projection_but_expires_when_capture_stales():
    from apps.analysis.agents.research_input import project_cross_asset
    from apps.renderer.markdown.research_evidence import multi_horizon_table
    cross = build_cross_asset_features({'observations': [], 'chart_series': long_policy()}, as_of=NOW)
    projected = project_cross_asset(cross)
    assert projected['chart_windows']['multi_horizon'] == cross['chart_windows']['multi_horizon']
    assert 'Since FOMC' in multi_horizon_table(cross)
    assert '不等于排除地缘对冲' in multi_horizon_table(cross)
    expired = refresh_chart_windows(cross['chart_windows'], as_of='2026-09-17T13:10:00+00:00')
    assert not matrix_row(expired, '1h')['aligned_comparison_allowed']


def test_fomc_anchor_comes_only_from_nonfuture_archived_official_event():
    from apps.features.research.multi_horizon import snapshot_window_anchors
    event = {'title': 'fomc_statement', 'occurred_at': '2026-09-17T09:00:00Z',
             'source_refs': [{'source': 'fed_rss', 'source_type': 'official',
                              'raw_path': 'raw/fed.json', 'reference': 'fed:event-1'}]}
    snapshot = {'snapshot_time': NOW, 'official_events': {'data': {'events': [event]}}}
    assert snapshot_window_anchors(snapshot)['since_fomc']['timestamp'] == '2026-09-17T09:00:00+00:00'
    event['occurred_at'] = '2026-09-18T09:00:00Z'
    assert 'since_fomc' not in snapshot_window_anchors(snapshot)


def test_cross_date_futures_need_per_bar_contract_continuity():
    now = '2026-09-17T01:10:00+00:00'
    rows = long_policy(now, '2026-09-16T19:00:00+00:00')[:1]
    oil = deepcopy(rows[0])
    oil['ticker'] = 'NYMEX:CL1!'
    rows.append(oil)
    result = build_chart_windows(rows, as_of=now)
    row = matrix_row(result, '4h', 'gold_vs_NYMEX:CL1!')
    assert row['reason'] == 'CROSS_DATE_CONTRACT_CONTINUITY_UNVERIFIED'
    for bar in oil['bars']:
        bar['front_contract'] = 'CLV2026'
    result = build_chart_windows(rows, as_of=now)
    assert matrix_row(result, '4h', 'gold_vs_NYMEX:CL1!')['aligned_comparison_allowed']
    oil['bars'][-3]['front_contract'] = 'CLX2026'
    assert not matrix_row(build_chart_windows(rows, as_of=now), '4h', 'gold_vs_NYMEX:CL1!')['aligned_comparison_allowed']


def test_packed_multi_horizon_preserves_all_windows_units_nulls_and_reasons():
    from apps.analysis.agents.research_input import _project_chart_window_tables
    bundle = build_chart_windows(long_policy(), as_of=NOW)
    original = deepcopy(bundle['multi_horizon']['rows'])
    _project_chart_window_tables(bundle)
    matrix = bundle['multi_horizon']
    def unpack(table):
        if isinstance(table, list):
            return table
        return [{key: row[i] for i, key in enumerate(table['columns'])
                 if i not in table.get('missing_by_row', {}).get(str(n), [])}
                for n, row in enumerate(table['rows'])]
    rows = unpack(matrix['rows_table'])
    for row in rows:
        row['changes'] = []
    for change in unpack(matrix['changes_table']):
        n = change.pop('row_index')
        rows[n]['changes'].append(change)
    assert rows == original
