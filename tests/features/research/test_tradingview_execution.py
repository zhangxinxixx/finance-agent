from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from apps.features.research.tradingview_execution import merge_tradingview_execution
from apps.features.research.price_action import build_price_action

AS_OF = '2026-09-28T10:31:30+00:00'


def series(seconds=900):
    end = datetime(2026, 9, 28, 10, 30, tzinfo=UTC)
    if seconds == 3600:
        end = end.replace(minute=0)
    if seconds == 14400:
        end = end.replace(hour=9, minute=0)
    bars = []
    for i in range(12):
        t = end - timedelta(seconds=seconds*(11-i))
        bars.append({'time': t.isoformat(), 'open':100+i, 'high':102+i, 'low':99+i, 'close':101+i})
    return {'ticker':'OANDA:XAUUSD', 'status':'available', 'resolution_seconds':seconds,
            'delay_seconds':0, 'retrieved_at':AS_OF, 'bars':bars,
            'continuous_contract':False,
            'metadata':{'exchange':'OANDA', 'instrument_type':'commodity', 'currency':'USD',
                        'series_completed':True, 'provider_delay_seconds':0},
            'source_refs':[{'source':'tradingview_chart','ticker':'OANDA:XAUUSD',
                            'raw_path':f'raw/{seconds}.json','retrieved_at':AS_OF}]}


def merge(rows, existing=None):
    return merge_tradingview_execution(existing, rows, as_of=AS_OF, analysis_date='2026-09-28')


def test_native_ohlc_reaches_pa_without_unfinished_bars_or_primary_mutation():
    rows = [series(s) for s in (900,3600,14400)]
    original = deepcopy(rows)
    result = merge(rows)
    assert rows == original
    pa = build_price_action({'trade_date':'2026-09-28','snapshot_time':AS_OF,
                             'daily_research':{'execution_timeframes':result}})
    assert all(v['status'] == 'available' for v in pa['timeframes'].values())
    assert result['timeframes']['15m']['latest_closed_time'] == '2026-09-28T10:30:00+00:00'
    assert result['timeframes']['4h']['bars'][-1]['open_time'] == '2026-09-28T05:00:00+00:00'
    assert all(v['source_refs'][0]['ticker'] == 'OANDA:XAUUSD' for v in pa['timeframes'].values())
    assert not pa['five_minute_enabled']
    primary = deepcopy(result)
    primary['timeframes']['15m']['raw_path'] = 'raw/primary.json'
    assert merge(rows, primary)['timeframes']['15m']['raw_path'] == 'raw/primary.json'


@pytest.mark.parametrize('change', [
    {'delay_seconds':600}, {'delay_seconds':None}, {'ticker':'COMEX:GC1!'},
    {'source_refs':[]}, {'retrieved_at':'2026-09-28T12:00:00Z'},
    {'status':'unavailable','error':'TimeoutError'},
])
def test_delayed_future_unlineaged_and_futures_inputs_fail_closed(change):
    row = series()
    row.update(change)
    assert merge([row])['timeframes'] == {}


def test_real_missing_trading_bar_is_not_a_scheduled_break():
    row = series()
    del row['bars'][4]
    result = merge([row])
    assert result['timeframes'] == {}
    assert result['fallback_diagnostics']['15m'] == 'missing_stale_or_gapped_bars'


def test_research_time_passing_does_not_refresh_old_bars():
    result=merge_tradingview_execution({},[series()],as_of='2026-09-28T11:00:00Z',analysis_date='2026-09-28')
    assert not result['timeframes']
    # A previously accepted frame must also fail PA after the final research cutoff advances.
    result=merge([series()])
    pa=build_price_action({'trade_date':'2026-09-28','snapshot_time':'2026-09-28T11:00:00Z',
                          'daily_research':{'execution_timeframes':result}})
    assert pa['timeframes']['15m']['status']=='unavailable'


@pytest.mark.parametrize('end,start', [
    ('2026-09-25T20:45:00Z','2026-09-27T22:00:00Z'),
    ('2026-09-24T20:45:00Z','2026-09-24T22:00:00Z'),
    ('2026-11-06T21:45:00Z','2026-11-08T23:00:00Z'),
])
def test_oanda_scheduled_breaks_preserve_real_bars_across_dst(end,start):
    from apps.features.research.timeframes import build_execution_timeframe_features
    a=datetime.fromisoformat(end.replace('Z','+00:00'))
    b=datetime.fromisoformat(start.replace('Z','+00:00'))
    times=[a-timedelta(minutes=15*i) for i in (2,1,0)]+[b+timedelta(minutes=15*i) for i in range(3)]
    bars=[{'open_time':t.isoformat(),'close_time':(t+timedelta(minutes=15)).isoformat(),
           'open':100,'high':102,'low':99,'close':101} for t in times]
    now=(times[-1]+timedelta(minutes=17)).isoformat()
    raw={'status':'available','timeframe':'15m','retrieved_at':now,'closed_before':now,'bars':bars,
         'ticker':'OANDA:XAUUSD','raw_path':'raw/bars.json',
         'source_refs':[{'source':'tradingview_chart','ticker':'OANDA:XAUUSD','raw_path':'raw/bars.json'}]}
    checked=build_execution_timeframe_features({'15m':raw})['15m']
    assert checked['continuity_status'] == 'continuous_over_scheduled_breaks'
    assert checked['bar_count'] == 6
    raw['source_refs']=[]
    assert build_execution_timeframe_features({'15m':raw})['15m']['continuity_status'] == 'gapped'


def test_worker_enrichment_connects_pa_and_preserves_archive(monkeypatch,tmp_path,warehouse_db):
    from apps.worker.cross_asset_research import enrich_cross_asset_snapshot
    import apps.worker.cross_asset_research as module
    class Clock:
        @staticmethod
        def now(tz):return datetime.fromisoformat(AS_OF)
    monkeypatch.setattr(module,'datetime',Clock)
    rows=[series(s) for s in (900,3600,14400)]
    observed={'observations':[], 'parsed_path':'parsed/scan.json','execution_chart_series':rows,
              'source_refs':[r['source_refs'][0] for r in rows]}
    snapshot={'run_id':'pa-regression','trade_date':'2026-09-28','input_snapshot_ids':{},'source_refs':[]}
    result=enrich_cross_asset_snapshot(snapshot,storage_root=tmp_path,collector=lambda **kw:observed,db_session=warehouse_db)
    assert 'daily_research' not in snapshot
    assert all(v['status']=='available' for v in build_price_action(result)['timeframes'].values())
    assert (tmp_path/result['input_snapshot_ids']['tradingview_cross_asset']).is_file()


@pytest.mark.parametrize('source_available', [True, False])
def test_post_research_refresh_replaces_only_expired_bars_with_lineage(monkeypatch, tmp_path, source_available, warehouse_db):
    import json
    import apps.worker.execution_research as module
    later = '2026-09-28T10:56:30+00:00'

    class Clock:
        @staticmethod
        def now(tz): return datetime.fromisoformat(later)

    monkeypatch.setattr(module, 'datetime', Clock)
    existing = merge([series(s) for s in (900, 3600, 14400)])
    snapshot = {'run_id': 'refresh', 'trade_date': '2026-09-28', 'snapshot_time': later,
                'daily_research': {'execution_timeframes': existing},
                'input_snapshot_ids': {}, 'source_refs': []}
    before = deepcopy(snapshot)
    calls = []

    def collector(**kwargs):
        calls.append(kwargs['resolution'])
        row = series()
        row['retrieved_at'] = later
        row['source_refs'][0].update(retrieved_at=later, raw_path='raw/refreshed.json')
        for bar in row['bars']:
            bar['time'] = (datetime.fromisoformat(bar['time']) + timedelta(minutes=15)).isoformat()
        if not source_available:
            row.update(status='unavailable', error='TimeoutError', bars=[])
        return {'series': [row], 'source_refs': row['source_refs'], 'parsed_path': 'parsed/refreshed.json'}

    result = module.refresh_execution_snapshot(snapshot, storage_root=tmp_path, collector=collector, db_session=warehouse_db)
    assert snapshot == before
    assert calls == ['15']
    frames = result['daily_research']['execution_timeframes']['timeframes']
    assert frames['1h'] == existing['timeframes']['1h']
    assert frames['4h'] == existing['timeframes']['4h']
    pa = build_price_action(result)['timeframes']['15m']
    assert pa['status'] == ('available' if source_available else 'unavailable')
    if source_available:
        assert pa['latest_bar_time'] == '2026-09-28T10:45:00+00:00'
        assert pa['source_refs'][0]['raw_path'] == 'raw/refreshed.json'
    else:
        assert frames['15m']['retrieved_at'] == AS_OF
        assert result['daily_research']['execution_timeframes']['fallback_diagnostics']['15m'] == 'TimeoutError'
    archived = json.loads((tmp_path/result['input_snapshot_ids']['execution_refresh']).read_text())
    assert archived['execution_timeframes'] == result['daily_research']['execution_timeframes']
    assert archived['source_refs'][0] in result['source_refs']


def test_post_research_refresh_does_not_collect_when_all_frames_are_fresh(monkeypatch, tmp_path):
    import apps.worker.execution_research as module

    class Clock:
        @staticmethod
        def now(tz): return datetime.fromisoformat(AS_OF)

    monkeypatch.setattr(module, 'datetime', Clock)
    snapshot = {'trade_date': '2026-09-28', 'snapshot_time': AS_OF,
                'daily_research': {'execution_timeframes': merge([series(s) for s in (900, 3600, 14400)])}}

    def collector(**kwargs):
        pytest.fail('fresh frames must not trigger additional collection')

    assert module.refresh_execution_snapshot(snapshot, storage_root=tmp_path, collector=collector) == snapshot
