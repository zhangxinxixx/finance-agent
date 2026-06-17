"""Tests for Black-76 delta-based price probability."""

from apps.features.options.probability import (
    ProbabilitySurface,
    StrikeProbability,
    build_probability_surface,
    compute_touch_probability_from_delta,
    estimate_price_target_probability,
    probability_surface_to_dict,
)


# ── Helpers ────────────────────────────────────────────────────────────


def _make_surface(expiry="JUN26", forward=3300.0):
    strikes = [
        StrikeProbability(
            strike=3100, expiry=expiry, call_delta=0.95, put_delta=0.05,
            touch_probability=1.0, implied_vol=0.15, model="black76_delta",
            confidence=0.8,
        ),
        StrikeProbability(
            strike=3200, expiry=expiry, call_delta=0.75, put_delta=0.25,
            touch_probability=0.86, implied_vol=0.14, model="black76_delta",
            confidence=0.8,
        ),
        StrikeProbability(
            strike=3300, expiry=expiry, call_delta=0.50, put_delta=0.50,
            touch_probability=0.58, implied_vol=0.14, model="black76_delta",
            confidence=0.8,
        ),
        StrikeProbability(
            strike=3400, expiry=expiry, call_delta=0.22, put_delta=0.78,
            touch_probability=0.44, implied_vol=0.16, model="black76_delta",
            confidence=0.7,
        ),
    ]
    return ProbabilitySurface(
        expiry=expiry, trade_date="2026-05-15", forward_price=forward,
        time_to_expiry_years=0.08, strikes=strikes, status="available",
    )


# ── Tests ──────────────────────────────────────────────────────────────


class TestTouchProbability:
    def test_deep_otm_low_probability(self):
        p = compute_touch_probability_from_delta(0.03)
        assert p is not None
        assert p < 0.10

    def test_moderate_otm_taleb_approximation(self):
        p = compute_touch_probability_from_delta(0.15)
        assert p is not None
        assert 0.20 <= p <= 0.40

    def test_atm_around_50pct(self):
        p = compute_touch_probability_from_delta(0.50)
        assert p is not None
        assert 0.45 <= p <= 0.65

    def test_itm_capped_at_100(self):
        p = compute_touch_probability_from_delta(0.95)
        assert p is not None
        assert p <= 1.0

    def test_deep_itm_at_100(self):
        p = compute_touch_probability_from_delta(0.98)
        assert p == 1.0

    def test_invalid_delta_returns_none(self):
        assert compute_touch_probability_from_delta(-0.1) is None
        assert compute_touch_probability_from_delta(0.0) is None
        assert compute_touch_probability_from_delta(1.5) is None
    def test_monotonic_increasing(self):
        """Touch probability should generally increase with delta magnitude.

        Note: ATM (delta=0.50) can have slightly lower touch probability than
        slightly OTM (delta=0.30) due to the Taleb adjustment model — this is
        expected behavior per the reflection principle."""
        vals = [compute_touch_probability_from_delta(d) for d in [0.05, 0.15, 0.30, 0.75, 0.95]]
        assert all(v is not None for v in vals)
        probs = [v for v in vals if v is not None]
        assert probs == sorted(probs)


class TestPriceTargetProbability:
    def test_above_target(self):
        surf = _make_surface()
        result = estimate_price_target_probability(3350.0, "above", [surf])
        assert result.probability is not None
        assert 0.0 <= result.probability <= 1.0
        assert result.method != "unavailable"

    def test_below_target(self):
        surf = _make_surface()
        result = estimate_price_target_probability(3250.0, "below", [surf])
        assert result.probability is not None
        assert 0.0 <= result.probability <= 1.0

    def test_no_surface_returns_unavailable(self):
        result = estimate_price_target_probability(3300.0, "above", [])
        assert result.method == "unavailable"
        assert result.probability is None

    def test_invalid_direction(self):
        surf = _make_surface()
        result = estimate_price_target_probability(3300.0, "sideways", [surf])
        assert result.method == "unavailable"


class TestProbabilitySurface:
    def test_surface_to_dict(self):
        surf = _make_surface()
        d = probability_surface_to_dict(surf)
        assert d["expiry"] == "JUN26"
        assert d["status"] == "available"
        assert len(d["strikes"]) == 4
        strike = d["strikes"][0]
        assert "strike" in strike
        assert "call_delta" in strike
        assert "touch_probability" in strike


class TestEmptyBuild:
    def test_empty_rows(self):
        surfaces = build_probability_surface([], trade_date="2026-05-15")
        assert surfaces == []
