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
_PROJECT_ROOT_PATCH = "apps.api.data_service._PROJECT_ROOT"


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
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path), mock.patch.dict(os.environ, {"HOME": str(tmp_path)}):
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
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        latest = api_jin10_weekly_report_latest()
        exact = api_jin10_weekly_report(date="2026-05-07", run_id="weekly-run")

    assert latest["run_id"] == "weekly-run"
    assert latest["report_type"] == "weekly"
    assert exact["content"] == "<html>weekly</html>"


def test_api_jin10_daily_report_exact_404(tmp_path: Path):
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        try:
            api_jin10_daily_report(date="2026-05-06", run_id="218330")
            raised = None
        except HTTPException as exc:
            raised = exc

    assert raised is not None
    assert raised.status_code == 404
