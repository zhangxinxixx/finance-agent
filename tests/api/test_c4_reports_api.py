"""C4 Final Report / Strategy Card / Reports Index API 测试。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.data_service import (
    _latest_asset_date_run,
    _collect_reports,
    get_final_report,
    get_final_report_latest,
    get_jin10_report_bundle,
    get_jin10_report_bundle_latest,
    get_options_snapshot,
    get_options_visual_report_html,
    get_strategy_card,
    get_strategy_card_latest,
    list_options_report_dates,
    list_reports_index,
    list_unified_dates,
)
from apps.api.main import app, api_strategy_card_detail, api_strategy_cards_latest
from database.models.analysis import ensure_analysis_tables
from database.models.report import ensure_report_tables
from database.queries.report import upsert_report_artifact, upsert_report_item

client = TestClient(app)

_PROJECT_ROOT_PATCH = "apps.api.data_service._PROJECT_ROOT"
_RS_PROJECT_ROOT_PATCH = "apps.api.services.report_service._PROJECT_ROOT"
_DB_SESSION_PATCH = "apps.api.data_service._try_db_session"


# ── helpers ──


def _make_tree(root: Path, files: dict[str, str | None]) -> None:
    """按 {relative_path: content} 创建目录和文件；content=None 则只建目录。"""
    for rel, content in files.items():
        p = root / rel
        if content is None:
            p.mkdir(parents=True, exist_ok=True)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")


def _make_report_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_analysis_tables(engine)
    ensure_report_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


# ── _latest_asset_date_run ──


def test_latest_asset_date_run_empty(tmp_path: Path):
    assert _latest_asset_date_run(tmp_path, "XAUUSD") == (None, None, None)


def test_latest_asset_date_run_no_asset_dir(tmp_path: Path):
    (tmp_path / "OTHER").mkdir(parents=True)
    assert _latest_asset_date_run(tmp_path, "XAUUSD") == (None, None, None)


def test_latest_asset_date_run_picks_latest_date_and_run(tmp_path: Path):
    _make_tree(tmp_path, {
        "XAUUSD/2026-05-07/run-a/final_report.md": "old",
        "XAUUSD/2026-05-14/run-b/final_report.md": "newer",
        "XAUUSD/2026-05-14/run-c/final_report.md": "newest",
    })
    date, run_id, run_dir = _latest_asset_date_run(tmp_path, "XAUUSD")
    assert date == "2026-05-14"
    assert run_id == "run-c"
    assert run_dir is not None
    assert run_dir.name == "run-c"


def test_latest_asset_date_run_date_with_no_runs(tmp_path: Path):
    """日期目录存在但没有 run_id 子目录时返回 date 但 run_id=None。"""
    _make_tree(tmp_path, {
        "XAUUSD/2026-05-07/": None,
    })
    date, run_id, run_dir = _latest_asset_date_run(tmp_path, "XAUUSD")
    assert date == "2026-05-07"
    assert run_id is None
    assert run_dir is None


# ── get_final_report_latest ──


def test_get_final_report_latest(tmp_path: Path):
    md = "# Final Report\nTrade date: 2026-05-14"
    _make_tree(tmp_path, {
        "storage/outputs/final_report/XAUUSD/2026-05-14/run-1/final_report.md": md,
    })
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        data = get_final_report_latest()
    assert data is not None
    assert data["asset"] == "XAUUSD"
    assert data["trade_date"] == "2026-05-14"
    assert data["run_id"] == "run-1"
    assert data["content"] == md
    assert data["format"] == "markdown"
    assert data["path"].endswith("final_report.md")


def test_get_final_report_latest_multiple_runs(tmp_path: Path):
    md_new = "# Newer"
    _make_tree(tmp_path, {
        "storage/outputs/final_report/XAUUSD/2026-05-14/run-early/final_report.md": "# Early",
        "storage/outputs/final_report/XAUUSD/2026-05-14/run-late/final_report.md": md_new,
        "storage/outputs/final_report/XAUUSD/2026-05-10/old/final_report.md": "# Old",
    })
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        data = get_final_report_latest()
    assert data is not None
    assert data["trade_date"] == "2026-05-14"
    assert data["run_id"] == "run-late"
    assert data["content"] == md_new


def test_get_final_report_latest_no_file(tmp_path: Path):
    _make_tree(tmp_path, {
        "storage/outputs/final_report/XAUUSD/2026-05-14/run-1/": None,
    })
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        assert get_final_report_latest() is None


def test_get_final_report_latest_no_dir(tmp_path: Path):
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        assert get_final_report_latest() is None


# ── get_final_report (exact) ──


def test_get_final_report_exact(tmp_path: Path):
    md = "# Exact final"
    _make_tree(tmp_path, {
        "storage/outputs/final_report/XAUUSD/2026-05-07/manual-run/final_report.md": md,
    })
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        data = get_final_report(date="2026-05-07", run_id="manual-run")
    assert data is not None
    assert data["trade_date"] == "2026-05-07"
    assert data["run_id"] == "manual-run"
    assert data["content"] == md


def test_get_final_report_exact_not_found(tmp_path: Path):
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        assert get_final_report(date="2099-01-01", run_id="nonexistent") is None


# ── get_strategy_card_latest ──


def test_get_strategy_card_latest(tmp_path: Path):
    sc_json = json.dumps({"bias": "bullish", "confidence": 0.8, "asset": "XAUUSD"})
    sc_md = "# Strategy Card\nBias: bullish"
    _make_tree(tmp_path, {
        "storage/outputs/strategy_card/XAUUSD/2026-05-14/run-1/strategy_card.json": sc_json,
        "storage/outputs/strategy_card/XAUUSD/2026-05-14/run-1/strategy_card.md": sc_md,
    })
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        data = get_strategy_card_latest()
    assert data is not None
    assert data["asset"] == "XAUUSD"
    assert data["trade_date"] == "2026-05-14"
    assert data["run_id"] == "run-1"
    assert data["json"]["bias"] == "bullish"
    assert data["json"]["confidence"] == 0.8
    assert data["markdown"] == sc_md
    assert "json" in data["paths"]
    assert "markdown" in data["paths"]


def test_get_strategy_card_latest_json_only_no_md(tmp_path: Path):
    """strategy_card 可能没有 .md 文件。"""
    sc_json = json.dumps({"bias": "bearish", "confidence": 0.6})
    _make_tree(tmp_path, {
        "storage/outputs/strategy_card/XAUUSD/2026-05-14/run-1/strategy_card.json": sc_json,
    })
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        data = get_strategy_card_latest()
    assert data is not None
    assert data["json"]["bias"] == "bearish"
    assert "markdown" not in data


def test_get_strategy_card_latest_bad_json(tmp_path: Path):
    _make_tree(tmp_path, {
        "storage/outputs/strategy_card/XAUUSD/2026-05-14/run-1/strategy_card.json": "not json",
    })
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        assert get_strategy_card_latest() is None


def test_get_strategy_card_latest_no_dir(tmp_path: Path):
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        assert get_strategy_card_latest() is None


# ── get_strategy_card (exact) ──


def test_get_strategy_card_exact(tmp_path: Path):
    sc_json = json.dumps({"bias": "neutral", "confidence": 0.5})
    sc_md = "# Strategy\nNeutral"
    _make_tree(tmp_path, {
        "storage/outputs/strategy_card/XAUUSD/2026-05-14/manual-c4/strategy_card.json": sc_json,
        "storage/outputs/strategy_card/XAUUSD/2026-05-14/manual-c4/strategy_card.md": sc_md,
    })
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        data = get_strategy_card(date="2026-05-14", run_id="manual-c4")
    assert data is not None
    assert data["trade_date"] == "2026-05-14"
    assert data["run_id"] == "manual-c4"
    assert data["json"]["bias"] == "neutral"
    assert data["markdown"] == sc_md


def test_get_strategy_card_exact_not_found(tmp_path: Path):
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        assert get_strategy_card(date="2099-01-01", run_id="nonexistent") is None


def test_strategy_cards_latest_route(tmp_path: Path):
    """Plural latest strategy route returns the frontend read-model payload."""
    sc_json = json.dumps(
        {
            "strategy_card_id": "sc-route-latest",
            "bias": "bullish",
            "confidence": 0.82,
            "direction": "bullish",
            "market_regime": "risk-on",
            "main_scenario": "站稳 3350 后延续上攻。",
            "alternative_scenarios": ["跌回 3320 下方则转为震荡回撤。"],
            "key_levels": {"resistance": [3350, 3380], "support": [3320, 3300]},
            "trigger_conditions": ["日线收在 3350 上方"],
            "invalidation_conditions": ["重新失守 3320"],
            "confirmation_conditions": ["美元指数继续走弱"],
            "risk_points": ["非农数据可能放大波动"],
        }
    )
    _make_tree(tmp_path, {
        "storage/outputs/strategy_card/XAUUSD/2026-05-14/run-route/strategy_card.json": sc_json,
        "storage/outputs/strategy_card/XAUUSD/2026-05-14/run-route/strategy_card.md": "# Route latest",
    })
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path), mock.patch(_RS_PROJECT_ROOT_PATCH, tmp_path), mock.patch(_DB_SESSION_PATCH, return_value=None):
        data = api_strategy_cards_latest()
    assert data["strategy_card_id"] == "sc-route-latest"
    assert data["run_id"] == "run-route"
    assert data["bias"] == "bullish"
    assert data["paths"]["json"].endswith("strategy_card.json")
    assert data["has_data"] is True
    assert data["hero"]["direction"] == "bullish"
    assert data["hero"]["market_regime"] == "risk-on"
    assert data["scenario"]["main_scenario"] == "站稳 3350 后延续上攻。"
    assert data["scenario"]["key_levels"]["support"] == [3320, 3300]


def test_strategy_card_detail_route_by_strategy_card_id(tmp_path: Path):
    """Plural detail route can look up by strategy_card_id, not only run_id."""
    sc_json = json.dumps(
        {
            "strategy_card_id": "sc-route-detail",
            "bias": "neutral",
            "confidence": 0.55,
            "direction": "neutral",
            "scenario_summary": "等待方向选择，优先观察 3320-3350。",
            "key_levels_from_options": ["3350", "3320"],
        }
    )
    _make_tree(tmp_path, {
        "storage/outputs/strategy_card/XAUUSD/2026-05-14/run-detail/strategy_card.json": sc_json,
        "storage/outputs/strategy_card/XAUUSD/2026-05-14/run-detail/strategy_card.md": "# Route detail",
    })
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        data = api_strategy_card_detail("sc-route-detail")
    assert data["strategy_card_id"] == "sc-route-detail"
    assert data["run_id"] == "run-detail"
    assert data["bias"] == "neutral"
    assert data["module_signals"] == []
    assert data["hero"]["direction"] == "neutral"
    assert data["scenario"]["main_scenario"] == "等待方向选择，优先观察 3320-3350。"
    assert data["scenario"]["key_levels"]["resistance"] == [3350, 3320]


def test_strategy_card_detail_route_not_found(tmp_path: Path):
    """Plural detail route returns 404 for unknown ids."""
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        try:
            api_strategy_card_detail("not-found-card")
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 404
        else:
            raise AssertionError("expected 404 HTTPException")


# ── _collect_reports ──


def test_collect_reports_final(tmp_path: Path):
    _make_tree(tmp_path, {
        "storage/outputs/final_report/XAUUSD/2026-05-14/run-a/final_report.md": "a",
        "storage/outputs/final_report/XAUUSD/2026-05-14/run-b/final_report.md": "b",
        "storage/outputs/final_report/XAUUSD/2026-05-07/run-c/final_report.md": "c",
    })
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        results = _collect_reports("final_report", "final_report", "markdown", "XAUUSD", "final_report.md")
    assert len(results) == 3
    assert results[0]["trade_date"] == "2026-05-14"
    assert results[0]["run_id"] == "run-b"
    assert results[0]["available"] is True
    assert results[2]["trade_date"] == "2026-05-07"


def test_collect_reports_empty_dir(tmp_path: Path):
    _make_tree(tmp_path, {"storage/outputs/final_report/XAUUSD/": None})
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        results = _collect_reports("final_report", "final_report", "markdown", "XAUUSD", "final_report.md")
    assert results == []


# ── list_reports_index ──


def test_list_reports_index_full(tmp_path: Path):
    _make_tree(tmp_path, {
        "storage/outputs/final_report/XAUUSD/2026-05-14/run-1/final_report.md": "fr",
        "storage/outputs/strategy_card/XAUUSD/2026-05-14/run-1/strategy_card.json": "{}",
        "storage/outputs/strategy_card/XAUUSD/2026-05-14/run-1/strategy_card.md": "sc",
        "storage/outputs/cme_options/2026-05-07/options_analysis.json": "{}",
        "storage/outputs/macro/2026-05-14/auto-v2/macro_snapshot.md": "macro",
    })
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        index = list_reports_index()
    assert index["asset"] == "XAUUSD"
    reports = index["reports"]

    types = {r["type"] for r in reports}
    assert "final_report" in types
    assert "strategy_card" in types
    assert "options_report" in types
    assert "macro_report" in types

    # 验证 final_report
    fr = [r for r in reports if r["type"] == "final_report"]
    assert len(fr) == 1
    assert fr[0]["trade_date"] == "2026-05-14"
    assert fr[0]["run_id"] == "run-1"
    assert fr[0]["available"] is True
    assert fr[0]["title"] == "XAUUSD 综合报告（2026-05-14）"
    assert fr[0]["family"] == "final_report_markdown"

    # 验证 strategy_card
    sc = [r for r in reports if r["type"] == "strategy_card"]
    assert len(sc) == 1
    assert sc[0]["trade_date"] == "2026-05-14"
    assert sc[0]["run_id"] == "run-1"
    assert sc[0]["available"] is True

    macro = [r for r in reports if r["type"] == "macro_report"]
    assert macro[0]["title"] == "XAUUSD 宏观数据报告（2026-05-14）"
    assert macro[0]["report_id"] == "macro_report:auto-v2"


def test_get_options_snapshot_prefers_new_cme_output(tmp_path: Path):
    _make_tree(tmp_path, {
        "storage/outputs/cme/2026-05-19/run-new/options_analysis.json": json.dumps({
            "trade_date": "2026-05-19",
            "data_source": {"product": "GC", "status": "FINAL"},
            "intent": {"type": "bullish"},
        }),
        "storage/outputs/cme_options/2026-05-19/options_analysis.json": json.dumps({
            "trade_date": "2026-05-19",
            "data_source": {"product": "GC", "status": "PRELIM"},
            "intent": {"type": "legacy"},
        }),
    })
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        data = get_options_snapshot("2026-05-19")
    assert data is not None
    assert data["trade_date"] == "2026-05-19"
    assert data["data_source"]["status"] == "FINAL"
    assert data["intent"]["type"] == "bullish"


def test_list_options_report_dates_includes_new_cme_output(tmp_path: Path):
    _make_tree(tmp_path, {
        "storage/outputs/cme/2026-05-19/run-new/options_analysis.json": "{}",
        "storage/outputs/cme/2026-05-18/run-old/options_analysis.json": "{}",
        "storage/outputs/cme/2026-05-17/run-md-only/options_analysis.md": "# md-only",
        "storage/outputs/cme_options/2026-05-07/options_analysis.json": "{}",
        "storage/features/snapshots/XAUUSD/2026-05-06/run-empty/premarket_snapshot.json": json.dumps({"options": {"status": "unavailable"}}),
        "storage/features/snapshots/XAUUSD/2026-05-05/run-snapshot/premarket_snapshot.json": json.dumps({"options": {"status": "available", "data": {"trade_date": "2026-05-05"}}}),
    })
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        dates = list_options_report_dates()
    assert dates == ["2026-05-19", "2026-05-18", "2026-05-07", "2026-05-05"]


def test_get_options_visual_report_html_falls_back_to_markdown(tmp_path: Path):
    _make_tree(tmp_path, {
        "storage/outputs/cme/2026-05-19/run-new/options_analysis.md": "# CME\n\nvisual fallback",
    })
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        data = get_options_visual_report_html("2026-05-19", "run-new")
    assert data is not None
    assert data["trade_date"] == "2026-05-19"
    assert data["run_id"] == "run-new"
    assert data["format"] == "html"
    assert "visual fallback" in data["content"]
    assert data["path"].startswith("fallback://options_report_md/")


def test_get_options_visual_report_html_latest_falls_back_when_html_missing(tmp_path: Path):
    _make_tree(tmp_path, {
        "storage/outputs/cme/2026-05-19/run-new/options_analysis_agent_report.md": "# Agent Report\n\nlatest visual fallback",
    })
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        data = get_options_visual_report_html()
    assert data is not None
    assert data["trade_date"] == "2026-05-19"
    assert data["run_id"] == "run-new"
    assert "latest visual fallback" in data["content"]


def test_list_reports_index_includes_visual_report_runs_without_html(tmp_path: Path):
    _make_tree(tmp_path, {
        "storage/outputs/cme/2026-05-19/run-new/options_analysis_agent_report.md": "# visual fallback",
    })
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        index = list_reports_index()
    visual_items = [item for item in index["reports"] if item["type"] == "options_visual_report"]
    assert len(visual_items) == 1
    assert visual_items[0]["trade_date"] == "2026-05-19"
    assert visual_items[0]["run_id"] == "run-new"
    assert visual_items[0]["available"] is True


def test_list_reports_index_includes_options_report_from_new_cme_runs(tmp_path: Path):
    _make_tree(tmp_path, {
        "storage/outputs/cme/2026-05-19/run-new/options_analysis_agent_report.md": "# options report",
    })
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        index = list_reports_index()
    option_items = [item for item in index["reports"] if item["type"] == "options_report"]
    assert len(option_items) == 1
    assert option_items[0]["trade_date"] == "2026-05-19"
    assert option_items[0]["run_id"] == "run-new"
    assert option_items[0]["available"] is True


def test_list_reports_index_empty(tmp_path: Path):
    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch("apps.api.services.report_service._collect_jin10_external_weekly_reports", return_value=[]),
    ):
        index = list_reports_index()
    assert index["asset"] == "XAUUSD"
    assert index["reports"] == []


def test_list_unified_dates_combines_modules_and_latest_run(tmp_path: Path):
    _make_tree(tmp_path, {
        "storage/features/snapshots/XAUUSD/2026-05-15/run-z/premarket_snapshot.json": json.dumps({
            "macro": {"status": "available"},
            "options": {"status": "available", "data": {"trade_date": "2026-05-15"}},
            "market_odds": {"status": "available"},
        }),
        "storage/outputs/final_report/XAUUSD/2026-05-15/run-z/final_report.md": "fr",
        "storage/outputs/strategy_card/XAUUSD/2026-05-15/run-z/strategy_card.json": "{}",
        "storage/outputs/cme_options/2026-05-07/options_analysis.json": "{}",
        "storage/outputs/macro/2026-05-16/run-m/macro_snapshot.md": "macro",
    })

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        data = list_unified_dates()

    assert data["asset"] == "XAUUSD"
    dates = {item["trade_date"]: item for item in data["dates"]}
    assert list(dates) == ["2026-05-16", "2026-05-15", "2026-05-07"]
    assert dates["2026-05-15"]["latest_run_id"] == "run-z"
    assert dates["2026-05-15"]["has_final_report"] is True
    assert dates["2026-05-15"]["has_strategy_card"] is True
    assert set(dates["2026-05-15"]["modules"]) == {
        "final_report", "macro", "market_odds", "options", "strategy_card"
    }
    assert dates["2026-05-16"]["modules"] == ["macro"]
    assert dates["2026-05-07"]["modules"] == ["options"]


def test_api_reports_dates_200(tmp_path: Path):
    _make_tree(tmp_path, {
        "storage/outputs/final_report/XAUUSD/2026-05-14/run-1/final_report.md": "x",
        "storage/outputs/strategy_card/XAUUSD/2026-05-14/run-1/strategy_card.json": "{}",
    })
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        resp = client.get("/api/reports/dates")
    assert resp.status_code == 200
    data = resp.json()
    assert data["dates"][0]["trade_date"] == "2026-05-14"
    assert data["dates"][0]["has_final_report"] is True
    assert data["dates"][0]["has_strategy_card"] is True


def test_get_jin10_report_bundle_latest_prefers_agent_analysis(tmp_path: Path):
    _make_tree(tmp_path, {
        "storage/outputs/jin10/2026-05-21/219824/agent_analysis_report.md": "# Agent 二次分析报告\n\n结论。",
        "storage/outputs/jin10/2026-05-21/219824/agent_analysis_report.json": json.dumps({
            "article_id": "219824",
            "title": "Jin10 05-21 报告",
            "source_url": "https://xnews.jin10.com/details/219824",
        }, ensure_ascii=False),
        "storage/outputs/jin10/2026-05-21/219824/daily_analysis.html": "<html><body>daily</body></html>",
        "storage/outputs/jin10/2026-05-21/219824/daily_analysis.json": json.dumps({
            "article_id": "219824",
            "title": "Jin10 05-21 报告",
        }, ensure_ascii=False),
        "storage/outputs/jin10/2026-05-21/219824/raw_article_report.md": "# 原文整理\n\n正文。",
        "storage/outputs/jin10/2026-05-21/219824/raw_article_report.json": json.dumps({
            "article_id": "219824",
            "title": "Jin10 05-21 报告",
        }, ensure_ascii=False),
    })

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        data = get_jin10_report_bundle_latest()

    assert data is not None
    assert data["trade_date"] == "2026-05-21"
    assert data["run_id"] == "219824"
    assert data["default_view"] == "agent_analysis"
    assert data["views"]["agent_analysis"]["available"] is True
    assert data["views"]["agent_analysis"]["asset_base_url"] == "/api/jin10/report-bundle/2026-05-21/219824/asset/"
    assert data["views"]["daily_visual"]["kind"] == "html"
    assert data["views"]["raw_article"]["kind"] == "markdown"
    assert data["views"]["raw_article"]["asset_base_url"] == "/api/jin10/report-bundle/2026-05-21/219824/asset/"


def test_get_jin10_report_bundle_keeps_missing_views_explicit(tmp_path: Path):
    _make_tree(tmp_path, {
        "storage/outputs/jin10/2026-05-21/219824/daily_analysis.html": "<html><body>daily</body></html>",
        "storage/outputs/jin10/2026-05-21/219824/daily_analysis.json": json.dumps({"article_id": "219824"}),
    })

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        data = get_jin10_report_bundle("2026-05-21", "219824")

    assert data is not None
    assert data["default_view"] == "daily_visual"
    assert data["views"]["agent_analysis"]["available"] is False
    assert data["views"]["raw_article"]["available"] is False
    assert data["views"]["daily_visual"]["available"] is True


def test_get_jin10_report_bundle_exposes_quality_audit(tmp_path: Path):
    _make_tree(tmp_path, {
        "storage/outputs/jin10/2026-06-09/221446/daily_analysis.html": "<html><body>daily</body></html>",
        "storage/outputs/jin10/2026-06-09/221446/daily_analysis.json": json.dumps(
            {
                "article_id": "221446",
                "title": "黄金ETF资金观望等待催化剂",
                "quality_audit": {
                    "status": "needs_review",
                    "checked_at": "2026-06-09T00:00:00+00:00",
                    "reasons": [
                        {"code": "evidence_insufficient", "message": "no stable evidence extracted"},
                        {"code": "fallback_chart_only", "message": "only fallback captions were available"},
                    ],
                },
            },
            ensure_ascii=False,
        ),
    })

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        data = get_jin10_report_bundle("2026-06-09", "221446")

    assert data is not None
    assert data["quality_audit"]["status"] == "needs_review"
    assert data["quality_audit"]["reason_codes"] == ["evidence_insufficient", "fallback_chart_only"]
    assert data["quality_audit"]["reasons"][0]["message"] == "no stable evidence extracted"


def test_list_reports_index_marks_rejected_jin10_report_degraded(tmp_path: Path):
    _make_tree(tmp_path, {
        "storage/outputs/jin10/2026-06-12/221592/daily_analysis.html": "<html><body>daily</body></html>",
        "storage/outputs/jin10/2026-06-12/221592/daily_analysis.json": json.dumps(
            {
                "article_id": "221592",
                "title": "霍尔木兹海峡受阻3个月，全球通胀水平如何了？",
                "quality_audit": {
                    "status": "rejected",
                    "checked_at": "2026-06-12T06:01:01+00:00",
                    "reasons": [
                        {"code": "evidence_insufficient", "message": "no stable evidence extracted"},
                    ],
                },
            },
            ensure_ascii=False,
        ),
    })

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        index = list_reports_index()

    [item] = [report for report in index["reports"] if report["type"] == "jin10_daily_report"]
    assert item["trade_date"] == "2026-06-12"
    assert item["status"] == "degraded"
    assert item["quality_audit"]["status"] == "rejected"
    assert item["quality_audit"]["reason_codes"] == ["evidence_insufficient"]


def test_list_reports_index_different_dates(tmp_path: Path):
    """final_report 和 strategy_card 的 trade_date 可以不一致。"""
    _make_tree(tmp_path, {
        "storage/outputs/final_report/XAUUSD/2026-05-07/run-a/final_report.md": "fr",
        "storage/outputs/strategy_card/XAUUSD/2026-05-14/run-b/strategy_card.json": "{}",
    })
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        index = list_reports_index()

    fr = [r for r in index["reports"] if r["type"] == "final_report"]
    sc = [r for r in index["reports"] if r["type"] == "strategy_card"]
    assert len(fr) == 1
    assert fr[0]["trade_date"] == "2026-05-07"
    assert len(sc) == 1
    assert sc[0]["trade_date"] == "2026-05-14"


# ── FastAPI routes (integration) ──


def test_api_final_report_latest_200(tmp_path: Path):
    md = "# API Final"
    _make_tree(tmp_path, {
        "storage/outputs/final_report/XAUUSD/2026-05-14/run-1/final_report.md": md,
    })
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        resp = client.get("/api/final-report/latest")
    assert resp.status_code == 200
    data = resp.json()
    assert data["content"] == md
    assert data["trade_date"] == "2026-05-14"


def test_api_final_report_latest_404(tmp_path: Path):
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        resp = client.get("/api/final-report/latest")
    assert resp.status_code == 404


def test_api_final_report_exact_200(tmp_path: Path):
    md = "# Exact via API"
    _make_tree(tmp_path, {
        "storage/outputs/final_report/XAUUSD/2026-05-07/my-run/final_report.md": md,
    })
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        resp = client.get("/api/final-report?date=2026-05-07&run_id=my-run")
    assert resp.status_code == 200
    assert resp.json()["content"] == md


def test_api_final_report_exact_404(tmp_path: Path):
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        resp = client.get("/api/final-report?date=2099-01-01&run_id=nope")
    assert resp.status_code == 404


def test_api_strategy_card_latest_200(tmp_path: Path):
    sc_json = json.dumps({"bias": "bullish", "confidence": 0.9})
    _make_tree(tmp_path, {
        "storage/outputs/strategy_card/XAUUSD/2026-05-14/run-1/strategy_card.json": sc_json,
    })
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        resp = client.get("/api/strategy-card/latest")
    assert resp.status_code == 200
    data = resp.json()
    assert data["json"]["bias"] == "bullish"


def test_api_strategy_card_latest_404(tmp_path: Path):
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        resp = client.get("/api/strategy-card/latest")
    assert resp.status_code == 404


def test_api_strategy_card_exact_200(tmp_path: Path):
    sc_json = json.dumps({"bias": "bearish"})
    _make_tree(tmp_path, {
        "storage/outputs/strategy_card/XAUUSD/2026-05-14/some-run/strategy_card.json": sc_json,
    })
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        resp = client.get("/api/strategy-card?date=2026-05-14&run_id=some-run")
    assert resp.status_code == 200
    assert resp.json()["json"]["bias"] == "bearish"


def test_api_strategy_card_exact_404(tmp_path: Path):
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        resp = client.get("/api/strategy-card?date=2099-01-01&run_id=nope")
    assert resp.status_code == 404


def test_api_jin10_report_bundle_latest_200(tmp_path: Path):
    _make_tree(tmp_path, {
        "storage/outputs/jin10/2026-05-21/219824/agent_analysis_report.md": "# Agent 二次分析报告\n\n结论。",
        "storage/outputs/jin10/2026-05-21/219824/agent_analysis_report.json": json.dumps({"article_id": "219824"}),
    })
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        resp = client.get("/api/jin10/report-bundle/latest")
    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] == "219824"
    assert data["default_view"] == "agent_analysis"


def test_api_jin10_report_bundle_asset_200(tmp_path: Path):
    _make_tree(tmp_path, {
        "storage/outputs/jin10/2026-05-21/219824/figures/fig_p2_001.png": "png-bytes",
    })
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        resp = client.get("/api/jin10/report-bundle/2026-05-21/219824/asset/figures/fig_p2_001.png")
    assert resp.status_code == 200


def test_api_jin10_report_bundle_exact_404(tmp_path: Path):
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        resp = client.get("/api/jin10/report-bundle?date=2099-01-01&run_id=nope")
    assert resp.status_code == 404


def test_api_reports_index_200(tmp_path: Path):
    _make_tree(tmp_path, {
        "storage/outputs/final_report/XAUUSD/2026-05-14/run-1/final_report.md": "x",
        "storage/outputs/strategy_card/XAUUSD/2026-05-14/run-1/strategy_card.json": "{}",
    })
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        resp = client.get("/api/reports/index")
    assert resp.status_code == 200
    data = resp.json()
    assert data["asset"] == "XAUUSD"
    assert len(data["reports"]) >= 2
