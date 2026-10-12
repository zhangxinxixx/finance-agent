from datetime import UTC, datetime, timedelta

from apps.features.research.timeframes import build_execution_timeframe_features


def _bar(index, *, close, high=None, low=None, seconds=300):
    opened = datetime(2026, 9, 8, tzinfo=UTC) + timedelta(seconds=index * seconds)
    closed = opened + timedelta(seconds=seconds)
    return {
        'open_time': opened.isoformat(),
        'close_time': closed.isoformat(),
        'open': close - 0.2, 'high': high if high is not None else close + 0.2,
        'low': low if low is not None else close - 0.3, 'close': close,
    }


def test_timeframe_features_only_confirm_explicit_completed_bar_events():
    bars = [_bar(index, close=100 + index) for index in range(5)]
    bars.append(_bar(5, close=106, high=106.5))
    result = build_execution_timeframe_features({
        '5m': {'status': 'available', 'timeframe': '5m', 'interval': '5min', 'timezone': 'UTC',
               'retrieved_at': '2026-09-08T00:40:00+00:00',
               'closed_before': '2026-09-08T00:38:45+00:00',
               'bars': bars, 'raw_path': 'raw/5m.json'},
    })
    feature = result['5m']
    assert feature['status'] == 'available'
    assert feature['trend'] == 'bullish'
    assert feature['structure_status'] == 'observed_proxy'
    assert feature['events'][0]['type'] == 'bos_up'
    assert feature['events'][0]['confirmed'] is False


def test_timeframe_features_leave_short_or_mixed_history_unconfirmed():
    result = build_execution_timeframe_features({
        '1h': {'status': 'available', 'timeframe': '1h', 'interval': '1h',
               'retrieved_at': '2026-09-08T04:00:00+00:00',
               'closed_before': '2026-09-08T03:58:45+00:00',
               'bars': [_bar(0, close=100, seconds=3600), _bar(1, close=101, seconds=3600)]},
        '4h': {'status': 'partial', 'timeframe': '4h', 'interval': '4h',
               'retrieved_at': '2026-09-08T04:00:00+00:00',
               'closed_before': '2026-09-08T03:58:45+00:00', 'bars': []},
    })
    assert result['1h']['status'] == 'partial'
    assert result['1h']['trend'] == 'unavailable'
    assert result['1h']['events'] == []
    assert result['4h']['status'] == 'partial'
    assert result['4h']['reason'] == 'no_completed_bars'


def test_timeframe_features_reject_future_duplicate_bad_interval_and_stale_latest_bar():
    bars = [_bar(index, close=100 + index) for index in range(6)]
    bars.append(dict(bars[-1]))
    bars.append(_bar(6, close=107))
    bars[-1]['close_time'] = '2026-09-08T01:00:00+00:00'
    result = build_execution_timeframe_features({
        '5m': {'status': 'available', 'timeframe': '5m', 'interval': '5min',
               'retrieved_at': '2026-09-08T01:00:00+00:00',
               'closed_before': '2026-09-08T00:58:45+00:00', 'bars': bars},
        '15m': {'status': 'available', 'timeframe': '15m', 'interval': '15min',
                'retrieved_at': '2026-09-08T01:50:00+00:00',
                'closed_before': '2026-09-08T01:48:45+00:00',
                'bars': [_bar(index, close=100 + index, seconds=900) for index in range(6)]},
    })
    assert result['5m']['bar_count'] == 6
    assert result['5m']['rejected_bar_count'] == 2
    assert result['5m']['structure_status'] == 'stale_latest_bar'
    assert result['5m']['events'] == []
    assert result['15m']['structure_status'] == 'observed_proxy'
    assert result['15m']['events'][0]['classification'] == 'prior_5_bar_range_break_proxy'
    assert result['15m']['events'][0]['confirmed'] is False


def test_timeframe_features_mark_gapped_window_without_confirming_structure():
    bars = [_bar(index, close=100 + index) for index in range(5)]
    bars.append(_bar(6, close=107))
    result = build_execution_timeframe_features({
        '5m': {'status': 'available', 'timeframe': '5m', 'interval': '5min',
               'retrieved_at': '2026-09-08T00:45:00+00:00',
               'closed_before': '2026-09-08T00:43:45+00:00', 'bars': bars},
    })
    assert result['5m']['continuity_status'] == 'gapped'
    assert result['5m']['structure_status'] == 'observed_proxy_gapped'
