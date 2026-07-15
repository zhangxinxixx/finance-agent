from __future__ import annotations

from datetime import UTC, datetime, timedelta

from apps.features.market_data import (
    aggregate_complete_candles,
    merge_candle_series,
    select_canonical_xauusd_rows,
)


def _row(open_time: datetime, *, source: str, price: float, source_ref: dict | None = None) -> dict:
    return {
        "asset": "XAUUSD",
        "timeframe": "1m",
        "open_time": open_time,
        "open": price,
        "high": price + 2,
        "low": price - 1,
        "close": price + 0.5,
        "volume": 12,
        "source": source,
        "source_ref": source_ref or {},
        "raw_path": f"raw/{source}.json",
    }


def test_aggregate_complete_five_minute_rejects_missing_component():
    base = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)
    rows = [_row(base + timedelta(minutes=index), source="jin10_mcp_kline_1m", price=4000 + index) for index in range(5)]

    complete = aggregate_complete_candles(
        rows,
        source_timeframe="1m",
        target_timeframe="5m",
        source="jin10_mcp_derived_5m",
        closed_before=base + timedelta(minutes=5),
    )
    missing = aggregate_complete_candles(
        rows[:-1],
        source_timeframe="1m",
        target_timeframe="5m",
        source="jin10_mcp_derived_5m",
        closed_before=base + timedelta(minutes=5),
    )

    assert len(complete) == 1
    assert complete[0].open == 4000
    assert complete[0].high == 4006
    assert complete[0].low == 3999
    assert complete[0].close == 4004.5
    assert complete[0].volume is None
    assert complete[0].source_ref["component_count"] == 5
    assert missing == []


def test_aggregate_excludes_open_bucket_until_closed_before():
    base = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)
    rows = [_row(base + timedelta(minutes=index), source="jin10_mcp_kline_1m", price=4000 + index) for index in range(5)]

    result = aggregate_complete_candles(
        rows,
        source_timeframe="1m",
        target_timeframe="5m",
        source="jin10_mcp_derived_5m",
        closed_before=base + timedelta(minutes=4, seconds=59),
    )

    assert result == []


def test_canonical_selection_prefers_jin10_and_rejects_gc_futures():
    open_time = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)
    twelve = _row(open_time, source="twelvedata_xauusd_5m", price=4000)
    jin10 = _row(open_time, source="jin10_mcp_derived_5m", price=4001)
    futures = _row(
        open_time + timedelta(minutes=5),
        source="yahoo_finance_gc_f",
        price=4002,
        source_ref={"provider_symbol": "GC=F", "instrument_type": "futures_continuous_proxy"},
    )

    selected = select_canonical_xauusd_rows([twelve, futures, jin10])

    assert selected == [jin10]


def test_merge_uses_whole_primary_bar_and_only_fills_missing_timestamp():
    base = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)
    fallback_first = _row(base, source="twelvedata_xauusd_5m", price=4000)
    fallback_second = _row(base + timedelta(minutes=5), source="twelvedata_xauusd_5m", price=4010)
    primary_first = _row(base, source="jin10_mcp_derived_5m", price=4001)

    merged = merge_candle_series([primary_first], [fallback_first, fallback_second])

    assert merged == [primary_first, fallback_second]
    assert merged[0]["high"] == primary_first["high"]


def test_four_hour_buckets_follow_new_york_17_session_anchor():
    base = datetime(2026, 7, 16, 5, 0, tzinfo=UTC)
    rows = [_row(base + timedelta(minutes=5 * index), source="jin10_mcp_derived_5m", price=4000 + index) for index in range(48)]

    result = aggregate_complete_candles(
        rows,
        source_timeframe="5m",
        target_timeframe="4h",
        source="canonical_xauusd_5m_aggregate_4h",
        closed_before=datetime(2026, 7, 16, 9, 0, tzinfo=UTC),
    )

    assert len(result) == 1
    assert result[0].open_time == datetime(2026, 7, 16, 5, 0, tzinfo=UTC)
