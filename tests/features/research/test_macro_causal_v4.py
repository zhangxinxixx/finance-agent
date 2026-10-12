from copy import deepcopy
import pytest

from apps.features.macro.inflation import build_inflation
from apps.features.macro.policy_expectations import build_policy_expectations
from apps.features.macro.treasury_causal import build_treasury
from apps.features.research.macro_causal import build_macro_causal
from apps.renderer.markdown.macro_causal import macro_causal_section


def monthly():
    return [
        {
            "symbol": "CPILFESL",
            "date": f"{2025 + (i + 7) // 12}-{(i + 7) % 12 + 1:02d}-01",
            "value": 100 * 1.002**i,
            "source": "fred",
            "source_url": "https://fred.stlouisfed.org",
            "raw_path": "raw/a.json",
            "retrieved_at": "2026-09-12T00:00:00Z",
        }
        for i in range(13)
    ]


def test_monthly_compounding_and_vintage_gaps():
    ps = monthly()
    original = deepcopy(ps)
    result = build_inflation(ps, as_of="2026-09-12T01:00:00Z")["series"]["core_cpi"]
    assert result["mom_pct"] == pytest.approx(0.2)
    assert result["saar_3m_pct"] == pytest.approx((1.002**12 - 1) * 100, abs=1e-6)
    assert result["saar_6m_pct"] == result["yoy_pct"]
    assert ps == original
    ps[9]["raw_path"] = "raw/other_vintage.json"
    assert build_inflation(ps, as_of="2026-09-12T01:00:00Z")["series"]["core_cpi"]["saar_3m_pct"] is None


def test_future_and_duplicate_months_rejected():
    ps = monthly()
    assert build_inflation(ps, as_of="2026-09-11T01:00:00Z")["series"]["core_cpi"]["status"] == "unavailable"
    ps.append({**ps[-1], "value": 999})
    assert build_inflation(ps, as_of="2026-09-12T01:00:00Z")["series"]["core_cpi"]["reason"] == "conflicting_months"


def distribution():
    return {
        "observed_at": "2026-09-12T12:00:00Z",
        "provider": "cme",
        "probability_unit": "fraction",
        "rate_unit": "percent",
        "current_target_midpoint": 4.375,
        "source_refs": [{"raw_path": "raw/policy"}],
        "meetings": [
            {
                "meeting_date": "2026-09-16",
                "bins": [
                    {"lower": 4.25, "upper": 4.5, "probability": 0.2},
                    {"lower": 4.5, "upper": 4.75, "probability": 0.65},
                    {"lower": 4.75, "upper": 5, "probability": 0.15},
                ],
            }
        ],
    }


def test_policy_mean_not_most_likely_rate_and_missing_horizons():
    result = build_policy_expectations(distribution(), as_of="2026-09-12T12:01:00Z")
    assert result["status"] == "available"
    assert result["next_meeting"]["expected_target_midpoint_pct"] == pytest.approx(4.6125)
    assert result["next_meeting"]["hike_vs_current_probability"] == pytest.approx(0.8)
    assert result["horizons"]["12m"] is None and result["year_end"] is None
    assert result["first_action_timing"].startswith("unavailable")


def test_policy_stale_invalid_mass_and_same_meeting_repricing():
    p = distribution()
    assert build_policy_expectations(p, as_of="2026-09-12T13:00:00Z")["status"] == "unavailable"
    old = deepcopy(p)
    old["observed_at"] = "2026-09-11T12:00:00Z"
    old["meetings"][0]["bins"][0]["probability"] = 0.3
    old["meetings"][0]["bins"][1]["probability"] = 0.55
    p["comparisons"] = {"1d": old}
    assert build_policy_expectations(p, as_of=p["observed_at"])["next_meeting"]["repricing_1d_bp"] == pytest.approx(2.5)
    p["meetings"][0]["bins"][0]["probability"] = 0.4
    assert build_policy_expectations(p, as_of=p["observed_at"])["status"] == "unavailable"


def test_real_yield_decomposition_rejects_asynchronous_dates():
    rows = [
        {
            "symbol": s,
            "status": "fresh",
            "source_refs": [{"raw_path": "raw/a"}],
            "previous_date": "2026-09-10",
            "observation_date": "2026-09-11",
            "change": v,
        }
        for s, v in [("US10Y", 0.01), ("REAL10Y", 0.05), ("BREAKEVEN_10Y", -0.04)]
    ]
    result = build_treasury(rows)
    assert result["windows"]["1d"]["real_bp"] == 5
    assert result["windows"]["1d"]["identity_residual_bp"] == 0
    assert result["term_premium"]["status"] == "unavailable"
    rows[1]["previous_date"] = "2026-09-09"
    assert build_treasury(rows)["windows"]["1d"]["status"] == "unavailable"


def test_empty_causal_is_explicit_and_renderable():
    s = {"snapshot_id": "test", "snapshot_time": "2026-09-12T12:00:00Z"}
    c = build_macro_causal(s)
    assert len(c["questions"]) == 8
    assert c["engines"]["policy"]["status"] == "unavailable"
    assert c["engines"]["residual"]["status"] == "unavailable"
    assert "未采集" in macro_causal_section(c)["body"]


def test_weekend_expected_stale_but_bad_capture_still_fails():
    from apps.features.research.cross_asset import build_cross_asset_features
    from apps.features.research.market_session import resolve_market_session

    assert resolve_market_session("2026-09-12T05:00:00Z")["state"] == "CLOSED"
    assert resolve_market_session("2026-09-13T23:00:00Z")["state"] == "OPEN"
    assert resolve_market_session("2026-09-14T21:30:00Z")["state"] == "MAINTENANCE"
    row = {
        "symbol": "WTI",
        "status": "available",
        "retrieved_at": "2026-09-12T05:00:00Z",
        "minute_bar_time": None,
        "delay_seconds": 600,
        "value": 100,
    }
    c = build_cross_asset_features({"observations": [row]}, as_of="2026-09-12T05:01:00Z")
    assert c["observations"][0]["freshness"] == "MARKET_CLOSED"
    assert not c["observations"][0]["intraday_confirmation_allowed"]
    row["retrieved_at"] = "2026-09-12T06:00:00Z"
    assert (
        build_cross_asset_features({"observations": [row]}, as_of="2026-09-12T05:01:00Z")["observations"][0][
            "freshness"
        ]
        == "INVALID_TIME"
    )


def test_yoy_uses_endpoints_despite_missing_intermediate_month():
    points = monthly()
    points.pop(2)
    result = build_inflation(points, as_of="2026-09-12T01:00:00Z")["series"]["core_cpi"]
    assert result["yoy_pct"] == pytest.approx((1.002**12-1)*100, abs=1e-6)


def test_latest_inflation_vintage_uses_instant_not_timezone_text():
    old = monthly()
    for p in old:
        p["retrieved_at"] = "2026-09-12T08:00:00+08:00"
    new = [{**p, "retrieved_at": "2026-09-12T00:30:00Z", "raw_path": "raw/new.json"} for p in old]
    new[-1]["value"] *= 1.01
    row = build_inflation(old + new, as_of="2026-09-12T01:00:00Z")["series"]["core_cpi"]
    assert row["source_refs"][0]["raw_path"] == "raw/new.json"
    assert row["mom_pct"] == pytest.approx(1.202)


def test_missing_clock_and_policy_input_fail_closed():
    from apps.features.research.market_session import resolve_market_session

    assert resolve_market_session(None)["state"] == "UNKNOWN"
    assert not resolve_market_session({})["new_intraday_confirmation_allowed"]
    assert build_policy_expectations({}, as_of="2026-09-12T12:00:00Z")["reason"] == "verified_market_distribution_missing"
    p = distribution()
    p["observed_at"] = None
    assert build_policy_expectations(p, as_of="2026-09-12T12:00:00Z")["status"] == "unavailable"


def test_policy_rounding_preserves_constant_expected_rate():
    p = distribution()
    p["meetings"][0]["bins"] = [{"lower": 4.25, "upper": 4.5, "probability": 0.9999}]
    row = build_policy_expectations(p, as_of=p["observed_at"])["next_meeting"]
    assert row["expected_target_midpoint_pct"] == pytest.approx(4.375)
    assert row["cumulative_bp_vs_current"] == pytest.approx(0)
    assert row["distribution_sd_bp"] == pytest.approx(0)
    assert row["input_probability_mass"] == 0.9999


def test_session_gate_does_not_depend_on_inflation_or_hide_missing_anchor():
    from apps.features.research.daily import build_daily_research_features

    row = build_daily_research_features({"snapshot_time": "2026-09-12T05:00:00Z"})
    assert row["market_session"]["state"] == "CLOSED"
    assert row["spot_anchor"]["status"] != "market_closed"
    assert row["spot_anchor"]["price"] is None
    assert row["spot_anchor"]["live_confirmation_allowed"] is False
