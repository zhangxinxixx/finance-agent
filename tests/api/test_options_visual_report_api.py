from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest
from fastapi import HTTPException

import apps.api.data_service as data_service
from apps.api.main import api_options_visual_report, api_options_visual_report_latest


def _make_tree(root: Path, files: dict[str, str | None]) -> None:
    for rel, content in files.items():
        p = root / rel
        if content is None:
            p.mkdir(parents=True, exist_ok=True)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")


def test_get_options_visual_report_latest(tmp_path: Path) -> None:
    html = "<html><body>visual</body></html>"
    _make_tree(tmp_path, {
        "storage/outputs/cme/2026-05-19/run-new/options_visual_report.html": html,
    })

    with mock.patch.object(data_service, "_PROJECT_ROOT", tmp_path):
        data = data_service.get_options_visual_report_html()

    assert data is not None
    assert data["trade_date"] == "2026-05-19"
    assert data["run_id"] == "run-new"
    assert data["content"] == html
    assert data["format"] == "html"


def test_api_options_visual_report_exact_200(tmp_path: Path) -> None:
    html = "<html><body>exact visual</body></html>"
    _make_tree(tmp_path, {
        "storage/outputs/cme/2026-05-07/run-a/options_visual_report.html": html,
    })

    with mock.patch.object(data_service, "_PROJECT_ROOT", tmp_path):
        data = api_options_visual_report(date="2026-05-07", run_id="run-a")

    assert data["content"] == html


def test_api_options_visual_report_latest_404(tmp_path: Path) -> None:
    with mock.patch.object(data_service, "_PROJECT_ROOT", tmp_path):
        with pytest.raises(HTTPException) as excinfo:
            api_options_visual_report_latest()

    assert excinfo.value.status_code == 404
