from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from apps.api.services.dashboard_service import (
    _get_dashboard_current_market,
    _dashboard_gold_macro_overview,
    _explicit_pin_level,
    _gate_agent_summary,
    _load_dashboard_strategy,
    _options_confidence,
    get_dashboard_summary,
)


@pytest.fixture(autouse=True)
def no_runtime_research_database(monkeypatch):
    monkeypatch.setattr("apps.api.services.dashboard_service.get_dashboard_research_context", lambda: None)
    monkeypatch.setattr("apps.api.services.dashboard_service._get_dashboard_current_market", lambda: None)


@pytest.mark.parametrize("has_plan", [True, False])
@pytest.mark.parametrize("verified", [True, False])
@pytest.mark.parametrize("reason", ["research_identity_or_artifact_unverified", "research_narrative_unavailable"])
def test_latest_research_never_mixes_legacy_macro_or_promotes_state(monkeypatch, verified, reason, has_plan):
    from apps.api.services import dashboard_service as service

    research = {
        "status": "available" if verified else "unavailable", "authority": "observation_only",
        "run_id": "research-new", "snapshot_id": "snapshot-new", "report_id": "report-new",
        "trade_date": "2026-09-17", "as_of": "2026-09-17T10:12:00Z",
        "macro": {"as_of": "2026-09-17", "indicators": {"REAL_10Y": {"value": 2.68, "date": "2026-09-16"}}},
        "price_anchor": {"instrument_type": "spot", "price": 4310.67, "price_time": "2026-09-17T10:09:00Z"},
        "summary": "新研究结论", "bias": "neutral", "confidence": 0.5,
        "risks": [], "invalid_conditions": [], "state": {"accepted_state": None, "candidate_state": "S4"},
    }
    facts_available = verified or reason == "research_narrative_unavailable"
    if has_plan:
        research["final_trade_plan"] = {"schema_version": "research_trade_plan.v1", "report_id": "report-new",
                                       "status": "waiting", "execution_ready": False}
    research["facts_status"] = "available" if facts_available else "unavailable"
    research["options"] = {"trade_date": "2026-09-17", "parameters": {"f_value": 3700},
                           "data_source": {"status": "PRELIM"}}
    research["source_refs"] = [{"source": "FRED", "symbol": "REAL_10Y"}]
    if not verified:
        research["reason"] = reason
    monkeypatch.setattr(service, "get_dashboard_research_context", lambda: research)
    monkeypatch.setattr(service, "get_macro_latest", lambda: pytest.fail("must not read legacy macro"))
    monkeypatch.setattr(service, "get_options_snapshot", lambda: pytest.fail("must not read unrelated options"))
    monkeypatch.setattr(service, "get_market_tickers", lambda: {"tickers": {"DXY": {"price": 99.8}}})
    monkeypatch.setattr(service, "list_recent_tasks", lambda _: [])
    monkeypatch.setattr(service, "list_reports_index", lambda: {"reports": [
        {"type": "observation_report", "family": "observation_report_markdown", "trade_date": "2026-09-17", "run_id": "research-new", "available": True},
        {"type": "final_report", "trade_date": "2026-09-06", "run_id": "formal-old", "available": True},
    ]})
    monkeypatch.setattr(service, "get_data_source_statuses", lambda: {"sources": [
        {"source_key": "jin10_news", "status": "disabled", "configured": False},
        {"source_key": "gdp_now", "status": "ready", "configured": True},
        {"source_key": "active_feed", "status": "failed", "configured": True},
    ]})
    monkeypatch.setattr(service, "_load_dashboard_strategy", lambda _: {"run_id": "formal-old"})
    monkeypatch.setattr(service, "build_dashboard_agent_summary", lambda: {})
    monkeypatch.setattr(service, "_load_gold_macro_overview", lambda: {"run_id": "old-news"})
    monkeypatch.setattr(service, "_load_latest_jin10_analysis", lambda: None)
    current_market = {"macro": {"indicators": {"REAL_10Y": {"value": 2.85, "date": "2026-09-24"}}},
                      "realtime_quotes": {"xauusd": {"price": 4125, "source": "twelvedata"}}}
    monkeypatch.setattr(service, "_get_dashboard_current_market", lambda: current_market)
    data = service.get_dashboard_summary()
    if verified and has_plan:
        assert data["integrated_macro"]["final_trade_plan"] == research["final_trade_plan"]
    else:
        assert "final_trade_plan" not in data["integrated_macro"]
    assert data["current_market"] == current_market
    assert data["risk_alerts"] == ["Data source active_feed: failed"]
    assert data["composite_analysis"]["run_id"] == "formal-old"
    assert data["gold_macro_overview"] is None
    assert data["strategy"] == {}
    assert "DXY" not in data["realtime_quotes"]
    if facts_available:
        assert data["macro"]["indicators"]["REAL_10Y"]["value"] == 2.68
        assert data["macro"]["snapshot_id"] == "snapshot-new"
        assert data["macro"]["source_refs"] == research["source_refs"]
        assert data["options"]["forward_price"] == 3700
        assert data["options"]["snapshot_id"] == "snapshot-new"
        assert data["options"]["data_status"] == "PRELIM"
        assert data["module_status"]["macro"] == "available"
        assert data["module_status"]["options"] == "available"
    else:
        assert data["macro"] is None
        assert data["options"] is None
    if verified:
        assert data["macro"]["indicators"]["REAL_10Y"]["value"] == 2.68
        assert data["macro"]["snapshot_id"] == "snapshot-new"
        assert data["integrated_macro"]["run_id"] == "research-new"
        assert data["integrated_macro"]["accepted_state"] is None
        assert "新研究结论" in data["integrated_macro"]["reasoning"]
    else:
        assert data["realtime_quotes"] == {}
        assert data["integrated_macro"]["direction"] == "neutral"
        assert data["integrated_macro"]["confidence"] is None
        assert data["integrated_macro"]["publish_allowed"] is False
        assert "accepted_state" not in data["integrated_macro"]
        assert data["research_context"]["status"] == "unavailable"
        assert data["research_context"]["facts_status"] == research["facts_status"]
        assert data["integrated_macro"]["source"] == "unavailable"
        assert data["integrated_macro"]["trade_date"] == "2026-09-17"
        assert data["integrated_macro"]["run_id"] == "research-new"
        assert data["integrated_macro"]["source_refs"][0]["source_ref"] == "report-new"
        assert data["integrated_macro"]["overall_bias"] == (
            "本次完整分析尚未生成" if reason == "research_narrative_unavailable" else "最新研究校验未通过"
        )


def test_dashboard_pin_level_accepts_only_finite_numeric_values() -> None:
    assert _explicit_pin_level(4325) == 4325.0
    assert _explicit_pin_level(4325.5) == 4325.5
    assert _explicit_pin_level({"price": 4325}) is None
    assert _explicit_pin_level("4325") is None
    assert _explicit_pin_level(float("nan")) is None
    assert _explicit_pin_level(True) is None


def test_dashboard_agent_summary_is_bound_to_accepted_composite_run():
    result = _gate_agent_summary(
        {
            "synthesis": {"run_id": "jin10-225471", "snapshot_id": "jin10:snapshot"},
            "coordinator": {"run_id": "old-composite", "snapshot_id": "old:snapshot"},
        },
        {"run_id": "current-composite", "degraded_newer_reports": []},
    )

    assert result["synthesis"] is None
    assert result["synthesis_gate"]["status"] == "stale"
    assert result["synthesis_gate"]["accepted_run_id"] == "current-composite"
    assert result["coordinator"] is None
    assert result["coordinator_gate"]["status"] == "stale"


def test_dashboard_agent_summary_keeps_output_from_accepted_composite_run():
    result = _gate_agent_summary(
        {
            "synthesis": None,
            "coordinator": {"run_id": "current-composite", "summary": "current"},
        },
        {"run_id": "current-composite", "degraded_newer_reports": []},
    )

    assert result["coordinator"]["summary"] == "current"
    assert "coordinator_gate" not in result


def test_dashboard_strategy_is_bound_to_accepted_composite_run(monkeypatch):
    monkeypatch.setattr(
        "apps.api.services.dashboard_service.get_strategy_card_latest",
        lambda: {
            "trade_date": "2026-07-23",
            "run_id": "current-composite",
            "json": {
                "trade_date": "2026-07-23",
                "run_id": "current-composite",
                "bias": "mixed",
                "confidence": 0.19,
                "market_regime": "rate_pressure",
                "scenario_summary": "Current formal composite summary.",
                "trigger_conditions": ["trigger"],
                "invalid_conditions": ["invalid"],
                "risk_points": ["risk"],
                "input_snapshot_ids": {"analysis_snapshot": "snapshot-current"},
            },
        },
    )

    result = _load_dashboard_strategy(
        {"trade_date": "2026-07-23", "run_id": "current-composite"},
    )

    assert result["scenario_summary"] == "Current formal composite summary."
    assert result["confidence"] == 0.19
    assert result["run_id"] == "current-composite"
    assert result["snapshot_id"] == "snapshot-current"


def test_dashboard_strategy_rejects_mismatched_run(monkeypatch):
    monkeypatch.setattr(
        "apps.api.services.dashboard_service.get_strategy_card_latest",
        lambda: {
            "trade_date": "2026-07-23",
            "run_id": "other-run",
            "json": {"trade_date": "2026-07-23", "run_id": "other-run"},
        },
    )

    assert _load_dashboard_strategy(
        {"trade_date": "2026-07-23", "run_id": "current-composite"},
    ) == {}


def test_dashboard_options_confidence_reuses_research_cme_weight_without_prelim_discount() -> None:
    snapshot = {
        "trade_date": "2026-09-09",
        "data_source": {
            "report_date": "2026-09-09",
            "status": "PRELIM",
            "source_refs": [{"source": "cme_daily_bulletin", "report_date": "2026-09-09"}],
        },
    }

    one_day = _options_confidence(
        options_snapshot=snapshot,
        intent_score=0.62,
        as_of=datetime(2026, 9, 10, 16, tzinfo=UTC),
    )
    two_days = _options_confidence(
        options_snapshot=snapshot,
        intent_score=0.62,
        as_of=datetime(2026, 9, 11, 16, tzinfo=UTC),
    )
    background = _options_confidence(
        options_snapshot=snapshot,
        intent_score=0.62,
        as_of=datetime(2026, 9, 14, 16, tzinfo=UTC),
    )

    assert one_day["score"] == 0.62
    assert one_day["weight_multiplier"] == 1.0
    assert "PRELIM_usable_without_extra_discount" in one_day["reasons"]
    assert two_days["score"] == 0.31
    assert two_days["weight_multiplier"] == 0.5
    assert background["score"] == 0.124
    assert background["trading_days"] == 3
    assert background["role"] == "background_only"


def test_dashboard_summary_exposes_cme_research_weight_and_proxy_semantics(monkeypatch):
    monkeypatch.setattr(
        "apps.api.services.dashboard_service.get_options_snapshot",
        lambda: {
            "trade_date": "2026-06-01",
            "data_source": {
                "report_date": "2026-06-01",
                "product": "OG",
                "expiries": ["JUL26"],
                "status": "PRELIM",
                "source_refs": [{"source": "cme_daily_bulletin", "report_date": "2026-06-01"}],
            },
            "intent": {"type": "I1_defensive", "score": 0.62},
            "gex": {
                "gamma_flip": {"label": "Selected Expiry Window Proxy Gamma Flip", "price": 4509.9},
                "netgex_aggregate": {"gamma_zero": {"price": 4509.9}},
            },
            "gex_semantics": {"label": "OI-Signed GEX Proxy", "dealer_position_unknown": True},
            "parameters": {"f_value": 4506.7},
            "support_resistance": {
                "resistance": [{"strike": 4515, "wall_score": 0.13, "distance_pct": 0.18}],
                "support": [{"strike": 4505, "wall_score": 0.11, "distance_pct": -0.04}],
            },
        },
    )
    monkeypatch.setattr("apps.api.services.dashboard_service.get_market_tickers", lambda: {"sources": [], "tickers": {}, "generated_at": None})
    monkeypatch.setattr("apps.api.services.dashboard_service.get_macro_latest", lambda: {"indicators": {}, "unavailable_symbols": []})
    monkeypatch.setattr("apps.api.services.dashboard_service.list_recent_tasks", lambda _limit=5: [])
    monkeypatch.setattr("apps.api.services.dashboard_service.list_reports_index", lambda: {"reports": []})
    monkeypatch.setattr("apps.api.services.dashboard_service.get_data_source_statuses", lambda: {"sources": []})
    monkeypatch.setattr("apps.api.services.dashboard_service.build_dashboard_agent_summary", lambda: {"coordinator": None, "synthesis": None})

    data = get_dashboard_summary()
    options = data["options"]
    assert options["trade_date"] == "2026-06-01"
    assert options["confidence"]["data_status"] == "PRELIM"
    assert options["confidence"]["score"] < 0.62
    assert "PRELIM_usable_without_extra_discount" in options["confidence"]["reasons"]
    assert options["confidence"]["role"] == "background_only"
    assert options["gamma_flip_label"] == "Selected Expiry Window Proxy Gamma Flip"
    assert options["gex_semantics_label"] == "OI-Signed GEX Proxy"
    assert options["dealer_position_unknown"] is True
    assert options["coordinate_space"] == "GC futures"
    assert options["pin_level"] is None


def test_dashboard_summary_includes_agent_read_model(monkeypatch):
    monkeypatch.setattr("apps.api.services.dashboard_service.get_options_snapshot", lambda: None)
    monkeypatch.setattr("apps.api.services.dashboard_service.get_market_tickers", lambda: {"sources": [], "tickers": {}, "generated_at": None})
    monkeypatch.setattr("apps.api.services.dashboard_service.get_macro_latest", lambda: None)
    monkeypatch.setattr("apps.api.services.dashboard_service.list_recent_tasks", lambda _limit=5: [])
    monkeypatch.setattr("apps.api.services.dashboard_service.list_reports_index", lambda: {"reports": []})
    monkeypatch.setattr("apps.api.services.dashboard_service.get_data_source_statuses", lambda: {"sources": []})
    monkeypatch.setattr(
        "apps.api.services.dashboard_service.build_dashboard_agent_summary",
        lambda: {
            "coordinator": {"agent_name": "coordinator", "summary": "协调摘要"},
            "synthesis": {"agent_name": "synthesis_agent", "summary": "综合摘要", "confidence": 0.72},
        },
    )

    data = get_dashboard_summary()

    assert data["agent_summary"]["synthesis"]["summary"] == "综合摘要"
    assert data["agent_summary"]["coordinator"]["agent_name"] == "coordinator"


def test_dashboard_summary_includes_gold_macro_overview(monkeypatch):
    monkeypatch.setattr("apps.api.services.dashboard_service.get_options_snapshot", lambda: None)
    monkeypatch.setattr("apps.api.services.dashboard_service.get_market_tickers", lambda: {"sources": [], "tickers": {}, "generated_at": None})
    monkeypatch.setattr("apps.api.services.dashboard_service.get_macro_latest", lambda: None)
    monkeypatch.setattr("apps.api.services.dashboard_service.list_recent_tasks", lambda _limit=5: [])
    monkeypatch.setattr("apps.api.services.dashboard_service.list_reports_index", lambda: {"reports": []})
    monkeypatch.setattr("apps.api.services.dashboard_service.get_data_source_statuses", lambda: {"sources": []})
    monkeypatch.setattr("apps.api.services.dashboard_service.build_dashboard_agent_summary", lambda: {"coordinator": None, "synthesis": None})
    monkeypatch.setattr(
        "apps.api.services.dashboard_service.get_gold_macro_overview_latest",
        lambda: {
            "asset": "XAUUSD",
            "as_of": "2026-06-30T00:00:00Z",
            "phase": "weak_repair_watch",
            "net_bias": "mixed",
            "dominant_mainline": "real_rates_usd",
            "theme_rankings": [
                {
                    "rank": 1,
                    "mainline_id": "real_rates_usd",
                    "score": 18,
                    "theme_score": 18,
                    "direction_score": -1,
                    "impact_score": 3,
                    "confidence_score": 3,
                    "freshness_score": 2,
                }
            ],
            "war_oil_rate_chain": {
                "path_id": "geopolitics_to_oil_to_rates",
                "conclusion_code": "C",
                "conclusion_label": "两者抵消，黄金震荡",
                "net_effect": "mixed",
            },
        },
    )

    data = get_dashboard_summary()

    assert data["gold_macro_overview"]["asset"] == "XAUUSD"
    assert data["gold_macro_overview"]["dominant_mainline"] == "real_rates_usd"
    assert data["gold_macro_overview"]["theme_rankings"][0]["theme_score"] == 18
    assert data["gold_macro_overview"]["theme_rankings"][0]["direction_score"] == -1
    assert data["gold_macro_overview"]["war_oil_rate_chain"]["conclusion_code"] == "C"


def test_dashboard_gold_macro_overview_projects_large_nested_evidence() -> None:
    large_ref = {"source_ref": "wire:1", "content": "x" * 100_000}
    overview = {
        "status": "partial",
        "asset": "XAUUSD",
        "as_of": "2026-09-14T00:00:00Z",
        "phase": "weak_repair_watch",
        "net_bias": "mixed",
        "risk_score": 42,
        "one_line_conclusion": "区间修复",
        "theme_rankings": [
            {
                "rank": 1,
                "mainline_id": "real_rates_usd",
                "label": "实际利率与美元",
                "direction": "bearish",
                "theme_score": 18,
                "source_refs": [large_ref],
            }
        ],
        "driver_conflict": {
            "status": "mixed",
            "bullish_drivers": ["safe_haven_bid"],
            "bearish_drivers": ["higher_for_longer_rate_pressure"],
            "verification_needed": ["确认实际利率"],
            "source_refs": [large_ref],
        },
        "war_oil_rate_chain": {
            "path_id": "geopolitics_to_oil_to_rates",
            "summary": "油价与利率链",
            "steps": [{"source_refs": [large_ref]}],
            "source_refs": [large_ref],
        },
        "verification_matrix": [
            {"id": "verify-1", "label": "确认实际利率", "status": "pending", "source_refs": [large_ref]}
        ],
        "source_refs": [large_ref],
    }

    projected = _dashboard_gold_macro_overview(overview)

    assert projected is not None
    assert projected["theme_rankings"][0]["theme_score"] == 18
    assert projected["driver_conflict"]["verification_needed"] == ["确认实际利率"]
    assert projected["war_oil_rate_chain"]["summary"] == "油价与利率链"
    assert projected["verification_matrix"][0]["label"] == "确认实际利率"
    assert len(json.dumps(projected, ensure_ascii=False)) < 5_000


def test_dashboard_summary_latest_reports_are_globally_sorted_by_trade_date(monkeypatch):
    monkeypatch.setattr("apps.api.services.dashboard_service.get_options_snapshot", lambda: None)
    monkeypatch.setattr("apps.api.services.dashboard_service.get_market_tickers", lambda: {"sources": [], "tickers": {}, "generated_at": None})
    monkeypatch.setattr("apps.api.services.dashboard_service.get_macro_latest", lambda: None)
    monkeypatch.setattr("apps.api.services.dashboard_service.list_recent_tasks", lambda _limit=5: [])
    monkeypatch.setattr(
        "apps.api.services.dashboard_service.list_reports_index",
        lambda: {
            "reports": [
                {"type": "final_report", "trade_date": "2026-06-08", "run_id": "final-run", "report_id": "final-run", "available": True},
                {"type": "strategy_card", "trade_date": "2026-06-08", "run_id": "strategy-run", "report_id": "strategy-run", "available": True},
                {"type": "jin10_daily_report", "trade_date": "2026-06-11", "run_id": "jin10-run", "report_id": "jin10-run", "available": True},
                {"type": "options_report", "trade_date": "2026-06-10", "run_id": "options-run", "report_id": "options-run", "available": True},
            ]
        },
    )
    monkeypatch.setattr("apps.api.services.dashboard_service.get_data_source_statuses", lambda: {"sources": []})
    monkeypatch.setattr("apps.api.services.dashboard_service.build_dashboard_agent_summary", lambda: {"coordinator": None, "synthesis": None})

    data = get_dashboard_summary()

    assert [item["trade_date"] for item in data["latest_reports"]] == [
        "2026-06-11",
        "2026-06-10",
        "2026-06-08",
        "2026-06-08",
    ]
    assert [item["type"] for item in data["latest_reports"][:2]] == [
        "jin10_daily_report",
        "options_report",
    ]


def test_dashboard_summary_composite_status_exposes_latest_run_ids(monkeypatch):
    monkeypatch.setattr("apps.api.services.dashboard_service.get_options_snapshot", lambda: None)
    monkeypatch.setattr("apps.api.services.dashboard_service.get_market_tickers", lambda: {"sources": [], "tickers": {}, "generated_at": None})
    monkeypatch.setattr("apps.api.services.dashboard_service.get_macro_latest", lambda: None)
    monkeypatch.setattr("apps.api.services.dashboard_service.list_recent_tasks", lambda _limit=5: [])
    monkeypatch.setattr(
        "apps.api.services.dashboard_service.list_reports_index",
        lambda: {
            "reports": [
                {"type": "strategy_card", "trade_date": "2026-07-14", "run_id": "run-new", "available": True},
                {"type": "final_report", "trade_date": "2026-07-14", "run_id": "run-new", "available": True},
                {"type": "strategy_card", "trade_date": "2026-07-13", "run_id": "run-old", "available": True},
            ]
        },
    )
    monkeypatch.setattr("apps.api.services.dashboard_service.get_data_source_statuses", lambda: {"sources": []})
    monkeypatch.setattr("apps.api.services.dashboard_service.build_dashboard_agent_summary", lambda: {"coordinator": None, "synthesis": None})

    data = get_dashboard_summary()

    assert data["composite_analysis"]["run_id"] == "run-new"
    assert data["composite_analysis"]["strategy_run_id"] == "run-new"
    assert data["composite_analysis"]["final_report_run_id"] == "run-new"


def test_dashboard_summary_marks_composite_partial_when_newer_jin10_is_degraded(monkeypatch):
    monkeypatch.setattr(
        "apps.api.services.dashboard_service.get_options_snapshot",
        lambda: {
            "trade_date": "2026-06-10",
            "data_source": {"product": "OG", "expiries": ["JUL26"], "status": "PRELIM"},
            "intent": {"type": "I1_defensive", "score": 0.46},
            "gex": {"netgex_aggregate": {"gamma_zero": {"price": 4515.6}}},
            "parameters": {"f_value": 4133.8},
            "support_resistance": {"resistance": [], "support": []},
        },
    )
    monkeypatch.setattr("apps.api.services.dashboard_service.get_market_tickers", lambda: {"sources": [], "tickers": {}, "generated_at": None})
    monkeypatch.setattr("apps.api.services.dashboard_service.get_macro_latest", lambda: None)
    monkeypatch.setattr("apps.api.services.dashboard_service.list_recent_tasks", lambda _limit=5: [])
    monkeypatch.setattr(
        "apps.api.services.dashboard_service.list_reports_index",
        lambda: {
            "reports": [
                {"type": "strategy_card", "trade_date": "2026-06-10", "run_id": "strategy-run", "report_id": "strategy-run", "available": True},
                {"type": "final_report", "trade_date": "2026-06-10", "run_id": "final-run", "report_id": "final-run", "available": True},
                {
                    "type": "jin10_daily_report",
                    "trade_date": "2026-06-12",
                    "run_id": "221592",
                    "report_id": "221592",
                    "title": "霍尔木兹海峡受阻3个月，全球通胀水平如何了？",
                    "available": True,
                    "status": "degraded",
                    "quality_audit": {"status": "rejected", "reason_codes": ["evidence_insufficient"]},
                },
            ]
        },
    )
    monkeypatch.setattr("apps.api.services.dashboard_service.get_data_source_statuses", lambda: {"sources": []})
    monkeypatch.setattr(
        "apps.api.services.dashboard_service.build_dashboard_agent_summary",
        lambda: {
            "coordinator": None,
            "synthesis": {
                "agent_name": "synthesis_agent",
                "run_id": "221592",
                "snapshot_id": "jin10:2026-06-12:221592:agent_analysis",
                "summary": "Rejected Jin10 synthesis",
            },
        },
    )

    data = get_dashboard_summary()

    assert data["composite_analysis"]["status"] == "partial"
    assert data["composite_analysis"]["trade_date"] == "2026-06-10"
    assert data["composite_analysis"]["latest_report_date"] == "2026-06-12"
    assert data["composite_analysis"]["latest_eligible_context_date"] == "2026-06-10"
    assert data["composite_analysis"]["degraded_newer_reports"][0]["run_id"] == "221592"
    assert data["latest_reports"][0]["status"] == "degraded"
    assert any("newer Jin10 reports are degraded" in warning for warning in data["warnings"])
    assert data["agent_summary"]["synthesis"] is None
    assert data["agent_summary"]["synthesis_gate"]["run_id"] == "221592"


def test_dashboard_summary_exposes_latest_macro_event_followup_without_replacing_formal_composite_date(monkeypatch):
    monkeypatch.setattr("apps.api.services.dashboard_service.get_options_snapshot", lambda: None)
    monkeypatch.setattr("apps.api.services.dashboard_service.get_market_tickers", lambda: {"sources": [], "tickers": {}, "generated_at": None})
    monkeypatch.setattr("apps.api.services.dashboard_service.get_macro_latest", lambda: None)
    monkeypatch.setattr("apps.api.services.dashboard_service.list_recent_tasks", lambda _limit=5: [])
    monkeypatch.setattr(
        "apps.api.services.dashboard_service.list_reports_index",
        lambda: {
            "reports": [
                {
                    "type": "final_report",
                    "trade_date": "2026-06-13",
                    "run_id": "final-run",
                    "report_id": "final-run",
                    "available": True,
                },
                {
                    "type": "strategy_card",
                    "trade_date": "2026-06-13",
                    "run_id": "strategy-run",
                    "report_id": "strategy-run",
                    "available": True,
                },
                {
                    "type": "macro_event_followup",
                    "trade_date": "2026-06-14",
                    "anchor_trade_date": "2026-06-13",
                    "run_id": "followup-run",
                    "report_id": "macro_event_followup:2026-06-14:followup-run",
                    "family": "macro_event_followup_supplement",
                    "title": "XAUUSD 宏观事件跟进补充（2026-06-14）",
                    "summary": "Weekend events reinforce the prior composite view.",
                    "available": True,
                },
            ]
        },
    )
    monkeypatch.setattr("apps.api.services.dashboard_service.get_data_source_statuses", lambda: {"sources": []})
    monkeypatch.setattr("apps.api.services.dashboard_service.build_dashboard_agent_summary", lambda: {"coordinator": None, "synthesis": None})

    data = get_dashboard_summary()

    assert data["composite_analysis"]["trade_date"] == "2026-06-13"
    assert data["composite_analysis"]["latest_report_date"] == "2026-06-14"
    assert data["latest_supplemental_report"]["type"] == "macro_event_followup"
    assert data["latest_supplemental_report"]["anchor_trade_date"] == "2026-06-13"
    assert data["latest_supplemental_report"]["summary"] == "Weekend events reinforce the prior composite view."
    assert data["latest_reports"][0]["type"] == "macro_event_followup"
    assert data["latest_reports"][0]["anchor_trade_date"] == "2026-06-13"
    assert data["latest_reports"][0]["summary"] == "Weekend events reinforce the prior composite view."


def test_dashboard_summary_keeps_latest_supplemental_report_when_it_falls_outside_latest_report_limit(monkeypatch):
    monkeypatch.setattr("apps.api.services.dashboard_service.get_options_snapshot", lambda: None)
    monkeypatch.setattr("apps.api.services.dashboard_service.get_market_tickers", lambda: {"sources": [], "tickers": {}, "generated_at": None})
    monkeypatch.setattr("apps.api.services.dashboard_service.get_macro_latest", lambda: None)
    monkeypatch.setattr("apps.api.services.dashboard_service.list_recent_tasks", lambda _limit=5: [])
    monkeypatch.setattr(
        "apps.api.services.dashboard_service.list_reports_index",
        lambda: {
            "reports": [
                *[
                    {
                        "type": "macro_report",
                        "trade_date": f"2026-06-{day:02d}",
                        "run_id": f"macro-{day}",
                        "report_id": f"macro_report:macro-{day}",
                        "available": True,
                    }
                    for day in range(20, 26)
                ],
                {
                    "type": "macro_event_followup",
                    "trade_date": "2026-06-14",
                    "anchor_trade_date": "2026-06-13",
                    "run_id": "followup-run",
                    "report_id": "macro_event_followup:2026-06-14:followup-run",
                    "family": "macro_event_followup_supplement",
                    "summary": "Older weekend supplement remains separately addressable.",
                    "available": True,
                },
            ]
        },
    )
    monkeypatch.setattr("apps.api.services.dashboard_service.get_data_source_statuses", lambda: {"sources": []})
    monkeypatch.setattr("apps.api.services.dashboard_service.build_dashboard_agent_summary", lambda: {"coordinator": None, "synthesis": None})

    data = get_dashboard_summary()

    assert all(item["type"] != "macro_event_followup" for item in data["latest_reports"])
    assert data["latest_supplemental_report"]["report_id"] == "macro_event_followup:2026-06-14:followup-run"
    assert data["latest_supplemental_report"]["summary"] == "Older weekend supplement remains separately addressable."


def test_current_market_keeps_observation_dates_and_provenance(monkeypatch):
    from apps.api.services import dashboard_service as service

    macro = {"snapshot_id": "feature-current", "source_refs": ["official-source"],
             "indicators": {"REAL_10Y": {"value": 2.85, "date": "2026-09-24"}}}
    monkeypatch.setattr(service, "get_market_macro_latest", lambda: macro)
    monkeypatch.setattr(service, "get_options_snapshot", lambda: {
        "trade_date": "2026-09-25", "data_source": {"status": "PRELIM"},
        "parameters": {"f_value": 4130}, "support_resistance": {"support": [{"strike": 4100}]},
    })
    quotes = {"xauusd": {"price": 4125, "source": "twelvedata", "time": "2026-09-28T15:00:00Z"}}
    monkeypatch.setattr(service, "get_market_tickers", lambda: {"tickers": quotes})
    data = _get_dashboard_current_market()
    assert data["macro"] == macro
    assert data["realtime_quotes"] == quotes
    assert data["options"]["trade_date"] == "2026-09-25"
    assert data["options"]["coordinate_space"] == "GC futures"
    assert data["options"]["data_status"] == "PRELIM"
    assert data["options"]["walls"]["support"][0]["strike"] == 4100


def test_current_market_source_failure_preserves_other_facts(monkeypatch):
    from apps.api.services import dashboard_service as service

    def failed_macro():
        raise RuntimeError("unavailable")

    monkeypatch.setattr(service, "get_market_macro_latest", failed_macro)
    monkeypatch.setattr(service, "get_options_snapshot", lambda: None)
    monkeypatch.setattr(service, "get_market_tickers", lambda: {"tickers": {"xauusd": {"price": 4125}}})
    data = _get_dashboard_current_market()
    assert data["macro"] is None
    assert data["options"] is None
    assert data["realtime_quotes"]["xauusd"]["price"] == 4125


def test_report_recency_uses_time_not_uuid_and_preserves_trade_date_priority():
    from apps.api.services.dashboard_service import _select_latest_reports, _select_latest_supplemental_report

    reports = [
        {"report_id": "z-old", "run_id": "z", "trade_date": "2026-09-28", "generated_at": "2026-09-28T18:28:00+08:00"},
        {"report_id": "a-new", "run_id": "a", "trade_date": "2026-09-28", "generated_at": "2026-09-28T16:03:00Z"},
        {"report_id": "newer-day", "trade_date": "2026-09-29", "generated_at": None},
        {"report_id": "unknown-time", "trade_date": "2026-09-28", "generated_at": "invalid"},
    ]
    for report in reports:
        report.update(available=True, type="macro_event_followup")
    assert [r["report_id"] for r in _select_latest_reports(reports)] == ["newer-day", "a-new", "z-old", "unknown-time"]
    assert _select_latest_supplemental_report(reports[:2])["report_id"] == "a-new"


def test_options_strength_uses_selected_window_scores_not_nearest_wall_subset():
    from apps.api.services.dashboard_service import _dashboard_options_summary

    snapshot = {
        "wall_scores": [{"wall_score": .69}, {"wall_score": .12}, {"wall_score": float("nan")}, {"wall_score": True}],
        "support_resistance": {"support": [{"strike": 4100, "wall_score": .12}]},
    }
    assert _dashboard_options_summary(snapshot)["wall_score"] == .69
    snapshot.pop("wall_scores")
    assert _dashboard_options_summary(snapshot)["wall_score"] is None
