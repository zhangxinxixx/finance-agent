from __future__ import annotations

from apps.analysis.gold_mainline_engine import build_gold_macro_overview
from apps.features.news.gold_event_mainlines import MAINLINE_ORDER, build_gold_event_mainlines


def _event(event_id: str, event_type: str, *, direction: str = "neutral", verification_status: str = "single_source") -> dict:
    return {
        "event_id": event_id,
        "event_type": event_type,
        "event_status": "developing",
        "event_time": "2026-06-30T08:15:00+00:00",
        "asset_tags": ["XAUUSD"],
        "direction": direction,
        "confidence": 0.72,
        "verification_status": verification_status,
        "source_refs": [{"source": "fixture_news", "source_ref": f"news:{event_id}"}],
    }


def _impact(event_id: str, impact_path: str, gold_impact: str, **extra: str) -> dict:
    return {
        "event_id": event_id,
        "impact_path": impact_path,
        "gold_impact": gold_impact,
        "pricing_status": extra.pop("pricing_status", "unknown"),
        **extra,
    }


def test_gold_macro_overview_preserves_nine_mainline_rankings_and_missing_rows() -> None:
    bundle = build_gold_event_mainlines(
        [
            _event("event:hormuz", "hormuz_risk", direction="mixed"),
            _event("event:fed", "fed_hawkish", verification_status="multi_source"),
        ],
        impact_assessments=[
            _impact(
                "event:hormuz",
                "geo_risk_to_oil_to_inflation",
                "mixed",
                dollar_impact="dollar_strength",
                yield_impact="yield_up",
                oil_impact="oil_up",
                pricing_status="unpriced",
            ),
            _impact(
                "event:fed",
                "strong_data_to_higher_for_longer",
                "bearish",
                dollar_impact="dollar_strength",
                yield_impact="yield_up",
                pricing_status="partially_priced",
            ),
        ],
        as_of="2026-06-30T08:30:00+00:00",
    )

    overview = build_gold_macro_overview(bundle).to_dict()

    assert [row["mainline_id"] for row in overview["theme_rankings"]] == MAINLINE_ORDER
    assert len(overview["theme_rankings"]) == 9
    assert overview["dominant_mainline"] in {"fed_policy_path", "real_rates_usd", "geopolitical_war_risk", "oil_prices"}

    rows = {row["mainline_id"]: row for row in overview["theme_rankings"]}
    assert rows["gold_technical_levels"]["coverage_status"] == "missing"
    assert rows["gold_technical_levels"]["evidence_count"] == 0
    assert rows["gold_technical_levels"]["missing_data"] == ["xauusd_price"]
    assert overview["driver_conflict"]["bullish_drivers"] == ["safe_haven_bid"]
    assert "oil_inflation_rate_pressure" in overview["driver_conflict"]["bearish_drivers"]
    assert overview["war_oil_rate_chain"]["path_id"] == "geopolitics_to_oil_to_rates"
    assert overview["war_oil_rate_chain"]["conclusion_code"] == "C"
    assert overview["war_oil_rate_chain"]["conclusion_label"] == "两者抵消，黄金震荡"
    assert rows["fed_policy_path"]["theme_score"] == 18
    assert rows["fed_policy_path"]["direction_score"] == -1


def test_gold_macro_overview_verification_matrix_includes_missing_mainline_sources() -> None:
    bundle = build_gold_event_mainlines(
        [_event("event:fed", "fed_hawkish", verification_status="multi_source")],
        impact_assessments=[
            _impact(
                "event:fed",
                "strong_data_to_higher_for_longer",
                "bearish",
                dollar_impact="dollar_strength",
                yield_impact="yield_up",
                pricing_status="partially_priced",
            )
        ],
        as_of="2026-06-30T08:30:00+00:00",
    )

    overview = build_gold_macro_overview(bundle).to_dict()

    checks = {(item["mainline_id"], item["required_source"]) for item in overview["verification_matrix"]}
    assert ("real_rates_usd", "real_rates") in checks
    assert ("gold_technical_levels", "xauusd_price") in checks
    assert ("etf_flows", "etf_flows") in checks
    assert ("central_bank_gold", "central_bank_reserves") in checks
    assert ("china_asia_demand", "asia_physical_demand") in checks
    assert ("institutional_sentiment", "positioning_data") in checks


def test_gold_macro_overview_exposes_first_principles_requirement_matrix() -> None:
    bundle = build_gold_event_mainlines(
        [
            _event("event:hormuz", "hormuz_risk", direction="mixed"),
            _event("event:funds", "gold_fund_flow", direction="bullish"),
            _event("event:options", "positioning_sentiment", direction="bearish"),
        ],
        impact_assessments=[
            _impact(
                "event:hormuz",
                "geo_risk_to_oil_to_inflation",
                "mixed",
                oil_impact="oil_up",
                yield_impact="yield_up",
                pricing_status="partially_priced",
            ),
            _impact("event:funds", "gold_etf_flow_watchlist", "bullish", pricing_status="unknown"),
            _impact("event:options", "gold_positioning_watchlist", "bearish", pricing_status="unknown"),
        ],
        as_of="2026-06-30T08:30:00+00:00",
    )

    overview = build_gold_macro_overview(bundle).to_dict()
    requirements = {item["mainline_id"]: item for item in overview["mainline_requirements"]}

    assert list(requirements) == MAINLINE_ORDER
    assert overview["analysis_readiness"]["total_count"] == 9
    assert overview["analysis_readiness"]["missing_count"] >= 1
    assert overview["architecture_gaps"]

    fed = requirements["fed_policy_path"]
    assert "无息资产" in fed["asset_principle"]
    assert fed["required_fields"] == [
        "fed_policy_bias",
        "rate_expectation_delta",
        "cut_hike_probability",
        "fomc_tone",
        "policy_surprise",
    ]
    assert "利率与美元页" in fed["page_targets"]

    etf = requirements["etf_flows"]
    institutional = requirements["institutional_sentiment"]
    assert "global_etf_flow" in etf["required_fields"]
    assert "call_put_oi_ratio" not in etf["required_fields"]
    assert "call_put_oi_ratio" in institutional["required_fields"]
    assert "etf_flows" in etf["required_sources"]
    assert "positioning_data" in institutional["required_sources"]

    technical = requirements["gold_technical_levels"]
    assert technical["required_fields"] == [
        "gold_spot_price",
        "level_4000_status",
        "level_4100_4120_status",
        "level_4300_status",
        "level_3900_status",
        "gold_phase",
        "technical_confirmation",
    ]
    assert "技术位监控页" in technical["page_targets"]
    assert technical["readiness_status"] == "missing"
    assert "xauusd_price" in technical["missing_sources"]


def test_gold_macro_overview_uses_macro_and_market_context_for_feature_fields() -> None:
    bundle = build_gold_event_mainlines(
        [_event("event:fed", "fed_hawkish", direction="neutral", verification_status="multi_source")],
        impact_assessments=[_impact("event:fed", "strong_data_to_higher_for_longer", "neutral")],
        as_of="2026-06-30T08:30:00+00:00",
    )
    macro_context = {
        "as_of": "2026-06-30",
        "indicators": {
            "REAL_10Y": {"value": 2.2, "weekly_change": -0.09},
            "US10Y": {"value": 4.44, "weekly_change": -0.06},
            "BREAKEVEN_10Y": {"value": 2.23, "weekly_change": 0.05},
            "DXY": {"value": 100.7, "weekly_change": -0.4},
        },
        "source_refs": {
            "REAL_10Y": {"source": "fred", "raw_path": "raw/macro/real.json"},
            "DXY": {"source": "cnbc", "raw_path": "raw/macro/dxy.json"},
        },
    }
    market_context = {
        "gold_spot_price": 4115.0,
        "source_refs": [{"source": "market_candles", "source_ref": "XAUUSD:1d"}],
    }

    overview = build_gold_macro_overview(
        bundle,
        macro_context=macro_context,
        market_context=market_context,
    ).to_dict()
    rows = {row["mainline_id"]: row for row in overview["theme_rankings"]}
    requirements = {item["mainline_id"]: item for item in overview["mainline_requirements"]}

    real_rates = rows["real_rates_usd"]
    assert real_rates["feature_fields"]["real_rate_level"] == 2.2
    assert real_rates["feature_fields"]["real_rate_trend"] == "falling"
    assert real_rates["feature_fields"]["dxy_trend"] == "falling"
    assert real_rates["missing_data"] == []
    assert requirements["real_rates_usd"]["readiness_status"] == "ready"

    technical = rows["gold_technical_levels"]
    assert technical["coverage_status"] == "covered"
    assert technical["feature_fields"]["gold_spot_price"] == 4115.0
    assert technical["feature_fields"]["level_3900_status"] == "above"
    assert technical["feature_fields"]["level_4000_status"] == "above"
    assert technical["feature_fields"]["level_4100_4120_status"] == "inside"
    assert technical["feature_fields"]["level_4300_status"] == "below"
    assert technical["feature_fields"]["gold_phase"] == "weak_repair_watch"
    assert requirements["gold_technical_levels"]["readiness_status"] == "ready"
