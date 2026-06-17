from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.services.jin10_article_brief_service import (
    get_jin10_article_briefs,
    get_jin10_article_briefs_latest,
)

client = TestClient(app)

_PROJECT_ROOT_PATCH = "apps.api.services.jin10_article_brief_service._PROJECT_ROOT"


def _write_briefs(root: Path, *, date: str, run_id: str, headline: str) -> Path:
    path = root / "storage" / "features" / "news" / date / run_id / "jin10_article_briefs.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "as_of": f"{date}T12:00:00+00:00",
                "rule_version": "jin10-article-briefs-v1",
                "brief_count": 1,
                "briefs": [
                    {
                        "brief_id": "jin10_brief:test",
                        "article_class": "gold_macro_market_reference",
                        "display_bucket": "重点分析",
                        "headline": headline,
                        "source_url": "https://xnews.jin10.com/details/1",
                        "access_status": "readable",
                        "original_excerpt": "能源推升通胀数据，美联储已难兑现宽松。",
                        "key_points": ["能源推升通胀数据，美联储已难兑现宽松"],
                        "analysis_summary": "这是一条黄金主线重点分析。",
                        "asset_tags": ["XAUUSD", "DXY"],
                        "topic_tags": ["gold", "inflation"],
                        "suggested_actions": ["show_in_news_flash", "queue_daily_analysis"],
                    }
                ],
                "data_quality": {
                    "display_bucket_counts": {"重点分析": 1},
                    "article_class_counts": {"gold_macro_market_reference": 1},
                    "access_status_counts": {"readable": 1},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_get_jin10_article_briefs_latest_picks_latest_run(tmp_path: Path) -> None:
    _write_briefs(tmp_path, date="2026-06-10", run_id="run-old", headline="旧文章")
    latest_path = _write_briefs(tmp_path, date="2026-06-11", run_id="run-new", headline="新文章")

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        payload = get_jin10_article_briefs_latest()

    assert payload is not None
    assert payload["date"] == "2026-06-11"
    assert payload["run_id"] == "run-new"
    assert payload["artifact_path"] == latest_path.relative_to(tmp_path).as_posix()
    assert payload["display_bucket_counts"] == {"重点分析": 1}
    assert payload["briefs"][0]["headline"] == "新文章"


def test_get_jin10_article_briefs_exact_missing_returns_none(tmp_path: Path) -> None:
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        assert get_jin10_article_briefs(date="2099-01-01", run_id="missing") is None


def test_api_jin10_article_briefs_latest_200(tmp_path: Path) -> None:
    _write_briefs(tmp_path, date="2026-06-11", run_id="run-news", headline="重点文章")

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        resp = client.get("/api/jin10/article-briefs/latest")

    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] == "run-news"
    assert data["brief_count"] == 1
    assert data["briefs"][0]["display_bucket"] == "重点分析"


def test_api_jin10_article_briefs_exact_404(tmp_path: Path) -> None:
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        resp = client.get("/api/jin10/article-briefs?date=2099-01-01&run_id=nope")

    assert resp.status_code == 404
