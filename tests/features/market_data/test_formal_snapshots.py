from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta

import pytest

from apps.features.market_data.formal_snapshots import (
    FormalMarketObservation,
    FormalSourceReference,
    MarketPriceSnapshot,
    build_market_price_snapshot,
    build_oil_snapshot,
)


AS_OF = datetime(2026, 7, 20, 21, 0, tzinfo=UTC)


def _bar(*, asset: str, timeframe: str, source: str, open_time: datetime, source_ref: dict, price: float = 100.0) -> dict:
    duration = timedelta(minutes=5) if timeframe == "5m" else timedelta(days=1)
    return {
        "asset": asset, "timeframe": timeframe, "source": source, "source_ref": source_ref,
        "open_time": open_time, "close_time": open_time + duration,
        "open": price, "high": price + 2, "low": price - 1, "close": price + 1,
        "raw_path": f"raw/{asset}/{source}.json", "retrieved_at": (open_time + duration).isoformat(),
    }


def _spot_bar(open_time: datetime) -> dict:
    return _bar(asset="XAUUSD", timeframe="5m", source="jin10_mcp_derived_5m", open_time=open_time, source_ref={"provider_symbol": "XAUUSD", "instrument_type": "otc_spot_quote_proxy", "source_role": "market_primary", "source_url": "https://example.test/xau"}, price=2400)


def _gc_bar(open_time: datetime) -> dict:
    return _bar(asset="GC", timeframe="1d", source="yahoo_finance_gc_f", open_time=open_time, source_ref={"provider_symbol": "GC=F", "instrument_type": "futures_continuous_proxy", "source_role": "futures_continuous_proxy"}, price=2410)


def _oil_bar(asset: str, open_time: datetime) -> dict:
    return _bar(asset=asset, timeframe="1d", source="ice_settlement", open_time=open_time, source_ref={"provider_symbol": asset, "instrument_type": "futures_settlement", "source_role": "oil_primary"}, price=75)


def test_market_snapshot_accepts_spot_5m_and_distinct_gc_daily_bar() -> None:
    snapshot = build_market_price_snapshot(candidates=[_spot_bar(AS_OF - timedelta(minutes=10)), _gc_bar(AS_OF - timedelta(days=2))], as_of=AS_OF)

    assert snapshot.schema_version == "market_price_snapshot.v1"
    assert snapshot.readiness == "ready"
    assert snapshot.xauusd_spot.value == snapshot.xauusd_spot.close
    assert snapshot.xauusd_spot.market_role == "spot"
    assert snapshot.gc_futures.market_role == "futures"
    assert snapshot.xauusd_spot.source_refs[0].raw_path


def test_gc_futures_cannot_fill_xauusd_spot() -> None:
    snapshot = build_market_price_snapshot(candidates=[_gc_bar(AS_OF - timedelta(days=2))], as_of=AS_OF)

    assert snapshot.xauusd_spot.value is None
    assert snapshot.xauusd_spot.quality_status == "blocked"
    assert snapshot.gc_futures.value is not None
    assert snapshot.readiness == "blocked"


def test_xauusd_canonical_primary_wins_over_same_bar_fallback() -> None:
    open_time = AS_OF - timedelta(minutes=10)
    primary = _spot_bar(open_time)
    fallback = copy.deepcopy(primary)
    fallback["source"] = "twelvedata_xauusd_5m"
    fallback["source_ref"]["source_role"] = "fallback"
    fallback["close"] = 2399.0
    snapshot = build_market_price_snapshot(
        candidates=[fallback, primary, _gc_bar(AS_OF - timedelta(days=2))],
        as_of=AS_OF,
    )

    assert snapshot.xauusd_spot.quality_status == "accepted"
    assert snapshot.xauusd_spot.source_refs[0].source == "jin10_mcp_derived_5m"


def test_oil_snapshot_accepts_explicit_wti_and_brent_daily_bars() -> None:
    snapshot = build_oil_snapshot(candidates=[_oil_bar("WTI", AS_OF - timedelta(days=2)), _oil_bar("BRENT", AS_OF - timedelta(days=2))], as_of=AS_OF)

    assert snapshot.schema_version == "oil_snapshot.v1"
    assert snapshot.readiness == "ready"
    assert snapshot.wti.value == 76.0
    assert snapshot.brent.value == 76.0


def test_missing_oil_is_explicitly_blocked_with_query_lineage() -> None:
    snapshot = build_oil_snapshot(candidates=[], as_of=AS_OF)

    assert snapshot.readiness == "blocked"
    for item in (snapshot.wti, snapshot.brent):
        assert (item.value, item.open, item.high, item.low, item.close, item.bar_open_time, item.bar_close_time) == (None,) * 7
        assert (item.freshness_status, item.quality_status, item.alignment_status) == ("missing", "blocked", "unknown")
        assert item.source_refs[0].reference.startswith("query://")


def test_rejected_supplemental_oil_and_future_or_incomplete_bars_fail_closed() -> None:
    supplemental = _oil_bar("WTI", AS_OF - timedelta(days=2))
    supplemental["source_ref"]["source_role"] = "supplemental_source"
    future = _oil_bar("BRENT", AS_OF)
    snapshot = build_oil_snapshot(candidates=[supplemental, future], as_of=AS_OF)

    assert snapshot.wti.quality_status == "blocked"
    assert snapshot.brent.quality_status == "blocked"
    assert snapshot.brent.alignment_status == "misaligned"
    assert snapshot.readiness == "blocked"


def test_stale_validation_source_is_observe_and_daily_weekend_window_is_fresh() -> None:
    wti = _oil_bar("WTI", AS_OF - timedelta(days=5))
    wti["source_ref"]["source_role"] = "validation"
    brent = _oil_bar("BRENT", AS_OF - timedelta(days=3))
    snapshot = build_oil_snapshot(candidates=[wti, brent], as_of=AS_OF)

    assert snapshot.wti.freshness_status == "stale"
    assert snapshot.wti.quality_status == "observe"
    assert snapshot.brent.freshness_status == "fresh"
    assert snapshot.readiness == "observe"


def test_ambiguous_latest_provider_is_blocked_and_input_is_unchanged() -> None:
    first = _oil_bar("WTI", AS_OF - timedelta(days=2))
    second = copy.deepcopy(first)
    second["source"] = "nymex_settlement"
    candidates = [first, second, _oil_bar("BRENT", AS_OF - timedelta(days=2))]
    before = copy.deepcopy(candidates)
    results = [build_oil_snapshot(candidates=candidates, as_of=AS_OF) for _ in range(100)]

    assert results[0].wti.quality_status == "blocked"
    assert results[0].wti.alignment_status == "misaligned"
    assert len({item.model_dump_json() for item in results}) == 1
    assert candidates == before


def test_ancient_daily_bar_is_present_but_quality_blocked_after_observe_max_age() -> None:
    snapshot = build_oil_snapshot(candidates=[_oil_bar("WTI", AS_OF - timedelta(days=8)), _oil_bar("BRENT", AS_OF - timedelta(days=2))], as_of=AS_OF)

    assert snapshot.wti.value is not None
    assert snapshot.wti.freshness_status == "stale"
    assert snapshot.wti.quality_status == "blocked"
    assert snapshot.readiness == "blocked"


def test_present_candidate_without_real_retrieval_time_is_blocked() -> None:
    wti = _oil_bar("WTI", AS_OF - timedelta(days=2))
    wti.pop("retrieved_at")
    snapshot = build_oil_snapshot(candidates=[wti, _oil_bar("BRENT", AS_OF - timedelta(days=2))], as_of=AS_OF)

    assert snapshot.wti.value is None
    assert snapshot.wti.quality_status == "blocked"
    assert snapshot.wti.source_refs[0].qualification_reason == "retrieval_time_missing"


def test_future_retrieval_time_is_misaligned_and_blocked() -> None:
    wti = _oil_bar("WTI", AS_OF - timedelta(days=2))
    wti["retrieved_at"] = (AS_OF + timedelta(minutes=1)).isoformat()
    snapshot = build_oil_snapshot(
        candidates=[wti, _oil_bar("BRENT", AS_OF - timedelta(days=2))],
        as_of=AS_OF,
    )

    assert snapshot.wti.value is None
    assert snapshot.wti.alignment_status == "misaligned"
    assert snapshot.wti.source_refs[0].qualification_reason == "retrieval_time_after_as_of"


def test_invalid_ohlc_is_rejected_before_contract_construction() -> None:
    wti = _oil_bar("WTI", AS_OF - timedelta(days=2))
    wti["low"] = 77.0
    snapshot = build_oil_snapshot(candidates=[wti, _oil_bar("BRENT", AS_OF - timedelta(days=2))], as_of=AS_OF)

    assert snapshot.wti.value is None
    assert snapshot.wti.source_refs[0].qualification_reason == "ohlc_invalid"


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_prices_are_rejected(invalid: float) -> None:
    wti = _oil_bar("WTI", AS_OF - timedelta(days=2))
    wti["close"] = invalid
    snapshot = build_oil_snapshot(
        candidates=[wti, _oil_bar("BRENT", AS_OF - timedelta(days=2))],
        as_of=AS_OF,
    )

    assert snapshot.wti.value is None
    assert snapshot.wti.source_refs[0].qualification_reason == "ohlc_missing"


def test_explicit_wrong_bar_duration_is_rejected() -> None:
    wti = _oil_bar("WTI", AS_OF - timedelta(days=2))
    wti["close_time"] = wti["open_time"] + timedelta(hours=23)
    snapshot = build_oil_snapshot(
        candidates=[wti, _oil_bar("BRENT", AS_OF - timedelta(days=2))],
        as_of=AS_OF,
    )

    assert snapshot.wti.value is None
    assert snapshot.wti.source_refs[0].qualification_reason == "bar_duration_mismatch"


def test_contract_rejects_incomplete_present_bar_and_wrong_market_snapshot_identity() -> None:
    source_ref = FormalSourceReference(source="fixture", reference="fixture://bar", retrieved_at=AS_OF, qualification_reason="fixture", normalized_role="market_primary")
    with pytest.raises(ValueError, match="complete OHLC"):
        FormalMarketObservation(series_id="WTI", asset="WTI", market_role="oil", timeframe="1d", value=75.0, open=75.0, high=76.0, low=74.0, close=75.0, bar_open_time=None, bar_close_time=AS_OF, expected_frequency="1d", freshness_status="fresh", quality_status="accepted", alignment_status="aligned", source_refs=(source_ref,))

    wrong = FormalMarketObservation(series_id="WTI", asset="WTI", market_role="oil", timeframe="1d", value=None, open=None, high=None, low=None, close=None, bar_open_time=None, bar_close_time=None, expected_frequency="1d", freshness_status="missing", quality_status="blocked", alignment_status="unknown", source_refs=(source_ref,))
    with pytest.raises(ValueError, match="XAUUSD_SPOT/XAUUSD/spot/5m"):
        MarketPriceSnapshot(as_of=AS_OF, readiness="blocked", xauusd_spot=wrong, gc_futures=wrong)


def test_contract_rejects_declared_readiness_that_disagrees_with_observations() -> None:
    snapshot = build_market_price_snapshot(candidates=[], as_of=AS_OF)
    with pytest.raises(ValueError, match="readiness must be blocked"):
        MarketPriceSnapshot(
            as_of=AS_OF,
            readiness="ready",
            xauusd_spot=snapshot.xauusd_spot,
            gc_futures=snapshot.gc_futures,
        )


def test_naive_as_of_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        build_oil_snapshot(candidates=[], as_of=datetime(2026, 7, 20, 21, 0))
