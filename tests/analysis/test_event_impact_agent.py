from __future__ import annotations

from apps.analysis.agents import AgentBias, AgentStatus
from apps.analysis.agents.event_impact import run_event_impact_agent, run_structured_event_impact_agent


def _daily_market_brief() -> dict:
    return {
        "market_mainline": {
            "status": "available",
            "summary": "Fed hawkish repricing dominates gold.",
            "risk_level": "high",
        },
        "confirmed_events": [
            {
                "event_id": "event:fed_hawkish:powell",
                "event_type": "fed_hawkish",
                "what_happened": "Powell says rates may stay higher for longer",
                "who_said": "Federal Reserve",
                "verification_status": "official_confirmed",
                "impact_path": "strong_data_to_higher_for_longer",
                "gold_impact": "bearish",
                "silver_impact": "bearish",
                "dollar_impact": "dollar_strength",
                "yield_impact": "yield_up",
                "oil_impact": "unknown",
                "risk_level": "medium",
                "pricing_status": "partially_priced",
                "market_validation": {
                    "pricing_status": "partially_priced",
                    "confirmation_summary": {"confirmed_count": 2, "contradicted_count": 0},
                },
                "source_refs": [{"source": "fed_rss", "source_ref": "fed:powell"}],
            }
        ],
        "candidate_events": [
            {
                "event_id": "event:hormuz_risk:abc123",
                "event_type": "hormuz_risk",
                "what_happened": "Iran-linked shipping risk headlines increase",
                "verification_status": "multi_source",
                "impact_path": "geo_risk_to_oil_to_inflation",
                "gold_impact": "mixed",
                "silver_impact": "mixed",
                "dollar_impact": "dollar_strength",
                "yield_impact": "yield_up",
                "oil_impact": "oil_up",
                "risk_level": "high",
                "pricing_status": "unpriced",
                "need_verification": True,
                "source_refs": [{"source": "gdelt_news", "source_ref": "gdelt:hormuz"}],
            },
            {
                "event_type": "gold_fund_flow",
                "what_happened": "Report-only gold ETF flow comment without stable event id",
                "verification_status": "single_source",
                "impact_path": "gold_etf_flow_watchlist",
                "gold_impact": "neutral",
                "risk_level": "low",
                "need_verification": True,
            },
        ],
        "unconfirmed_risks": [
            {
                "event_id": "event:hormuz_risk:abc123",
                "event_type": "hormuz_risk",
                "what_happened": "Iran-linked shipping risk headlines increase",
                "verification_status": "multi_source",
                "impact_path": "geo_risk_to_oil_to_inflation",
                "gold_impact": "mixed",
                "risk_level": "high",
                "pricing_status": "unpriced",
                "need_verification": True,
            }
        ],
        "source_refs": [{"source": "daily_market_brief", "source_ref": "brief:run-001"}],
    }


def test_structured_event_impact_preserves_event_ids_and_verification_boundaries():
    output = run_structured_event_impact_agent(
        daily_market_brief=_daily_market_brief(),
        snapshot_id="snapshot:news:p0",
        run_id="run:p0",
    )

    assert output.status is AgentStatus.SUCCESS
    assert output.bias is AgentBias.BEARISH
    assert any("event:fed_hawkish:powell" in finding for finding in output.key_findings)
    assert any("official_confirmed" in finding for finding in output.key_findings)
    assert not any("event:hormuz_risk:abc123" in finding for finding in output.key_findings)
    assert any("event:hormuz_risk:abc123" in risk for risk in output.risk_points)
    assert any("multi_source" in risk for risk in output.risk_points)
    assert any("missing event_id" in condition for condition in output.invalid_conditions)
    assert any(ref.get("source") == "daily_market_brief" for ref in output.source_refs)
    assert any(ref.get("source") == "fed_rss" for ref in output.source_refs)
    assert output.evidence_refs[0]["type"] == "structured_event_impact"
    assert "event:fed_hawkish:powell" in output.evidence_refs[0]["event_ids"]
    assert output.evidence_refs[0]["excluded_missing_event_id_count"] == 1
    assert output.input_payload is not None
    assert output.input_payload["daily_market_brief"]["market_mainline"]["status"] == "available"
    assert output.llm_raw_output is None


def test_run_event_impact_agent_uses_structured_path_when_brief_is_present():
    output = run_event_impact_agent(
        [],
        daily_market_brief=_daily_market_brief(),
        snapshot_id="snapshot:news:p0",
        run_id="run:p0",
    )

    assert output.status is AgentStatus.SUCCESS
    assert output.data_category is not None
    assert output.evidence_refs[0]["generated_by"] == "structured_rules"
    assert output.input_snapshot_ids["daily_market_brief"] == "snapshot:news:p0"
