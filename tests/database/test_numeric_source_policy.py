from datetime import UTC, datetime, timedelta
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from database.models.analysis import MarketCandle, ensure_analysis_tables
from database.numeric_source_policy import is_formal_numeric_source
from database.queries.market import upsert_market_candle, list_market_candles, list_completed_market_candles, list_market_candles_by_assets
from apps.features.market_data import select_canonical_xauusd_rows, aggregate_complete_candles, merge_candle_series
from apps.features.market_data.source_role_policy import qualify_market_source


_LEGACY_TWELVEDATA_SOURCE = "twelvedata_xauusd_15m"
_LEGACY_TWELVEDATA_PATH = "raw/market/twelvedata/2026-09-02/XAU-USD-15min.json"


def _legacy_twelvedata_ref(**changes):
    ref = {
        "provider": "twelve_data",
        "source_key": "twelvedata_xauusd",
        "source_role": "fallback",
        "quality_status": "accepted_fallback",
        "fallback_reason": "jin10_incomplete_or_stale",
        "instrument_type": "composite_otc_spot_proxy",
        "provider_symbol": "XAU/USD",
        "provider_timeframe": "15min",
        "volume_semantics": "unavailable",
        "raw_path": _LEGACY_TWELVEDATA_PATH,
    }
    ref.update(changes)
    return ref


@pytest.mark.parametrize("wrapper", [lambda ref: ref, lambda ref: [ref], lambda ref: (ref, None)])
def test_exact_legacy_twelvedata_diagnostic_is_allowed_without_promoting_fallback(wrapper):
    from copy import deepcopy
    from database.numeric_source_policy import quarantine_numeric_payload

    ref = _legacy_twelvedata_ref()
    original = deepcopy(ref)
    assert is_formal_numeric_source(
        _LEGACY_TWELVEDATA_SOURCE,
        wrapper(ref),
        _LEGACY_TWELVEDATA_PATH,
    )
    quality = qualify_market_source(
        asset="XAUUSD",
        source=_LEGACY_TWELVEDATA_SOURCE,
        source_ref=ref,
    )
    assert (quality.quality_status, quality.reason_code, quality.normalized_role) == (
        "observe",
        "twelvedata_validation_or_fallback",
        "validation_fallback",
    )
    payload = {
        "source": _LEGACY_TWELVEDATA_SOURCE,
        "source_ref": ref,
        "raw_path": _LEGACY_TWELVEDATA_PATH,
        "close": 4000.0,
    }
    assert quarantine_numeric_payload(payload) == payload
    assert ref == original


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("source", "jin10"),
        ("provider", "jin10"),
        ("source_key", "jin10_mcp"),
        ("source_url", "https://jin10.com/price"),
        ("raw_path", "raw/jin10/old.json"),
        ("upstream", {"source": "jin10"}),
        ("components", [{"provider": "金十"}]),
        ("component_source_refs", [{"source_url": "https://jin10.com/api"}]),
        ("fallback_reason", "derived_from_jin10"),
        ("fallback_reason", {"source": "jin10"}),
        ("fallback_reason", "jin10_incomplete_or_stale "),
        ("fallback_reason", "JIN10_INCOMPLETE_OR_STALE"),
        ("provider", "unknown"),
        ("source_key", "twelvedata_xauusd_jin10"),
        ("history", {"source_refs": [{"source": "jin10"}]}),
    ],
)
def test_legacy_diagnostic_does_not_mask_real_lineage_or_unknown_text(key, value):
    ref = _legacy_twelvedata_ref(**{key: value})
    assert not is_formal_numeric_source(
        _LEGACY_TWELVEDATA_SOURCE,
        ref,
        _LEGACY_TWELVEDATA_PATH,
    )


@pytest.mark.parametrize(
    ("source", "raw_path"),
    [
        ("jin10_mcp_derived", _LEGACY_TWELVEDATA_PATH),
        (_LEGACY_TWELVEDATA_SOURCE, "raw/jin10/price.json"),
    ],
)
def test_legacy_diagnostic_does_not_override_outer_identity(source, raw_path):
    assert not is_formal_numeric_source(source, _legacy_twelvedata_ref(), raw_path)


@pytest.mark.parametrize('source,ref,path', [
    ('JIN10_quote', {}, None), ('official', {'components': [{'source': 'jin10_mcp'}]}, None),
    ('cache', {'history': {'provider': '金十数据'}}, None),
    ('canonical', {'component_source_refs': [{'source_ref': {'source_url': 'https://mcp.jin10.com'}}]}, None),
    ('official', {}, 'raw/jin10/old.json'),
])
def test_numeric_quarantine_blocks_writes_and_legacy_reads(source, ref, path):
    assert not is_formal_numeric_source(source, ref, path)
    engine = create_engine('sqlite:///:memory:')
    ensure_analysis_tables(engine)
    now = datetime(2026, 10, 9, tzinfo=UTC)
    values = dict(asset='XAUUSD', timeframe='5m', open_time=now, open=2400, high=2402, low=2399, close=2401, source=source, source_ref=ref, raw_path=path)
    with Session(engine) as session:
        with pytest.raises(ValueError, match='jin10_numeric_source_forbidden'):
            upsert_market_candle(session, **values)
        session.add(MarketCandle(**values))  # simulate existing pre-policy history
        session.flush()
        assert list_market_candles(session, asset='XAUUSD', timeframe='5m') == []
        assert list_completed_market_candles(session, asset='XAUUSD', timeframe='5m', as_of=now+timedelta(hours=1), bar_duration=timedelta(minutes=5)) == []
        assert list_market_candles_by_assets(session, assets=['XAUUSD'], timeframe='5m') == []
    assert select_canonical_xauusd_rows([values]) == []
    assert merge_candle_series([values], [values]) == []
    assert aggregate_complete_candles([values], source_timeframe='5m', target_timeframe='5m', source='canonical') == []
    outcome = qualify_market_source(asset='XAUUSD', source=source, source_ref={**ref, 'raw_path': path, 'source_role': 'market_primary'})
    assert outcome.reason_code == 'jin10_numeric_source_forbidden'


@pytest.mark.parametrize('source', ['twelvedata_xauusd_5m', 'fred', 'treasury', 'cme'])
def test_numeric_quarantine_preserves_other_sources(source):
    assert is_formal_numeric_source(source, {'source': source})


@pytest.mark.parametrize('source', ['jin10', 'cache'])
def test_old_snapshot_quarantine_is_repeatable_and_preserves_news(source):
    from copy import deepcopy
    from apps.analysis.snapshots.input_validation import prepare_analysis_inputs

    snapshot = {'snapshot_id': 'old', 'run_id': 'run',
                'macro': {'indicators': {'DXY': {'value': 102, 'source': source,
                    'source_refs': [{'raw_path': 'raw/jin10/dxy.json'}]}}},
                'news': {'headline': '金十新闻', 'source_refs': [{'source': 'jin10'}]},
                'jin10': {'quotes': {'XAUUSD': {'price': 4400}}, 'counts': {'flash_news': 1}}}
    original = deepcopy(snapshot)
    safe = prepare_analysis_inputs(snapshot)
    assert snapshot == original
    assert safe['macro']['indicators']['DXY']['value'] is None
    assert safe['jin10']['quotes'] == {}
    assert safe['news'] == original['news']
    assert safe['input_validation']['can_analyze'] is False
    assert prepare_analysis_inputs(safe) == safe


def test_aggregate_lineage_quarantines_nested_numeric_leaves():
    from database.numeric_source_policy import quarantine_numeric_payload

    raw = {'source': 'cache', 'source_refs': [{'components': [{'provider': 'jin10'}]}],
           'indicators': {'RSI': 52.3, 'XAUUSD': {'price': '4400.5'}}, 'series': [4400, 4401]}
    safe = quarantine_numeric_payload(raw)
    assert safe['indicators']['RSI'] is None
    assert safe['indicators']['XAUUSD']['price'] is None
    assert safe['series'] == [None, None]
    assert safe['source_refs'] == raw['source_refs']
    assert quarantine_numeric_payload(safe) == safe
