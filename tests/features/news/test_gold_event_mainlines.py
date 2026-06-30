from __future__ import annotations

from apps.features.news.gold_event_mainlines import MAINLINE_ORDER, build_gold_event_mainlines


def _event(
    *,
    event_id: str,
    event_type: str,
    title: str,
    verification_status: str = "single_source",
    direction: str = "neutral",
) -> dict:
    return {
        "event_id": event_id,
        "event_type": event_type,
        "event_status": "developing",
        "event_time": "2026-06-30T08:15:00+00:00",
        "asset_tags": ["XAUUSD"],
        "topic_tags": [],
        "direction": direction,
        "confidence": 0.72,
        "verification_status": verification_status,
        "need_verification": verification_status not in {"official_confirmed", "multi_source"},
        "evidence_text": title,
        "source_refs": [
            {
                "source_ref": f"news:{event_id}",
                "source": "fixture_news",
                "title": title,
                "url": f"https://example.com/{event_id}",
            }
        ],
        "source_count": 1,
        "data_quality": {"verification_reason": verification_status},
    }


def _impact(
    *,
    event_id: str,
    impact_path: str,
    gold_impact: str,
    dollar_impact: str = "unknown",
    yield_impact: str = "unknown",
    oil_impact: str = "unknown",
    pricing_status: str = "unknown",
) -> dict:
    return {
        "event_id": event_id,
        "impact_path": impact_path,
        "gold_impact": gold_impact,
        "dollar_impact": dollar_impact,
        "yield_impact": yield_impact,
        "oil_impact": oil_impact,
        "pricing_status": pricing_status,
        "risk_level": "medium",
        "confidence": 0.7,
    }


def test_gold_event_mainlines_always_outputs_nine_mainline_coverage() -> None:
    bundle = build_gold_event_mainlines(
        [
            _event(
                event_id="event:fed-hawkish",
                event_type="fed_hawkish",
                title="Fed officials signal rates may stay higher for longer",
                verification_status="multi_source",
            ),
            _event(
                event_id="event:hormuz",
                event_type="hormuz_risk",
                title="Hormuz shipping risk lifts oil inflation concern",
                direction="mixed",
            ),
        ],
        impact_assessments=[
            _impact(
                event_id="event:fed-hawkish",
                impact_path="strong_data_to_higher_for_longer",
                gold_impact="bearish",
                dollar_impact="dollar_strength",
                yield_impact="yield_up",
                pricing_status="partially_priced",
            ),
            _impact(
                event_id="event:hormuz",
                impact_path="geo_risk_to_oil_to_inflation",
                gold_impact="mixed",
                dollar_impact="dollar_strength",
                yield_impact="yield_up",
                oil_impact="oil_up",
                pricing_status="unpriced",
            ),
        ],
        as_of="2026-06-30T08:30:00+00:00",
    )

    data = bundle.to_dict()
    assert [row["mainline_id"] for row in data["mainlines"]] == MAINLINE_ORDER
    assert len(data["mainlines"]) == 9

    covered = {row["mainline_id"]: row for row in data["mainlines"]}
    assert covered["fed_policy_path"]["coverage_status"] == "covered"
    assert covered["real_rates_usd"]["coverage_status"] == "covered"
    assert covered["oil_prices"]["coverage_status"] == "covered"
    assert covered["geopolitical_war_risk"]["coverage_status"] == "covered"
    assert covered["gold_technical_levels"]["coverage_status"] == "missing"
    assert covered["gold_technical_levels"]["missing_data"] == ["xauusd_price"]
    assert covered["etf_flows"]["missing_data"] == ["etf_flows"]
    assert covered["central_bank_gold"]["missing_data"] == ["central_bank_reserves"]
    assert covered["china_asia_demand"]["missing_data"] == ["asia_physical_demand"]
    assert covered["institutional_sentiment"]["missing_data"] == ["positioning_data"]
    assert covered["fed_policy_path"]["theme_score"] == 18
    assert covered["fed_policy_path"]["direction_score"] == -1
    assert covered["fed_policy_path"]["impact_score"] == 3
    assert covered["fed_policy_path"]["confidence_score"] == 3
    assert covered["fed_policy_path"]["freshness_score"] == 2


def test_mixed_geopolitical_event_keeps_driver_split_and_verification_chain() -> None:
    bundle = build_gold_event_mainlines(
        [
            _event(
                event_id="event:hormuz",
                event_type="hormuz_risk",
                title="Hormuz shipping risk lifts oil inflation concern",
                direction="mixed",
            )
        ],
        impact_assessments=[
            _impact(
                event_id="event:hormuz",
                impact_path="geo_risk_to_oil_to_inflation",
                gold_impact="mixed",
                dollar_impact="dollar_strength",
                yield_impact="yield_up",
                oil_impact="oil_up",
                pricing_status="unpriced",
            )
        ],
        as_of="2026-06-30T08:30:00+00:00",
    )

    link = bundle.to_dict()["event_links"][0]
    assert link["primary_mainline"] == "geopolitical_war_risk"
    assert link["transmission_path_ids"] == ["geopolitics_to_oil_to_rates", "haven_bid"]
    assert link["bullish_drivers"] == ["safe_haven_bid"]
    assert link["bearish_drivers"] == ["oil_inflation_rate_pressure", "usd_strength_pressure"]
    assert link["dominant_driver"] == "oil_inflation_rate_pressure"
    assert link["verification_needed"] == [
        "multi_source_confirmation_needed",
        "oil_price_reaction_needed",
        "real_rate_response_needed",
    ]
    assert link["verification_chain"]["status"] == "single_source"
    assert link["verification_chain"]["source_count"] == 1
    assert link["verification_chain"]["official_source_count"] == 0
    assert link["verification_chain"]["independent_source_count"] == 1
    assert link["verification_chain"]["has_multi_source"] is False
    assert "multi_source_confirmation_needed" in link["verification_chain"]["missing_confirmations"]


def test_official_confirmed_event_does_not_require_multi_source_confirmation() -> None:
    bundle = build_gold_event_mainlines(
        [
            _event(
                event_id="event:official-fed",
                event_type="fomc_statement",
                title="FOMC official statement confirms policy hold",
                verification_status="official_confirmed",
                direction="neutral",
            )
        ],
        impact_assessments=[
            _impact(
                event_id="event:official-fed",
                impact_path="strong_data_to_higher_for_longer",
                gold_impact="neutral",
                pricing_status="partially_priced",
            )
        ],
        as_of="2026-06-30T08:30:00+00:00",
    )

    link = bundle.to_dict()["event_links"][0]
    assert "multi_source_confirmation_needed" not in link["verification_needed"]
    assert "real_rate_response_needed" in link["verification_needed"]
    assert link["verification_chain"]["status"] == "official_confirmed"
    assert link["verification_chain"]["has_official_source"] is True
    assert link["verification_chain"]["required_status"] == "not_required"
    assert "multi_source_confirmation_needed" not in link["verification_chain"]["missing_confirmations"]


def test_multi_source_event_verification_chain_counts_independent_sources() -> None:
    event = _event(
        event_id="event:multi-fed",
        event_type="fed_hawkish",
        title="Fed signal confirmed by official and wire sources",
        verification_status="multi_source",
    )
    event["source_count"] = 3
    event["source_refs"] = [
        {"source_ref": "fed:official", "source": "fed_rss", "source_type": "official"},
        {"source_ref": "reuters:fed", "source": "reuters_public_news", "source_type": "wire"},
        {"source_ref": "gdelt:fed", "source": "gdelt_news", "source_type": "aggregator"},
    ]

    bundle = build_gold_event_mainlines(
        [event],
        impact_assessments=[
            _impact(
                event_id="event:multi-fed",
                impact_path="strong_data_to_higher_for_longer",
                gold_impact="bearish",
                dollar_impact="dollar_strength",
                yield_impact="yield_up",
                pricing_status="partially_priced",
            )
        ],
        as_of="2026-06-30T08:30:00+00:00",
    )

    chain = bundle.to_dict()["event_links"][0]["verification_chain"]
    assert chain["status"] == "multi_source"
    assert chain["source_count"] == 3
    assert chain["official_source_count"] == 1
    assert chain["independent_source_count"] == 3
    assert chain["has_official_source"] is True
    assert chain["has_multi_source"] is True
    assert chain["required_status"] == "not_required"
    assert chain["missing_confirmations"] == ["real_rate_response_needed"]
