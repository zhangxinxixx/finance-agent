from __future__ import annotations

from apps.features.news.gold_event_mainlines import MAINLINE_ORDER, build_gold_event_mainlines
from apps.contracts.gold import normalize_gold_transmission_chain_id


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


def _normalized_chains(link: dict) -> set[str]:
    return {normalize_gold_transmission_chain_id(item) for item in link["transmission_path_ids"]}


def test_issue35_sample_fomc_cpi_nfp_maps_to_fed_rate_chain() -> None:
    bundle = build_gold_event_mainlines(
        [
            _event(
                event_id="event:cpi-fed",
                event_type="inflation_release",
                title="美国 CPI 高于预期，美联储官员称不急于降息。",
                verification_status="official_confirmed",
                direction="bearish",
            )
        ],
        impact_assessments=[
            _impact(
                event_id="event:cpi-fed",
                impact_path="strong_data_to_higher_for_longer",
                gold_impact="bearish",
                dollar_impact="dollar_strength",
                yield_impact="yield_up",
                pricing_status="partially_priced",
            )
        ],
        as_of="2026-07-06T09:30:00+00:00",
    )

    link = bundle.to_dict()["event_links"][0]
    assert link["primary_mainline"] == "fed_policy_path"
    assert "rate_chain" in _normalized_chains(link)
    assert link["direction_by_asset"]["XAUUSD"] == "bearish"
    assert link["bearish_drivers"] == ["higher_for_longer_rate_pressure", "usd_strength_pressure"]


def test_issue35_sample_middle_east_oil_keeps_safe_haven_and_rate_paths() -> None:
    bundle = build_gold_event_mainlines(
        [
            _event(
                event_id="event:middle-east-oil",
                event_type="middle_east_escalation",
                title="中东冲突升级，市场担心霍尔木兹运输风险，Brent 油价上涨。",
                direction="mixed",
            )
        ],
        impact_assessments=[
            _impact(
                event_id="event:middle-east-oil",
                impact_path="geo_risk_to_oil_to_inflation",
                gold_impact="mixed",
                dollar_impact="dollar_strength",
                yield_impact="yield_up",
                oil_impact="oil_up",
                pricing_status="unpriced",
            )
        ],
        as_of="2026-07-06T09:30:00+00:00",
    )

    link = bundle.to_dict()["event_links"][0]
    assert set(link["mainline_ids"]) == {"geopolitical_war_risk", "oil_prices", "real_rates_usd"}
    assert {"safe_haven_chain", "war_oil_rate_chain"}.issubset(_normalized_chains(link))
    assert link["direction_by_asset"]["XAUUSD"] == "mixed"
    assert link["bullish_drivers"]
    assert link["bearish_drivers"]
    assert {"oil_price_reaction_needed", "real_rate_response_needed"}.issubset(set(link["verification_needed"]))


def test_issue35_sample_etf_inflow_maps_to_flow_chain() -> None:
    bundle = build_gold_event_mainlines(
        [
            _event(
                event_id="event:etf-inflow",
                event_type="gold_fund_flow",
                title="全球黄金 ETF 连续两周净流入，北美 ETF 流入明显。",
                verification_status="multi_source",
                direction="bullish",
            )
        ],
        impact_assessments=[
            _impact(
                event_id="event:etf-inflow",
                impact_path="capital_confirmation",
                gold_impact="bullish",
                pricing_status="partially_priced",
            )
        ],
        as_of="2026-07-06T09:30:00+00:00",
    )

    link = bundle.to_dict()["event_links"][0]
    assert link["primary_mainline"] == "etf_flows"
    assert _normalized_chains(link) == {"flow_chain"}
    assert link["direction_by_asset"]["XAUUSD"] == "bullish"


def test_issue35_sample_central_bank_buying_is_structural_not_short_term_strong_bullish() -> None:
    bundle = build_gold_event_mainlines(
        [
            _event(
                event_id="event:central-bank",
                event_type="central_bank_gold_buying",
                title="新兴市场央行继续增持黄金储备。",
                direction="bullish",
            )
        ],
        impact_assessments=[
            _impact(
                event_id="event:central-bank",
                impact_path="reserve_reallocation",
                gold_impact="bullish",
                pricing_status="unknown",
            )
        ],
        as_of="2026-07-06T09:30:00+00:00",
    )

    data = bundle.to_dict()
    link = data["event_links"][0]
    central_bank = next(row for row in data["mainlines"] if row["mainline_id"] == "central_bank_gold")
    assert link["primary_mainline"] == "central_bank_gold"
    assert _normalized_chains(link) == {"reserve_chain"}
    assert link["bullish_drivers"] == []
    assert "official_reserve_data_needed" in link["verification_needed"]
    assert central_bank["impact_strength"] != "high"


def test_issue35_sample_technical_level_with_unconfirmed_etf_flow_requires_both_confirmations() -> None:
    bundle = build_gold_event_mainlines(
        [
            _event(
                event_id="event:technical-4100",
                event_type="key_level_watchlist",
                title="黄金重新站上4100-4120区间。",
                direction="bullish",
            ),
            _event(
                event_id="event:etf-unconfirmed",
                event_type="gold_fund_flow",
                title="ETF资金尚未确认回流。",
                direction="neutral",
            ),
        ],
        impact_assessments=[
            _impact(
                event_id="event:technical-4100",
                impact_path="technical_confirmation",
                gold_impact="bullish",
                pricing_status="unpriced",
            ),
            _impact(
                event_id="event:etf-unconfirmed",
                impact_path="capital_confirmation",
                gold_impact="neutral",
                pricing_status="unknown",
            ),
        ],
        as_of="2026-07-06T09:30:00+00:00",
    )

    links = {link["event_id"]: link for link in bundle.to_dict()["event_links"]}
    covered_mainlines = {
        row["mainline_id"] for row in bundle.to_dict()["mainlines"] if row["coverage_status"] == "covered"
    }
    assert {"gold_technical_levels", "etf_flows"}.issubset(covered_mainlines)
    assert _normalized_chains(links["event:technical-4100"]) == {"technical_chain"}
    assert _normalized_chains(links["event:etf-unconfirmed"]) == {"flow_chain"}
    assert "price_level_confirmation_needed" in links["event:technical-4100"]["verification_needed"]
    assert "flow_data_confirmation_needed" in links["event:etf-unconfirmed"]["verification_needed"]
