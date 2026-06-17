"""Black-76 delta-based price-touch probability and probability surface.

Uses Black-76 call delta as a risk-neutral proxy for the probability of
the underlying finishing above a given strike at expiry. This is the
standard industry approximation used by CME, Bloomberg, and other
institutional platforms.

Key relationship:
  - Call delta ≈ P(price > strike at expiry)
  - Put delta  ≈ P(price < strike at expiry)

References:
  - Breeden & Litzenberger (1978), "Prices of State-Contingent Claims
    Implicit in Option Prices"
  - Taleb (1997), "Dynamic Hedging"
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from apps.features.options.black76 import (
    DEFAULT_R,
    black76_delta,
    calc_time_to_expiry,
    implied_vol_black76,
    infer_forward_price,
    sort_expiry_codes,
)
from apps.features.options.normalize import NormalizedOptionRow

# ── Output types ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StrikeProbability:
    """Probability estimate for a single strike."""

    strike: int
    expiry: str
    call_delta: float | None  # ≈ P(price > strike)
    put_delta: float | None   # ≈ P(price < strike)
    touch_probability: float | None  # ≈ 2 × delta for OTM (Taleb approximation)
    implied_vol: float | None  # IV at this strike
    model: str = "black76_delta"  # black76_delta | proxy_delta | unavailable
    confidence: float | None = None  # based on IV quality / data availability


@dataclass(frozen=True)
class ProbabilitySurface:
    """A grid of strike-level probabilities for a single expiry."""

    expiry: str
    trade_date: str
    forward_price: float | None
    time_to_expiry_years: float | None
    strikes: list[StrikeProbability] = field(default_factory=list)
    source: str = "cme_options"
    status: str = "unavailable"  # available | partial | unavailable


@dataclass(frozen=True)
class PriceTargetProbability:
    """Probability of a specific price target being hit by expiry."""

    target_price: float
    direction: str  # above | below
    expiry: str
    probability: float | None
    confidence: float | None
    method: str  # delta_backed | delta_proxy | oi_based | unavailable
    nearest_strike: int | None
    notes: str = ""


# ── Public API ──────────────────────────────────────────────────────────────


def compute_touch_probability_from_delta(
    call_delta_mag: float,
    *,
    tail_adjustment: bool = True,
) -> float | None:
    """Approximate probability of price *touching* a level from its delta.

    For OTM options, the risk-neutral probability of *finishing* beyond
    the strike is approximately the delta. Taleb's approximation doubles
    this for touch probability (the "reflection principle").

    For ATM/ITM (delta ≥ 0.5), touch probability is near 1.0 — the price
    has already crossed this level, so the probability depends on
    maintaining vs breaking.

    Returns 0.0–1.0, or None if delta is invalid.
    """
    if call_delta_mag <= 0 or call_delta_mag > 1:
        return None
    if call_delta_mag >= 0.95:
        return 1.0  # deep ITM: already past this level
    if call_delta_mag >= 0.50:
        # ATM/ITM: high probability of maintaining, but not guaranteed
        base = call_delta_mag
        return min(base * 1.15, 0.98) if tail_adjustment else base
    # OTM: Taleb-style doubling with attenuation for deep OTM
    if tail_adjustment and call_delta_mag < 0.15:
        # Deep OTM: the doubling overestimates; use a sigmoid dampener
        dampening = 1.5 * (1.0 - math.exp(-3.0 * call_delta_mag))
        return min(call_delta_mag * dampening, 0.30)
    return min(call_delta_mag * 2.0, 0.85) if tail_adjustment else call_delta_mag


def build_probability_surface(
    normalized_rows: list[NormalizedOptionRow],
    *,
    trade_date: str = "",
    risk_free_rate: float = DEFAULT_R,
) -> list[ProbabilitySurface]:
    """Build per-expiry probability surfaces from CME option rows.

    For each expiry:
      1. Inferred forward price.
      2. For each strike, compute delta-based probabilities.
      3. Produce a StrikeProbability for CALL and PUT at each strike.

    Returns one ProbabilitySurface per expiry, sorted chronologically.
    """
    expiry_rows: dict[str, list[NormalizedOptionRow]] = {}
    for row in normalized_rows:
        expiry_rows.setdefault(row.expiry, []).append(row)

    sorted_expiries = sort_expiry_codes(list(expiry_rows.keys()))
    surfaces: list[ProbabilitySurface] = []

    for exp in sorted_expiries:
        rows = expiry_rows[exp]
        # Infer forward price for this expiry
        F, _warnings = infer_forward_price(rows, trade_date=trade_date, expiry=exp)
        T, _exp_date, _w = calc_time_to_expiry(trade_date, expiry=exp)

        strikes: dict[int, dict[str, Any]] = {}

        for row in rows:
            s = strikes.setdefault(row.strike, {
                "strike": row.strike,
                "expiry": exp,
                "call_delta": None,
                "put_delta": None,
                "iv": None,
                "model": "unavailable",
            })

            if row.settlement is not None and F and T and T > 0:
                sigma, low_conf = implied_vol_black76(
                    row.settlement, F, row.strike, T, row.option_type, r=risk_free_rate,
                )
                if sigma is not None:
                    delta_mag = black76_delta(
                        F, row.strike, sigma, T, row.option_type, r=risk_free_rate,
                    )
                    key = "call_delta" if row.option_type == "CALL" else "put_delta"
                    s[key] = round(delta_mag, 6)
                    if s["iv"] is None:
                        s["iv"] = round(sigma, 4)
                    if s["model"] == "unavailable":
                        s["model"] = "black76_delta"

        if strikes:
            strike_list: list[StrikeProbability] = []
            for s in sorted(strikes.values(), key=lambda x: x["strike"]):
                call_d = s.get("call_delta")
                put_d = s.get("put_delta")
                # Touch probability from the more informative side
                if call_d is not None and call_d >= 0.05:
                    touch = compute_touch_probability_from_delta(call_d)
                elif put_d is not None and put_d >= 0.05:
                    touch = compute_touch_probability_from_delta(put_d)
                else:
                    touch = None

                confidence = _delta_confidence(s.get("iv"), call_d, put_d)

                strike_list.append(StrikeProbability(
                    strike=s["strike"],
                    expiry=s["expiry"],
                    call_delta=call_d,
                    put_delta=put_d,
                    touch_probability=round(touch, 4) if touch is not None else None,
                    implied_vol=s.get("iv"),
                    model=s.get("model", "unavailable"),
                    confidence=confidence,
                ))

            status = "available" if strike_list else "unavailable"
        else:
            strike_list = []
            status = "unavailable"

        surfaces.append(ProbabilitySurface(
            expiry=exp,
            trade_date=trade_date,
            forward_price=round(F, 2) if F else None,
            time_to_expiry_years=round(T, 6) if T and T > 0 else None,
            strikes=strike_list,
            source="cme_options",
            status=status,
        ))

    return surfaces


def estimate_price_target_probability(
    target_price: float,
    direction: str,
    surfaces: list[ProbabilitySurface],
) -> PriceTargetProbability:
    """Estimate probability of price reaching a target from a probability surface.

    Finds the nearest strike in the surface and returns its touch probability.
    Falls back to delta-based estimate if no matching strike exists.
    """
    if direction not in ("above", "below"):
        return PriceTargetProbability(
            target_price=target_price,
            direction=direction,
            expiry="",
            probability=None,
            confidence=None,
            method="unavailable",
            nearest_strike=None,
            notes=f"Invalid direction: {direction}",
        )

    if not surfaces:
        return PriceTargetProbability(
            target_price=target_price,
            direction=direction,
            expiry="",
            probability=None,
            confidence=None,
            method="unavailable",
            nearest_strike=None,
            notes="No probability surface available.",
        )

    # Use the nearest expiry
    surface = surfaces[0]

    # Find nearest strike
    best_strike: int | None = None
    best_dist = float("inf")
    for sp in surface.strikes:
        dist = abs(sp.strike - target_price)
        if dist < best_dist:
            best_dist = dist
            best_strike = sp.strike

    if best_strike is None:
        return PriceTargetProbability(
            target_price=target_price,
            direction=direction,
            expiry=surface.expiry,
            probability=None,
            confidence=None,
            method="unavailable",
            nearest_strike=None,
            notes="No strikes in surface.",
        )

    # Get the matched strike probability
    matched = next((sp for sp in surface.strikes if sp.strike == best_strike), None)
    if matched is None:
        return PriceTargetProbability(
            target_price=target_price,
            direction=direction,
            expiry=surface.expiry,
            probability=None,
            confidence=None,
            method="unavailable",
            nearest_strike=best_strike,
            notes="Strike match failed.",
        )

    prob = matched.touch_probability
    conf = matched.confidence

    # Adjust for direction
    if direction == "below" and matched.put_delta is not None:
        # Use put delta for "below" estimates
        touch_below = compute_touch_probability_from_delta(matched.put_delta)
        prob = touch_below if touch_below is not None else prob

    if prob is None:
        return PriceTargetProbability(
            target_price=target_price,
            direction=direction,
            expiry=surface.expiry,
            probability=None,
            confidence=None,
            method="unavailable",
            nearest_strike=best_strike,
            notes="No probability data at nearest strike.",
        )

    return PriceTargetProbability(
        target_price=target_price,
        direction=direction,
        expiry=surface.expiry,
        probability=round(prob, 4),
        confidence=round(conf, 4) if conf is not None else None,
        method="delta_backed" if matched.model == "black76_delta" else "delta_proxy",
        nearest_strike=best_strike,
        notes="",
    )


# ── Internal helpers ────────────────────────────────────────────────────────


def _delta_confidence(
    iv: float | None,
    call_delta: float | None,
    put_delta: float | None,
) -> float | None:
    """Compute a confidence score for delta-based probability.

    0.0 = no data, 1.0 = high confidence.
    """
    if iv is None:
        return None
    available_deltas = sum(1 for d in (call_delta, put_delta) if d is not None)
    if available_deltas == 0:
        return None
    # Base confidence from number of deltas available
    base = 0.6 if available_deltas >= 2 else 0.4
    # IV within reasonable range reduces noise
    if 0.05 <= iv <= 0.60:
        base += 0.2
    elif iv > 1.0:
        base -= 0.2  # extreme IV = less reliable delta
    # Delta at extremes is less reliable
    for d in (call_delta, put_delta):
        if d is not None:
            if d < 0.01 or d > 0.99:
                base -= 0.1
    return max(0.0, min(base, 1.0))


def probability_surface_to_dict(surface: ProbabilitySurface) -> dict[str, Any]:
    """Serialize a ProbabilitySurface to a JSON-safe dict."""
    return {
        "expiry": surface.expiry,
        "trade_date": surface.trade_date,
        "forward_price": surface.forward_price,
        "time_to_expiry_years": surface.time_to_expiry_years,
        "source": surface.source,
        "status": surface.status,
        "strikes": [
            {
                "strike": sp.strike,
                "call_delta": sp.call_delta,
                "put_delta": sp.put_delta,
                "touch_probability": sp.touch_probability,
                "implied_vol": sp.implied_vol,
                "model": sp.model,
                "confidence": sp.confidence,
            }
            for sp in surface.strikes
        ],
    }


def target_probs_to_dict(probs: list[PriceTargetProbability]) -> list[dict[str, Any]]:
    """Serialize price target probabilities to JSON-safe dicts."""
    return [
        {
            "target_price": p.target_price,
            "direction": p.direction,
            "expiry": p.expiry,
            "probability": p.probability,
            "confidence": p.confidence,
            "method": p.method,
            "nearest_strike": p.nearest_strike,
            "notes": p.notes,
        }
        for p in probs
    ]
