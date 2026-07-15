from __future__ import annotations

import json
from pathlib import Path

from apps.analysis.jin10.daily_context import build_daily_analysis_context, compact_context_for_prompt


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_daily_context_prefers_weekly_revision_and_compacts_current_inputs(tmp_path: Path) -> None:
    _write(
        tmp_path / "outputs/weekly_context_revision/XAUUSD/2026-07-12/224965-run-v1/report_structured.json",
        {
            "trade_date": "2026-07-12",
            "context_as_of": "2026-07-12T11:00:00+00:00",
            "run_id": "224965-run-v1",
            "anchor": {"article_id": "224965", "title": "周报底部线索"},
            "quality_status": "needs_review",
            "publication_status": "observe",
            "publish_allowed": False,
            "executive_summary": "底部线索仍待价格和利率确认。",
            "claim_revisions": [{"claim_id": "overall", "action": "weaken", "reason": "利率仍高"}],
            "confirmation_matrix": {"price": {"status": "observed"}},
            "watch_items": [{"label": "4000", "status": "active"}],
            "source_refs": [{"source_ref": "weekly:224965", "source": "jin10"}],
        },
    )
    _write(
        tmp_path / "features/snapshots/XAUUSD/2026-07-13/run/premarket_snapshot.json",
        {
            "trade_date": "2026-07-13",
            "snapshot_time": "2026-07-13T12:00:00+08:00",
            "technical": {"data": {"price": 4016.55, "trend": "neutral", "volatility": "normal"}},
            "macro": {
                "data": {
                    "as_of": "2026-07-13",
                    "indicators": {"US10Y": {"value": 4.57, "date": "2026-07-13", "unit": "%"}},
                }
            },
            "options": {
                "data": {
                    "trade_date": "2026-07-17",
                    "data_source": {"status": "PRELIM"},
                    "gex": {"netgex_aggregate": {"gamma_zero": {"price": 4126.43}}},
                    "support_resistance": {"support": [{"strike": 4000}], "resistance": [{"strike": 4235}]},
                }
            },
            "positioning": {"data": {"as_of": "2026-07-13", "noncomm_net": 120779, "noncomm_net_prev": 116161}},
            "source_refs": [{"source_ref": "snapshot:run", "source": "premarket"}],
        },
    )
    _write(
        tmp_path / "features/news/2026-07-13/run/daily_market_brief.json",
        {
            "retrieved_date": "2026-07-13",
            "daily_market_brief": {
                "as_of": "2026-07-13T11:00:00+00:00",
                "market_mainline": {"summary": "油价风险上升", "verification_status": "multi_source"},
                "candidate_events": [{"event_id": "e1", "what_happened": "航运风险", "need_verification": True}],
            },
        },
    )
    _write(
        tmp_path / "analysis/gold_mainlines/2026-07-13/run/gold_macro_overview.json",
        {
            "retrieved_date": "2026-07-13",
            "as_of": "2026-07-13T11:00:00+00:00",
            "dominant_mainline": "fed_policy_path",
            "driver_conflict": {"dominant_driver": "higher_for_longer_rate_pressure", "net_effect": "neutral_bearish"},
            "war_oil_rate_chain": {
                "status": "partial",
                "summary": "油价与避险路径冲突",
                "steps": [{"id": "oil_status", "status": "partial", "source_refs": [{"url": "x" * 5000}]}],
            },
        },
    )
    _write(
        tmp_path / "outputs/jin10/2026-07-13/224998/agent_analysis_report.json",
        {
            "trade_date": "2026-07-13",
            "article_id": "224998",
            "title": "原油供应冲击与需求反噬｜原油市场专项分析",
            "report_identity": {"report_type": "oil", "report_family": "jin10_oil_report"},
            "one_line_conclusion": "供应冲击支撑近月油价，但高油价的需求反噬仍待确认。",
            "market_stage": {"label": "供应冲击偏强"},
            "key_levels": [{"asset": "WTI", "value": "82.33美元/桶"}],
            "risk_points": ["海峡通行恢复会削弱供应冲击。"],
            "quality_audit": {"status": "accepted"},
            "source_refs": [{"source": "jin10", "source_ref": "jin10:224998"}],
        },
    )

    context = build_daily_analysis_context(trade_date="2026-07-13", storage_root=tmp_path)

    assert context["status"] == "ready"
    assert context["weekly_anchor"]["source_kind"] == "weekly_context_revision"
    assert context["weekly_anchor"]["article_id"] == "224965"
    assert context["weekly_anchor"]["publish_allowed"] is False
    assert context["latest_market"]["technical"]["price"] == 4016.55
    assert context["latest_market"]["options"]["gamma_zero"] == 4126.43
    assert context["latest_market"]["positioning"]["noncomm_net"] == 120779
    assert context["freshness"]["market"] == {"status": "current", "as_of": "2026-07-13", "age_days": 0}
    assert context["freshness"]["oil"] == {"status": "current", "as_of": "2026-07-13", "age_days": 0}
    assert context["oil_report_summary"]["article_id"] == "224998"
    assert context["oil_context"]["source_kind"] == "jin10_oil_analysis"
    assert "weekly_anchor" in context["input_snapshot_ids"]
    assert len(json.dumps(compact_context_for_prompt(context), ensure_ascii=False)) < 20_000


def test_daily_context_prefers_active_run_news_over_sibling_run_name(tmp_path: Path) -> None:
    _write(
        tmp_path / "features/news/2026-07-21/z-sibling/daily_market_brief.json",
        {
            "retrieved_date": "2026-07-21",
            "daily_market_brief": {
                "as_of": "2026-07-21T08:00:00+00:00",
                "market_mainline": {"summary": "sibling run"},
            },
        },
    )
    _write(
        tmp_path / "features/news/2026-07-21/current-run/daily_market_brief.json",
        {
            "retrieved_date": "2026-07-21",
            "daily_market_brief": {
                "as_of": "2026-07-21T10:00:00+00:00",
                "market_mainline": {"summary": "current run"},
            },
        },
    )

    context = build_daily_analysis_context(
        trade_date="2026-07-21",
        storage_root=tmp_path,
        preferred_run_id="current-run",
    )

    assert context["latest_news"]["market_mainline"]["summary"] == "current run"
    assert context["input_snapshot_ids"]["daily_market_brief"] == (
        "features/news/2026-07-21/current-run/daily_market_brief.json"
    )


def test_compact_context_for_prompt_keeps_one_baseline_and_drops_transport_refs() -> None:
    context = {
        "status": "degraded",
        "baseline_kind": "weekly_fallback",
        "continuity_status": "weekly_fallback",
        "analysis_baseline": {
            "one_line_conclusion": "有效基准",
            "source_refs": [{"source_ref": "baseline-ref"}],
        },
        "weekly_anchor": {"one_line_conclusion": "重复周报"},
        "previous_analysis_report": {"one_line_conclusion": "过期日报"},
        "latest_market": {
            "technical": {"price": 4060.78},
            "nested": {"source_refs": [{"source_ref": "nested-ref"}]},
        },
        "input_snapshot_ids": {"analysis_baseline": "outputs/weekly.json"},
    }

    compact = compact_context_for_prompt(context)

    assert compact["schema_version"] == "daily-analysis-prompt-context-v2"
    assert compact["analysis_baseline"]["one_line_conclusion"] == "有效基准"
    assert "weekly_anchor" not in compact
    assert "previous_analysis_report" not in compact
    assert "source_refs" not in compact["analysis_baseline"]
    assert "source_refs" not in compact["latest_market"]["nested"]
    assert compact["input_snapshot_ids"] == {"analysis_baseline": "outputs/weekly.json"}


def test_daily_context_weekly_fallback_excludes_newer_daily_report(tmp_path: Path) -> None:
    _write(
        tmp_path / "outputs/jin10/2026-07-13/900001/agent_analysis_report.json",
        {
            "family": "jin10_agent_analysis",
            "trade_date": "2026-07-13",
            "article_id": "900001",
            "title": "不能作为周报锚点的日报",
            "report_identity": {"report_type": "daily"},
        },
    )
    _write(
        tmp_path / "outputs/jin10/2026-07-12/224965/agent_analysis_report.json",
        {
            "family": "jin10_agent_analysis",
            "trade_date": "2026-07-12",
            "article_id": "224965",
            "title": "黄金周报",
            "one_line_conclusion": "周报基准",
            "report_identity": {"report_type": "weekly"},
            "quality_audit": {"status": "accepted"},
        },
    )

    context = build_daily_analysis_context(trade_date="2026-07-13", storage_root=tmp_path)

    assert context["weekly_anchor"]["source_kind"] == "jin10_weekly_analysis"
    assert context["weekly_anchor"]["article_id"] == "224965"
    assert context["weekly_anchor"]["title"] == "黄金周报"
    assert context["status"] == "degraded"


def test_daily_context_marks_old_inputs_stale_without_fabricating_data(tmp_path: Path) -> None:
    _write(
        tmp_path / "outputs/jin10/2026-06-30/224000/agent_analysis_report.json",
        {
            "family": "jin10_agent_analysis",
            "trade_date": "2026-06-30",
            "article_id": "224000",
            "report_identity": {"report_type": "weekly"},
        },
    )
    _write(
        tmp_path / "features/snapshots/XAUUSD/2026-07-10/run/premarket_snapshot.json",
        {"trade_date": "2026-07-10", "technical": {"data": {"price": 3900}}},
    )

    context = build_daily_analysis_context(trade_date="2026-07-20", storage_root=tmp_path)

    assert context["status"] == "degraded"
    assert context["freshness"]["weekly_anchor"]["status"] == "stale"
    assert context["freshness"]["market"]["status"] == "stale"
    assert context["freshness"]["news"]["status"] == "missing"
    assert context["oil_context"] == {}


def test_daily_context_uses_previous_latest_analysis_report_after_monday(tmp_path: Path) -> None:
    _write(
        tmp_path / "outputs/weekly_context_revision/XAUUSD/2026-07-12/run/report_structured.json",
        {
            "trade_date": "2026-07-12",
            "context_as_of": "2026-07-12",
            "anchor": {"article_id": "224965", "title": "周报"},
            "quality_status": "accepted",
            "publication_status": "observe",
            "publish_allowed": False,
        },
    )
    _write(
        tmp_path / "outputs/final_report/XAUUSD/2026-07-13/composite-224994/structured_report.json",
        {
            "version": {
                "report_id": "XAUUSD:2026-07-13:composite-224994:final_report",
                "run_id": "composite-224994",
                "trade_date": "2026-07-13",
                "status": "generated",
                "is_final": True,
            },
            "sections": [
                {"section_id": "one_line_summary", "title": "One-line Summary", "body": "前一日综合结论"},
                {"section_id": "market_phase", "title": "Market Phase", "body": "观察阶段"},
            ],
        },
    )

    context = build_daily_analysis_context(trade_date="2026-07-14", storage_root=tmp_path)

    assert context["baseline_kind"] == "previous_analysis_report"
    assert context["analysis_baseline"]["run_id"] == "composite-224994"
    assert context["analysis_baseline"]["source_kind"] == "final_analysis_report"
    assert context["weekly_anchor"]["article_id"] == "224965"
    assert context["freshness"]["analysis_baseline"]["status"] == "current"


def test_daily_context_does_not_promote_jin10_daily_to_serial_baseline(tmp_path: Path) -> None:
    _write(
        tmp_path / "outputs/jin10/2026-07-20/224994/agent_analysis_report.json",
        {
            "trade_date": "2026-07-20",
            "article_id": "224994",
            "report_identity": {"report_type": "daily"},
        },
    )

    context = build_daily_analysis_context(trade_date="2026-07-21", storage_root=tmp_path)

    assert context["baseline_kind"] == "weekly_fallback"
    assert context["analysis_baseline"].get("source_kind") != "jin10_daily_analysis"


def test_daily_context_marks_weekly_fallback_when_weekday_daily_is_missing(tmp_path: Path) -> None:
    _write(
        tmp_path / "outputs/weekly_context_revision/XAUUSD/2026-07-12/run/report_structured.json",
        {
            "trade_date": "2026-07-12",
            "context_as_of": "2026-07-12",
            "anchor": {"article_id": "224965", "title": "周报"},
            "quality_status": "accepted",
            "publication_status": "observe",
            "publish_allowed": False,
        },
    )

    context = build_daily_analysis_context(trade_date="2026-07-14", storage_root=tmp_path)

    assert context["baseline_kind"] == "weekly_fallback"
    assert context["analysis_baseline"]["article_id"] == "224965"
    assert context["status"] == "degraded"


def test_daily_context_uses_current_weekly_anchor_when_previous_report_is_stale(tmp_path: Path) -> None:
    _write(
        tmp_path / "outputs/weekly_context_revision/XAUUSD/2026-07-19/run/report_structured.json",
        {
            "trade_date": "2026-07-19",
            "context_as_of": "2026-07-19",
            "anchor": {"article_id": "225100", "title": "当周黄金周报"},
            "quality_status": "accepted",
            "publication_status": "observe",
            "publish_allowed": False,
            "source_refs": [{"source": "jin10", "source_ref": "weekly:225100"}],
        },
    )
    _write(
        tmp_path / "outputs/final_report/XAUUSD/2026-07-16/old/structured_report.json",
        {
            "version": {
                "report_id": "old-report",
                "run_id": "old",
                "trade_date": "2026-07-16",
                "status": "generated",
                "is_final": True,
            },
            "sections": [{"section_id": "one_line_summary", "body": "过期日报"}],
        },
    )
    _write(
        tmp_path / "features/snapshots/XAUUSD/2026-07-21/run/premarket_snapshot.json",
        {"trade_date": "2026-07-21", "technical": {"data": {"price": 4071.5}}},
    )
    _write(
        tmp_path / "features/news/2026-07-21/run/daily_market_brief.json",
        {"retrieved_date": "2026-07-21", "daily_market_brief": {"as_of": "2026-07-21"}},
    )
    _write(
        tmp_path / "analysis/gold_mainlines/2026-07-21/run/gold_macro_overview.json",
        {"retrieved_date": "2026-07-21", "dominant_mainline": "fed_policy_path"},
    )

    context = build_daily_analysis_context(trade_date="2026-07-21", storage_root=tmp_path)

    assert context["status"] == "ready"
    assert context["baseline_kind"] == "weekly_fallback"
    assert context["continuity_status"] == "weekly_fallback"
    assert context["analysis_baseline"]["article_id"] == "225100"
    assert context["freshness"]["previous_analysis_report"]["status"] == "stale"
    assert context["warnings"] == ["previous_analysis_report_stale; using current weekly anchor"]
