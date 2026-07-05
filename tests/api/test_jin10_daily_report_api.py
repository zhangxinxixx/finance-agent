from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

from fastapi import HTTPException

from apps.api.data_service import list_reports_index, list_unified_dates
from apps.api.main import (
    api_jin10_daily_report,
    api_jin10_daily_report_latest,
    api_jin10_weekly_report,
    api_jin10_weekly_report_latest,
)
from apps.api.services.report_service import _legacy_jin10_report_detail
_PROJECT_ROOT_PATCH = "apps.api.data_service._PROJECT_ROOT"
_REPORT_SERVICE_PROJECT_ROOT_PATCH = "apps.api.services.report_service._PROJECT_ROOT"


def _make_tree(root: Path, files: dict[str, str | None]) -> None:
    for relative, content in files.items():
        path = root / relative
        if content is None:
            path.mkdir(parents=True, exist_ok=True)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def test_list_reports_index_includes_jin10_daily_report(tmp_path: Path):
    _make_tree(
        tmp_path,
        {
            "storage/outputs/jin10/2026-05-06/218330/daily_analysis.json": json.dumps({"family": "jin10_daily_visual"}),
            "storage/outputs/jin10/2026-05-06/218330/daily_analysis.html": "<html>jin10</html>",
        },
    )
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        index = list_reports_index()

    report_types = {item["type"] for item in index["reports"]}
    assert "jin10_daily_report" in report_types


def test_list_reports_index_includes_external_jin10_weekly_report(tmp_path: Path):
    _make_tree(
        tmp_path,
        {
            "jin10-reports/2026-05-31/weekly/220787/meta.json": json.dumps(
                {
                    "id": 220787,
                    "date": "2026-05-31",
                    "title": "黄金周报",
                    "report_type": "weekly",
                }
            ),
            "jin10-reports/2026-05-31/weekly/220787/report.md": "# weekly",
            "jin10-reports/2026-06-05/weekly/220973/meta.json": json.dumps(
                {
                    "id": 220973,
                    "date": "2026-06-05",
                    "title": "美伊谈判反复，金价仍陷入两难｜黄金头条",
                    "category": "报告",
                    "report_type": "weekly",
                }
            ),
            "jin10-reports/2026-06-05/weekly/220973/report.md": "# gold headline",
        },
    )
    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch("apps.api.services.report_service._JIN10_EXTERNAL_ROOT", tmp_path / "jin10-reports"),
        mock.patch.dict(os.environ, {"HOME": str(tmp_path)}),
    ):
        index = list_reports_index()

    weekly = [item for item in index["reports"] if item["type"] == "jin10_weekly_report"]
    assert len(weekly) == 1
    assert weekly[0]["trade_date"] == "2026-05-31"
    assert weekly[0]["run_id"] == "220787"
    assert weekly[0]["format"] == "markdown"
    assert "220973" not in {item["run_id"] for item in weekly}


def test_list_unified_dates_marks_jin10_daily_report(tmp_path: Path):
    _make_tree(
        tmp_path,
        {
            "storage/outputs/jin10/2026-05-06/218330/daily_analysis.json": json.dumps({"family": "jin10_daily_visual"}),
            "storage/outputs/jin10/2026-05-06/218330/daily_analysis.html": "<html>jin10</html>",
        },
    )
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        dates = list_unified_dates()

    assert dates["dates"][0]["trade_date"] == "2026-05-06"
    assert "jin10_daily_report" in dates["dates"][0]["modules"]


def test_api_jin10_daily_report_latest_200(tmp_path: Path):
    _make_tree(
        tmp_path,
        {
            "storage/outputs/jin10/2026-05-06/218330/daily_analysis.json": json.dumps(
                {"family": "jin10_daily_visual", "trade_date": "2026-05-06", "run_id": "218330"}
            ),
            "storage/outputs/jin10/2026-05-06/218330/daily_analysis.html": "<html>jin10 latest</html>",
        },
    )
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        response = api_jin10_daily_report_latest()

    assert response["content"] == "<html>jin10 latest</html>"


def test_daily_latest_skips_storage_rows_marked_weekly(tmp_path: Path):
    _make_tree(
        tmp_path,
        {
            "storage/outputs/jin10/2026-05-07/weekly-run/daily_analysis.json": json.dumps(
                {
                    "family": "jin10_daily_visual",
                    "trade_date": "2026-05-07",
                    "run_id": "weekly-run",
                    "report_type": "weekly",
                }
            ),
            "storage/outputs/jin10/2026-05-07/weekly-run/daily_analysis.html": "<html>weekly</html>",
            "storage/outputs/jin10/2026-05-06/daily-run/daily_analysis.json": json.dumps(
                {"family": "jin10_daily_visual", "trade_date": "2026-05-06", "run_id": "daily-run"}
            ),
            "storage/outputs/jin10/2026-05-06/daily-run/daily_analysis.html": "<html>daily</html>",
        },
    )
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        response = api_jin10_daily_report_latest()

    assert response["run_id"] == "daily-run"
    assert response["report_type"] == "daily"
    assert response["content"] == "<html>daily</html>"


def test_daily_latest_skips_storage_rows_marked_non_daily_report_family(tmp_path: Path):
    _make_tree(
        tmp_path,
        {
            "storage/outputs/jin10/2026-07-04/positioning-run/daily_analysis.json": json.dumps(
                {
                    "family": "jin10_positioning_report",
                    "trade_date": "2026-07-04",
                    "run_id": "positioning-run",
                    "report_type": "positioning",
                }
            ),
            "storage/outputs/jin10/2026-07-04/positioning-run/daily_analysis.html": "<html>positioning</html>",
            "storage/outputs/jin10/2026-07-03/daily-run/daily_analysis.json": json.dumps(
                {"family": "jin10_daily_visual", "trade_date": "2026-07-03", "run_id": "daily-run", "report_type": "daily"}
            ),
            "storage/outputs/jin10/2026-07-03/daily-run/daily_analysis.html": "<html>daily</html>",
        },
    )
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        response = api_jin10_daily_report_latest()

    assert response["run_id"] == "daily-run"
    assert response["content"] == "<html>daily</html>"


def test_daily_latest_index_and_dates_skip_non_report_title_marker(tmp_path: Path):
    _make_tree(
        tmp_path,
        {
            "storage/outputs/jin10/2026-07-04/223594/daily_analysis.json": json.dumps(
                {
                    "family": "jin10_daily_visual",
                    "trade_date": "2026-07-04",
                    "run_id": "223594",
                    "report_type": "daily",
                    "title": "弱非农下加息押注退潮",
                }
            ),
            "storage/outputs/jin10/2026-07-04/223594/daily_analysis.html": "<html>hotlist</html>",
            "storage/outputs/jin10/2026-07-04/223594/raw_article_report.json": json.dumps(
                {"title": "一周热榜精选：弱非农下加息押注退潮！大空头警告AI派对结束-金十数据VIP"}
            ),
            "storage/outputs/jin10/2026-07-03/daily-run/daily_analysis.json": json.dumps(
                {"family": "jin10_daily_visual", "trade_date": "2026-07-03", "run_id": "daily-run", "report_type": "daily"}
            ),
            "storage/outputs/jin10/2026-07-03/daily-run/daily_analysis.html": "<html>daily</html>",
        },
    )
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        latest = api_jin10_daily_report_latest()
        index = list_reports_index()
        dates = list_unified_dates()
        try:
            api_jin10_daily_report(date="2026-07-04", run_id="223594")
            raised = None
        except HTTPException as exc:
            raised = exc

    assert latest["run_id"] == "daily-run"
    assert raised is not None
    assert raised.status_code == 404
    daily_runs = {item["run_id"] for item in index["reports"] if item["type"] == "jin10_daily_report"}
    assert "223594" not in daily_runs
    assert "daily-run" in daily_runs
    modules_by_date = {item["trade_date"]: set(item["modules"]) for item in dates["dates"]}
    assert "jin10_daily_report" not in modules_by_date.get("2026-07-04", set())
    assert "jin10_daily_report" in modules_by_date["2026-07-03"]


def test_reports_index_and_unified_dates_expose_non_daily_jin10_report_families(tmp_path: Path):
    _make_tree(
        tmp_path,
        {
            "storage/outputs/jin10/2026-07-04/positioning-run/daily_analysis.json": json.dumps(
                {
                    "family": "jin10_positioning_report",
                    "trade_date": "2026-07-04",
                    "run_id": "positioning-run",
                    "report_type": "positioning",
                }
            ),
            "storage/outputs/jin10/2026-07-04/positioning-run/daily_analysis.html": "<html>positioning</html>",
            "storage/outputs/jin10/2026-07-04/technical-run/daily_analysis.json": json.dumps(
                {
                    "family": "jin10_technical_levels_report",
                    "trade_date": "2026-07-04",
                    "run_id": "technical-run",
                    "report_type": "technical_levels",
                }
            ),
            "storage/outputs/jin10/2026-07-04/technical-run/daily_analysis.html": "<html>technical</html>",
            "storage/outputs/jin10/2026-07-04/oil-run/daily_analysis.json": json.dumps(
                {
                    "family": "jin10_oil_report",
                    "trade_date": "2026-07-04",
                    "run_id": "oil-run",
                    "report_type": "oil",
                }
            ),
            "storage/outputs/jin10/2026-07-04/oil-run/daily_analysis.html": "<html>oil</html>",
            "storage/outputs/jin10/2026-07-04/fx-run/daily_analysis.json": json.dumps(
                {
                    "family": "jin10_fx_report",
                    "trade_date": "2026-07-04",
                    "run_id": "fx-run",
                    "report_type": "fx",
                }
            ),
            "storage/outputs/jin10/2026-07-04/fx-run/daily_analysis.html": "<html>fx</html>",
            "storage/outputs/jin10/2026-07-04/market-observation-run/daily_analysis.json": json.dumps(
                {
                    "family": "jin10_market_observation_report",
                    "trade_date": "2026-07-04",
                    "run_id": "market-observation-run",
                    "report_type": "market_observation",
                }
            ),
            "storage/outputs/jin10/2026-07-04/market-observation-run/daily_analysis.html": "<html>market observation</html>",
            "storage/outputs/jin10/2026-07-03/daily-run/daily_analysis.json": json.dumps(
                {"family": "jin10_daily_visual", "trade_date": "2026-07-03", "run_id": "daily-run", "report_type": "daily"}
            ),
            "storage/outputs/jin10/2026-07-03/daily-run/daily_analysis.html": "<html>daily</html>",
        },
    )
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        index = list_reports_index()
        dates = list_unified_dates()

    jin10_daily_runs = {item["run_id"] for item in index["reports"] if item["type"] == "jin10_daily_report"}
    assert "daily-run" in jin10_daily_runs
    assert "positioning-run" not in jin10_daily_runs
    report_types_by_run = {item["run_id"]: item["type"] for item in index["reports"]}
    assert report_types_by_run["positioning-run"] == "jin10_positioning_report"
    assert report_types_by_run["technical-run"] == "jin10_technical_levels_report"
    assert report_types_by_run["oil-run"] == "jin10_oil_report"
    assert report_types_by_run["fx-run"] == "jin10_fx_report"
    assert report_types_by_run["market-observation-run"] == "jin10_market_observation_report"

    modules_by_date = {item["trade_date"]: set(item["modules"]) for item in dates["dates"]}
    assert "jin10_daily_report" not in modules_by_date.get("2026-07-04", set())
    assert {
        "jin10_positioning_report",
        "jin10_technical_levels_report",
        "jin10_oil_report",
        "jin10_fx_report",
        "jin10_market_observation_report",
    } <= modules_by_date["2026-07-04"]
    assert "jin10_daily_report" in modules_by_date["2026-07-03"]


def test_report_detail_preserves_market_observation_family(tmp_path: Path):
    _make_tree(
        tmp_path,
        {
            "storage/outputs/jin10/2026-07-04/market-observation-run/daily_analysis.json": json.dumps(
                {
                    "family": "jin10_market_observation_report",
                    "trade_date": "2026-07-04",
                    "run_id": "market-observation-run",
                    "report_type": "market_observation",
                    "title": "VIP每日市场观察：市场赔率表提示降息预期升温",
                },
                ensure_ascii=False,
            ),
            "storage/outputs/jin10/2026-07-04/market-observation-run/daily_analysis.html": "<html>market observation</html>",
            "storage/outputs/jin10/2026-07-04/market-observation-run/raw_article_report.json": json.dumps(
                {
                    "title": "VIP每日市场观察：市场赔率表提示降息预期升温",
                    "report_type": "market_observation",
                    "source_url": "https://svip.jin10.com/news/224000",
                    "source_refs": [{"source_url": "https://svip.jin10.com/news/224000", "asset_type": "report_md"}],
                },
                ensure_ascii=False,
            ),
            "storage/outputs/jin10/2026-07-04/market-observation-run/raw_article_report.md": "# 市场观察",
        },
    )

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path), mock.patch(_REPORT_SERVICE_PROJECT_ROOT_PATCH, tmp_path):
        detail = _legacy_jin10_report_detail("market-observation-run")

    assert detail is not None
    assert detail.family == "jin10_market_observation_report"
    assert detail.title == "VIP每日市场观察：市场赔率表提示降息预期升温"
    assert detail.structured_payload["report_type"] == "market_observation"
    assert detail.source_refs[0].url == "https://svip.jin10.com/news/224000"


def test_weekly_report_reads_storage_rows_marked_weekly(tmp_path: Path):
    _make_tree(
        tmp_path,
        {
            "storage/outputs/jin10/2026-05-07/weekly-run/daily_analysis.json": json.dumps(
                {
                    "family": "jin10_daily_visual",
                    "trade_date": "2026-05-07",
                    "run_id": "weekly-run",
                    "report_type": "weekly",
                }
            ),
            "storage/outputs/jin10/2026-05-07/weekly-run/daily_analysis.html": "<html>weekly</html>",
        },
    )
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path), mock.patch.dict(os.environ, {"HOME": str(tmp_path)}):
        latest = api_jin10_weekly_report_latest()
        exact = api_jin10_weekly_report(date="2026-05-07", run_id="weekly-run")

    assert latest["run_id"] == "weekly-run"
    assert latest["report_type"] == "weekly"
    assert exact["content"] == "<html>weekly</html>"


def test_weekly_latest_prefers_newer_external_report_over_older_storage(tmp_path: Path):
    _make_tree(
        tmp_path,
        {
            "storage/outputs/jin10/2026-06-07/old-weekly/daily_analysis.json": json.dumps(
                {
                    "family": "jin10_daily_visual",
                    "trade_date": "2026-06-07",
                    "run_id": "old-weekly",
                    "report_type": "weekly",
                }
            ),
            "storage/outputs/jin10/2026-06-07/old-weekly/daily_analysis.html": "<html>old weekly</html>",
            "jin10-reports/2026-06-14/weekly/221823/meta.json": json.dumps(
                {
                    "id": "221823",
                    "date": "2026-06-14",
                    "title": "黄金深度洗盘结束",
                    "category": "黄金周报",
                    "report_type": "weekly",
                    "images": [],
                }
            ),
            "jin10-reports/2026-06-14/weekly/221823/report.md": "# new weekly",
        },
    )
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path), mock.patch.dict(os.environ, {"HOME": str(tmp_path)}):
        latest = api_jin10_weekly_report_latest()

    assert latest["article_id"] == "221823"
    assert latest["date"] == "2026-06-14"
    assert latest["content"] == "# new weekly"


def test_weekly_report_prefers_storage_raw_markdown_with_local_assets(tmp_path: Path):
    _make_tree(
        tmp_path,
        {
            "jin10-reports/2026-07-05/weekly/223608/meta.json": json.dumps(
                {
                    "id": "223608",
                    "date": "2026-07-05",
                    "title": "黄金引入新观察变量",
                    "category": "黄金周报",
                    "report_type": "weekly",
                    "images": [{"file": "remote-a.jpg"}, {"file": "remote-b.jpg"}],
                }
            ),
            "jin10-reports/2026-07-05/weekly/223608/report.md": "# external weekly\n\n![Remote Hash](https://example.test/a.jpg)",
            "storage/outputs/jin10/2026-07-05/223608/daily_analysis.json": json.dumps(
                {
                    "family": "jin10_weekly_visual",
                    "trade_date": "2026-07-05",
                    "run_id": "223608",
                    "report_type": "weekly",
                }
            ),
            "storage/outputs/jin10/2026-07-05/223608/daily_analysis.html": "<html>weekly</html>",
            "storage/outputs/jin10/2026-07-05/223608/raw_article_report.md": "# storage weekly\n\n![本地图表](figures/fig_p2_001.png)",
            "storage/outputs/jin10/2026-07-05/223608/figures/fig_p2_001.png": "png",
        },
    )
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path), mock.patch.dict(os.environ, {"HOME": str(tmp_path)}):
        latest = api_jin10_weekly_report_latest()
        exact = api_jin10_weekly_report(date="2026-07-05", run_id="223608")

    assert latest["content"] == "# storage weekly\n\n![本地图表](figures/fig_p2_001.png)"
    assert exact["content"] == latest["content"]
    assert latest["image_count"] == 1
    assert latest["asset_base_url"] == "/api/jin10/report-bundle/2026-07-05/223608/asset/"
    assert latest["path"] == "storage/outputs/jin10/2026-07-05/223608/raw_article_report.md"


def test_api_jin10_daily_report_exact_404(tmp_path: Path):
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        try:
            api_jin10_daily_report(date="2026-05-06", run_id="218330")
            raised = None
        except HTTPException as exc:
            raised = exc

    assert raised is not None
    assert raised.status_code == 404
