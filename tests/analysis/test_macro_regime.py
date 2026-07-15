"""P4-05: Macro regime engine tests."""

from __future__ import annotations

import pytest

from apps.analysis.macro.regime import (
    _change_conditions,
    _direction,
    _eval_dxy,
    _eval_liquidity_price,
    _eval_liquidity_quantity,
    _eval_real_yield,
    _extract_change,
    _extract_value,
    _render_gold_interpretation,
    classify_macro_regime,
)


# ── Unit: helpers ─────────────────────────────────────────────────────


def test_direction_falling():
    assert _direction(-0.05) == "falling"


def test_direction_rising():
    assert _direction(0.05) == "rising"


def test_direction_flat():
    assert _direction(0.0) == "flat"


def test_direction_none():
    assert _direction(None) == "unknown"


def test_extract_value_found():
    ind = {"DGS10": {"value": 4.5, "daily_change": 0.02}}
    assert _extract_value(ind, ("DGS10", "US10Y")) == 4.5


def test_extract_value_not_found():
    ind = {"UNKNOWN": {"value": 1.0}}
    assert _extract_value(ind, ("DGS10",)) is None


def test_extract_change_found():
    ind = {"DGS10": {"value": 4.5, "daily_change": 0.02}}
    assert _extract_change(ind, ("DGS10",)) == 0.02


def test_extract_change_weekly_fallback():
    ind = {"DGS10": {"value": 4.5, "weekly_change": -0.03}}
    assert _extract_change(ind, ("DGS10",)) == -0.03


# ── Unit: regime phases ───────────────────────────────────────────────


def test_regime_rate_pressure():
    """Rising real yields + rising DXY + rising rates → rate_pressure."""
    indicators = {
        "REAL_10Y": {"value": 2.0, "daily_change": 0.15, "weekly_change": 0.30},
        "DXY": {"value": 106.0, "daily_change": 0.2, "weekly_change": 0.8},
        "DGS2": {"value": 5.0, "daily_change": 0.10},
        "DGS10": {"value": 4.55, "daily_change": 0.08},
        "T10YIE": {"value": 2.3, "daily_change": 0.05},
        "ON_RRP_USAGE": {"value": 500.0, "daily_change": 20.0},
        "TGA": {"value": 600.0, "daily_change": 30.0},
        "SOFR": {"value": 5.3, "daily_change": 0.01},
        "EFFR": {"value": 5.25, "daily_change": 0.01},
        "IORB": {"value": 5.4, "daily_change": 0.0},
    }
    result = classify_macro_regime(indicators)
    assert result["market_phase"] == "rate_pressure"
    assert result["confidence"] > 0.5


def test_regime_liquidity_crunch():
    """10Y stress zone + DXY surge + real-yield pressure → liquidity_crunch."""
    indicators = {
        "REAL_10Y": {"value": 2.0, "daily_change": 0.15, "weekly_change": 0.30},
        "DXY": {"value": 106.0, "daily_change": 0.5, "weekly_change": 1.5},
        "DGS2": {"value": 5.0, "daily_change": 0.10},
        "DGS10": {"value": 4.8, "daily_change": 0.08},
        "T10YIE": {"value": 2.3, "daily_change": 0.05},
        "ON_RRP_USAGE": {"value": 500.0, "daily_change": 20.0},
        "TGA": {"value": 600.0, "daily_change": 30.0},
        "SOFR": {"value": 5.3, "daily_change": 0.01},
        "EFFR": {"value": 5.25, "daily_change": 0.01},
        "IORB": {"value": 5.4, "daily_change": 0.0},
    }
    result = classify_macro_regime(indicators)
    assert result["market_phase"] == "liquidity_crunch"


def test_regime_monetary_credit_repricing():
    """Gold strength despite rates/USD pressure → monetary_credit_repricing."""
    indicators = {
        "XAUUSD": {"value": 2450.0, "daily_change": 25.0},
        "DXY": {"value": 103.0, "daily_change": 0.2},
        "DGS2": {"value": 4.7, "daily_change": 0.05},
        "DGS10": {"value": 4.45, "daily_change": 0.08},
        "T10YIE": {"value": 2.3, "daily_change": 0.02},
        "ON_RRP_USAGE": {"value": 300.0, "daily_change": -5.0},
        "TGA": {"value": 600.0, "daily_change": 5.0},
        "SOFR": {"value": 4.9, "daily_change": 0.0},
        "EFFR": {"value": 4.9, "daily_change": 0.0},
        "IORB": {"value": 5.0, "daily_change": 0.0},
    }
    result = classify_macro_regime(indicators)
    assert result["market_phase"] == "monetary_credit_repricing"


def test_regime_trend_tailwind():
    """Falling real yields + falling DXY + liquidity easing → trend_tailwind."""
    indicators = {
        "REAL_10Y": {"value": 1.2, "daily_change": -0.20, "weekly_change": -0.40},
        "DXY": {"value": 100.0, "daily_change": -0.8, "weekly_change": -2.0},
        "DGS2": {"value": 3.8, "daily_change": -0.15},
        "DGS10": {"value": 3.5, "daily_change": -0.12},
        "T10YIE": {"value": 2.3, "daily_change": -0.05},
        "ON_RRP_USAGE": {"value": 200.0, "daily_change": -50.0},
        "TGA": {"value": 400.0, "daily_change": -30.0},
        "SOFR": {"value": 4.3, "daily_change": -0.02},
        "EFFR": {"value": 4.35, "daily_change": -0.02},
        "IORB": {"value": 4.4, "daily_change": 0.0},
    }
    result = classify_macro_regime(indicators)
    assert result["market_phase"] == "trend_tailwind"
    assert result["confidence"] > 0.5


def test_regime_requires_dxy_direction_to_confirm_trend_tailwind():
    """A high easing score cannot replace confirmation from the dollar."""
    indicators = {
        "REAL_10Y": {"value": 1.2, "daily_change": -0.20, "weekly_change": -0.40},
        "DXY": {"value": 100.0},
        "DGS2": {"value": 3.8, "daily_change": -0.15},
        "DGS10": {"value": 3.5, "daily_change": -0.12},
        "T10YIE": {"value": 2.3, "daily_change": -0.05},
        "ON_RRP_USAGE": {"value": 200.0, "daily_change": -50.0},
        "TGA": {"value": 400.0, "daily_change": -30.0},
        "SOFR": {"value": 4.3, "daily_change": -0.02},
        "EFFR": {"value": 4.35, "daily_change": -0.02},
        "IORB": {"value": 4.4, "daily_change": 0.0},
    }

    result = classify_macro_regime(indicators)

    assert result["drivers"]["real_yield"]["direction"] == "falling"
    assert result["drivers"]["dxy"]["direction"] == "unknown"
    assert result["market_phase"] == "transition_release"


def test_regime_transition_release():
    """Mixed signals → transition_release."""
    indicators = {
        "REAL_10Y": {"value": 1.6, "daily_change": 0.02, "weekly_change": -0.05},
        "DXY": {"value": 103.0, "daily_change": -0.1, "weekly_change": 0.2},
        "DGS2": {"value": 4.5, "daily_change": -0.02},
        "DGS10": {"value": 4.2, "daily_change": 0.01},
        "T10YIE": {"value": 2.4, "daily_change": 0.0},
        "ON_RRP_USAGE": {"value": 350.0, "daily_change": -10.0},
        "TGA": {"value": 500.0, "daily_change": 5.0},
        "SOFR": {"value": 4.8, "daily_change": 0.0},
        "EFFR": {"value": 4.83, "daily_change": 0.0},
        "IORB": {"value": 4.9, "daily_change": 0.0},
    }
    result = classify_macro_regime(indicators)
    assert result["market_phase"] == "transition_release"
    assert 0.0 <= result["confidence"] <= 1.0


def test_regime_unavailable_empty():
    """Empty indicators → unavailable."""
    result = classify_macro_regime({})
    assert result["market_phase"] == "unavailable"
    assert result["confidence"] == 0.0


def test_regime_unavailable_minimal():
    """Only one indicator → unavailable."""
    result = classify_macro_regime({"DXY": {"value": 100.0}})
    assert result["market_phase"] == "unavailable"


# ── Unit: driver evaluators ────────────────────────────────────────────


def test_eval_real_yield_direct():
    ind = {"REAL_10Y": {"value": 1.8, "daily_change": -0.10, "weekly_change": -0.20}}
    result = _eval_real_yield(ind)
    assert result["status"] == "available"
    assert result["direction"] == "falling"


def test_eval_real_yield_computed():
    ind = {
        "DGS10": {"value": 4.5, "daily_change": -0.05},
        "T10YIE": {"value": 2.3, "daily_change": -0.02},
    }
    result = _eval_real_yield(ind)
    assert result["status"] == "available"
    assert result["value"] == pytest.approx(2.2)
    assert result["source"] == "US10Y - T10YIE (computed_main)"


def test_eval_real_yield_unavailable():
    result = _eval_real_yield({})
    assert result["status"] == "unavailable"


def test_eval_dxy():
    ind = {"DXY": {"value": 104.5, "daily_change": 0.3}}
    result = _eval_dxy(ind)
    assert result["status"] == "available"
    assert result["direction"] == "rising"


def test_eval_liquidity_quantity_easing():
    ind = {
        "ON_RRP_USAGE": {"value": 400, "daily_change": -30},
        "TGA": {"value": 600, "daily_change": -20},
    }
    result = _eval_liquidity_quantity(ind)
    assert result["trend"] == "easing"


def test_eval_liquidity_quantity_unavailable():
    result = _eval_liquidity_quantity({})
    assert result["status"] == "unavailable"


def test_eval_liquidity_price_sofr_effr_spread():
    ind = {
        "SOFR": {"value": 5.30},
        "EFFR": {"value": 5.33},
    }
    result = _eval_liquidity_price(ind)
    assert result["status"] == "available"
    assert result["sofr_effr_spread"] == pytest.approx(-0.03)


# ── Unit: interpretation ──────────────────────────────────────────────


def test_gold_interpretation_rate_pressure():
    gi = _render_gold_interpretation("rate_pressure", {}, [])
    assert "MACRO HEADWIND" in gi


def test_gold_interpretation_trend_tailwind():
    gi = _render_gold_interpretation("trend_tailwind", {}, ["Real yields falling → bullish for gold"])
    assert "MACRO TAILWIND" in gi
    assert "Real yields falling" in gi


def test_gold_interpretation_transition():
    gi = _render_gold_interpretation("transition_release", {}, [])
    assert "MACRO TRANSITION" in gi


def test_gold_interpretation_unavailable():
    gi = _render_gold_interpretation("unavailable", {}, [])
    assert "Insufficient macro data" in gi


def test_gold_interpretation_liquidity_crunch():
    gi = _render_gold_interpretation("liquidity_crunch", {}, [])
    assert "LIQUIDITY CRUNCH" in gi


def test_gold_interpretation_monetary_credit_repricing():
    gi = _render_gold_interpretation("monetary_credit_repricing", {}, [])
    assert "MONETARY CREDIT REPRICING" in gi


# ── Unit: change conditions ────────────────────────────────────────────


def test_change_conditions_rate_pressure():
    conds = _change_conditions("rate_pressure")
    assert any("US10Y - T10YIE turns lower" in c for c in conds)


def test_change_conditions_trend_tailwind():
    conds = _change_conditions("trend_tailwind")
    assert any("US10Y - T10YIE begins rising" in c for c in conds)


# ── Integration: classify_macro_regime returns all fields ──────────────


def test_classify_returns_all_fields():
    indicators = {
        "DGS10": {"value": 4.2, "daily_change": -0.05},
        "T10YIE": {"value": 2.3, "daily_change": -0.02},
        "DXY": {"value": 103.0, "daily_change": -0.1},
        "DGS2": {"value": 4.3, "daily_change": -0.02},
    }
    result = classify_macro_regime(indicators)
    assert "market_phase" in result
    assert "confidence" in result
    assert "drivers" in result
    assert "gold_interpretation" in result
    assert "change_conditions" in result
    assert "source_refs" in result
    assert isinstance(result["drivers"], dict)
    for key in ("real_yield", "dxy", "us02y", "us10y", "breakeven", "liquidity_quantity", "liquidity_price"):
        assert key in result["drivers"]
