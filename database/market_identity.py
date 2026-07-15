"""Stable instrument identity guards for persisted market candles.

``XAUUSD`` is the canonical spot/OTC proxy identity.  Yahoo's ``GC=F`` is a
continuous futures contract and must remain under the separate ``GC`` asset
identity even when an old caller passes ``asset="XAUUSD"``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class MarketCandleIdentity:
    asset: str
    source_ref: dict[str, Any]
    reclassified_from: str | None = None


def normalize_market_candle_identity(
    *,
    asset: str,
    source: str,
    source_ref: Mapping[str, Any] | None = None,
) -> MarketCandleIdentity:
    """Normalize candle identity and quarantine futures from the spot chain.

    A legacy writer may still label a ``GC=F`` row as ``XAUUSD``.  Reclassify
    that row to ``GC`` at the persistence boundary so it cannot be returned by
    canonical XAUUSD reads.  Unknown futures labels fail closed instead of
    silently being presented as spot data.
    """

    normalized_asset = str(asset or "").strip().upper()
    if not normalized_asset:
        raise ValueError("market candle asset must not be empty")

    normalized_source = str(source or "").strip()
    normalized_ref = dict(source_ref) if isinstance(source_ref, Mapping) else {}
    provider_symbol = str(
        normalized_ref.get("provider_symbol")
        or normalized_ref.get("ticker")
        or normalized_ref.get("symbol")
        or ""
    ).strip().upper()
    instrument_type = str(normalized_ref.get("instrument_type") or "").strip().lower()
    source_key = normalized_source.lower()
    is_gc_futures = provider_symbol == "GC=F" or "gc_f" in source_key

    if normalized_asset == "XAUUSD" and instrument_type.startswith("futures") and not is_gc_futures:
        raise ValueError("futures instrument cannot be persisted with asset=XAUUSD")

    if normalized_asset == "XAUUSD" and is_gc_futures:
        normalized_ref.setdefault("provider_symbol", "GC=F")
        normalized_ref.setdefault("instrument_type", "futures_continuous_proxy")
        normalized_ref["identity_guard"] = "reclassified_xauusd_futures"
        return MarketCandleIdentity(asset="GC", source_ref=normalized_ref, reclassified_from="XAUUSD")

    return MarketCandleIdentity(asset=normalized_asset, source_ref=normalized_ref)


def is_xauusd_spot_identity(*, asset: str, source: str, source_ref: Mapping[str, Any] | None = None) -> bool:
    """Return whether a persisted row belongs to the canonical XAUUSD chain."""

    try:
        identity = normalize_market_candle_identity(asset=asset, source=source, source_ref=source_ref)
    except ValueError:
        return False
    return identity.asset == "XAUUSD"
