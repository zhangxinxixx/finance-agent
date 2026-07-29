"""Deterministic market-data features."""

from .canonical_candles import (
    AggregatedCandle,
    aggregate_complete_candles,
    aggregate_provider_complete_candles,
    is_xauusd_compatible_row,
    merge_candle_series,
    select_canonical_xauusd_rows,
)
from .formal_snapshots import (
    FormalMarketObservation,
    FormalSourceReference,
    MarketPriceSnapshot,
    OilSnapshot,
    build_market_price_snapshot,
    build_oil_snapshot,
)
from .formal_snapshot_loader import (
    FormalSnapshotBundle,
    load_formal_market_snapshots,
    resolve_formal_snapshot_as_of,
)

__all__ = [
    "AggregatedCandle",
    "aggregate_complete_candles",
    "aggregate_provider_complete_candles",
    "is_xauusd_compatible_row",
    "merge_candle_series",
    "select_canonical_xauusd_rows",
    "FormalMarketObservation",
    "FormalSourceReference",
    "MarketPriceSnapshot",
    "OilSnapshot",
    "build_market_price_snapshot",
    "build_oil_snapshot",
    "FormalSnapshotBundle",
    "load_formal_market_snapshots",
    "resolve_formal_snapshot_as_of",
]
