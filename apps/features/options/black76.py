"""Black-76 option pricing, Greeks, and GEX engine for CME gold options."""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from statistics import median

from apps.features.options.normalize import NormalizedOptionRow

CONTRACT_MULTIPLIER = 100
DEFAULT_R = 0.0
IV_SIGMA_MIN = 0.01
IV_SIGMA_MAX = 3.0
GEX_GRID_MIN = 3500
GEX_GRID_MAX = 5500
GEX_GRID_STEP = 50

_SQRT_2 = math.sqrt(2.0)
_MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}


def expiry_sort_key(expiry: str) -> tuple[int, int, str]:
    """Return a chronological sort key for CME month-code expiries."""
    normalized = expiry.strip().upper()
    try:
        year, month = _parse_expiry(normalized)
    except (KeyError, ValueError, IndexError):
        return 9999, 99, normalized
    return year, month, normalized


def sort_expiry_codes(expiries: list[str] | set[str] | tuple[str, ...]) -> list[str]:
    """Sort unique expiry codes chronologically, with lexical fallback."""
    unique = {expiry.strip().upper() for expiry in expiries if expiry and expiry.strip()}
    return sorted(unique, key=expiry_sort_key)


def compute_iv_skew(
    normalized_rows: list[NormalizedOptionRow],
    F: float,
    T: float,
    r: float = DEFAULT_R,
) -> dict:
    """Compute IV smile/skew metrics for a single expiry.

    Uses Black-76 theoretical delta magnitude to select strikes closest
    to target absolute deltas: ATM (0.50), 25-delta (0.25), 10-delta (0.10).
    Returns None for metrics where suitable data is unavailable.
    """
    iv_entries: list[tuple[float, float, str]] = []  # (abs_delta, iv, option_type)

    for row in normalized_rows:
        if row.settlement is None or F <= 0 or T <= 0:
            continue
        sigma, _low_confidence = implied_vol_black76(
            row.settlement, F, row.strike, T, row.option_type, r=r,
        )
        if sigma is None:
            continue
        delta_mag = black76_delta(F, row.strike, sigma, T, row.option_type, r=r)
        iv_entries.append((delta_mag, sigma, row.option_type))

    if not iv_entries:
        return {
            "atm_iv": None,
            "call_25d_iv": None,
            "put_25d_iv": None,
            "skew_25d": None,
            "call_10d_iv": None,
            "put_10d_iv": None,
            "tail_skew_10d": None,
            "interpretation": "数据不足：无可计算 IV 的期权",
        }

    def _closest(target: float, option_type: str | None = None) -> float | None:
        filtered = [(d, iv) for d, iv, ot in iv_entries
                    if option_type is None or ot == option_type]
        if not filtered:
            return None
        best = min(filtered, key=lambda x: abs(x[0] - target))
        return best[1]

    atm_iv = _closest(0.50)
    call_25d_iv = _closest(0.25, "CALL")
    put_25d_iv = _closest(0.25, "PUT")
    call_10d_iv = _closest(0.10, "CALL")
    put_10d_iv = _closest(0.10, "PUT")

    skew_25d = (
        round(put_25d_iv - call_25d_iv, 6)
        if call_25d_iv is not None and put_25d_iv is not None
        else None
    )
    tail_skew_10d = (
        round(put_10d_iv - call_10d_iv, 6)
        if call_10d_iv is not None and put_10d_iv is not None
        else None
    )

    missing: list[str] = []
    if atm_iv is None:
        missing.append("ATM")
    if call_25d_iv is None:
        missing.append("25D Call")
    if put_25d_iv is None:
        missing.append("25D Put")
    if call_10d_iv is None:
        missing.append("10D Call")
    if put_10d_iv is None:
        missing.append("10D Put")

    interpretation_parts: list[str] = []
    if skew_25d is not None:
        direction = "Put 偏贵（下行保护溢价）" if skew_25d > 0 else "Call 偏贵（上行溢价）"
        interpretation_parts.append(f"25D Skew={skew_25d:.4f}, {direction}")
    if tail_skew_10d is not None:
        direction = "左尾更贵（崩盘保护溢价）" if tail_skew_10d > 0 else "右尾更贵（上行弹性溢价）"
        interpretation_parts.append(f"10D Tail Skew={tail_skew_10d:.4f}, {direction}")
    if missing:
        interpretation_parts.append(f"缺失指标: {', '.join(missing)}")

    return {
        "atm_iv": round(atm_iv, 6) if atm_iv is not None else None,
        "call_25d_iv": round(call_25d_iv, 6) if call_25d_iv is not None else None,
        "put_25d_iv": round(put_25d_iv, 6) if put_25d_iv is not None else None,
        "skew_25d": skew_25d,
        "call_10d_iv": round(call_10d_iv, 6) if call_10d_iv is not None else None,
        "put_10d_iv": round(put_10d_iv, 6) if put_10d_iv is not None else None,
        "tail_skew_10d": tail_skew_10d,
        "interpretation": "; ".join(interpretation_parts) if interpretation_parts else "IV Skew 数据完整",
    }


@dataclass(frozen=True)
class OptionExposure:
    """Per-row exposure outputs for a normalized CME option row."""

    strike: int
    option_type: str
    iv: float | None
    gamma: float
    gex_1pct: float
    delta_exposure: float
    vega_exposure_1vol: float
    theta_exposure_day: float
    method: str
    data_quality: list[str]
    trade_date: str = ""
    expiry: str = ""


@dataclass(frozen=True)
class NetGEXResult:
    """Grid result for structural NetGEX and zero-axis estimation."""

    price_grid: list[float]
    net_gex_values: list[float]
    gamma_zero: float | None
    gamma_zero_method: str
    warnings: list[str]


@dataclass(frozen=True)
class ForwardContext:
    """Forward-price and expiry context used by the quant engine."""

    F: float | None
    T: float
    expiry_date: dt.date
    warnings: list[str]
    method: str


def norm_pdf(x: float) -> float:
    """Return the standard normal probability density."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def norm_cdf(x: float) -> float:
    """Return the standard normal cumulative distribution."""
    return 0.5 * (1.0 + math.erf(x / _SQRT_2))


def black76_d1_d2(F: float, K: float, sigma: float, T: float) -> tuple[float, float]:
    """Return the Black-76 d1 and d2 terms."""
    if F <= 0 or K <= 0 or sigma <= 0 or T <= 0:
        return float("nan"), float("nan")
    root_t = math.sqrt(T)
    vol_term = sigma * root_t
    d1 = (math.log(F / K) + 0.5 * sigma * sigma * T) / vol_term
    return d1, d1 - vol_term


def _discount_factor(T: float, r: float) -> float:
    return math.exp(-r * T)


def _option_kind(option_type: str) -> str:
    return "CALL" if option_type.upper() == "CALL" else "PUT"


def black76_price(F: float, K: float, sigma: float, T: float, option_type: str, r: float = DEFAULT_R) -> float:
    """Return the Black-76 call or put price."""
    if F <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        intrinsic = max(F - K, 0.0) if _option_kind(option_type) == "CALL" else max(K - F, 0.0)
        return _discount_factor(T, r) * intrinsic

    d1, d2 = black76_d1_d2(F, K, sigma, T)
    d = _discount_factor(T, r)
    if _option_kind(option_type) == "CALL":
        return d * (F * norm_cdf(d1) - K * norm_cdf(d2))
    return d * (K * norm_cdf(-d2) - F * norm_cdf(-d1))


def black76_delta(F: float, K: float, sigma: float, T: float, option_type: str, r: float = DEFAULT_R) -> float:
    """Return the magnitude of Black-76 delta for the requested option type."""
    if F <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        return 0.0
    d1, _ = black76_d1_d2(F, K, sigma, T)
    d = _discount_factor(T, r)
    if _option_kind(option_type) == "CALL":
        return d * norm_cdf(d1)
    return d * norm_cdf(-d1)


def black76_gamma(F: float, K: float, sigma: float, T: float, r: float = DEFAULT_R) -> float:
    """Return Black-76 gamma."""
    if F <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        return 0.0
    d1, _ = black76_d1_d2(F, K, sigma, T)
    return _discount_factor(T, r) * norm_pdf(d1) / (F * sigma * math.sqrt(T))


def black76_vega(F: float, K: float, sigma: float, T: float, r: float = DEFAULT_R) -> float:
    """Return raw Black-76 vega per 100% volatility."""
    if F <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        return 0.0
    d1, _ = black76_d1_d2(F, K, sigma, T)
    return _discount_factor(T, r) * F * norm_pdf(d1) * math.sqrt(T)


def black76_theta_annual(F: float, K: float, sigma: float, T: float, option_type: str, r: float = DEFAULT_R) -> float:
    """Return annualized Black-76 theta."""
    if F <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        return 0.0
    d1, d2 = black76_d1_d2(F, K, sigma, T)
    d = _discount_factor(T, r)
    time_decay = -(d * F * norm_pdf(d1) * sigma) / (2.0 * math.sqrt(T))
    kind = _option_kind(option_type)
    if kind == "CALL":
        return time_decay + r * d * K * norm_cdf(d2) - r * d * F * norm_cdf(d1)
    return time_decay - r * d * K * norm_cdf(-d2) + r * d * F * norm_cdf(-d1)


def implied_vol_black76(
    settlement: float | None,
    F: float,
    K: float,
    T: float,
    option_type: str,
    r: float = DEFAULT_R,
    tol: float = 1e-6,
    max_iter: int = 100,
) -> tuple[float | None, bool]:
    """Invert Black-76 price to implied volatility by bisection."""
    if settlement is None or F <= 0 or K <= 0 or T <= 0 or settlement < 0:
        return None, True

    low_confidence = settlement < 0.5
    low = IV_SIGMA_MIN
    high = IV_SIGMA_MAX
    low_price = black76_price(F, K, low, T, option_type, r=r)
    high_price = black76_price(F, K, high, T, option_type, r=r)

    if settlement < low_price - tol or settlement > high_price + tol:
        return None, True

    lo = low
    hi = high
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        price = black76_price(F, K, mid, T, option_type, r=r)
        if abs(price - settlement) <= tol or (hi - lo) <= tol:
            return mid, low_confidence
        if price > settlement:
            hi = mid
        else:
            lo = mid

    return None, True


def infer_forward_price(
    normalized_rows: list[NormalizedOptionRow],
    trade_date: str,
    expiry: str,
) -> tuple[float | None, list[str]]:
    """Infer the forward price from paired call-put settlements."""
    warnings: list[str] = []
    call_by_strike: dict[int, float] = {}
    put_by_strike: dict[int, float] = {}

    for row in normalized_rows:
        if row.trade_date != trade_date or row.expiry != expiry or row.settlement is None:
            continue
        if row.option_type == "CALL":
            call_by_strike[row.strike] = row.settlement
        elif row.option_type == "PUT":
            put_by_strike[row.strike] = row.settlement

    estimates: list[float] = []
    for strike in sorted(set(call_by_strike) & set(put_by_strike)):
        call_settle = call_by_strike[strike]
        put_settle = put_by_strike[strike]
        estimate = strike + (call_settle - put_settle)
        if estimate <= 0:
            continue
        if abs(call_settle - put_settle) > estimate * 0.5:
            continue
        estimates.append(estimate)

    if not estimates:
        warnings.append("forward_price_no_valid_pairs")
        return None, warnings

    if len(estimates) < 3:
        warnings.append("forward_price_low_confidence")

    return float(median(estimates)), warnings


def _last_day_of_month(year: int, month: int) -> dt.date:
    if month == 12:
        return dt.date(year, 12, 31)
    return dt.date(year, month + 1, 1) - dt.timedelta(days=1)


def _is_business_day(value: dt.date) -> bool:
    return value.weekday() < 5


def _previous_business_day(value: dt.date) -> dt.date:
    current = value - dt.timedelta(days=1)
    while not _is_business_day(current):
        current -= dt.timedelta(days=1)
    return current


def _subtract_business_days(value: dt.date, business_days: int) -> dt.date:
    current = value
    for _ in range(business_days):
        current = _previous_business_day(current)
    return current


def estimate_cme_gold_expiry(year: int, month: int) -> dt.date:
    """Estimate CME gold option expiry from the delivery month."""
    if month == 1:
        prior_year = year - 1
        prior_month = 12
    else:
        prior_year = year
        prior_month = month - 1
    prior_month_end = _last_day_of_month(prior_year, prior_month)
    last_business_day = prior_month_end
    while not _is_business_day(last_business_day):
        last_business_day -= dt.timedelta(days=1)
    return _subtract_business_days(last_business_day, 4)


def _parse_expiry(expiry: str) -> tuple[int, int]:
    normalized = expiry.strip().upper()
    if len(normalized) < 5:
        raise ValueError(f"invalid expiry format: {expiry!r}")
    month = _MONTHS[normalized[:3]]
    year = 2000 + int(normalized[3:5])
    return year, month


def calc_time_to_expiry(
    trade_date: str,
    expiry_date: dt.date | None = None,
    expiry: str | None = None,
) -> tuple[float, dt.date, list[str]]:
    """Calculate year fraction to expiry with an optional estimated expiry date."""
    warnings: list[str] = []
    trade = dt.date.fromisoformat(trade_date)

    if expiry_date is not None:
        actual_expiry = expiry_date
    elif expiry is not None:
        year, month = _parse_expiry(expiry)
        actual_expiry = estimate_cme_gold_expiry(year, month)
        warnings.append("expiry_date_estimated_from_delivery_month")
    else:
        actual_expiry = trade
        warnings.append("expiry_date_missing")

    delta_days = (actual_expiry - trade).days
    T = delta_days / 365.0
    if T <= 0:
        T = 1.0 / 365.0
        warnings.append("time_to_expiry_floor_applied")
    return T, actual_expiry, warnings


def _signed_delta_from_row(row: NormalizedOptionRow) -> float:
    if row.delta is not None:
        return row.delta
    if row.delta_raw is None:
        return 0.0
    return -row.delta_raw if row.option_type == "PUT" else row.delta_raw


def compute_exposure(row: NormalizedOptionRow, F: float, T: float, r: float = DEFAULT_R) -> OptionExposure:
    """Compute per-row exposures using Black-76 or a Gamma proxy fallback."""
    data_quality = list(row.data_quality)
    delta_signed = _signed_delta_from_row(row)
    oi = row.open_interest
    strike = row.strike

    if row.settlement is not None and F > 0 and T > 0:
        sigma, low_confidence = implied_vol_black76(row.settlement, F, strike, T, row.option_type, r=r)
        if sigma is not None:
            gamma = black76_gamma(F, strike, sigma, T, r=r)
            delta_mag = black76_delta(F, strike, sigma, T, row.option_type, r=r)
            delta = delta_mag if row.option_type == "CALL" else -delta_mag
            vega = black76_vega(F, strike, sigma, T, r=r)
            theta_annual = black76_theta_annual(F, strike, sigma, T, row.option_type, r=r)
            method = "black76"
            if low_confidence:
                data_quality.append("low_confidence_iv")
            if sigma is not None:
                data_quality.append("iv_inferred")
            gex_1pct = gamma * oi * CONTRACT_MULTIPLIER * F * F * 0.01
            delta_exposure = delta * oi * CONTRACT_MULTIPLIER * F
            vega_exposure_1vol = vega * oi * CONTRACT_MULTIPLIER * 0.01
            theta_exposure_day = (theta_annual / 365.0) * oi * CONTRACT_MULTIPLIER
            return OptionExposure(
                strike=strike,
                option_type=row.option_type,
                iv=sigma,
                gamma=gamma,
                gex_1pct=gex_1pct,
                delta_exposure=delta_exposure,
                vega_exposure_1vol=vega_exposure_1vol,
                theta_exposure_day=theta_exposure_day,
                method=method,
                data_quality=data_quality,
                trade_date=row.trade_date,
                expiry=row.expiry,
            )

    proxy_delta = abs(row.delta_raw if row.delta_raw is not None else delta_signed)
    proxy_delta = max(0.0, min(proxy_delta, 1.0))
    gamma_proxy = proxy_delta * (1.0 - proxy_delta)
    data_quality.append("gamma_proxy_used")
    gex_1pct = gamma_proxy * oi * CONTRACT_MULTIPLIER * F * F * 0.01
    delta_exposure = delta_signed * oi * CONTRACT_MULTIPLIER * F
    return OptionExposure(
        strike=strike,
        option_type=row.option_type,
        iv=None,
        gamma=gamma_proxy,
        gex_1pct=gex_1pct,
        delta_exposure=delta_exposure,
        vega_exposure_1vol=0.0,
        theta_exposure_day=0.0,
        method="proxy",
        data_quality=data_quality,
        trade_date=row.trade_date,
        expiry=row.expiry,
    )


def compute_exposures(
    rows: list[NormalizedOptionRow],
    F: float,
    T: float,
    r: float = DEFAULT_R,
) -> list[OptionExposure]:
    """Compute per-row exposures for a batch of normalized rows."""
    return [compute_exposure(row, F, T, r=r) for row in rows]


def compute_netgex_grid(
    rows: list[NormalizedOptionRow],
    F: float,
    T: float,
    r: float = DEFAULT_R,
    grid_min: int = GEX_GRID_MIN,
    grid_max: int = GEX_GRID_MAX,
    grid_step: int = GEX_GRID_STEP,
) -> NetGEXResult:
    """Compute a structural NetGEX grid and interpolate the gamma zero."""
    warnings: list[str] = []
    price_grid = [float(price) for price in range(grid_min, grid_max + 1, grid_step)]
    net_gex_values: list[float] = []

    row_specs: list[tuple[NormalizedOptionRow, float, float]] = []
    skipped_rows = 0
    for row in rows:
        if row.settlement is None or F <= 0:
            skipped_rows += 1
            continue
        row_T = T
        if row.trade_date and row.expiry:
            try:
                row_T, _actual_expiry, _warnings = calc_time_to_expiry(row.trade_date, expiry=row.expiry)
            except ValueError:
                row_T = T
        if row_T <= 0:
            skipped_rows += 1
            continue
        sigma, _low_confidence = implied_vol_black76(row.settlement, F, row.strike, row_T, row.option_type, r=r)
        if sigma is None:
            skipped_rows += 1
            continue
        row_specs.append((row, sigma, row_T))

    if skipped_rows:
        warnings.append("grid_skipped_rows_without_iv")

    for price in price_grid:
        call_gex = 0.0
        put_gex = 0.0
        for row, sigma, row_T in row_specs:
            gamma = black76_gamma(price, row.strike, sigma, row_T, r=r)
            gex = gamma * row.open_interest * CONTRACT_MULTIPLIER * price * price * 0.01
            if row.option_type == "CALL":
                call_gex += gex
            else:
                put_gex += gex
        net_gex_values.append(call_gex - put_gex)

    gamma_zero = None
    gamma_zero_method = "none"
    for index in range(1, len(price_grid)):
        left_value = net_gex_values[index - 1]
        right_value = net_gex_values[index]
        if left_value == 0.0:
            gamma_zero = price_grid[index - 1]
            gamma_zero_method = "linear_interpolation"
            break
        if right_value == 0.0:
            gamma_zero = price_grid[index]
            gamma_zero_method = "linear_interpolation"
            break
        if left_value * right_value < 0:
            left_price = price_grid[index - 1]
            right_price = price_grid[index]
            gamma_zero = left_price + (0.0 - left_value) * (right_price - left_price) / (right_value - left_value)
            gamma_zero_method = "linear_interpolation"
            break

    return NetGEXResult(
        price_grid=price_grid,
        net_gex_values=net_gex_values,
        gamma_zero=gamma_zero,
        gamma_zero_method=gamma_zero_method,
        warnings=warnings,
    )


__all__ = [
    "CONTRACT_MULTIPLIER",
    "DEFAULT_R",
    "GEX_GRID_MAX",
    "GEX_GRID_MIN",
    "GEX_GRID_STEP",
    "IV_SIGMA_MAX",
    "IV_SIGMA_MIN",
    "ForwardContext",
    "NetGEXResult",
    "OptionExposure",
    "compute_iv_skew",
    "expiry_sort_key",
    "black76_d1_d2",
    "black76_delta",
    "black76_gamma",
    "black76_price",
    "black76_theta_annual",
    "black76_vega",
    "calc_time_to_expiry",
    "compute_exposure",
    "compute_exposures",
    "compute_netgex_grid",
    "estimate_cme_gold_expiry",
    "implied_vol_black76",
    "infer_forward_price",
    "norm_cdf",
    "norm_pdf",
    "sort_expiry_codes",
]
