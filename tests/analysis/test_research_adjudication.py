from copy import deepcopy
from datetime import UTC, datetime

from apps.analysis.agents.coordinator import coordinate_agent_outputs
from apps.analysis.agents.cme_options import analyze_cme_options
from apps.analysis.agents.research_adjudication import adjudicate_research
from apps.analysis.agents.research_context import build_research_assessment
from apps.analysis.agents.schemas import AgentBias, AgentOutput, AgentStatus
from apps.analysis.strategy.card import build_strategy_card


def snapshot(*, real_change=0.01, dollar_change=0.2, trend="bearish"):
    ref = {"source": "official", "source_url": "https://example.test/series", "raw_path": "raw/series.json", "retrieved_at": "2026-09-05T15:00:00+00:00"}
    rows = []
    for key, value, delta in (("REAL_10Y", 2.43, real_change), ("DXY", 99.16, dollar_change), ("US02Y", 4.37, 0.03), ("US10Y", 4.78, 0.01), ("XAUUSD_DAILY", 4430, -40)):
        rows.append({"symbol": key, "value": value, "change": delta, "status": "fresh", "lineage_status": "verified", "source_refs": [ref], "observation_date": "2026-09-04", "previous_date": "2026-09-03"})
    return {"snapshot_id": "research-test", "trade_date": "2026-09-05", "snapshot_time": "2026-09-05T16:00:00+00:00", "input_snapshot_ids": {"macro": "macro-test"}, "source_refs": [ref],
            "daily_research": {"schema_version": "daily_research.v1", "passport": rows, "rate_changes_same_window": True, "input_snapshot_ids": {"macro": "macro-test"}, "source_refs": [ref]},
            "technical": {"status": "available", "data": {"price": 4430, "ma20": 4500, "trend": trend, "key_levels": [{"kind": "daily_low", "price": 4350}, {"kind": "daily_high", "price": 4510}]}},
            "options": {"status": "available", "data": {"data_source": {"status": "PRELIM", "report_date": "2026-09-04"}, "intent": {"score": 0.9, "type": "bullish"}, "wall_scores": [{"strike": 4400, "wall_score": 0.9, "wall_type": "put_support"}]}}}


def prior(module, bias):
    return AgentOutput(version="1.0", agent_name=f"{module}_agent", module=module, snapshot_id="research-test", input_snapshot_ids={}, bias=bias, confidence=0.5,
                       key_findings=[], risk_points=[], watchlist=[], invalid_conditions=[], summary="test", source_refs=[], status=AgentStatus.PARTIAL, created_at=datetime(2026, 9, 5, tzinfo=UTC))


def test_risk_and_model_options_do_not_overwrite_independent_rate_and_dollar_evidence():
    data = snapshot()
    before = deepcopy(data)
    result = coordinate_agent_outputs(data, macro_output=prior("macro", "bearish"), options_output=prior("options", "bullish"), risk_output=prior("risk", "mixed"))
    assert result.bias == AgentBias.BEARISH
    assert result.accepted_state_conclusion is None
    assert result.input_payload["daily_research_assessment"]["adjudication"]["dominant_factor_ids"] == ["real_yield", "dollar"]
    assert data == before
    options = analyze_cme_options(data)
    assert options.bias == AgentBias.NEUTRAL
    assert all(item["direction"] == "neutral" for item in options.evidence_items)


def test_direction_and_scenario_react_to_opposite_joint_evidence_and_are_shared_with_card():
    data = snapshot(real_change=-0.04, dollar_change=-0.3, trend="bullish")
    result = coordinate_agent_outputs(data, macro_output=prior("macro", "bearish"), options_output=prior("options", "bearish"), risk_output=prior("risk", "bearish"))
    assessment = result.input_payload["daily_research_assessment"]
    assert result.bias == AgentBias.BULLISH
    assert assessment["scenarios"][0]["name"] == "修复展开"
    card = build_strategy_card(snapshot=data, coordinator_output=result)
    assert card.scenario_summary == assessment["summary"]
    assert any("2Y−3M" in item for item in card.watchlist)
    assert any(assessment["scenarios"][0]["trigger"] in item for item in card.trigger_conditions)


def test_unaligned_dollar_cannot_confirm_rate_direction_or_select_directional_primary_path():
    data = snapshot()
    data["daily_research"]["passport"][1]["previous_date"] = "2026-09-02"
    result = adjudicate_research(data)
    assert result["dominant_factor_ids"] == ["real_yield"]
    assert result["preferred_scenario"] == "区间消化"
    assert "美元与实际利率同步窗口" in result["missing_confirmations"]


def test_undated_provider_previous_close_is_context_not_aligned_primary_evidence():
    data = snapshot()
    data["daily_research"]["passport"][1].update(change=None, previous_date=None, provider_reported_change=.249, provider_previous_close=98.908)
    result = adjudicate_research(data)
    dollar = next(item for item in result["factors"] if item["factor_id"] == "dollar")
    assert dollar["role"] == "context" and dollar["bias"] == "bearish"
    assert result["dominant_factor_ids"] == ["real_yield"]
    assert result["preferred_scenario"] == "区间消化"


def test_new_price_window_cannot_confirm_older_macro_direction():
    data = snapshot()
    next(row for row in data["daily_research"]["passport"] if row["symbol"] == "XAUUSD_DAILY")["observation_date"] = "2026-09-05"
    result = adjudicate_research(data)
    assert result["factor_tilt"] == "bearish"
    assert result["bias"] == "neutral"
    assert result["preferred_scenario"] == "区间消化"
    assert "现货与宏观同一观察日确认" in result["missing_confirmations"]


def test_unverified_rate_value_and_duplicate_correlated_curve_do_not_create_votes():
    data = snapshot()
    data["daily_research"]["project_signals"] = {"short_curve": {"status": "available", "summary": "2Y 上行、3M 未降", "source_refs": data["source_refs"]}}
    result = adjudicate_research(data)
    assert result["dominant_factor_ids"] == ["real_yield", "dollar"]
    assert len({factor["family"] for factor in result["factors"] if factor["factor_id"] in {"real_yield", "short_curve_2y_3m"}}) == 1
    data["daily_research"]["passport"][0]["lineage_status"] = "missing_or_future_source"
    data["daily_research"]["passport"][1]["change"] = None
    result = adjudicate_research(data)
    assert result["bias"] == "unavailable"
    assert result["confidence"] == 0
    assert build_research_assessment(data)["scenarios"][0]["name"] == "区间消化"
