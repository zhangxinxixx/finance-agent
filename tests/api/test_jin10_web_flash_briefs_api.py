from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.services.jin10_web_flash_brief_service import (
    get_jin10_web_flash_briefs,
    get_jin10_web_flash_briefs_latest,
)

client = TestClient(app)

_PROJECT_ROOT_PATCH = "apps.api.services.jin10_web_flash_brief_service._PROJECT_ROOT"


def _write_web_flash_briefs(
    root: Path,
    *,
    date: str,
    run_id: str,
    headline: str,
    retrieved_date: str | None = None,
) -> Path:
    path = root / "storage" / "features" / "news" / date / run_id / "jin10_web_flash_briefs.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "retrieved_date": retrieved_date or date,
        "run_id": run_id,
        "jin10_web_flash_briefs": {
            "as_of": f"{date}T12:00:00+00:00",
            "rule_version": "jin10-web-flash-briefs-v1",
            "status": "ok",
            "brief_count": 1,
            "briefs": [
                {
                    "brief_id": "web_flash:test",
                    "headline": headline,
                    "importance": "important",
                    "content": "Web Important headline content",
                    "source_url": "https://flash.jin10.com/details/1",
                }
            ],
            "data_quality": {"total_fetched": 5, "selected": 1},
            "source_refs": ["jin10_web_flash_collector"],
            "artifact_refs": ["jin10_web_flash_parser"],
            "quality_flags": {"low_confidence": False},
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


# ── Service tests ──


def test_get_jin10_web_flash_briefs_latest_picks_latest_run(tmp_path: Path) -> None:
    _write_web_flash_briefs(tmp_path, date="2026-06-10", run_id="run-old", headline="旧快讯")
    latest_path = _write_web_flash_briefs(
        tmp_path, date="2026-06-11", run_id="run-new", headline="新快讯"
    )

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        payload = get_jin10_web_flash_briefs_latest()

    assert payload is not None
    assert payload["date"] == "2026-06-11"
    assert payload["run_id"] == "run-new"
    assert payload["artifact_path"] == latest_path.relative_to(tmp_path).as_posix()
    assert payload["briefs"][0]["headline"] == "新快讯"


def test_get_jin10_web_flash_briefs_latest_returns_relative_artifact_path(tmp_path: Path) -> None:
    _write_web_flash_briefs(tmp_path, date="2026-06-15", run_id="run-1", headline="t")

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        payload = get_jin10_web_flash_briefs_latest()

    assert payload is not None
    assert not Path(payload["artifact_path"]).is_absolute()
    assert payload["artifact_path"].startswith("storage/")


def test_get_jin10_web_flash_briefs_exact_missing_returns_none(tmp_path: Path) -> None:
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        assert get_jin10_web_flash_briefs(date="2099-01-01", run_id="missing") is None


def test_get_jin10_web_flash_briefs_malformed_wrapper_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "storage" / "features" / "news" / "2026-06-20" / "run-bad" / "jin10_web_flash_briefs.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"brief_count": "bad"}), encoding="utf-8")

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        assert get_jin10_web_flash_briefs(date="2026-06-20", run_id="run-bad") is None


def test_get_jin10_web_flash_briefs_preserves_wrapper_metadata(tmp_path: Path) -> None:
    _write_web_flash_briefs(
        tmp_path,
        date="2026-06-20",
        run_id="run-meta",
        headline="meta test",
        retrieved_date="2026-06-21",
    )

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        payload = get_jin10_web_flash_briefs(date="2026-06-20", run_id="run-meta")

    assert payload is not None
    assert payload["retrieved_date"] == "2026-06-21"
    assert payload["source_refs"] == ["jin10_web_flash_collector"]
    assert payload["artifact_refs"] == ["jin10_web_flash_parser"]
    assert payload["quality_flags"] == {"low_confidence": False}
    assert payload["data_quality"] == {"total_fetched": 5, "selected": 1}
    assert payload["as_of"] == "2026-06-20T12:00:00+00:00"
    assert payload["rule_version"] == "jin10-web-flash-briefs-v1"


# ── API route tests ──


def test_api_jin10_web_flash_briefs_latest_200(tmp_path: Path) -> None:
    _write_web_flash_briefs(tmp_path, date="2026-06-11", run_id="run-news", headline="重点快讯")

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        resp = client.get("/api/jin10/web-flash-briefs/latest")

    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] == "run-news"
    assert data["brief_count"] == 1
    assert data["briefs"][0]["headline"] == "重点快讯"
    assert data["status"] == "ok"


def test_api_jin10_web_flash_briefs_latest_404(tmp_path: Path) -> None:
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        resp = client.get("/api/jin10/web-flash-briefs/latest")

    assert resp.status_code == 404


def test_api_jin10_web_flash_briefs_exact_200(tmp_path: Path) -> None:
    _write_web_flash_briefs(tmp_path, date="2026-06-12", run_id="run-exact", headline="精确查询")

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        resp = client.get("/api/jin10/web-flash-briefs?date=2026-06-12&run_id=run-exact")

    assert resp.status_code == 200
    data = resp.json()
    assert data["date"] == "2026-06-12"
    assert data["run_id"] == "run-exact"


def test_api_jin10_web_flash_briefs_exact_404(tmp_path: Path) -> None:
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        resp = client.get("/api/jin10/web-flash-briefs?date=2099-01-01&run_id=nope")

    assert resp.status_code == 404
