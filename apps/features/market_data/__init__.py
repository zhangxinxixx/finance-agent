"""Deterministic market-data features."""

from .canonical_candles import (
    AggregatedCandle,
    aggregate_complete_candles,
    is_xauusd_compatible_row,
    merge_candle_series,
    select_canonical_xauusd_rows,
)

__all__ = [
    "AggregatedCandle",
    "aggregate_complete_candles",
    "is_xauusd_compatible_row",
    "merge_candle_series",
    "select_canonical_xauusd_rows",
]
