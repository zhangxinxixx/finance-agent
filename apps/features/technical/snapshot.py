from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

YAHOO_FINANCE_XAUUSD_URL = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F"


@dataclass(frozen=True)
class TechnicalSnapshot:
    """Read-only technical snapshot for XAUUSD derived from Yahoo Finance chart API."""

    price: float
    ma20: float | None = None
    ma50: float | None = None
    rsi14: float | None = None
    rsi14_note: str = ""
    atr14: float | None = None
    atr14_note: str = ""
    trend: str = "neutral"  # bullish / bearish / neutral
    volatility: str = "normal"  # high / normal / low
    source_refs: list[dict[str, str]] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_technical_snapshot(
    *,
    close: float,
    open_: float | None = None,
    high: float | None = None,
    low: float | None = None,
    ma20: float | None = None,
    ma50: float | None = None,
    closes: list[float] | None = None,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    source_refs: list[dict[str, str]] | None = None,
) -> TechnicalSnapshot:
    """Build a TechnicalSnapshot from Yahoo Finance chart data.

    Uses real OHLC history from Yahoo Finance:
      - ma20: SMA(20) computed from actual close prices
      - ma50: SMA(50) computed from actual close prices
      - rsi14: computed from last 14 closes if available, else None
      - atr14: computed from last 14 daily ranges (high-low) if available,
        else from the latest single-day range
    """

    # Trend: compare current price vs ma20 (preferred anchor)
    trend: str = "neutral"
    if ma20 is not None:
        if close > ma20 * 1.01:
            trend = "bullish"
        elif close < ma20 * 0.99:
            trend = "bearish"

    # RSI(14): compute from last 14 closes
    rsi14: float | None = None
    rsi14_note: str = ""
    if closes and len(closes) >= 15:
        rsi14 = _compute_rsi14(closes)
    else:
        rsi14_note = "RSI(14) requires at least 15 daily closes; insufficient data available."

    # ATR(14): compute from last 14 daily ranges (high - low)
    atr14: float | None = None
    atr14_note: str = ""
    if highs and lows and len(highs) >= 14 and len(lows) >= 14:
        atr14 = _compute_atr14(highs[-14:], lows[-14:])
        atr14_note = "ATR(14) computed from last 14 daily ranges."
    elif high is not None and low is not None:
        atr14 = round(high - low, 6)
        atr14_note = "ATR approximated from single-day range (high - low); true ATR(14) requires 14 days."
    else:
        atr14_note = "ATR(14) requires OHLC data; high/low missing."

    # Volatility: based on ATR relative to price
    volatility: str = "normal"
    if atr14 is not None and close > 0:
        ratio = atr14 / close
        if ratio > 0.02:       # >2% of price
            volatility = "high"
        elif ratio < 0.005:    # <0.5% of price
            volatility = "low"
        else:
            volatility = "normal"

    return TechnicalSnapshot(
        price=close,
        ma20=ma20,
        ma50=ma50,
        rsi14=rsi14,
        rsi14_note=rsi14_note,
        atr14=atr14,
        atr14_note=atr14_note,
        trend=trend,
        volatility=volatility,
        source_refs=source_refs,
    )


# ---------------------------------------------------------------------------
# Technical indicator computations
# ---------------------------------------------------------------------------


def _compute_rsi14(closes: list[float]) -> float:
    """Compute RSI(14) from a list of closes (needs at least 15 points)."""
    gains = 0.0
    losses = 0.0
    # Use the last 15 closes → 14 price changes
    window = closes[-15:]
    for i in range(1, len(window)):
        delta = window[i] - window[i - 1]
        if delta > 0:
            gains += delta
        else:
            losses += abs(delta)
    avg_gain = gains / 14.0
    avg_loss = losses / 14.0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return round(rsi, 2)


def _compute_atr14(highs: list[float], lows: list[float]) -> float:
    """Compute ATR(14) from 14 daily high-low ranges."""
    if len(highs) < 14 or len(lows) < 14:
        return round(highs[-1] - lows[-1], 6) if highs and lows else 0.0
    ranges = [high - low for high, low in zip(highs[-14:], lows[-14:], strict=False)]
    return round(sum(ranges) / len(ranges), 6)
