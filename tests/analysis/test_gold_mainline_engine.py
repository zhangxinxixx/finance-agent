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
            "YIELD_SPREAD_2Y_3M": {"value": -0.45, "weekly_change": 0.12},
            "DXY": {"value": 100.7, "weekly_change": -0.4},
        },
        "source_refs": {
            "REAL_10Y": {"source": "fred", "raw_path": "raw/macro/real.json"},
            "DGS2": {"source": "fred", "raw_path": "raw/macro/dgs2.json"},
            "DGS3MO": {"source": "fred", "raw_path": "raw/macro/dgs3mo.json"},
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
    assert real_rates["feature_fields"]["real_rate_weekly_change"] == -0.09
    assert real_rates["feature_fields"]["real_rate_monthly_change"] is None
    assert real_rates["feature_fields"]["real_rate_trend"] == "falling"
    assert real_rates["feature_fields"]["real_rate_trend_basis"] == "weekly"
    assert real_rates["feature_fields"]["nominal_yield_level"] == 4.44
    assert real_rates["feature_fields"]["nominal_yield_weekly_change"] == -0.06
    assert real_rates["feature_fields"]["nominal_yield_pressure"] == "easing_pressure"
    assert real_rates["feature_fields"]["breakeven_10y_level"] == 2.23
    assert real_rates["feature_fields"]["breakeven_10y_weekly_change"] == 0.05
    assert real_rates["feature_fields"]["yield_spread_2y_3m_level"] == -0.45
    assert real_rates["feature_fields"]["yield_spread_2y_3m_weekly_change"] == 0.12
    assert real_rates["feature_fields"]["yield_spread_2y_3m_trend"] == "rising"
    assert real_rates["feature_fields"]["yield_curve_2y3m_signal"] == "pivot_window_improving"
    assert "政策拐点" in real_rates["feature_fields"]["yield_curve_2y3m_market_meaning"]
    assert real_rates["feature_fields"]["dxy_trend"] == "falling"
    assert real_rates["feature_fields"]["dxy_weekly_change"] == -0.4
    assert real_rates["feature_fields"]["dxy_monthly_change"] is None
    assert real_rates["feature_fields"]["dxy_trend_basis"] == "weekly"
    assert real_rates["feature_fields"]["dollar_liquidity_pressure"] == "weaker_dollar_support"
    assert real_rates["missing_data"] == []
    assert requirements["real_rates_usd"]["readiness_status"] == "ready"
    assert "yield_curve" in requirements["real_rates_usd"]["required_sources"]
    assert "yield_curve_2y3m_signal" in requirements["real_rates_usd"]["required_fields"]

    technical = rows["gold_technical_levels"]
    assert technical["coverage_status"] == "covered"
    assert technical["feature_fields"]["gold_spot_price"] == 4115.0
    assert technical["feature_fields"]["level_3900_status"] == "above"
    assert technical["feature_fields"]["level_4000_status"] == "above"
    assert technical["feature_fields"]["level_4100_4120_status"] == "inside"
    assert technical["feature_fields"]["level_4300_status"] == "below"
    assert technical["feature_fields"]["gold_phase"] == "weak_repair_watch"
    assert requirements["gold_technical_levels"]["readiness_status"] == "ready"


def test_gold_macro_overview_real_rates_uses_monthly_fallback_but_keeps_partial_when_weekly_changes_missing() -> None:
    bundle = build_gold_event_mainlines(
        [_event("event:fed", "fed_hawkish", direction="neutral", verification_status="multi_source")],
        impact_assessments=[_impact("event:fed", "strong_data_to_higher_for_longer", "neutral")],
        as_of="2026-06-30T08:30:00+00:00",
    )
    macro_context = {
        "as_of": "2026-06-30",
        "indicators": {
            "REAL_10Y": {"value": 2.2, "monthly_change": -0.12},
            "US10Y": {"value": 4.44, "monthly_change": 0.18},
            "BREAKEVEN_10Y": {"value": 2.23, "monthly_change": 0.07},
            "YIELD_SPREAD_2Y_3M": {"value": -0.62, "monthly_change": 0.24},
            "DXY": {"value": 100.7, "monthly_change": -0.8},
        },
        "source_refs": {
            "REAL_10Y": {"source": "fred", "raw_path": "raw/macro/real.json"},
            "DGS2": {"source": "fred", "raw_path": "raw/macro/dgs2.json"},
            "DGS3MO": {"source": "fred", "raw_path": "raw/macro/dgs3mo.json"},
            "DXY": {"source": "cnbc", "raw_path": "raw/macro/dxy.json"},
        },
    }

    overview = build_gold_macro_overview(bundle, macro_context=macro_context).to_dict()
    rows = {row["mainline_id"]: row for row in overview["theme_rankings"]}
    requirements = {item["mainline_id"]: item for item in overview["mainline_requirements"]}

    real_rates = rows["real_rates_usd"]
    assert real_rates["feature_fields"]["real_rate_trend"] == "falling"
    assert real_rates["feature_fields"]["real_rate_trend_basis"] == "monthly"
    assert real_rates["feature_fields"]["nominal_yield_pressure"] == "rising_pressure"
    assert real_rates["feature_fields"]["yield_spread_2y_3m_trend"] == "rising"
    assert real_rates["feature_fields"]["yield_spread_2y_3m_trend_basis"] == "monthly"
    assert real_rates["feature_fields"]["dxy_trend"] == "falling"
    assert real_rates["feature_fields"]["dxy_trend_basis"] == "monthly"
    assert requirements["real_rates_usd"]["readiness_status"] == "partial"
    assert "real_rate_weekly_change" in requirements["real_rates_usd"]["missing_fields"]
    assert "dxy_weekly_change" in requirements["real_rates_usd"]["missing_fields"]


def test_gold_macro_overview_oil_context_marks_inflation_rate_pressure_as_dominant() -> None:
    bundle = build_gold_event_mainlines(
        [_event("event:hormuz", "hormuz_risk", direction="mixed", verification_status="multi_source")],
        impact_assessments=[
            _impact(
                "event:hormuz",
                "geo_risk_to_oil_to_inflation",
                "mixed",
                oil_impact="oil_up",
                yield_impact="yield_up",
                pricing_status="partially_priced",
            )
        ],
        as_of="2026-06-30T08:30:00+00:00",
    )
    macro_context = {
        "as_of": "2026-06-30",
        "indicators": {
            "REAL_10Y": {"value": 2.2, "weekly_change": 0.08},
            "US10Y": {"value": 4.44, "weekly_change": 0.11},
            "BREAKEVEN_10Y": {"value": 2.23, "weekly_change": 0.06},
            "DXY": {"value": 100.7, "weekly_change": 0.3},
        },
        "source_refs": {
            "REAL_10Y": {"source": "fred", "raw_path": "raw/macro/real.json"},
            "DXY": {"source": "cnbc", "raw_path": "raw/macro/dxy.json"},
        },
    }
    oil_context = {
        "brent_price": 92.4,
        "wti_price": 88.1,
        "brent_weekly_change": 4.8,
        "wti_weekly_change": 4.2,
        "inventory_weekly_change": -6.5,
        "source_refs": [{"source": "energy_context", "source_ref": "oil:weekly"}],
    }

    overview = build_gold_macro_overview(bundle, macro_context=macro_context, oil_context=oil_context).to_dict()
    rows = {row["mainline_id"]: row for row in overview["theme_rankings"]}
    requirements = {item["mainline_id"]: item for item in overview["mainline_requirements"]}

    oil = rows["oil_prices"]
    assert oil["feature_fields"]["oil_price_trend"] == "rising"
    assert oil["feature_fields"]["brent_wti_status"] == "backwardation_risk"
    assert oil["feature_fields"]["oil_supply_shock"] == "supply_draw"
    assert oil["feature_fields"]["energy_inflation_risk"] == "building"
    assert oil["feature_fields"]["oil_to_fed_pressure"] == "inflation_reacceleration_risk"
    assert oil["missing_data"] == []
    assert requirements["oil_prices"]["readiness_status"] == "ready"
    assert overview["war_oil_rate_chain"]["conclusion_code"] == "B"
    assert overview["war_oil_rate_chain"]["dominant_driver"] == "oil_inflation_rate_pressure"


def test_gold_macro_overview_oil_context_can_preserve_safe_haven_dominance_when_real_rates_fall() -> None:
    bundle = build_gold_event_mainlines(
        [_event("event:hormuz", "hormuz_risk", direction="mixed", verification_status="multi_source")],
        impact_assessments=[
            _impact(
                "event:hormuz",
                "geo_risk_to_oil_to_inflation",
                "mixed",
                oil_impact="oil_up",
                yield_impact="yield_down",
                pricing_status="unpriced",
            )
        ],
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
    oil_context = {
        "brent_price": 93.2,
        "wti_price": 89.7,
        "brent_weekly_change": 5.1,
        "wti_weekly_change": 4.9,
        "inventory_weekly_change": -4.3,
        "source_refs": [{"source": "energy_context", "source_ref": "oil:weekly"}],
    }

    overview = build_gold_macro_overview(bundle, macro_context=macro_context, oil_context=oil_context).to_dict()

    assert overview["war_oil_rate_chain"]["conclusion_code"] == "A"
    assert overview["war_oil_rate_chain"]["conclusion_label"] == "避险主导，黄金受支撑"


def test_gold_macro_overview_etf_flow_context_marks_capital_confirmation_as_ready() -> None:
    bundle = build_gold_event_mainlines(
        [_event("event:funds", "gold_fund_flow", direction="bullish", verification_status="multi_source")],
        impact_assessments=[_impact("event:funds", "gold_etf_flow_watchlist", "bullish", pricing_status="unknown")],
        as_of="2026-06-30T08:30:00+00:00",
    )
    flow_context = {
        "global_etf_flow": 18.4,
        "north_america_etf_flow": 11.2,
        "asia_etf_flow": 4.6,
        "source_refs": [{"source": "wgc", "source_ref": "gold_etf:weekly"}],
    }

    overview = build_gold_macro_overview(bundle, flow_context=flow_context).to_dict()
    rows = {row["mainline_id"]: row for row in overview["theme_rankings"]}
    requirements = {item["mainline_id"]: item for item in overview["mainline_requirements"]}

    etf = rows["etf_flows"]
    assert etf["feature_fields"]["global_etf_flow"] == 18.4
    assert etf["feature_fields"]["north_america_etf_flow"] == 11.2
    assert etf["feature_fields"]["asia_etf_flow"] == 4.6
    assert etf["feature_fields"]["etf_flow_trend"] == "inflow"
    assert etf["feature_fields"]["flow_confirmation_status"] == "confirmed_inflow"
    flow_ref = next(ref for ref in etf["source_refs"] if ref.get("evidence_role") == "flow_context")
    assert flow_ref["source_tier"] == "official"
    assert flow_ref["lineage_type"] == "context_artifact"
    assert etf["missing_data"] == []
    assert requirements["etf_flows"]["readiness_status"] == "ready"


def test_gold_macro_overview_supplemental_etf_flow_does_not_satisfy_production_readiness() -> None:
    bundle = build_gold_event_mainlines(
        [_event("event:funds", "gold_fund_flow", direction="bullish", verification_status="multi_source")],
        impact_assessments=[_impact("event:funds", "gold_etf_flow_watchlist", "bullish", pricing_status="unknown")],
        as_of="2026-06-30T08:30:00+00:00",
    )
    flow_context = {
        "global_etf_flow": 18.4,
        "north_america_etf_flow": 11.2,
        "asia_etf_flow": 4.6,
        "source_refs": [
            {
                "source": "jin10_datacenter",
                "source_ref": "gold_etf:supplemental",
                "provider_role": "supplemental_source",
            }
        ],
    }

    overview = build_gold_macro_overview(bundle, flow_context=flow_context).to_dict()
    requirements = {item["mainline_id"]: item for item in overview["mainline_requirements"]}

    etf_requirement = requirements["etf_flows"]
    assert etf_requirement["readiness_status"] == "partial"
    assert "etf_flows" in etf_requirement["missing_sources"]
    assert "regional_etf_flows" in etf_requirement["missing_sources"]


def test_gold_macro_overview_reserve_and_asia_context_mark_structural_support_lines_ready() -> None:
    bundle = build_gold_event_mainlines(
        [
            _event("event:reserve", "central_bank_gold_buying", direction="bullish", verification_status="multi_source"),
            _event("event:asia", "shanghai_gold_premium", direction="bullish", verification_status="multi_source"),
        ],
        impact_assessments=[
            _impact("event:reserve", "reserve_reallocation", "bullish", pricing_status="unknown"),
            _impact("event:asia", "asia_demand", "bullish", pricing_status="unknown"),
        ],
        as_of="2026-06-30T08:30:00+00:00",
    )
    reserve_context = {
        "central_bank_net_buying": 61.0,
        "pboc_gold_holdings_change": 2.4,
        "reserve_diversification_signal": "broadening",
        "monetary_credit_repricing": "usd_confidence_erosion",
        "long_term_support_score": 8.2,
        "source_refs": [{"source": "wgc", "source_ref": "central_bank:monthly"}],
    }
    asia_context = {
        "usdcnh_weekly_change": -0.18,
        "shanghai_gold_premium": 42.5,
        "china_gold_etf_flow": 6.3,
        "asia_demand_score": 7.4,
        "india_physical_demand": 5.1,
        "source_refs": [{"source": "sge", "source_ref": "premium:weekly"}],
    }

    overview = build_gold_macro_overview(
        bundle,
        reserve_context=reserve_context,
        asia_context=asia_context,
    ).to_dict()
    rows = {row["mainline_id"]: row for row in overview["theme_rankings"]}
    requirements = {item["mainline_id"]: item for item in overview["mainline_requirements"]}

    central = rows["central_bank_gold"]
    assert central["feature_fields"]["central_bank_net_buying"] == 61.0
    assert central["feature_fields"]["pboc_gold_holdings_change"] == 2.4
    assert central["feature_fields"]["reserve_diversification_signal"] == "broadening"
    assert central["feature_fields"]["monetary_credit_repricing"] == "usd_confidence_erosion"
    assert central["feature_fields"]["long_term_support_score"] == 8.2
    assert central["missing_data"] == []
    assert requirements["central_bank_gold"]["readiness_status"] == "ready"

    asia = rows["china_asia_demand"]
    assert asia["feature_fields"]["usdcnh_trend"] == "falling"
    assert asia["feature_fields"]["shanghai_gold_premium"] == 42.5
    assert asia["feature_fields"]["china_gold_etf_flow"] == 6.3
    assert asia["feature_fields"]["asia_demand_score"] == 7.4
    assert asia["feature_fields"]["india_physical_demand"] == 5.1
    assert asia["feature_fields"]["cny_gold_relative_strength"] == "supportive"
    assert asia["missing_data"] == []
    assert requirements["china_asia_demand"]["readiness_status"] == "ready"


def test_gold_macro_overview_positioning_context_marks_institutional_sentiment_ready() -> None:
    bundle = build_gold_event_mainlines(
        [_event("event:options", "positioning_sentiment", direction="bearish", verification_status="multi_source")],
        impact_assessments=[_impact("event:options", "gold_positioning_watchlist", "bearish", pricing_status="unknown")],
        as_of="2026-06-30T08:30:00+00:00",
    )
    positioning_context = {
        "comex_net_long": 185000,
        "cot_positioning": "stretched_long",
        "option_skew": 1.35,
        "call_put_oi_ratio": 0.82,
        "institutional_sentiment": "cautious_bullish",
        "positioning_crowding": "crowded_long",
        "source_refs": [{"source": "cme_cot", "source_ref": "comex:weekly"}],
    }

    overview = build_gold_macro_overview(
        bundle,
        positioning_context=positioning_context,
    ).to_dict()
    rows = {row["mainline_id"]: row for row in overview["theme_rankings"]}
    requirements = {item["mainline_id"]: item for item in overview["mainline_requirements"]}

    positioning = rows["institutional_sentiment"]
    assert positioning["feature_fields"]["comex_net_long"] == 185000
    assert positioning["feature_fields"]["cot_positioning"] == "stretched_long"
    assert positioning["feature_fields"]["option_skew"] == 1.35
    assert positioning["feature_fields"]["call_put_oi_ratio"] == 0.82
    assert positioning["feature_fields"]["institutional_sentiment"] == "cautious_bullish"
    assert positioning["feature_fields"]["positioning_crowding"] == "crowded_long"
    positioning_ref = next(
        ref for ref in positioning["source_refs"] if ref.get("evidence_role") == "positioning_context"
    )
    assert positioning_ref["source_tier"] == "official"
    assert positioning_ref["lineage_type"] == "context_artifact"
    assert positioning["missing_data"] == []
    assert requirements["institutional_sentiment"]["readiness_status"] == "ready"


def test_gold_macro_overview_policy_and_geopolitical_context_mark_verification_layers_ready() -> None:
    bundle = build_gold_event_mainlines(
        [
            _event("event:fed", "fed_hawkish", direction="bearish", verification_status="official_confirmed"),
            _event("event:hormuz", "hormuz_risk", direction="mixed", verification_status="multi_source"),
        ],
        impact_assessments=[
            _impact("event:fed", "strong_data_to_higher_for_longer", "bearish", pricing_status="partially_priced"),
            _impact("event:hormuz", "geo_risk_to_oil_to_inflation", "mixed", pricing_status="unpriced"),
        ],
        as_of="2026-06-30T08:30:00+00:00",
    )
    policy_context = {
        "fed_policy_bias": "higher_for_longer",
        "rate_expectation_delta": 0.32,
        "cut_hike_probability": 0.18,
        "fomc_tone": "hawkish",
        "policy_surprise": "hawkish_repricing",
        "treasury_2y_change": 0.11,
        "treasury_10y_change": 0.08,
        "source_refs": [{"source": "fed", "source_ref": "fomc:2026-06"}],
    }
    geopolitical_context = {
        "geopolitical_status": "escalating",
        "war_escalation_level": "regional_risk",
        "safe_haven_score": 7.6,
        "energy_channel_risk": "elevated",
        "war_oil_rate_chain_status": "active",
        "vix_reaction": "risk_off",
        "equity_reaction": "selloff",
        "treasury_yield_reaction": "bull_flattening",
        "source_refs": [
            {"source": "reuters", "source_ref": "geo:1"},
            {"source": "ap", "source_ref": "geo:2"},
            {"source": "market_volatility", "source_ref": "vix:reaction"},
            {"source": "equity_market", "source_ref": "spx:reaction"},
            {"source": "treasury", "source_ref": "ust:reaction"},
            {"source": "energy_market", "source_ref": "oil:reaction"},
        ],
    }

    overview = build_gold_macro_overview(
        bundle,
        policy_context=policy_context,
        geopolitical_context=geopolitical_context,
    ).to_dict()
    rows = {row["mainline_id"]: row for row in overview["theme_rankings"]}
    requirements = {item["mainline_id"]: item for item in overview["mainline_requirements"]}

    fed = rows["fed_policy_path"]
    assert fed["feature_fields"]["fed_policy_bias"] == "higher_for_longer"
    assert fed["feature_fields"]["rate_expectation_delta"] == 0.32
    assert fed["feature_fields"]["cut_hike_probability"] == 0.18
    assert fed["feature_fields"]["fomc_tone"] == "hawkish"
    assert fed["feature_fields"]["policy_surprise"] == "hawkish_repricing"
    assert fed["missing_data"] == []
    assert requirements["fed_policy_path"]["readiness_status"] == "ready"

    geo = rows["geopolitical_war_risk"]
    assert geo["feature_fields"]["geopolitical_status"] == "escalating"
    assert geo["feature_fields"]["war_escalation_level"] == "regional_risk"
    assert geo["feature_fields"]["safe_haven_score"] == 7.6
    assert geo["feature_fields"]["energy_channel_risk"] == "elevated"
    assert geo["feature_fields"]["war_oil_rate_chain_status"] == "active"
    assert geo["missing_data"] == []
    assert requirements["geopolitical_war_risk"]["readiness_status"] == "ready"


def test_gold_macro_overview_priority_regime_normal_rates_keeps_theme_score_order() -> None:
    payload = {
        "asset": "XAUUSD",
        "status": "available",
        "as_of": "2026-06-30T08:30:00+00:00",
        "mainlines": [
            {
                "mainline_id": "fed_policy_path",
                "coverage_status": "covered",
                "score": 8,
                "theme_score": 8,
                "direction": "bearish",
                "source_refs": [{"source": "fixture", "source_ref": "fed"}],
            },
            {
                "mainline_id": "etf_flows",
                "coverage_status": "covered",
                "score": 24,
                "theme_score": 24,
                "direction": "bullish",
                "source_refs": [{"source": "fixture", "source_ref": "flow"}],
            },
        ],
        "event_links": [],
    }

    overview = build_gold_macro_overview(payload).to_dict()

    assert overview["priority_regime"] == "normal_rate_environment"
    assert "theme_score" in overview["priority_reason"]
    assert overview["dominant_mainline"] == "etf_flows"


def test_gold_macro_overview_priority_regime_fomc_cycle_prioritizes_fed_path() -> None:
    payload = {
        "asset": "XAUUSD",
        "status": "available",
        "as_of": "2026-06-30T08:30:00+00:00",
        "mainlines": [
            {"mainline_id": "etf_flows", "coverage_status": "covered", "score": 30, "theme_score": 30},
            {"mainline_id": "fed_policy_path", "coverage_status": "covered", "score": 6, "theme_score": 6},
        ],
        "event_links": [],
    }
    policy_context = {
        "fed_policy_bias": "higher_for_longer",
        "rate_expectation_delta": 0.28,
        "cut_hike_probability": 0.22,
        "fomc_tone": "hawkish",
        "policy_surprise": "hawkish_repricing",
        "treasury_2y_change": 0.1,
        "treasury_10y_change": 0.06,
        "source_refs": [{"source": "fed", "source_ref": "fomc"}],
    }

    overview = build_gold_macro_overview(payload, policy_context=policy_context).to_dict()

    assert overview["priority_regime"] == "policy_event_cycle"
    assert overview["dominant_mainline"] == "fed_policy_path"


def test_gold_macro_overview_priority_regime_war_escalation_prioritizes_geopolitics_or_oil() -> None:
    payload = {
        "asset": "XAUUSD",
        "status": "available",
        "as_of": "2026-06-30T08:30:00+00:00",
        "mainlines": [
            {"mainline_id": "fed_policy_path", "coverage_status": "covered", "score": 30, "theme_score": 30},
            {"mainline_id": "geopolitical_war_risk", "coverage_status": "covered", "score": 9, "theme_score": 9},
        ],
        "event_links": [],
    }
    geopolitical_context = {
        "geopolitical_status": "escalating",
        "war_escalation_level": "regional_risk",
        "safe_haven_score": 8.2,
        "energy_channel_risk": "elevated",
        "war_oil_rate_chain_status": "active",
        "vix_reaction": "risk_off",
        "equity_reaction": "selloff",
        "treasury_yield_reaction": "bull_flattening",
        "source_refs": [{"source": "reuters", "source_ref": "geo"}],
    }

    overview = build_gold_macro_overview(payload, geopolitical_context=geopolitical_context).to_dict()

    assert overview["priority_regime"] == "war_escalation"
    assert overview["dominant_mainline"] == "geopolitical_war_risk"


def test_gold_macro_overview_priority_regime_large_flow_prioritizes_etf_or_positioning() -> None:
    payload = {
        "asset": "XAUUSD",
        "status": "available",
        "as_of": "2026-06-30T08:30:00+00:00",
        "mainlines": [
            {"mainline_id": "fed_policy_path", "coverage_status": "covered", "score": 30, "theme_score": 30},
            {"mainline_id": "etf_flows", "coverage_status": "covered", "score": 6, "theme_score": 6},
        ],
        "event_links": [],
    }
    flow_context = {
        "global_etf_flow": 7.5,
        "north_america_etf_flow": 6.2,
        "asia_etf_flow": 1.3,
        "source_refs": [{"source": "official_etf_flow", "source_ref": "flow"}],
    }

    overview = build_gold_macro_overview(payload, flow_context=flow_context).to_dict()

    assert overview["priority_regime"] == "large_capital_flow"
    assert overview["dominant_mainline"] == "etf_flows"


def test_gold_macro_overview_priority_regime_monetary_credit_repricing_prioritizes_central_bank_gold() -> None:
    payload = {
        "asset": "XAUUSD",
        "status": "available",
        "as_of": "2026-06-30T08:30:00+00:00",
        "mainlines": [
            {"mainline_id": "fed_policy_path", "coverage_status": "covered", "score": 30, "theme_score": 30},
            {"mainline_id": "central_bank_gold", "coverage_status": "covered", "score": 4, "theme_score": 4},
        ],
        "event_links": [],
    }
    reserve_context = {
        "central_bank_net_buying": 52.0,
        "pboc_gold_holdings_change": 4.1,
        "reserve_diversification_signal": "strong",
        "monetary_credit_repricing": "active",
        "long_term_support_score": 8.4,
        "source_refs": [{"source": "official_reserves", "source_ref": "reserves"}],
    }

    overview = build_gold_macro_overview(payload, reserve_context=reserve_context).to_dict()

    assert overview["priority_regime"] == "monetary_credit_repricing"
    assert overview["dominant_mainline"] == "central_bank_gold"


def test_gold_macro_overview_exposes_silver_etf_holdings_as_cross_metal_confirmation() -> None:
    payload = {
        "asset": "XAUUSD",
        "status": "available",
        "as_of": "2026-07-21T08:30:00+00:00",
        "mainlines": [{"mainline_id": "etf_flows", "coverage_status": "missing", "score": 0}],
        "event_links": [],
    }
    flow_context = {
        "global_etf_flow": 4.566,
        "gold_etf_holdings_tonnes": 1003.59,
        "gold_etf_change_tonnes": 4.566,
        "gold_etf_reported_on": "2026-07-20",
        "silver_etf_holdings_tonnes": 15052.89,
        "silver_etf_change_tonnes": -8.43,
        "silver_etf_reported_on": "2026-07-20",
        "cross_metal_confirmation": "divergent",
        "source_refs": [{"source": "jin10_minipro", "source_tier": "supplemental"}],
    }

    overview = build_gold_macro_overview(payload, flow_context=flow_context).to_dict()
    etf = next(row for row in overview["theme_rankings"] if row["mainline_id"] == "etf_flows")

    assert etf["feature_fields"]["gold_etf_holdings_tonnes"] == 1003.59
    assert etf["feature_fields"]["silver_etf_holdings_tonnes"] == 15052.89
    assert etf["feature_fields"]["silver_etf_change_tonnes"] == -8.43
    assert etf["feature_fields"]["cross_metal_confirmation"] == "divergent"
