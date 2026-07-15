from __future__ import annotations

from datetime import datetime, timezone

from apps.analysis.agents import AgentBias, AgentStatus
from apps.analysis.agents.news import analyze_news

_CREATED_AT = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)


def _snapshot(news_section: dict) -> dict:
    return {
        "snapshot_id": "XAUUSD:2026-05-16:test-run",
        "input_snapshot_ids": {"analysis_snapshot": "XAUUSD:2026-05-16:test-run"},
        "source_refs": [{"source": "analysis_snapshot", "snapshot_id": "XAUUSD:2026-05-16:test-run"}],
        "news": news_section,
    }


def test_analyze_news_returns_neutral_success_for_available_news():
    output = analyze_news(
        _snapshot({
            "status": "available",
            "data": {
                "risk_level": "HIGH",
                "high_star_count_7d": 2,
                "recent_events": [
                    {"title": "美国CPI", "pub_time": "2026-05-16T08:30:00+00:00", "star": 5},
                ],
                "recent_flashes": [
                    {"time": "2026-05-16T09:00:00+00:00", "content": "", "url": "美联储-利率"},
                ],
                "source_refs": [{"source": "jin10_mcp", "method": "list_calendar"}],
            },
        }),
        created_at=_CREATED_AT,
    )

    assert output.agent_name == "news_agent"
    assert output.module == "news"
    assert output.status is AgentStatus.SUCCESS
    assert output.bias is AgentBias.NEUTRAL
    assert 0.0 < output.confidence <= 0.80
    assert any("HIGH" in finding for finding in output.key_findings)
    assert any(ref.get("source") == "jin10_mcp" for ref in output.source_refs)


def test_analyze_news_unavailable_when_snapshot_section_missing():
    output = analyze_news(_snapshot({"status": "unavailable", "reason": "no_news_collected_points"}), created_at=_CREATED_AT)

    assert output.status is AgentStatus.UNAVAILABLE
    assert output.bias is AgentBias.NEUTRAL
    assert output.confidence == 0.0
    assert "news status" in output.invalid_conditions[0]


def test_analyze_news_consumes_daily_market_brief_without_upgrading_unconfirmed_events():
    output = analyze_news(
        _snapshot({
            "status": "available",
            "data": {
                "daily_market_brief": {
                    "market_mainline": {
                        "status": "available",
                        "summary": "中东航运风险升温",
                        "risk_level": "high",
                    },
                    "confirmed_events": [
                        {
                            "event_id": "event:inflation_release:cpi",
                            "what_happened": "Consumer Price Index",
                            "verification_status": "official_confirmed",
                            "impact_path": "scheduled_macro_release_to_rates",
                            "pricing_status": "scheduled",
                            "risk_level": "medium",
                        }
                    ],
                    "candidate_events": [
                        {
                            "event_id": "event:hormuz_risk:abc123",
                            "what_happened": "Iran warns over Strait of Hormuz shipping",
                            "verification_status": "multi_source",
                            "impact_path": "geo_risk_to_oil_to_inflation",
                            "pricing_status": "partially_priced",
                            "risk_level": "high",
                            "need_verification": True,
                        },
                        {
                            "event_id": "event:gold_fund_flow:jin10",
                            "what_happened": "Jin10 report says gold ETF money is waiting for catalysts",
                            "verification_status": "single_source",
                            "impact_path": "gold_etf_flow_watchlist",
                            "pricing_status": "unknown",
                            "risk_level": "low",
                            "need_verification": True,
                        },
                    ],
                    "unconfirmed_risks": [
                        {
                            "event_id": "event:hormuz_risk:abc123",
                            "what_happened": "Iran warns over Strait of Hormuz shipping",
                            "verification_status": "multi_source",
                            "impact_path": "geo_risk_to_oil_to_inflation",
                            "pricing_status": "partially_priced",
                            "risk_level": "high",
                            "need_verification": True,
                        }
                    ],
                    "report_inputs": {
                        "news_highlights": [],
                        "watchlist": [],
                        "risk_points": [],
                        "market_observations": [
                            {
                                "observation_type": "external_market_odds",
                                "source_kind": "jin10_external_market_odds",
                                "provider_role": "supplemental_source",
                                "article_id": "223555",
                                "extraction_status": "needs_review",
                                "influence_policy": {
                                    "can_change_macro_regime": False,
                                    "can_set_strategy_direction": False,
                                    "can_block_readiness": False,
                                },
                                "items": [{"item_id": "odds-1", "asset": "XAUUSD", "probability": 0.94}],
                            }
                        ],
                    },
                    "source_refs": [{"source": "daily_market_brief", "source_ref": "brief:run-001"}],
                }
            },
        }),
        created_at=_CREATED_AT,
    )

    assert output.status is AgentStatus.SUCCESS
    assert output.bias is AgentBias.NEUTRAL
    assert any("Consumer Price Index" in finding for finding in output.key_findings)
    assert any("official_confirmed" in finding for finding in output.key_findings)
    assert any("Iran warns" in risk for risk in output.risk_points)
    assert any("gold ETF money" in item for item in output.watchlist)
    assert not any("gold ETF money" in finding for finding in output.key_findings)
    assert any(ref.get("source") == "daily_market_brief" for ref in output.source_refs)
    assert output.bias is AgentBias.NEUTRAL
    assert any("外部赔率观察" in item for item in output.watchlist)
    assert any("不得升级为方向结论" in item for item in output.risk_points)
    assert output.input_payload["external_market_odds_count"] == 1
    assert output.evidence_items[0]["provider_role"] == "supplemental_source"
