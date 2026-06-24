"""P4-05: Deterministic macro regime engine for gold (XAUUSD).

Classifies the current macro environment into one of three gold-relevant phases:
  - rate_pressure: Rising rates, tight liquidity — bearish headwind for gold.
  - transition_release: Rate cuts beginning / liquidity easing — neutral-bullish.
  - trend_tailwind: Falling rates, ample liquidity — bullish tailwind for gold.
  - unavailable: Insufficient macro data to classify.

This is a pure-in-memory, deterministic classifier. It does NOT read files,
call external APIs, or use LLM inference. All inputs come from the
already-loaded macro snapshot indicators (dict).
"""

from __future__ import annotations

from typing import Any


def classify_macro_regime(indicators: dict[str, Any]) -> dict[str, Any]:
    """Classify the gold macro regime from loaded macro indicator values.

    Args:
        indicators: dict of symbol → indicator dict with keys: value, daily_change,
                    weekly_change, monthly_change, label, unit, direction_note.

    Returns:
        {
            "market_phase": "rate_pressure" | "transition_release" | "trend_tailwind" | "unavailable",
            "confidence": float (0.0–1.0),
            "drivers": {
                "real_yield": {...},
                "dxy": {...},
                "us02y": {...},
                "us10y": {...},
                "breakeven": {...},
                "liquidity_quantity": {...},
                "liquidity_price": {...},
            },
            "gold_interpretation": str,
            "change_conditions": list[str],
            "source_refs": list[dict],
        }
    """
    drivers: dict[str, Any] = {}
    score = 0.0
    bulletins: list[str] = []
    missing: list[str] = []
    confidence = 0.5

    # ── 1. Real yield (prefer FRED:DFII10; fallback can compute nominal - breakeven) ──
    real_yield_data = _eval_real_yield(indicators)
    drivers["real_yield"] = real_yield_data
    if real_yield_data["status"] == "available":
        if real_yield_data["direction"] == "falling":
            score += 2.0
            bulletins.append("Real yields falling → bullish for gold")
            confidence += 0.10
        elif real_yield_data["direction"] == "rising":
            score -= 2.0
            bulletins.append("Real yields rising → bearish for gold")
            confidence += 0.10
        else:
            bulletins.append("Real yields flat — no directional signal")
    else:
        missing.append("real_yield")
        confidence -= 0.12

    # ── 2. DXY ──────────────────────────────────────────────────────────
    dxy_data = _eval_dxy(indicators)
    drivers["dxy"] = dxy_data
    if dxy_data["status"] == "available":
        if dxy_data["direction"] == "falling":
            score += 1.5
            bulletins.append("DXY falling → dollar weakness supports gold")
            confidence += 0.08
        elif dxy_data["direction"] == "rising":
            score -= 1.5
            bulletins.append("DXY rising → dollar strength pressures gold")
            confidence += 0.08
    else:
        missing.append("dxy")
        confidence -= 0.08

    # ── 3. US02Y (short-end rate) ───────────────────────────────────────
    us02y_data = _eval_indicator(indicators, ("US02Y", "DGS2"), "US02Y")
    drivers["us02y"] = us02y_data
    if us02y_data["status"] == "available":
        change = us02y_data.get("daily_change") or us02y_data.get("weekly_change")
        if isinstance(change, (int, float)) and change < 0:
            score += 0.5
            bulletins.append("Short-end rates falling — potential easing signal")
            confidence += 0.04
        elif isinstance(change, (int, float)) and change > 0:
            score -= 0.5
            bulletins.append("Short-end rates rising — tightening signal")
            confidence += 0.04
    else:
        missing.append("us02y")

    # ── 4. US10Y (long-end rate) ────────────────────────────────────────
    us10y_data = _eval_indicator(indicators, ("US10Y", "DGS10"), "US10Y")
    drivers["us10y"] = us10y_data
    if us10y_data["status"] == "available":
        change = us10y_data.get("daily_change") or us10y_data.get("weekly_change")
        if isinstance(change, (int, float)) and change < 0:
            score += 0.5
            bulletins.append("Long-end rates falling — supportive for gold")
            confidence += 0.04
        elif isinstance(change, (int, float)) and change > 0:
            score -= 0.5
            bulletins.append("Long-end rates rising — headwind for gold")
            confidence += 0.04
    else:
        missing.append("us10y")

    # ── 5. Breakeven (T10YIE) ───────────────────────────────────────────
    breakeven_data = _eval_indicator(indicators, ("BREAKEVEN_10Y", "T10YIE"), "Breakeven 10Y")
    drivers["breakeven"] = breakeven_data
    if breakeven_data["status"] == "available":
        change = breakeven_data.get("daily_change") or breakeven_data.get("weekly_change")
        if isinstance(change, (int, float)) and change > 0:
            bulletins.append("Breakeven rising — inflation expectation supports gold")
            score += 0.5
        elif isinstance(change, (int, float)) and change < 0:
            bulletins.append("Breakeven falling — disinflation signal")
            score -= 0.5
    else:
        missing.append("breakeven")

    # ── 6. Liquidity quantity (ON RRP, TGA, Reserves) ───────────────────
    liq_q = _eval_liquidity_quantity(indicators)
    drivers["liquidity_quantity"] = liq_q
    if liq_q["status"] == "available":
        if liq_q["trend"] == "easing":
            score += 1.0
            bulletins.append("Liquidity conditions easing — supportive")
            confidence += 0.06
        elif liq_q["trend"] == "tightening":
            score -= 1.0
            bulletins.append("Liquidity conditions tightening — restrictive")
            confidence += 0.06
    elif liq_q["status"] == "partial":
        confidence -= 0.04
    else:
        missing.append("liquidity_quantity")
        confidence -= 0.06

    # ── 7. Liquidity price (SOFR, EFFR, IORB) ───────────────────────────
    liq_p = _eval_liquidity_price(indicators)
    drivers["liquidity_price"] = liq_p
    if liq_p["status"] == "available":
        spread = liq_p.get("sofr_effr_spread")
        if isinstance(spread, (int, float)):
            if spread < 0:
                bulletins.append("SOFR < EFFR — funding stress signal")
                score -= 0.5
            else:
                bulletins.append("SOFR-EFFR spread normal — no funding stress")
    elif liq_p["status"] == "partial":
        confidence -= 0.03
    else:
        missing.append("liquidity_price")

    # ── Classify ────────────────────────────────────────────────────────
    if len(missing) >= 4:
        market_phase = "unavailable"
        confidence = 0.0
    elif score >= 3.0:
        market_phase = "trend_tailwind"
    elif score <= -3.0:
        market_phase = "rate_pressure"
    else:
        market_phase = "transition_release"

    confidence = max(0.0, min(1.0, confidence))
    if market_phase == "unavailable":
        confidence = 0.0

    # ── Gold interpretation ─────────────────────────────────────────────
    gold_interpretation = _render_gold_interpretation(market_phase, drivers, bulletins)

    # ── Change conditions ───────────────────────────────────────────────
    change_conditions = _change_conditions(market_phase)

    return {
        "market_phase": market_phase,
        "confidence": round(confidence, 4),
        "drivers": drivers,
        "gold_interpretation": gold_interpretation,
        "change_conditions": change_conditions,
        "source_refs": [{"source": "macro_regime_engine", "version": "1.0.0", "method": "deterministic"}],
    }


# ═══════════════════════════════════════════════════════════════════════════
# Driver evaluators
# ═══════════════════════════════════════════════════════════════════════════

_REAL_YIELD_KEYS = ("REAL_10Y", "REAL_YIELD_10Y", "10Y_REAL_YIELD")
_NOMINAL_10Y_KEYS = ("US10Y", "DGS10")
_BREAKEVEN_KEYS = ("BREAKEVEN_10Y", "T10YIE")
_DXY_KEYS = ("DXY", "dxy")
_US02Y_KEYS = ("US02Y", "DGS2")


def _eval_real_yield(indicators: dict[str, Any]) -> dict[str, Any]:
    """Evaluate real yield from direct field, or compute from nominal - breakeven."""
    # Direct real yield field
    for key in _REAL_YIELD_KEYS:
        item = indicators.get(key)
        if isinstance(item, dict):
            value = item.get("value")
            change = item.get("daily_change") or item.get("weekly_change")
            if isinstance(value, (int, float)):
                direction = _direction(change)
                return {
                    "status": "available",
                    "source": key,
                    "value": value,
                    "daily_change": item.get("daily_change"),
                    "weekly_change": item.get("weekly_change"),
                    "direction": direction,
                }

    # Compute from nominal - breakeven
    nominal = _extract_value(indicators, _NOMINAL_10Y_KEYS)
    breakeven = _extract_value(indicators, _BREAKEVEN_KEYS)
    if nominal is not None and breakeven is not None:
        value = nominal - breakeven
        n_change = _extract_change(indicators, _NOMINAL_10Y_KEYS)
        b_change = _extract_change(indicators, _BREAKEVEN_KEYS)
        change = (n_change - b_change) if (n_change is not None and b_change is not None) else None
        return {
            "status": "available",
            "source": f"{_NOMINAL_10Y_KEYS[0]} - {_BREAKEVEN_KEYS[0]} (computed)",
            "value": value,
            "daily_change": change,
            "direction": _direction(change),
            "note": "Computed from nominal 10Y minus breakeven",
        }

    return {"status": "unavailable", "reason": "Neither direct real yield nor nominal+breakeven available"}


def _eval_dxy(indicators: dict[str, Any]) -> dict[str, Any]:
    return _eval_indicator(indicators, _DXY_KEYS, "DXY")


def _eval_indicator(
    indicators: dict[str, Any],
    keys: tuple[str, ...],
    driver_name: str,
) -> dict[str, Any]:
    for key in keys:
        item = indicators.get(key)
        if isinstance(item, dict):
            value = item.get("value")
            change = item.get("daily_change") or item.get("weekly_change")
            if isinstance(value, (int, float)):
                return {
                    "status": "available",
                    "source": key,
                    "value": value,
                    "daily_change": item.get("daily_change"),
                    "weekly_change": item.get("weekly_change"),
                    "direction": _direction(change),
                }
    return {"status": "unavailable", "reason": f"Indicator {driver_name} not found in macro snapshot"}


def _eval_liquidity_quantity(indicators: dict[str, Any]) -> dict[str, Any]:
    """Evaluate balance sheet liquidity: ON RRP, TGA, Reserves."""
    rrp = _extract_value(indicators, ("ON_RRP_USAGE", "RRPONTSYD"))
    tga = _extract_value(indicators, ("TGA",))
    reserves = _extract_value(indicators, ("RESERVES", "WRESBAL"))

    available = sum(1 for v in (rrp, tga, reserves) if v is not None)
    if available == 0:
        return {"status": "unavailable", "reason": "No liquidity quantity indicators available"}

    # RRP falling = easing (cash leaving Fed facility)
    # TGA falling = easing (Treasury spending)
    signs: list[str] = []
    rrp_change = _extract_change(indicators, ("ON_RRP_USAGE", "RRPONTSYD"))
    tga_change = _extract_change(indicators, ("TGA",))
    if rrp_change is not None:
        signs.append("easing" if rrp_change < 0 else "tightening")
    if tga_change is not None:
        signs.append("easing" if tga_change < 0 else "tightening")

    easing_count = signs.count("easing")
    tightening_count = signs.count("tightening")
    if easing_count > tightening_count:
        trend = "easing"
    elif tightening_count > easing_count:
        trend = "tightening"
    else:
        trend = "neutral"

    return {
        "status": "available" if available >= 2 else "partial",
        "on_rrp": rrp,
        "tga": tga,
        "reserves": reserves,
        "trend": trend,
        "signals": signs,
        "available_count": available,
    }


def _eval_liquidity_price(indicators: dict[str, Any]) -> dict[str, Any]:
    """Evaluate short-term rate environment: SOFR, EFFR, IORB."""
    sofr = _extract_value(indicators, ("SOFR",))
    effr = _extract_value(indicators, ("EFFR",))
    iorb = _extract_value(indicators, ("IORB",))

    available = sum(1 for v in (sofr, effr, iorb) if v is not None)
    if available == 0:
        return {"status": "unavailable", "reason": "No liquidity price indicators available"}

    result: dict[str, Any] = {
        "status": "available" if available >= 2 else "partial",
        "sofr": sofr,
        "effr": effr,
        "iorb": iorb,
    }
    if sofr is not None and effr is not None:
        result["sofr_effr_spread"] = sofr - effr
    return result


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _extract_value(indicators: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        item = indicators.get(key)
        if isinstance(item, dict):
            value = item.get("value")
            if isinstance(value, (int, float)):
                return float(value)
    return None


def _extract_change(indicators: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        item = indicators.get(key)
        if isinstance(item, dict):
            change = item.get("daily_change") or item.get("weekly_change")
            if isinstance(change, (int, float)):
                return float(change)
    return None


def _direction(change: float | None) -> str:
    if change is None:
        return "unknown"
    if change < -0.01:
        return "falling"
    if change > 0.01:
        return "rising"
    return "flat"


def _render_gold_interpretation(
    phase: str,
    drivers: dict[str, Any],
    bulletins: list[str],
) -> str:
    if phase == "unavailable":
        return "Insufficient macro data to classify gold regime. Core indicators (real yield, DXY, liquidity) are missing."
    if phase == "rate_pressure":
        prefix = "MACRO HEADWIND: Rising real yields and tight liquidity conditions create a rate-pressure environment for gold. "
    elif phase == "trend_tailwind":
        prefix = "MACRO TAILWIND: Falling real yields and ample liquidity provide a supportive trend-tailwind for gold. "
    else:
        prefix = "MACRO TRANSITION: Mixed signals with rates stabilizing or in transition. Gold direction depends on breakout confirmation. "

    if bulletins:
        prefix += "Key drivers: " + "; ".join(bulletins[:4]) + "."
    return prefix


def _change_conditions(phase: str) -> list[str]:
    if phase == "rate_pressure":
        return [
            "Real yields turn lower (FRED:DFII10 declining 2+ weeks)",
            "DXY breaks below 50-day moving average",
            "Fed signals rate cut timeline",
            "ON RRP usage drops significantly (liquidity injection)",
        ]
    if phase == "trend_tailwind":
        return [
            "Real yields begin rising (FRED:DFII10 increasing 2+ weeks)",
            "DXY strengthens above resistance",
            "Fed signals pause or rate hike",
            "ON RRP usage surges (liquidity drain)",
        ]
    # transition_release
    return [
        "Real yields break decisively lower (confirmed rate-cut cycle)",
        "DXY breaks trend in either direction",
        "Liquidity conditions shift clearly toward easing or tightening",
    ]
