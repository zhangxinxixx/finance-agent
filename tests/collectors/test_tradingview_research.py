import pytest

from apps.collectors.market.tradingview_research import collect_tradingview_research


def test_targeted_chart_collection_adds_gold_anchor_and_preserves_both_lineages(tmp_path):
    calls = []

    def scanner(**kwargs):
        calls.append(('scanner', kwargs))
        return {'observations': [], 'parsed_path': 'parsed/scanner.json',
                'source_refs': [{'raw_path': 'raw/scanner.json'}]}

    def chart(**kwargs):
        calls.append(('chart', kwargs))
        return {'series': [{'ticker': 'NYMEX:CL1!'}], 'parsed_path': 'parsed/chart.json',
                'source_refs': [{'raw_path': 'raw/chart.json'}]}

    result = collect_tradingview_research(retrieved_date='2026-09-17', storage_root=tmp_path,
                                         symbols=('NYMEX:CL1!',), resolution='1',
                                         scanner_collector=scanner, chart_collector=chart)
    assert calls[0][1]['symbols'] == ('NYMEX:CL1!',)
    assert calls[1][1]['symbols'] == ('OANDA:XAUUSD', 'NYMEX:CL1!')
    assert calls[1][1]['resolution'] == '1'
    assert calls[1][1]['bar_count'] == 256
    assert result['parsed_path'] == 'parsed/scanner.json'
    assert result['chart_parsed_path'] == 'parsed/chart.json'
    assert len(result['source_refs']) == 2


@pytest.mark.parametrize('resolution', ['5', 'D', '', None])
def test_unsupported_period_fails_before_network(tmp_path, resolution):
    def unexpected(**kwargs):
        raise AssertionError('must not reach network')
    with pytest.raises(ValueError):
        collect_tradingview_research(retrieved_date='2026-09-17', storage_root=tmp_path,
                                     resolution=resolution, scanner_collector=unexpected, chart_collector=unexpected)


def test_baseline_fetches_native_gold_execution_frames(tmp_path):
    calls = []
    def chart(**kwargs):
        calls.append(kwargs)
        return {'series':[{'ticker':'OANDA:XAUUSD','resolution':kwargs['resolution']}],
                'parsed_path':f"parsed/{kwargs['resolution']}.json",
                'source_refs':[{'raw_path':f"raw/{kwargs['resolution']}.json"}]}
    result = collect_tradingview_research(
        retrieved_date='2026-09-28', storage_root=tmp_path,
        scanner_collector=lambda **kw: {'observations':[], 'parsed_path':'parsed/scan.json'}, chart_collector=chart)
    assert {r['resolution'] for r in result['execution_chart_series']} == {'15','60','240'}
    assert len(result['chart_series']) == 1
    assert len(result['source_refs']) == 3
    assert all(c['symbols'] == ('OANDA:XAUUSD',) for c in calls if c['resolution'] != '15')
