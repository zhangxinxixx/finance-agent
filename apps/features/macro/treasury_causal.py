"""Two alternative yield decompositions; neither is a causal regression."""

from copy import deepcopy
from math import isfinite


def build_treasury(rows):
    by = {r["symbol"]: r for r in rows}
    result = {
        "schema_version": "treasury_causal.v4",
        "windows": {},
        "term_premium": {"status": "unavailable", "reason": "no_vintage_matched_term_structure_model"},
        "auction_supply": {"status": "unavailable", "reason": "no_auction_WI_bidder_supply_dataset"},
        "limitations": [
            "Real+BE and expected_short_rates+term_premium are alternative decompositions, never sum all four",
            "TIPS includes real term premium; BE includes risk and liquidity premia",
            "daily changes are not announcement-window causal estimates",
        ],
    }
    for window, delta, anchor in [("1d", "change", "previous_date"), ("1w", "weekly_change", "weekly_anchor_date")]:
        series = [by.get(s, {}) for s in ("US10Y", "REAL10Y", "BREAKEVEN_10Y")]
        valid = all(
            r.get("status") == "fresh"
            and r.get("source_refs")
            and isinstance(r.get(delta), (int, float))
            and isfinite(r[delta])
            for r in series
        )
        valid = valid and all(r.get(anchor) and r.get("observation_date") for r in series)
        valid = valid and len({(r.get(anchor), r.get("observation_date")) for r in series}) == 1
        if not valid:
            result["windows"][window] = {"status": "unavailable", "reason": "nonmatching_or_missing_yield_windows"}
            continue
        n, r, b = [round(x[delta] * 100, 6) for x in series]
        residual = round(n - r - b, 6)
        result["windows"][window] = {
            "status": "available",
            "from": series[0][anchor],
            "to": series[0]["observation_date"],
            "nominal_bp": n,
            "real_bp": r,
            "breakeven_bp": b,
            "identity_residual_bp": residual,
            "dominant_component": "real" if abs(r) > abs(b) else "breakeven" if abs(b) > abs(r) else "mixed",
            "source_refs": deepcopy([ref for row in series for ref in row["source_refs"]]),
        }
    result["curves"] = [
        {
            k: r.get(k)
            for k in ("symbol", "value", "observation_date", "change", "weekly_change", "source_refs", "status")
        }
        for r in rows
        if r["symbol"] in {"YIELD_SPREAD_2Y_3M", "YIELD_SPREAD_10Y_2Y", "YIELD_SPREAD_30Y_10Y"}
    ]
    return result
