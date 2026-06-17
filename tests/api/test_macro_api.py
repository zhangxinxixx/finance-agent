"""Macro API 文件发现测试 — 验证 date/run_id 子目录支持。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from apps.api.data_service import (
    _latest_date_dir,
    _latest_run_file,
    get_macro_latest,
    get_macro_report_md,
)


# ── helpers ──

_PROJECT_ROOT_PATCH = "apps.api.data_service._PROJECT_ROOT"


def _make_tree(root: Path, files: dict[str, str | None]) -> None:
    """按 {relative_path: content} 创建目录和文件；content=None 则只建目录。"""
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if content is not None:
            p.write_text(content, encoding="utf-8")


# ── _latest_date_dir ──


def test_latest_date_dir_empty(tmp_path: Path):
    assert _latest_date_dir(tmp_path) is None


def test_latest_date_dir_returns_newest(tmp_path: Path):
    (tmp_path / "2026-05-10").mkdir()
    (tmp_path / "2026-05-14").mkdir()
    (tmp_path / "2026-05-07").mkdir()
    result = _latest_date_dir(tmp_path)
    assert result is not None
    assert result.name == "2026-05-14"


# ── _latest_run_file ──


def test_latest_run_file_direct_fallback(tmp_path: Path):
    """旧格式：文件直接放在 date 目录下。"""
    date_dir = tmp_path / "2026-05-07"
    date_dir.mkdir(parents=True)
    (date_dir / "macro_snapshot.json").write_text('{"a": 1}')
    path = _latest_run_file(date_dir, "macro_snapshot.json")
    assert path is not None
    assert path.name == "macro_snapshot.json"
    assert path.parent == date_dir


def test_latest_run_file_picks_newest_run_id(tmp_path: Path):
    """新格式：多个 run_id 子目录，选最新的。"""
    date_dir = tmp_path / "2026-05-14"
    _make_tree(date_dir, {
        "auto-20260513/macro_snapshot.json": "old",
        "auto-v2/macro_snapshot.json": "new",
    })
    path = _latest_run_file(date_dir, "macro_snapshot.json")
    assert path is not None
    assert path.parent.name == "auto-v2"  # v2 > 20260513 字母序


def test_latest_run_file_run_id_beats_direct(tmp_path: Path):
    """run_id 子目录文件优先于 date 根目录文件。"""
    date_dir = tmp_path / "2026-05-14"
    _make_tree(date_dir, {
        "macro_snapshot.json": "direct",
        "auto-v2/macro_snapshot.json": "nested",
    })
    path = _latest_run_file(date_dir, "macro_snapshot.json")
    assert path is not None
    assert path.parent.name == "auto-v2"
    assert path.read_text() == "nested"


def test_latest_run_file_missing(tmp_path: Path):
    date_dir = tmp_path / "empty"
    date_dir.mkdir()
    assert _latest_run_file(date_dir, "macro_snapshot.json") is None


# ── get_macro_latest ──


def test_get_macro_latest_new_format(tmp_path: Path):
    _make_tree(tmp_path, {
        "storage/features/macro/2026-05-14/auto-v2/macro_snapshot.json":
            json.dumps({"as_of": "2026-05-14", "indicators": {"SPX": 5900}}),
        "storage/features/macro/2026-05-14/auto-20260513/macro_snapshot.json":
            json.dumps({"as_of": "2026-05-14-old"}),
    })
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        data = get_macro_latest()
    assert data is not None
    assert data["as_of"] == "2026-05-14"
    assert data["indicators"]["SPX"] == 5900


def test_get_macro_latest_old_format_direct(tmp_path: Path):
    _make_tree(tmp_path, {
        "storage/features/macro/2026-05-07/macro_snapshot.json":
            json.dumps({"as_of": "2026-05-07"}),
    })
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        data = get_macro_latest()
    assert data is not None
    assert data["as_of"] == "2026-05-07"


def test_get_macro_latest_empty(tmp_path: Path):
    _make_tree(tmp_path, {"storage/features/macro/": None})
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        assert get_macro_latest() is None


def test_get_macro_latest_no_dir(tmp_path: Path):
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        assert get_macro_latest() is None


def test_get_macro_latest_bad_json_raises(tmp_path: Path):
    _make_tree(tmp_path, {
        "storage/features/macro/2026-05-14/auto-v2/macro_snapshot.json":
            "not valid json",
    })
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        with pytest.raises(json.JSONDecodeError):
            get_macro_latest()


# ── get_macro_report_md ──


def test_get_macro_report_md_new_format(tmp_path: Path):
    md_content = "# Macro Report\nSPX at 5900."
    _make_tree(tmp_path, {
        "storage/outputs/macro/2026-05-14/auto-v2/macro_snapshot.md": md_content,
        "storage/outputs/macro/2026-05-14/auto-20260513/macro_snapshot.md": "old",
    })
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        result = get_macro_report_md()
    assert result == md_content


def test_get_macro_report_md_old_format_direct(tmp_path: Path):
    md_content = "# Legacy Report"
    _make_tree(tmp_path, {
        "storage/outputs/macro/2026-05-07/macro_snapshot.md": md_content,
    })
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        result = get_macro_report_md()
    assert result == md_content


def test_get_macro_report_md_specific_date(tmp_path: Path):
    md_content = "# Specific Date"
    _make_tree(tmp_path, {
        "storage/outputs/macro/2026-05-08/compare/macro_snapshot.md": md_content,
    })
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        result = get_macro_report_md("2026-05-08")
    assert result == md_content


def test_get_macro_report_md_specific_date_missing(tmp_path: Path):
    _make_tree(tmp_path, {"storage/outputs/macro/": None})
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        assert get_macro_report_md("2026-05-99") is None


def test_get_macro_report_md_empty(tmp_path: Path):
    _make_tree(tmp_path, {"storage/outputs/macro/": None})
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        assert get_macro_report_md() is None


def test_get_macro_report_md_ignores_full_report(tmp_path: Path):
    """macro_full_report.md 不替代 macro_snapshot.md。"""
    _make_tree(tmp_path, {
        "storage/outputs/macro/2026-05-14/auto-v2/macro_full_report.md": "full",
        "storage/outputs/macro/2026-05-14/auto-v2/macro_snapshot.md": "snapshot",
    })
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        result = get_macro_report_md()
    assert result == "snapshot"
