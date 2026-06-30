from __future__ import annotations

from apps.api.services.dashboard_service import get_dashboard_summary


def test_dashboard_summary_options_confidence_degrades_for_prelim_and_stale(monkeypatch):
    monkeypatch.setattr(
        "apps.api.services.dashboard_service.get_options_snapshot",
        lambda: {
            "trade_date": "2026-06-01",
            "data_source": {"product": "OG", "expiries": ["JUL26"], "status": "PRELIM"},
            "intent": {"type": "I1_defensive", "score": 0.62},
            "gex": {"netgex_aggregate": {"gamma_zero": {"price": 4509.9}}},
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
    assert "PRELIM" in options["confidence"]["reasons"]


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
        "apps.api.services.dashboard_service.get_gold_mainlines_latest",
        lambda: {
            "status": "partial",
            "gold_macro_overview": {
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
        },
    )

    data = get_dashboard_summary()

    assert data["gold_macro_overview"]["asset"] == "XAUUSD"
    assert data["gold_macro_overview"]["dominant_mainline"] == "real_rates_usd"
    assert data["gold_macro_overview"]["theme_rankings"][0]["theme_score"] == 18
    assert data["gold_macro_overview"]["theme_rankings"][0]["direction_score"] == -1
    assert data["gold_macro_overview"]["war_oil_rate_chain"]["conclusion_code"] == "C"


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
