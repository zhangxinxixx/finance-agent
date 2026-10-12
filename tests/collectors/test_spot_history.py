from datetime import UTC, datetime
from types import SimpleNamespace

from apps.collectors.technical.spot_history import collect_spot_history
import pytest


def test_only_completed_weekday_spot_bars_are_collected(monkeypatch, tmp_path):
    def bar(day):
        return SimpleNamespace(open_time=datetime(2026,9,day,tzinfo=UTC),open=10,high=12,low=9,close=11)
    result = SimpleNamespace(candles=[bar(6),bar(5),bar(4),bar(3)], retrieved_at=datetime(2026,9,6,12,tzinfo=UTC),raw_path='raw/market/test.json',source_ref=lambda:{'source_role':'validation_and_fallback'})
    monkeypatch.setattr('apps.collectors.technical.spot_history.TwelveDataClient',lambda **kwargs:SimpleNamespace(fetch_time_series=lambda **kwargs: result))
    output = collect_spot_history(retrieved_date='2026-09-05',storage_root=tmp_path)
    assert [point.date for point in output.points] == ['2026-09-03','2026-09-04']
    assert output.source_refs[0]['notes']['quote_time'] == '2026-09-05T00:00:00+00:00'
    assert output.source_refs[0]['source_role'] == 'validation_and_fallback'


def test_optional_quote_and_execution_timeframes_preserve_provider_times(monkeypatch, tmp_path):
    retrieved_at = datetime(2026, 9, 8, 12, 30, tzinfo=UTC)

    def bar(minute, close):
        return SimpleNamespace(
            open_time=datetime(2026, 9, 8, 12, minute, tzinfo=UTC),
            open=close - .1, high=close + .2, low=close - .2, close=close,
        )

    daily = SimpleNamespace(
        candles=[SimpleNamespace(open_time=datetime(2026, 9, 7, tzinfo=UTC), open=4400, high=4450, low=4380, close=4430)],
        retrieved_at=retrieved_at, raw_path='raw/daily.json',
        source_ref=lambda: {'source_role': 'validation_and_fallback'},
    )
    intraday = {
        '5min': SimpleNamespace(candles=[bar(0, 100), bar(5, 101), bar(10, 102), bar(15, 103), bar(20, 104), bar(25, 105)], retrieved_at=retrieved_at, raw_path='raw/5m.json', credits_used=1, credits_left=7, timeframe='5m'),
        '15min': SimpleNamespace(candles=[bar(0, 100), bar(5, 101), bar(10, 102)], retrieved_at=retrieved_at, raw_path='raw/15m.json', credits_used=1, credits_left=7, timeframe='15m'),
        '1h': SimpleNamespace(candles=[bar(0, 100), bar(5, 101), bar(10, 102)], retrieved_at=retrieved_at, raw_path='raw/1h.json', credits_used=1, credits_left=7, timeframe='1h'),
        '4h': SimpleNamespace(candles=[bar(0, 100), bar(5, 101), bar(10, 102)], retrieved_at=retrieved_at, raw_path='raw/4h.json', credits_used=1, credits_left=7, timeframe='4h'),
    }

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def fetch_time_series(self, *, interval, outputsize):
            return daily if interval == '1day' else intraday[interval]

    monkeypatch.setattr('apps.collectors.technical.spot_history.TwelveDataClient', FakeClient)
    quote_call = {}

    def fake_quote(**kwargs):
        quote_call.update(kwargs)
        return ({
            'price': 4433.5, 'price_time': '2026-09-08T12:29:00+00:00',
            'instrument_type': 'spot', 'timezone': 'UTC', 'delay': 'provider_quote_timestamp',
            'status': 'verified', 'source_refs': [{'source': 'quote', 'raw_path': 'raw/quote.json'}],
        }, {'source': 'quote', 'raw_path': 'raw/quote.json'})

    monkeypatch.setattr('apps.collectors.technical.spot_history._collect_quote', fake_quote)
    output = collect_spot_history(
        retrieved_date='2026-09-08', storage_root=tmp_path,
        include_quote=True, include_intraday=True, intraday_outputsize=20,
        clock=lambda: datetime(2026, 9, 8, 12, 31, tzinfo=UTC),
    )
    notes = output.source_refs[0]['notes']
    assert notes['spot_anchor']['status'] == 'verified'
    assert notes['spot_anchor']['price_time'] == '2026-09-08T12:29:00+00:00'
    assert quote_call['retrieved_at'] == datetime(2026, 9, 8, 12, 31, tzinfo=UTC)
    assert set(notes['execution_timeframes']) == {'4h', '1h', '15m', '5m'}
    assert notes['execution_timeframes']['5m']['latest_closed_time'] == '2026-09-08T12:25:00+00:00'
    frame = notes['execution_timeframes']['15m']
    assert frame['ticker'] == 'XAUUSD' and frame['unit'] == 'USD/oz'
    ref = frame['source_refs'][0]
    assert ref['source'] == 'twelvedata_xauusd_15m'
    assert ref['raw_path'] == frame['raw_path'] == 'raw/15m.json'
    assert ref['retrieved_at'] == frame['retrieved_at'] == retrieved_at.isoformat()
    assert ref['instrument_type'] == 'spot' and ref['provider_symbol'] == 'XAU/USD'


def test_execution_timeframe_provider_errors_use_safe_reason(monkeypatch, tmp_path):
    retrieved_at = datetime(2026, 9, 8, 12, 30, tzinfo=UTC)
    daily = SimpleNamespace(
        candles=[SimpleNamespace(
            open_time=datetime(2026, 9, 7, tzinfo=UTC), open=4400, high=4450, low=4380, close=4430,
        )],
        retrieved_at=retrieved_at, raw_path='raw/daily.json',
        source_ref=lambda: {'source_role': 'validation_and_fallback'},
    )

    class FailingClient:
        def __init__(self, **kwargs):
            pass

        def fetch_time_series(self, *, interval, outputsize):
            if interval == '1day':
                return daily
            raise RuntimeError('provider key=SECRET https://private.example/request')

    monkeypatch.setattr('apps.collectors.technical.spot_history.TwelveDataClient', FailingClient)
    output = collect_spot_history(
        retrieved_date='2026-09-08', storage_root=tmp_path, include_intraday=True,
    )
    execution = output.source_refs[0]['notes']['execution_timeframes']
    assert all(item['error_type'] == 'RuntimeError' for item in execution.values())
    assert all(item['reason'] == 'provider_request_failed' for item in execution.values())
    assert 'SECRET' not in str(execution)


def test_quote_archive_uses_response_received_time(monkeypatch, tmp_path):
    import json
    import apps.collectors.technical.spot_history as module

    sent = datetime(2026, 9, 8, 12, 29, tzinfo=UTC)
    received = datetime(2026, 9, 8, 12, 30, tzinfo=UTC)
    quoted = datetime(2026, 9, 8, 12, 29, 30, tzinfo=UTC)
    response = SimpleNamespace(status_code=200, json=lambda: {"close": "4400", "last_quote_at": quoted.timestamp()})

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, *args, **kwargs):
            return response

    monkeypatch.setattr(module, "resolve_runtime_secret", lambda key: "fixture-key")
    monkeypatch.setattr(module.httpx, "Client", Client)
    anchor, ref = module._collect_quote(storage_root=tmp_path, retrieved_at=sent, clock=lambda: received)
    assert anchor["status"] == "verified"
    assert ref["retrieved_at"] == received.isoformat()
    raw = json.loads((tmp_path / ref["raw_path"]).read_text())
    assert "fixture-key" not in json.dumps(raw)


@pytest.mark.parametrize("daily_failure", [True, False])
def test_daily_failure_or_empty_history_does_not_skip_intraday(monkeypatch, tmp_path, daily_failure):
    from datetime import timedelta
    from apps.features.research.daily import _extract_execution_timeframes
    captured = datetime(2026, 9, 28, 12, 31, tzinfo=UTC)
    calls = []
    seconds = {'4h': 14400, '1h': 3600, '15min': 900, '5min': 300}

    class Client:
        def __init__(self, **kwargs):
            pass

        def fetch_time_series(self, *, interval, outputsize):
            calls.append(interval)
            if interval == '1day':
                if daily_failure:
                    raise RuntimeError('secret provider details')
                return SimpleNamespace(candles=[], retrieved_at=captured, source_ref=lambda: {})
            step = seconds[interval]
            end = datetime(2026, 9, 28, 12, tzinfo=UTC)
            candles = [SimpleNamespace(open_time=end-timedelta(seconds=step*i),
                       open=100, high=102, low=99, close=101) for i in range(6, 0, -1)]
            return SimpleNamespace(candles=candles, retrieved_at=captured, raw_path=f'raw/{interval}.json',
                                   timeframe={'15min':'15m', '5min':'5m'}.get(interval, interval),
                                   credits_used=1, credits_left=5)

    monkeypatch.setattr('apps.collectors.technical.spot_history.TwelveDataClient', Client)
    out = collect_spot_history(retrieved_date='2026-09-28', storage_root=tmp_path,
                               include_intraday=True, clock=lambda: captured)
    assert calls == ['1day', '4h', '1h', '15min', '5min']
    assert not out.points and out.unavailable_symbols == ['XAUUSD']
    assert 'secret' not in str(out.source_refs)
    execution = _extract_execution_timeframes(
        {'snapshot_time': captured.isoformat(), 'source_refs': out.source_refs}, {'status':'unavailable'})
    assert execution['status'] == 'available'
    assert execution['timeframes']['4h']['bar_count'] == 6
    assert execution['timeframes']['1h']['raw_path'] == 'raw/1h.json'
