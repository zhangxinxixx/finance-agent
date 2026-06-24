"""Tests for the Black-76 option pricing and GEX engine."""

from __future__ import annotations

import datetime as dt

import pytest

from apps.features.options.black76 import (
    CONTRACT_MULTIPLIER,
    black76_delta,
    black76_gamma,
    black76_price,
    black76_theta_annual,
    black76_vega,
    calc_time_to_expiry,
    compute_exposure,
    compute_netgex_grid,
    estimate_cme_gold_expiry,
    implied_vol_black76,
    infer_forward_price,
    norm_cdf,
    norm_pdf,
    sort_expiry_codes,
)
from apps.features.options.normalize import normalize_option_rows


def _make_row(
    *,
    trade_date: str = "2026-05-06",
    report_date: str = "2026-05-06",
    product_code: str = "OG",
    expiry: str = "JUN26",
    strike: int = 4200,
    option_type: str = "CALL",
    settlement: float | None = 100.0,
    delta: float | None = 0.5,
    open_interest: int | None = 1000,
    oi_change: int | None = 10,
    total_volume: int | None = 200,
    block_volume: int | None = 20,
    pnt_volume: int | None = 5,
    globex_volume: int | None = 100,
    outcry_volume: int | None = 50,
    exercises: int | None = 0,
    pt_change: float | None = 1.0,
) -> dict:
    return {
        "trade_date": trade_date,
        "report_date": report_date,
        "product_code": product_code,
        "expiry": expiry,
        "strike": strike,
        "option_type": option_type,
        "settlement": settlement,
        "delta": delta,
        "open_interest": open_interest,
        "oi_change": oi_change,
        "total_volume": total_volume,
        "block_volume": block_volume,
        "pnt_volume": pnt_volume,
        "globex_volume": globex_volume,
        "outcry_volume": outcry_volume,
        "exercises": exercises,
        "pt_change": pt_change,
    }


def _normalized_row(**kwargs):
    return normalize_option_rows([_make_row(**kwargs)])[0][0]


def _price_for_sigma(F: float, K: float, sigma: float, T: float, option_type: str) -> float:
    return black76_price(F, K, sigma, T, option_type)


def test_normal_distribution_sanity() -> None:
    assert abs(norm_pdf(0.0) - 0.3989422804) < 1e-6
    assert abs(norm_cdf(0.0) - 0.5) < 1e-9
    assert abs(norm_cdf(1.96) - 0.9750021049) < 1e-4


def test_black76_price_sanity() -> None:
    F = 4200.0
    K = 4200.0
    sigma = 0.2
    T = 0.25

    call_price = black76_price(F, K, sigma, T, "CALL")
    put_price = black76_price(F, K, sigma, T, "PUT")

    expected_atm = F * sigma * (T**0.5) * norm_pdf(0.0)
    assert call_price > 0
    assert abs(call_price - expected_atm) / expected_atm < 0.05
    assert abs(call_price - put_price) < 1e-9

    deep_itm = black76_price(4200.0, 3000.0, 0.2, 0.25, "CALL")
    deep_otm = black76_price(4200.0, 5500.0, 0.2, 0.25, "CALL")
    assert abs(deep_itm - 1200.0) < 5.0
    assert deep_otm < 1.0

    parity_gap = black76_price(F, K, sigma, T, "CALL") - black76_price(F, K, sigma, T, "PUT")
    assert abs(parity_gap - (F - K)) < 1e-6


def test_black76_greeks_sanity() -> None:
    F = 4200.0
    K = 4200.0
    sigma = 0.2
    T = 0.25

    call_delta = black76_delta(F, K, sigma, T, "CALL")
    put_delta = black76_delta(F, K, sigma, T, "PUT")

    assert 0.0 < call_delta < 1.0
    assert 0.0 < put_delta < 1.0
    assert abs(call_delta - 0.5) < 0.1
    assert black76_gamma(F, K, sigma, T) > 0.0
    assert black76_vega(F, K, sigma, T) > 0.0
    assert black76_theta_annual(F, K, sigma, T, "CALL") < 0.0


def test_black76_iv_round_trip() -> None:
    F = 4200.0
    K = 4300.0
    T = 0.35

    for sigma in (0.15, 0.25, 0.50):
        for option_type in ("CALL", "PUT"):
            settlement = _price_for_sigma(F, K, sigma, T, option_type)
            recovered, low_confidence = implied_vol_black76(settlement, F, K, T, option_type)
            assert recovered is not None
            assert abs(recovered - sigma) < 1e-4
            assert low_confidence is False


def test_forward_price_inference_from_pairs() -> None:
    trade_date = "2026-05-06"
    expiry = "JUN26"
    true_f = 4210.0
    rows = []
    for strike in (4100, 4200, 4300, 4400):
        call_settle = 50.0 + max(true_f - strike, 0.0)
        put_settle = call_settle - (true_f - strike)
        rows.append(_make_row(trade_date=trade_date, expiry=expiry, strike=strike, option_type="CALL", settlement=call_settle))
        rows.append(_make_row(trade_date=trade_date, expiry=expiry, strike=strike, option_type="PUT", settlement=put_settle))

    rows[1]["settlement"] = None

    normalized, _ = normalize_option_rows(rows, filter_strikes=False, aggregate_duplicates=False)
    inferred, warnings = infer_forward_price(normalized, trade_date, expiry)

    assert inferred is not None
    assert abs(inferred - true_f) < 1e-6
    assert "forward_price_low_confidence" not in warnings


def test_time_to_expiry_calculation() -> None:
    expiry = estimate_cme_gold_expiry(2026, 6)
    assert expiry < dt.date(2026, 6, 1)

    t_explicit, actual_expiry, warnings = calc_time_to_expiry(
        "2026-05-06",
        expiry_date=dt.date(2026, 5, 20),
    )
    assert actual_expiry == dt.date(2026, 5, 20)
    assert abs(t_explicit - (14 / 365.0)) < 1e-9
    assert warnings == []

    t_estimated, estimated_expiry, warnings2 = calc_time_to_expiry("2026-05-06", expiry="JUN26")
    assert estimated_expiry < dt.date(2026, 6, 1)
    assert t_estimated > 0.0
    assert any("estimate" in warning for warning in warnings2)


def test_gamma_proxy_fallback() -> None:
    row = normalize_option_rows([_make_row(settlement=None, delta=0.4, open_interest=1000, option_type="PUT")])[0][0]
    exposure = compute_exposure(row, F=4200.0, T=0.25)

    assert exposure.method == "proxy"
    assert "gamma_proxy_used" in exposure.data_quality
    assert exposure.trade_date == row.trade_date
    assert exposure.expiry == row.expiry
    assert exposure.gamma == pytest.approx(0.4 * (1.0 - 0.4))


def test_gamma_proxy_scales_linearly_with_open_interest() -> None:
    rows = normalize_option_rows(
        [
            _make_row(settlement=None, delta=0.4, open_interest=1000, option_type="PUT"),
            _make_row(settlement=None, delta=0.4, open_interest=2000, option_type="PUT"),
        ],
        aggregate_duplicates=False,
    )[0]

    low_oi = compute_exposure(rows[0], F=4200.0, T=0.25)
    high_oi = compute_exposure(rows[1], F=4200.0, T=0.25)

    assert low_oi.method == "proxy"
    assert high_oi.method == "proxy"
    assert high_oi.gamma == pytest.approx(low_oi.gamma)
    assert high_oi.gex_1pct == pytest.approx(low_oi.gex_1pct * 2.0)


def test_compute_exposure_integration() -> None:
    sigma = 0.25
    F = 4200.0
    T = 0.25
    settlement = black76_price(F, 4200.0, sigma, T, "CALL")
    row = normalize_option_rows([_make_row(strike=4200, settlement=settlement, delta=0.52, open_interest=1500, option_type="CALL")])[0][0]
    exposure = compute_exposure(row, F=F, T=T)

    assert exposure.method == "black76"
    assert exposure.iv is not None
    assert abs(exposure.iv - sigma) < 1e-4
    assert abs(exposure.gex_1pct - exposure.gamma * row.open_interest * CONTRACT_MULTIPLIER * F * F * 0.01) < 1e-6
    assert exposure.trade_date == row.trade_date
    assert exposure.expiry == row.expiry

    missing = normalize_option_rows([_make_row(strike=4200, settlement=None, delta=0.45, open_interest=1500, option_type="PUT")])[0][0]
    proxy = compute_exposure(missing, F=F, T=T)
    assert proxy.method == "proxy"
    assert proxy.vega_exposure_1vol == 0.0
    assert proxy.trade_date == missing.trade_date
    assert proxy.expiry == missing.expiry


def test_netgex_grid_and_gamma_zero() -> None:
    F = 4200.0
    T = 0.25
    sigma = 0.2
    rows = []
    rows.append(_normalized_row(strike=4300, option_type="CALL", settlement=black76_price(F, 4300.0, sigma, T, "CALL"), open_interest=2500))
    rows.append(_normalized_row(strike=4400, option_type="CALL", settlement=black76_price(F, 4400.0, sigma, T, "CALL"), open_interest=2000))
    rows.append(_normalized_row(strike=4100, option_type="PUT", settlement=black76_price(F, 4100.0, sigma, T, "PUT"), open_interest=2500))
    rows.append(_normalized_row(strike=4000, option_type="PUT", settlement=black76_price(F, 4000.0, sigma, T, "PUT"), open_interest=2000))

    result = compute_netgex_grid(rows, F=F, T=T)

    assert len(result.price_grid) == len(result.net_gex_values)
    assert result.gamma_zero is not None
    assert 3500 <= result.gamma_zero <= 5500
    assert result.gamma_zero_method == "linear_interpolation"
    assert result.net_gex_values[0] < 0 < result.net_gex_values[-1]


def test_netgex_grid_uses_per_expiry_time_to_expiry() -> None:
    F = 4200.0
    rows = normalize_option_rows(
        [
            _make_row(expiry="JUN26", strike=4200, settlement=100.0, open_interest=1000, option_type="CALL"),
            _make_row(expiry="JUL26", strike=4200, settlement=100.0, open_interest=1000, option_type="CALL"),
        ]
    )[0]

    result = compute_netgex_grid(
        rows,
        F=F,
        T=calc_time_to_expiry("2026-05-06", expiry="JUN26")[0],
        grid_min=4200,
        grid_max=4200,
        grid_step=50,
    )

    expected = 0.0
    for row in rows:
        row_T, _, _ = calc_time_to_expiry(row.trade_date, expiry=row.expiry)
        sigma, _ = implied_vol_black76(row.settlement, F, row.strike, row_T, row.option_type)
        assert sigma is not None
        gamma = black76_gamma(4200.0, row.strike, sigma, row_T)
        expected += gamma * row.open_interest * CONTRACT_MULTIPLIER * 4200.0 * 4200.0 * 0.01

    assert result.net_gex_values[0] == pytest.approx(expected)


def test_expiry_codes_sort_chronologically() -> None:
    assert sort_expiry_codes(["DEC26", "JUN26", "FEB27", "JUL26"]) == [
        "JUN26",
        "JUL26",
        "DEC26",
        "FEB27",
    ]
