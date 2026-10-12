import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from apps.collectors.market.tradingview import collect_tradingview
from apps.features.research.cross_asset import build_cross_asset_features
from apps.features.research.production_shadow import apply_production_shadow_features
from apps.features.research.source_health import build_core_source_health
from apps.parsers.market.tradingview import parse_tradingview
from apps.renderer.markdown.gold_reader import cross_asset_table, etf_window_table
from apps.worker.cross_asset_research import enrich_cross_asset_snapshot

FIXTURE = Path('tests/fixtures/research/tradingview_cross_asset.json')
AS_OF = '2026-09-10T15:53:00+00:00'


def parsed(payload=None):
    return parse_tradingview(payload or json.loads(FIXTURE.read_text()), retrieved_at=AS_OF,
                            source_ref={'source': 'tradingview_cross_asset', 'raw_path': 'raw/test.json'})


def test_delayed_oil_not_promoted_to_fresh_using_capture_or_daily_time():
    data = parsed()
    original = deepcopy(data)
    result = build_cross_asset_features(data, as_of=AS_OF)
    rows = {r['symbol']: r for r in result['observations']}
    assert rows['WTI']['ticker'] == 'NYMEX:CL1!'
    assert rows['WTI']['delay_seconds'] == 600
    assert rows['WTI']['quote_time'] is None
    assert rows['WTI']['freshness'] == 'DELAYED_CLOCK_UNVERIFIED'
    assert rows['WTI']['display_value'] == 100.68
    assert result['analysis_capability']['energy_regime_analysis'] == 'DEGRADED'
    assert result['critical_freshness_failures'] == ['ENERGY_INTRADAY']
    assert rows['US02Y']['freshness'] == 'FRESH_MINUTE_BAR'
    assert rows['US03M']['freshness'] == 'STALE_BAR'
    assert result['curves'][0]['value_bp'] is None
    assert result['curves'][1]['value_bp'] == pytest.approx(38.9)
    assert not result['synchronous_event_attribution_allowed']
    assert data == original


@pytest.mark.parametrize(('field','value'), [(0, float('nan')), (0, True), (3, 'cfd'), (4, 'GBEBROKERS'), (5, 'EUR')])
def test_invalid_price_or_instrument_fails_closed(field, value):
    data = json.loads(FIXTURE.read_text())
    data['data'][0]['d'][field] = value
    result = build_cross_asset_features(parsed(data), as_of=AS_OF)
    assert result['observations'][0]['freshness'] == 'INVALID'
    assert result['observations'][0]['display_value'] is None


def test_duplicate_and_missing_rows_and_unknown_provider_are_not_substitutes():
    data = json.loads(FIXTURE.read_text())
    data['data'].append(deepcopy(data['data'][0]))
    data['data'][1]['s'] = 'GBEBROKERS:USOIL'
    result = parsed(data)
    assert result['observations'][0]['status'] == 'invalid'
    assert result['observations'][1]['status'] == 'missing'


def test_future_time_stale_capture_and_unverified_delay():
    data = parsed()
    data['observations'][2]['minute_bar_time'] = '2026-09-11T00:00:00+00:00'
    data['observations'][3]['delay_seconds'] = None
    result = build_cross_asset_features(data, as_of=AS_OF)
    assert result['observations'][2]['freshness'] == 'INVALID_TIME'
    assert result['observations'][3]['freshness'] == 'DELAY_UNVERIFIED'
    stale = build_cross_asset_features(parsed(), as_of='2026-09-10T16:20:00+00:00')
    assert all(r['freshness'] == 'STALE_CAPTURE' for r in stale['observations'])
    assert all(c['value_bp'] is None for c in stale['curves'])


def test_same_age_but_different_curve_windows_do_not_align():
    data = parsed()
    data['observations'][4]['minute_bar_time'] = '2026-09-10T15:45:00+00:00'
    result = build_cross_asset_features(data, as_of=AS_OF)
    assert result['observations'][4]['freshness'] == 'FRESH_MINUTE_BAR'
    assert result['curves'][0]['value_bp'] is None


def test_raw_parsed_and_feature_lineage_and_input_protection(tmp_path, warehouse_db):
    requests = []
    def response(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=json.loads(FIXTURE.read_text()))
    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        data = collect_tradingview(retrieved_date='2026-09-10', storage_root=tmp_path, client=client)
    assert 'NYMEX:CL1!' in requests[0]['symbols']['tickers']
    assert not any('USOIL' in x for x in requests[0]['symbols']['tickers'])
    raw = json.loads((tmp_path / data['source_refs'][0]['raw_path']).read_text())
    assert raw['response'] == json.loads(FIXTURE.read_text())
    assert json.loads((tmp_path / data['parsed_path']).read_text())['observations'] == data['observations']
    source = {'trade_date':'2026-09-10', 'run_id':'tv-test', 'source_refs':[], 'input_snapshot_ids':{},
              'macro': {'official_real_yield': 2.46}}
    original = deepcopy(source)
    result = enrich_cross_asset_snapshot(source, storage_root=tmp_path, collector=lambda **kwargs:data, db_session=warehouse_db)
    assert source == original
    assert result['macro'] == source['macro']
    saved = json.loads((tmp_path/result['input_snapshot_ids']['tradingview_cross_asset']).read_text())
    assert saved == result['tradingview_cross_asset']


def test_targeted_collector_requests_only_agent_selected_symbol(tmp_path):
    requests = []
    payload = {"totalCount": 1, "data": [{"s": "TVC:SILVER", "d": [51.2, 1788991200,
        "streaming", "commodity", "TVC", "USD", "Silver", 1.2, 0.6,
        51.19, 1789055520, "market"]}]}

    def response(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=payload)

    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        result = collect_tradingview(retrieved_date='2026-09-10', storage_root=tmp_path,
                                     client=client, symbols=('TVC:SILVER',))
    assert requests[0]['symbols']['tickers'] == ['TVC:SILVER']
    assert len(result['observations']) == 1
    assert result['observations'][0]['symbol'] == 'SILVER_SPOT_PROXY'
    assert result['observations'][0]['status'] == 'available'


def test_collector_failure_is_archived_without_secret_error(tmp_path):
    def response(request):
        raise httpx.ConnectError('secret must not escape')
    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        result = collect_tradingview(retrieved_date='2026-09-10', storage_root=tmp_path, client=client)
    assert result['error'] == 'tradingview_collection_failed:ConnectError'
    assert 'secret' not in json.dumps(result)
    assert all(r['status'] == 'missing' for r in result['observations'])


def test_live_source_health_and_quality_gate_surface_energy_failure():
    from tests.analysis.test_daily_research import _snapshot
    from apps.features.research.workflow import build_gold_workflow
    snapshot = _snapshot()
    snapshot['snapshot_time'] = AS_OF
    snapshot['tradingview_cross_asset'] = build_cross_asset_features(parsed(), as_of=AS_OF)
    flow = apply_production_shadow_features(snapshot, build_gold_workflow(snapshot))
    assert any(c['id'] == 'Q12' and not c['passed'] for c in flow['quality_gate']['checks'])
    assert not flow['quality_gate']['strong_direction_allowed']
    health = build_core_source_health(snapshot)
    oil = next(x for x in health['items'] if x['source_key'] == 'tv_wti')
    assert oil['source_type'] == 'secondary_market_data'
    assert oil['critical_freshness_failure'] == 'ENERGY_INTRADAY'
    assert oil['source_health'] == 'FAILED'
    assert not health['production_ready']


def test_reader_preserves_clock_uncertainty_and_etf_window():
    text = cross_asset_table(build_cross_asset_features(parsed(), as_of=AS_OF))
    assert 'NYMEX:CL1!' in text and '600秒' in text and 'ENERGY_INTRADAY' in text
    assert '延迟，精确报价时点未验证' in text
    window = etf_window_table({'shares_weekly_anchor_date':'2026-09-02', 'shares_weekly_anchor_value':370300000,
                              'shares_reported_on':'2026-09-09', 'shares_outstanding':368200000, 'shares_weekly_delta':-2100000})
    assert '2026-09-02 / 370,300,000' in window
    assert '2026-09-09 / 368,200,000' in window
