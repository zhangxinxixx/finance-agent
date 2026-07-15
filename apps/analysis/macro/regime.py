"""Deterministic macro regime engine for gold (XAUUSD).

Classifies the current macro environment into v2.1 gold-relevant phases:
  - rate_pressure: Rising rates, tight liquidity — bearish headwind for gold.
  - transition_release: Rate cuts beginning / liquidity easing — neutral-bullish.
  - trend_tailwind: Falling rates, ample liquidity — bullish tailwind for gold.
  - liquidity_crunch: USD cash scramble/liquidity stress can pressure gold first.
  - monetary_credit_repricing: Gold rises despite rates/USD headwinds.
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
            "market_phase": "rate_pressure" | "transition_release" | "trend_tailwind" |
                            "liquidity_crunch" | "monetary_credit_repricing" | "unavailable",
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

    # ── 1. Real yield (main口径: nominal 10Y - T10YIE; TIPS is supplementary) ──
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
    liquidity_crunch = _is_liquidity_crunch(drivers)
    monetary_credit_repricing = _is_monetary_credit_repricing(indicators, drivers)
    if len(missing) >= 4:
        market_phase = "unavailable"
        confidence = 0.0
    elif liquidity_crunch:
        market_phase = "liquidity_crunch"
        confidence += 0.08
    elif monetary_credit_repricing:
        market_phase = "monetary_credit_repricing"
        confidence += 0.04
    elif score >= 3.0 and _has_trend_tailwind_confirmation(drivers):
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
        "source_refs": [{"source": "macro_regime_engine", "version": "2.1.0", "method": "deterministic"}],
    }


def _has_trend_tailwind_confirmation(drivers: dict[str, Any]) -> bool:
    """Require both core gold drivers to confirm a durable macro tailwind."""
    real_yield = drivers.get("real_yield", {})
    dxy = drivers.get("dxy", {})
    return (
        real_yield.get("status") == "available"
        and real_yield.get("direction") == "falling"
        and dxy.get("status") == "available"
        and dxy.get("direction") == "falling"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Driver evaluators
# ═══════════════════════════════════════════════════════════════════════════

_REAL_YIELD_KEYS = ("REAL_10Y", "REAL_YIELD_10Y", "10Y_REAL_YIELD")
_NOMINAL_10Y_KEYS = ("US10Y", "DGS10")
_BREAKEVEN_KEYS = ("BREAKEVEN_10Y", "T10YIE")
_DXY_KEYS = ("DXY", "dxy")
_US02Y_KEYS = ("US02Y", "DGS2")


def _eval_real_yield(indicators: dict[str, Any]) -> dict[str, Any]:
    """Evaluate real yield using US10Y/DGS10 - T10YIE as the main口径.

    Direct TIPS fields such as DFII10/REAL_10Y are treated as supplementary
    fallback only. This keeps the report scoring口径 stable with the liquidity
    daily framework.
    """
    # Main口径: nominal 10Y minus 10Y breakeven.
    nominal = _extract_value(indicators, _NOMINAL_10Y_KEYS)
    breakeven = _extract_value(indicators, _BREAKEVEN_KEYS)
    if nominal is not None and breakeven is not None:
        value = nominal - breakeven
        n_change = _extract_change(indicators, _NOMINAL_10Y_KEYS)
        b_change = _extract_change(indicators, _BREAKEVEN_KEYS)
        change = (n_change - b_change) if (n_change is not None and b_change is not None) else None
        return {
            "status": "available",
            "source": "US10Y - T10YIE (computed_main)",
            "value": value,
            "daily_change": change,
            "direction": _direction(change),
            "note": "Main report口径: nominal 10Y minus T10YIE.",
        }

    # Supplementary fallback: direct real-yield/TIPS field.
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
                    "note": "Supplementary fallback; main口径 requires US10Y/DGS10 and T10YIE.",
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
    reserves_change = _extract_change(indicators, ("RESERVES", "WRESBAL"))
    if rrp_change is not None:
        signs.append("easing" if rrp_change < 0 else "tightening")
    if tga_change is not None:
        signs.append("easing" if tga_change < 0 else "tightening")
    if reserves_change is not None:
        signs.append("easing" if reserves_change > 0 else "tightening")

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


def _is_liquidity_crunch(drivers: dict[str, Any]) -> bool:
    us10y = drivers.get("us10y", {})
    real_yield = drivers.get("real_yield", {})
    dxy = drivers.get("dxy", {})
    liq_quantity = drivers.get("liquidity_quantity", {})
    us10y_value = us10y.get("value")
    dxy_change = dxy.get("daily_change")
    dxy_weekly = dxy.get("weekly_change")
    dollar_surge = (
        dxy.get("direction") == "rising"
        and ((isinstance(dxy_change, (int, float)) and dxy_change >= 0.3) or (isinstance(dxy_weekly, (int, float)) and dxy_weekly >= 1.0))
    )
    rate_break = isinstance(us10y_value, (int, float)) and us10y_value >= 4.7
    real_pressure = real_yield.get("direction") == "rising"
    liquidity_not_easing = liq_quantity.get("trend") != "easing"
    return bool(rate_break and dollar_surge and real_pressure and liquidity_not_easing)


def _is_monetary_credit_repricing(indicators: dict[str, Any], drivers: dict[str, Any]) -> bool:
    gold_change = _extract_change(indicators, ("XAUUSD", "GOLD", "GC"))
    if gold_change is None or gold_change <= 0:
        return False
    real_yield = drivers.get("real_yield", {})
    dxy = drivers.get("dxy", {})
    us10y = drivers.get("us10y", {})
    return (
        real_yield.get("direction") == "rising"
        and dxy.get("direction") != "falling"
        and us10y.get("direction") == "rising"
    )


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
    elif phase == "liquidity_crunch":
        prefix = "LIQUIDITY CRUNCH: Long-end yields and USD strength are stressing cash conditions; gold can be sold first before safe-haven demand returns. "
    elif phase == "monetary_credit_repricing":
        prefix = "MONETARY CREDIT REPRICING: Gold is holding up despite rates/USD pressure, suggesting fiscal-credit or reserve-diversification demand is overriding the classic real-rate channel. "
    else:
        prefix = "MACRO TRANSITION: Mixed signals with rates stabilizing or in transition. Gold direction depends on breakout confirmation. "

    if bulletins:
        prefix += "Key drivers: " + "; ".join(bulletins[:4]) + "."
    return prefix


def _change_conditions(phase: str) -> list[str]:
    if phase == "rate_pressure":
        return [
            "US10Y - T10YIE turns lower for 2+ weeks",
            "DXY breaks below 50-day moving average",
            "Fed signals rate cut timeline",
            "ON RRP usage drops significantly (liquidity injection)",
        ]
    if phase == "trend_tailwind":
        return [
            "US10Y - T10YIE begins rising for 2+ weeks",
            "DXY strengthens above resistance",
            "Fed signals pause or rate hike",
            "ON RRP usage surges (liquidity drain)",
        ]
    if phase == "liquidity_crunch":
        return [
            "US10Y falls back below the 4.5%-4.7% stress band",
            "DXY stops rising and funding spreads normalize",
            "Risk assets stabilize without forced USD liquidation",
        ]
    if phase == "monetary_credit_repricing":
        return [
            "Gold stops outperforming while real yields and DXY remain firm",
            "Fiscal-credit or reserve-diversification evidence fades",
            "Classic real-rate sensitivity reasserts itself for multiple sessions",
        ]
    # transition_release
    return [
        "Real yields break decisively lower (confirmed rate-cut cycle)",
        "DXY breaks trend in either direction",
        "Liquidity conditions shift clearly toward easing or tightening",
    ]
