"""Explicit semantic metadata for the public CME option structure outputs.

The numerical engine computes gamma from settlement-implied IV where possible
and falls back to a delta-shaped proxy.  Public reports must expose that
provenance and must never imply that the exchange data reveals dealer
inventory or dealer hedging direction.
"""

from __future__ import annotations

from typing import Any, Iterable


GEX_SEMANTICS_VERSION = "oi_signed_gex_proxy.v2"
GAMMA_FLIP_LABEL = "Selected Expiry Window Proxy Gamma Flip"
CONCENTRATION_LABEL = "OI/Gamma Concentration Zone"


def signed_gex_components(call_gex: float, put_gex: float) -> dict[str, float]:
    """Return the explicit option-type signed convention used by the proxy.

    Legacy snapshot fields keep call/put as positive leg magnitudes.  The
    signed fields make the net equation auditable and avoid subtracting a put
    value twice when a consumer already receives a negative contribution.
    """

    call = float(call_gex or 0.0)
    put = float(put_gex or 0.0)
    return {
        "call_gex_signed": abs(call),
        "put_gex_signed": -abs(put),
        "net_gex_signed": abs(call) - abs(put),
    }


def build_gex_semantics(
    *,
    selected_expiries: Iterable[str],
    used_settlement_implied_gamma: bool,
    proxy_row_count: int,
    black76_row_count: int,
    scope: str = "selected_expiry_window",
) -> dict[str, Any]:
    """Build stable metadata describing the GEX calculation semantics."""

    if black76_row_count and proxy_row_count:
        method = "settlement_implied_black76_oi_gex_plus_separate_shape_proxy"
    elif black76_row_count:
        method = "settlement_implied_black76_gamma"
    elif proxy_row_count:
        method = "separate_shape_proxy_only"
    else:
        method = "unavailable"
    return {
        "label": "OI-Signed GEX Proxy",
        "version": GEX_SEMANTICS_VERSION,
        "scope": scope,
        "selected_expiries": list(selected_expiries),
        "method": method,
        "black76_gex_unit": "USD_per_1pct_move_model_gamma",
        "shape_proxy_unit": "contracts_times_dimensionless_delta_shape",
        "shape_proxy_formula": "OI × |delta| × (1 - |delta|)",
        "shape_proxy_included_in_usd_gex": False,
        "shape_proxy_included_in_gamma_flip": False,
        "coverage": {
            "black76_rows": int(black76_row_count),
            "shape_proxy_rows": int(proxy_row_count),
            "black76_row_share": (
                round(black76_row_count / (black76_row_count + proxy_row_count), 6)
                if black76_row_count + proxy_row_count
                else None
            ),
        },
        "settlement_implied_black76_gamma_available": bool(used_settlement_implied_gamma),
        "black76_row_count": int(black76_row_count),
        "gamma_proxy_row_count": int(proxy_row_count),
        "call_contribution_sign": "+",
        "put_contribution_sign": "-",
        "legacy_leg_fields_are_absolute_magnitudes": True,
        "net_formula": "sum(call_gex_signed) + sum(put_gex_signed)",
        "dealer_position_unknown": True,
        "position_sign_inference": "option_type_signed_public_OI_proxy_only",
        "interpretation": "Black-76 行是公开 OI 与模型 Gamma 的期权类型符号代理；缺少 IV 的行仅保留无量纲 shape proxy，不参与 USD GEX 或 Gamma Flip；全部不代表已知 dealer inventory、dealer gamma 或做市商意图。",
    }


def build_oi_gamma_concentration_zone(
    strike_metrics: Iterable[Any],
    *,
    selected_expiries: Iterable[str],
    max_levels: int = 5,
) -> dict[str, Any]:
    """Find the most concentrated OI/Gamma strikes in the selected window.

    The zone is a descriptive strike cluster.  It deliberately uses public
    OI and absolute model exposure, without trying to infer dealer inventory.
    """

    entries: list[dict[str, Any]] = []
    for metric in strike_metrics:
        strike = getattr(metric, "strike", None)
        if strike is None:
            continue
        try:
            strike_value = float(strike)
        except (TypeError, ValueError):
            continue
        call_oi = float(getattr(metric, "call_oi", 0) or 0)
        put_oi = float(getattr(metric, "put_oi", 0) or 0)
        call_gex = float(getattr(metric, "call_gex", 0) or 0)
        put_gex = float(getattr(metric, "put_gex", 0) or 0)
        oi = max(0.0, call_oi + put_oi)
        gamma = abs(call_gex) + abs(put_gex)
        if oi <= 0 and gamma <= 0:
            continue
        entries.append({
            "strike": int(strike_value) if strike_value.is_integer() else strike_value,
            "expiry": str(getattr(metric, "expiry", "") or ""),
            "open_interest": round(oi, 4),
            "absolute_gamma_exposure": round(gamma, 4),
            "net_gex": round(float(getattr(metric, "net_gex", 0) or 0), 4),
        })

    entries.sort(key=lambda item: (item["open_interest"], item["absolute_gamma_exposure"]), reverse=True)
    selected = entries[: max(1, int(max_levels))]
    levels = sorted({float(item["strike"]) for item in selected})
    if not levels:
        lower = upper = None
    elif len(levels) == 1:
        lower = upper = levels[0]
    else:
        gaps = [right - left for left, right in zip(levels, levels[1:]) if right > left]
        step = min(gaps) if gaps else 50.0
        lower = levels[0] - step / 2
        upper = levels[-1] + step / 2
    return {
        "label": CONCENTRATION_LABEL,
        "version": "oi_gamma_concentration_zone.v1",
        "scope": "selected_expiry_window_main_analysis_range",
        "selected_expiries": list(selected_expiries),
        "levels": selected,
        "strike_levels": [int(level) if level.is_integer() else level for level in levels],
        "lower": int(lower) if isinstance(lower, float) and lower.is_integer() else lower,
        "upper": int(upper) if isinstance(upper, float) and upper.is_integer() else upper,
        "selection": "top_open_interest_then_absolute_model_gamma_exposure",
        "dealer_position_unknown": True,
        "limitations": [
            "OI/Gamma cluster is a public-data concentration descriptor, not a dealer position estimate.",
            "Only the selected expiry window and main analysis strike range are included.",
        ],
    }


__all__ = [
    "CONCENTRATION_LABEL",
    "GAMMA_FLIP_LABEL",
    "GEX_SEMANTICS_VERSION",
    "build_gex_semantics",
    "build_oi_gamma_concentration_zone",
    "signed_gex_components",
]
