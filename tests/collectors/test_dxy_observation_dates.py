from datetime import UTC, datetime

import httpx

from apps.collectors.dxy.collector import _collect_from_cnbc, _collect_from_tradingview


def test_performance_is_not_fabricated_dated_history(monkeypatch, tmp_path):
    timestamp = int(datetime(2026,9,4,tzinfo=UTC).timestamp())
    monkeypatch.setattr(httpx.Client,'post',lambda self,url,**kwargs:httpx.Response(200,json={'data':[{'d':[99.1,1,2,'DXY',timestamp]}]},request=httpx.Request('POST',url)))
    result = _collect_from_tradingview(retrieved_date='2026-09-06',storage_root=tmp_path)
    assert len(result.points) == 1
    assert result.points[0].date == '2026-09-04'
    assert result.source_refs[0]['weekly_performance_pct'] == 1
    assert (tmp_path/result.points[0].raw_path).exists()


def test_cnbc_previous_close_is_emitted_with_explicit_provenance(monkeypatch, tmp_path):
    payload = {
        'QuickQuoteResult': {
            'QuickQuote': [{
                'symbol': '.DXY',
                'last': '99.157',
                'reg_last_time': '2026-09-04T16:59:59.000-0400',
                'previous_day_closing': '98.908',
                'change': '0.249',
            }],
        },
    }
    monkeypatch.setattr(
        httpx.Client,
        'get',
        lambda self, url, **kwargs: httpx.Response(
            200,
            json=payload,
            request=httpx.Request('GET', url),
        ),
    )

    result = _collect_from_cnbc(retrieved_date='2026-09-06', storage_root=tmp_path)

    assert [point.date for point in result.points] == ['2026-09-04']
    assert [point.value for point in result.points] == [99.157]
    assert result.source_refs[0]['previous_close_field'] == 'previous_day_closing'
    assert result.source_refs[0]['previous_observation_date'] is None
    assert float(result.source_refs[0]['previous_close']) == 98.908
    assert float(result.source_refs[0]['reported_daily_change']) == 0.249
    assert result.source_refs[0]['history_points'] == '1'
    assert all(point.source == 'cnbc' for point in result.points)


def test_cnbc_does_not_promote_conflicting_previous_close(monkeypatch, tmp_path):
    payload = {
        'QuickQuoteResult': {
            'QuickQuote': [{
                'symbol': '.DXY',
                'last': '99.157',
                'reg_last_time': '2026-09-04T16:59:59.000-0400',
                'previous_day_closing': '90.000',
                'change': '0.249',
            }],
        },
    }
    monkeypatch.setattr(
        httpx.Client,
        'get',
        lambda self, url, **kwargs: httpx.Response(
            200,
            json=payload,
            request=httpx.Request('GET', url),
        ),
    )

    result = _collect_from_cnbc(retrieved_date='2026-09-06', storage_root=tmp_path)

    assert len(result.points) == 1
    assert result.points[0].date == '2026-09-04'
    assert result.source_refs[0]['previous_observation_status'] == 'unavailable'
