from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from datetime import date
from math import isfinite

YAHOO_FINANCE_XAUUSD_URL = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F"


@dataclass(frozen=True)
class TechnicalSnapshot:
    """Read-only technical facts for the explicitly identified spot source."""

    price: float
    previous_price: float | None = None
    daily_change: float | None = None
    ma20: float | None = None
    ma50: float | None = None
    rsi14: float | None = None
    rsi14_note: str = ""
    atr14: float | None = None
    atr14_note: str = ""
    daily_range: float | None = None
    indicator_method: str = "SMA; RSI simple 14-change window; ATR simple 14 true ranges"
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
    """Compute indicators from aligned daily spot history; missing stays missing.

    ATR uses previous closes to include gaps. A single daily range is exposed
    separately and must never be labeled ATR(14). RSI uses simple window means,
    not Wilder's recursive smoothing.
    """

    if closes and len(closes) >= 20:
        ma20 = round(sum(closes[-20:]) / 20, 6)
    if closes and len(closes) >= 50:
        ma50 = round(sum(closes[-50:]) / 50, 6)

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

    # 14 true ranges require 15 aligned daily closes.
    atr14: float | None = None
    atr14_note: str = ""
    if highs and lows and closes and len(highs) == len(lows) == len(closes) and len(closes) >= 15:
        atr14 = _compute_atr14(highs, lows, closes)
        atr14_note = "Simple mean of 14 true ranges, including previous-close gaps."
    else:
        atr14_note = "ATR(14) requires 15 aligned daily closes with high/low history."

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
        previous_price=closes[-2] if closes and len(closes) >= 2 and closes[-1] == close else None,
        daily_change=round(close - closes[-2], 6) if closes and len(closes) >= 2 and closes[-1] == close else None,
        ma20=ma20,
        ma50=ma50,
        rsi14=rsi14,
        rsi14_note=rsi14_note,
        atr14=atr14,
        atr14_note=atr14_note,
        daily_range=round(high - low, 6) if high is not None and low is not None else None,
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
        return 100.0 if avg_gain else 50.0
    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return round(rsi, 2)


def _compute_atr14(highs: list[float], lows: list[float], closes: list[float]) -> float:
    ranges = [max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])) for i in range(len(closes) - 14, len(closes))]
    return round(sum(ranges) / 14, 6)


def build_price_structure(*, dates: list[str], closes: list[float], highs: list[float], lows: list[float]) -> dict[str, Any]:
    """Compare the latest complete session with prior rolling ranges.

    The latest bar never defines the range it is tested against. Lifecycle
    labels describe observable bars, not an accepted Gold state or event cause.
    """
    if not (len(dates) == len(closes) == len(highs) == len(lows)) or len(dates) < 2:
        return {"status": "unavailable", "reason": "aligned_history_missing", "levels": []}
    try:
        parsed_dates = [date.fromisoformat(value) for value in dates]
    except (TypeError, ValueError):
        return {"status": "unavailable", "reason": "invalid_dates", "levels": []}
    if parsed_dates != sorted(set(parsed_dates)) or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and isfinite(v) and v > 0 for seq in (closes, highs, lows) for v in seq) or any(not low <= close <= high for close, high, low in zip(closes, highs, lows)):
        return {"status": "unavailable", "reason": "invalid_history", "levels": []}
    levels = []
    for window in (5, 20):
        if len(dates) <= window:
            continue
        start, end = len(dates) - window - 1, len(dates) - 1
        for side, values, choose in (("low", lows, min), ("high", highs, max)):
            value = choose(values[start:end])
            origin = next(i for i in range(end - 1, start - 1, -1) if values[i] == value)
            if side == "low":
                state = "broken_on_close" if closes[-1] < value else "reclaimed_after_intraday_breach" if lows[-1] < value else "not_broken"
            else:
                state = "broken_on_close" if closes[-1] > value else "rejected_after_intraday_breach" if highs[-1] > value else "not_broken"
            levels.append({"price": value, "kind": f"prior_{window}d_{side}", "status": state, "date": dates[origin],
                           "evaluation_date": dates[-1], "window_start": dates[start], "window_end": dates[end - 1],
                           "basis": "prior_complete_daily_range", "formal_state_line": False})
    return {"status": "available" if levels else "partial", "as_of": dates[-1], "previous_date": dates[-2],
            "history_sessions": len(dates), "levels": levels, "state_authority": False}
