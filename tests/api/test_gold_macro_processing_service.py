from __future__ import annotations

from apps.analysis.gold_mainline_engine import (
    build_verification_matrix,
    classify_gold_phase,
    detect_transmission_chains,
    score_theme_rankings,
)
from apps.api.services.gold_macro_processing_service import (
    build_driver_decomposition,
    build_gold_macro_overview,
    build_mainline_attribution,
    build_processing_trace,
    build_transmission_chains,
    build_view_bindings,
)


def _hormuz_event() -> dict:
    return {
        "event_id": "event:hormuz",
        "event_type": "hormuz_risk",
        "direction": "mixed",
        "impact_path": "geo_risk_to_oil_to_inflation",
        "gold_impact": "mixed",
        "oil_impact": "oil_up",
        "yield_impact": "yield_up",
        "pricing_status": "unpriced",
        "confidence": 0.78,
        "verification_status": "single_source",
        "source_refs": [{"source": "fixture_news", "source_ref": "news:hormuz"}],
    }


def test_gold_macro_processing_service_builds_entity_attribution_and_chains() -> None:
    event = _hormuz_event()

    attribution = build_mainline_attribution(event)
    chains = build_transmission_chains(event)
    decomposition = build_driver_decomposition(event)

    assert attribution["primary_mainline"] == "geopolitical_war_risk"
    assert attribution["mainlines"] == ["geopolitical_war_risk", "oil_prices", "real_rates_usd"]
    assert attribution["transmission_chains"] == ["geopolitics_to_oil_to_rates", "haven_bid"]
    assert attribution["processing_trace_id"] == "trace:event:hormuz"
    assert {item["chain_id"] for item in chains} == {"war_oil_rate_chain", "safe_haven_chain"}
    assert decomposition["bullish_drivers"] == ["safe_haven_bid"]
    assert "oil_inflation_rate_pressure" in decomposition["bearish_drivers"]
    assert decomposition["dominant_driver"] == "oil_inflation_rate_pressure"
    assert decomposition["why_not_one_sided"]
    assert decomposition["source_refs"] == event["source_refs"]


def test_gold_macro_processing_service_builds_overview_trace_and_view_bindings() -> None:
    event = _hormuz_event()
    payload = build_gold_macro_overview(
        events=[event],
        as_of="2026-07-06T10:00:00+00:00",
        oil_context={
            "brent_price": 88.5,
            "brent_weekly_change": 4.2,
            "source_refs": [{"source": "market", "source_ref": "brent:1d"}],
        },
        macro_context={
            "indicators": {
                "REAL_10Y": {"value": 2.1, "weekly_change": 0.05},
                "BREAKEVEN_10Y": {"value": 2.3, "weekly_change": 0.08},
            },
            "source_refs": {
                "REAL_10Y": {"source": "fred", "raw_path": "raw/macro/real.json"},
                "BREAKEVEN_10Y": {"source": "fred", "raw_path": "raw/macro/breakeven.json"},
            },
        },
    )

    overview = payload["gold_macro_overview"]
    assert len(overview["theme_rankings"]) == 9
    assert overview["war_oil_rate_chain"]
    assert overview["war_oil_rate_chain"]["path_id"] == "geopolitics_to_oil_to_rates"
    assert overview["driver_conflict"]["bullish_drivers"] == ["safe_haven_bid"]
    assert "oil_inflation_rate_pressure" in overview["driver_conflict"]["bearish_drivers"]
    assert overview["verification_matrix"]
    assert payload["processing_traces"][0]["trace_id"] == "trace:event:hormuz"
    assert payload["processing_traces"][0]["source_refs"] == event["source_refs"]
    assert payload["source_refs"]
    assert any(row["mainline_id"] == "gold_technical_levels" and "xauusd_price" in row["missing_data"] for row in overview["theme_rankings"])
    bindings = {item["view"]: item["status"] for item in payload["view_bindings"]}
    assert bindings["Dashboard"] == "bound"
    assert bindings["GoldMainlinesPage"] == "bound"
    assert bindings["OilGeopoliticsPage"] == "bound"
    assert bindings["ProcessingMonitor"] == "bound"


def test_processing_trace_marks_missing_sources_without_fabricating_refs() -> None:
    trace = build_processing_trace("event:no-source", entity={"event_id": "event:no-source"})

    assert trace["trace_id"] == "trace:event:no-source"
    assert trace["source_refs"] == []
    assert "source_refs_missing" in trace["warnings"]
    assert trace["stages"][-1]["warnings"] == ["source_refs_missing"]


def test_view_bindings_are_missing_when_overview_sections_are_absent() -> None:
    bindings = {item["view"]: item["status"] for item in build_view_bindings({})}

    assert bindings["Dashboard"] == "missing"
    assert bindings["GoldMainlinesPage"] == "missing"
    assert bindings["OilGeopoliticsPage"] == "missing"


def test_gold_mainline_engine_public_rule_functions_remain_available() -> None:
    event = _hormuz_event()
    rankings = score_theme_rankings([event], {"as_of": "2026-07-06T10:00:00+00:00"})
    verification_matrix = build_verification_matrix(rankings)

    assert detect_transmission_chains(event) == ["geopolitics_to_oil_to_rates", "haven_bid"]
    assert len(rankings) == 9
    assert classify_gold_phase(rankings) in {
        "strong_uptrend",
        "high_level_range",
        "weak_repair_watch",
        "correction_escalation",
        "trend_failure",
        "unknown",
    }
    assert verification_matrix
