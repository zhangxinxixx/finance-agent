from __future__ import annotations

from apps.analysis.agents.macro_liquidity import build_macro_liquidity_structured_payload
from apps.analysis.gold_mainline_engine import _real_rates_usd_features
from apps.features.macro.snapshot import build_macro_snapshot
from apps.features.research.daily import build_daily_research_features


def _point(symbol: str, observation_date: str, value: float) -> dict[str, object]:
    return {
        "symbol": symbol,
        "date": observation_date,
        "value": value,
        "source": "fred",
        "source_url": f"fixture://fred/{symbol}",
        "retrieved_at": "2026-09-05T12:00:00+00:00",
        "raw_path": f"raw/macro/fred/2026-09-05/{symbol}.json",
    }


def _snapshot() -> dict[str, object]:
    series = {
        "DGS2": [("2026-08-28", 4.20), ("2026-09-03", 4.30), ("2026-09-04", 4.40)],
        "DGS3MO": [("2026-08-28", 4.30), ("2026-09-03", 4.25), ("2026-09-04", 4.20)],
        "DGS10": [("2026-08-28", 4.60), ("2026-09-03", 4.70), ("2026-09-04", 4.80)],
        "T10YIE": [("2026-08-28", 2.20), ("2026-09-03", 2.25), ("2026-09-04", 2.30)],
        "SOFR": [("2026-08-28", 5.00), ("2026-09-03", 5.05), ("2026-09-04", 5.10)],
        "EFFR": [("2026-08-28", 4.98), ("2026-09-03", 5.00), ("2026-09-04", 5.02)],
        "IORB": [("2026-08-28", 5.00), ("2026-09-03", 5.00), ("2026-09-04", 5.00)],
    }
    points = [_point(symbol, day, value) for symbol, observations in series.items() for day, value in observations]
    macro = build_macro_snapshot(points, as_of="2026-09-04").to_dict()
    return {
        "trade_date": "2026-09-05",
        "snapshot_time": "2026-09-05T16:00:00+00:00",
        "macro": {"status": "available", "data": macro},
    }


def test_project_signals_keep_two_legs_and_policy_corridor_on_common_windows() -> None:
    daily = build_daily_research_features(_snapshot())

    short = daily["project_signals"]["short_curve"]
    assert short["status"] == "fresh"
    assert short["as_of"] == "2026-09-04"
    assert short["previous_date"] == "2026-09-03"
    assert short["weekly_anchor_date"] == "2026-08-28"
    assert short["spread"] == 0.2
    assert short["spread_change"] == 0.15
    assert short["two_year_change"] == 0.1
    assert short["three_month_change"] == -0.05
    assert short["weekly_two_year_change"] == 0.2
    assert short["weekly_three_month_change"] == -0.1
    assert short["driver"] == "left_up_right_down"
    assert "周度" in short["summary"]
    assert "2Y 上行而 3M 下行" in short["summary"]
    assert "鹰派预期与近期政策价格转松并存" in short["summary"]
    assert short["directional_role"] == "context_only"
    assert len(short["source_refs"]) == 2

    corridor = daily["project_signals"]["policy_corridor"]
    assert corridor["status"] == "fresh"
    assert corridor["sofr_minus_iorb"]["spread"] == 0.1
    assert corridor["effr_minus_iorb"]["spread"] == 0.02
    assert corridor["directional_role"] == "same_family_confirmation"


def test_dollar_provider_comparison_keeps_undated_previous_close_out_of_history():
    point = {**_point("DXY", "2026-09-04", 99.157), "source": "cnbc"}
    reference = {**{key: point[key] for key in ("source", "source_url", "raw_path", "retrieved_at")}, "symbol": "DXY",
                 "previous_close": "98.908", "reported_daily_change": "0.249",
                 "previous_close_status": "verified_by_provider_change", "previous_observation_date": None}
    macro = build_macro_snapshot([point], as_of="2026-09-05", source_refs=[reference]).to_dict()
    value = _snapshot()
    value["macro"]["data"] = macro
    dollar = next(row for row in build_daily_research_features(value)["passport"] if row["symbol"] == "DXY")
    assert dollar["previous_date"] is None and dollar["change"] is None
    assert dollar["provider_previous_close"] == 98.908
    assert dollar["provider_reported_change"] == 0.249
    # Metadata belonging to a different source response cannot attach to this point.
    reference["raw_path"] = "raw/other.json"
    value["macro"]["data"] = build_macro_snapshot([point], as_of="2026-09-05", source_refs=[reference]).to_dict()
    dollar = next(row for row in build_daily_research_features(value)["passport"] if row["symbol"] == "DXY")
    assert "provider_reported_change" not in dollar


def test_policy_corridor_uses_common_historical_date_when_latest_legs_differ() -> None:
    series = {
        "SOFR": [("2026-08-27", 3.50), ("2026-09-02", 3.55), ("2026-09-03", 3.60)],
        "EFFR": [("2026-08-27", 3.49), ("2026-09-02", 3.54), ("2026-09-03", 3.59)],
        "IORB": [("2026-08-27", 3.65), ("2026-09-03", 3.65), ("2026-09-05", 3.65)],
    }
    points = [_point(symbol, day, value) for symbol, observations in series.items() for day, value in observations]
    macro = build_macro_snapshot(points, as_of="2026-09-05").to_dict()
    snapshot = {
        "trade_date": "2026-09-05",
        "snapshot_time": "2026-09-05T16:00:00+00:00",
        "macro": {"status": "available", "data": macro},
    }

    daily = build_daily_research_features(snapshot)
    corridor = daily["project_signals"]["policy_corridor"]

    assert macro["indicators"]["SOFR"]["date"] == "2026-09-03"
    assert macro["indicators"]["IORB"]["date"] == "2026-09-05"
    assert macro["indicators"]["SOFR_MINUS_IORB"]["date"] == "2026-09-03"
    assert macro["indicators"]["EFFR_MINUS_IORB"]["date"] == "2026-09-03"
    assert corridor["status"] == "fresh"
    assert corridor["as_of"] == "2026-09-03"
    assert corridor["sofr_minus_iorb"]["spread"] == -0.05
    assert corridor["effr_minus_iorb"]["spread"] == -0.06
    assert {leg["observation_date"] for leg in corridor["legs"]} == {"2026-09-03"}


def test_stale_corridor_keeps_dated_historical_context_without_current_signal():
    snapshot = _snapshot()
    snapshot["trade_date"] = "2026-09-10"
    snapshot["snapshot_time"] = "2026-09-10T16:00:00+00:00"
    signal = build_daily_research_features(snapshot)["project_signals"]["policy_corridor"]
    assert signal["status"] == "unavailable"
    assert signal["driver"] == "unavailable"
    assert signal["sofr_minus_iorb"]["status"] == "unavailable"
    assert "2026-09-04" in signal["summary"]
    assert "+10.0bp" in signal["summary"]
    assert "不能据此确认当前融资状况" in signal["summary"]


def test_policy_corridor_accepts_equal_current_iorb_from_fed_and_fred() -> None:
    snapshot = _snapshot()
    points = [
        _point("IORB", "2026-09-04", 5.00),
        {
            **_point("IORB", "2026-09-04", 5.00),
            "source": "fed_prates",
            "source_url": "https://www.federalreserve.gov/monetarypolicy/prates/PRATES.json",
            "raw_path": "raw/fed/IORB.json",
        },
    ]
    macro = build_macro_snapshot(
        [
            _point(symbol, day, value)
            for symbol, observations in {
                "SOFR": [("2026-08-28", 5.00), ("2026-09-03", 5.05), ("2026-09-04", 5.10)],
                "EFFR": [("2026-08-28", 4.98), ("2026-09-03", 5.00), ("2026-09-04", 5.02)],
                "IORB": [("2026-08-28", 5.00), ("2026-09-03", 5.00), ("2026-09-04", 5.00)],
            }.items()
            for day, value in observations
        ]
        + points,
        as_of="2026-09-04",
    ).to_dict()
    snapshot["macro"] = {"status": "available", "data": macro}

    corridor = build_daily_research_features(snapshot)["project_signals"]["policy_corridor"]

    assert corridor["status"] == "fresh"
    assert corridor["as_of"] == "2026-09-04"


def test_policy_corridor_rejects_conflicting_duplicate_iorb() -> None:
    base = _snapshot()
    points = [
        _point("IORB", "2026-09-04", 5.10),
        {
            **_point("IORB", "2026-09-04", 5.00),
            "source": "fed_prates",
            "source_url": "https://www.federalreserve.gov/monetarypolicy/prates/PRATES.json",
            "raw_path": "raw/fed/IORB.json",
        },
    ]
    macro = build_macro_snapshot(
        [
            _point(symbol, day, value)
            for symbol, observations in {
                "SOFR": [("2026-08-28", 5.00), ("2026-09-03", 5.05), ("2026-09-04", 5.10)],
                "EFFR": [("2026-08-28", 4.98), ("2026-09-03", 5.00), ("2026-09-04", 5.02)],
                "IORB": [("2026-08-28", 5.00), ("2026-09-03", 5.00), ("2026-09-04", 5.00)],
            }.items()
            for day, value in observations
        ]
        + points,
        as_of="2026-09-04",
    ).to_dict()
    base["macro"] = {"status": "available", "data": macro}

    corridor = build_daily_research_features(base)["project_signals"]["policy_corridor"]

    assert corridor["status"] == "unavailable"
    assert corridor["sofr_minus_iorb"]["status"] == "unavailable"


def test_project_signal_requires_numeric_daily_and_weekly_values() -> None:
    snapshot = _snapshot()
    snapshot["macro"]["data"]["indicators"]["US02Y"]["weekly_change"] = None

    daily = build_daily_research_features(snapshot)
    short = daily["project_signals"]["short_curve"]

    assert short["status"] == "unavailable"
    assert short["change_type"] == "unavailable"
    assert "共同的当前/前值/周度日期" in short["summary"]


def test_project_signal_does_not_join_mismatched_leg_comparison_dates() -> None:
    snapshot = _snapshot()
    indicators = snapshot["macro"]["data"]["indicators"]
    indicators["US03M"]["previous_date"] = "2026-09-02"

    daily = build_daily_research_features(snapshot)
    short = daily["project_signals"]["short_curve"]

    assert short["status"] == "unavailable"
    assert short["spread"] == 0.2
    assert short["change_type"] == "unavailable"
    assert short["driver"] == "unavailable"
    assert "共同的当前/前值/周度日期" in short["summary"]


def test_macro_daily_path_consumes_project_signals_without_legacy_spread_fallback() -> None:
    snapshot = _snapshot()
    snapshot["daily_research"] = build_daily_research_features(snapshot)
    snapshot["macro"]["data"]["indicators"]["YIELD_SPREAD_2Y_3M"] = {
        "value": 99.0,
        "weekly_change": 99.0,
        "monthly_change": 99.0,
    }

    payload = build_macro_liquidity_structured_payload(snapshot)

    assert payload["project_signals"]["short_curve"]["spread"] == 0.2
    assert payload["short_curve_policy"]["signal"]["spread"] == 0.2
    assert payload["indicators"]["YIELD_SPREAD_2Y_3M"]["value"] == 0.2


def test_gold_mainline_treats_short_curve_as_context_and_requires_independent_direction() -> None:
    curve = {
        "status": "fresh",
        "as_of": "2026-09-04",
        "previous_date": "2026-09-03",
        "spread": -0.4,
        "weekly_spread_change": 0.2,
        "two_year_change": 0.1,
        "three_month_change": -0.1,
        "weekly_two_year_change": 0.3,
        "weekly_three_month_change": 0.1,
        "change_type": "inversion_narrowing",
        "driver": "left_rise_dominant",
        "summary": "2Y-3M 两腿变化仅作政策定价观察。",
        "source_refs": [{"source": "fred", "raw_path": "raw/curve.json"}],
    }
    context = {"project_signals": {"short_curve": curve}}

    curve_only = _real_rates_usd_features(context)
    assert curve_only is not None
    assert curve_only["direction"] == "neutral"
    assert curve_only["feature_fields"]["yield_curve_2y3m_driver"] == "left_rise_dominant"
    assert curve_only["feature_fields"]["yield_curve_2y3m_directional_role"] == "context_only"

    context.update(
        {
            "indicators": {
                "REAL_10Y": {"value": 1.9, "weekly_change": -0.1},
                "DXY": {"value": 99.0, "weekly_change": -0.3},
            }
        }
    )
    confirmed = _real_rates_usd_features(context)
    assert confirmed is not None
    assert confirmed["direction"] == "bullish"
    assert confirmed["feature_fields"]["yield_curve_2y3m_two_year_weekly_change"] == 0.3
