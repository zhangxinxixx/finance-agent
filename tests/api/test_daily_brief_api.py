from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.services.daily_brief_service import get_daily_brief, get_daily_brief_latest

client = TestClient(app)

_PROJECT_ROOT_PATCH = "apps.api.services.daily_brief_service._PROJECT_ROOT"


def _write_daily_brief(root: Path, *, date: str, run_id: str, headline: str, status: str = "available") -> Path:
    output_dir = root / "storage" / "outputs" / "daily_brief" / date / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / "daily_brief.md"
    json_path = output_dir / "daily_brief.json"
    markdown = f"# 每日市场快讯\n\n## 一句话结论\n\n{headline}\n"
    markdown_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {
                "status": status,
                "date": date,
                "run_id": run_id,
                "report_mode": "hybrid" if status == "available" else "empty",
                "artifact_path": f"outputs/daily_brief/{date}/{run_id}/daily_brief.md",
                "input_snapshot_path": f"features/news/{date}/{run_id}/daily_brief_input_snapshot.json",
                "markdown": markdown,
                "structured": {"core_event_count": 1 if status == "available" else 0},
                "source_refs": [{"source": "reuters", "source_ref": "wire:1"}],
                "quality_flags": ["single_source_verification_required"] if status == "available" else ["no_actionable_inputs"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return json_path


def test_get_daily_brief_latest_picks_latest_run(tmp_path: Path) -> None:
    _write_daily_brief(tmp_path, date="2026-06-10", run_id="run-old", headline="旧日报")
    latest_path = _write_daily_brief(tmp_path, date="2026-06-12", run_id="run-new", headline="新日报")

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        payload = get_daily_brief_latest()

    assert payload is not None
    assert payload["date"] == "2026-06-12"
    assert payload["run_id"] == "run-new"
    assert payload["artifact_path"] == "outputs/daily_brief/2026-06-12/run-new/daily_brief.md"
    assert payload["json_path"] == latest_path.relative_to(tmp_path).as_posix()
    assert payload["markdown"].startswith("# 每日市场快讯")
    assert payload["source_refs"] == [{"source": "reuters", "source_ref": "wire:1"}]


def test_get_daily_brief_exact_missing_returns_none(tmp_path: Path) -> None:
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        assert get_daily_brief(date="2099-01-01", run_id="missing") is None


def test_api_daily_brief_latest_200(tmp_path: Path) -> None:
    _write_daily_brief(tmp_path, date="2026-06-12", run_id="run-news", headline="最新日报")

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        resp = client.get("/api/news/daily-brief/latest")

    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] == "run-news"
    assert data["status"] == "available"
    assert data["structured"]["core_event_count"] == 1
    assert "最新日报" in data["markdown"]


def test_api_daily_brief_exact_404(tmp_path: Path) -> None:
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        resp = client.get("/api/news/daily-brief?date=2099-01-01&run_id=nope")

    assert resp.status_code == 404
