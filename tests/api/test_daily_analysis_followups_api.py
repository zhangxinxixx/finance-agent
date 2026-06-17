from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.services.daily_analysis_followup_service import (
    get_daily_analysis_followups,
    get_daily_analysis_followups_latest,
)

client = TestClient(app)

_PROJECT_ROOT_PATCH = "apps.api.services.daily_analysis_trigger_service._PROJECT_ROOT"


def _write_triggers(root: Path, *, date: str, run_id: str, title: str, actions: list[str] | None = None) -> Path:
    path = root / "storage" / "features" / "news" / date / run_id / "daily_analysis_triggers.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "as_of": f"{date}T12:00:00+00:00",
                "rule_version": "jin10-daily-analysis-trigger-v1",
                "trigger_count": 1,
                "triggers": [
                    {
                        "trigger_id": "trigger:jin10_daily_analysis:test",
                        "trigger_type": "jin10_daily_analysis",
                        "priority": "high",
                        "status": "queued",
                        "source_news_item_id": "news-item-1",
                        "source_key": "jin10_feishu",
                        "source_title": title,
                        "source_url": "https://xnews.jin10.com/details/trigger",
                        "source_event_id": "event:fed_hawkish:test",
                        "event_type": "fed_hawkish",
                        "impact_path": "strong_data_to_higher_for_longer",
                        "gold_impact": "bearish",
                        "reason_codes": ["gold_daily_topic", "fed_inflation_path"],
                        "suggested_actions": actions or ["fetch_detail_page", "run_jin10_daily_analysis"],
                        "evidence_text": "黄金和美联储主线仍需重点跟进。",
                        "asset_tags": ["XAUUSD", "DXY"],
                        "topic_tags": ["gold", "macro"],
                        "source_refs": [{"source": "jin10_feishu", "source_ref": "jin10_feishu:test"}],
                        "data_quality": {"trigger_score": 0.91, "verification_status": "single_source"},
                        "created_at": f"{date}T12:00:00+00:00",
                    }
                ],
                "data_quality": {"event_candidate_count": 2, "trigger_count": 1, "rejected_event_count": 1},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def _write_article_briefs(root: Path, *, date: str, run_id: str, headline: str, actions: list[str] | None = None) -> Path:
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
                        "suggested_actions": actions or ["show_in_news_flash", "queue_daily_analysis"],
                        "source_refs": [{"source": "jin10_feishu", "source_ref": "jin10_article_briefs:test"}],
                        "data_quality": {"verification_status": "single_source"},
                        "created_at": f"{date}T12:00:00+00:00",
                    }
                ],
                "data_quality": {"display_bucket_counts": {"重点分析": 1}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_get_daily_analysis_followups_latest_picks_latest_run(tmp_path: Path) -> None:
    _write_triggers(tmp_path, date="2026-06-10", run_id="run-old", title="旧跟进")
    latest_path = _write_triggers(tmp_path, date="2026-06-11", run_id="run-new", title="新跟进")

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        payload = get_daily_analysis_followups_latest()

    assert payload is not None
    assert payload["date"] == "2026-06-11"
    assert payload["run_id"] == "run-new"
    assert payload["artifact_path"] == latest_path.relative_to(tmp_path).as_posix()
    assert payload["queue_count"] == 1
    assert payload["high_priority_count"] == 1
    assert payload["followups"][0]["action"] == "run_jin10_daily_analysis"
    assert payload["followups"][0]["title"] == "新跟进"
    assert payload["followups"][0]["source_title"] == "新跟进"
    assert payload["followups"][0]["evidence_text"] == "黄金和美联储主线仍需重点跟进。"
    assert payload["followups"][0]["impact_path"] == "strong_data_to_higher_for_longer"
    assert payload["followups"][0]["gold_impact"] == "bearish"


def test_get_daily_analysis_followups_exact_missing_returns_none(tmp_path: Path) -> None:
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        assert get_daily_analysis_followups(date="2099-01-01", run_id="missing") is None


def test_get_daily_analysis_followups_returns_empty_when_no_actionable_trigger(tmp_path: Path) -> None:
    _write_triggers(tmp_path, date="2026-06-11", run_id="run-news", title="非动作触发", actions=["fetch_detail_page"])

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        payload = get_daily_analysis_followups_latest()

    assert payload is not None
    assert payload["status"] == "empty"
    assert payload["queue_count"] == 0
    assert payload["followups"] == []


def test_get_daily_analysis_followups_latest_falls_back_to_article_briefs(tmp_path: Path) -> None:
    latest_path = _write_article_briefs(tmp_path, date="2026-06-11", run_id="run-news", headline="重点文章")

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        payload = get_daily_analysis_followups_latest(project_root=tmp_path)

    assert payload is not None
    assert payload["date"] == "2026-06-11"
    assert payload["run_id"] == "run-news"
    assert payload["artifact_path"] == latest_path.relative_to(tmp_path).as_posix()
    assert payload["source_artifact"] == "jin10_article_briefs"
    assert payload["queue_count"] == 1
    assert payload["followups"][0]["action"] == "queue_daily_analysis"
    assert payload["followups"][0]["title"] == "重点文章"
    assert payload["followups"][0]["source_title"] == "重点文章"
    assert payload["followups"][0]["summary"] == "这是一条黄金主线重点分析。"
    assert payload["followups"][0]["evidence_text"] == "能源推升通胀数据，美联储已难兑现宽松。"
    assert payload["followups"][0]["key_points"] == ["能源推升通胀数据，美联储已难兑现宽松"]


def test_get_daily_analysis_followups_exact_merges_triggers_and_article_briefs(tmp_path: Path) -> None:
    _write_triggers(tmp_path, date="2026-06-11", run_id="run-news", title="触发器")
    _write_article_briefs(tmp_path, date="2026-06-11", run_id="run-news", headline="文章跟进")

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        payload = get_daily_analysis_followups(date="2026-06-11", run_id="run-news", project_root=tmp_path)

    assert payload is not None
    assert payload["source_artifact"] == "mixed"
    assert payload["queue_count"] == 2
    assert payload["artifact_paths"]["daily_analysis_triggers"].endswith("daily_analysis_triggers.json")
    assert payload["artifact_paths"]["jin10_article_briefs"].endswith("jin10_article_briefs.json")
    assert {item["action"] for item in payload["followups"]} == {"run_jin10_daily_analysis", "queue_daily_analysis"}


def test_api_daily_analysis_followups_latest_200(tmp_path: Path) -> None:
    _write_triggers(tmp_path, date="2026-06-11", run_id="run-news", title="重点跟进")

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        resp = client.get("/api/news/daily-analysis-followups/latest")

    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] == "run-news"
    assert data["queue_count"] == 1
    assert data["followups"][0]["queue_type"] == "jin10_daily_analysis"


def test_api_daily_analysis_followups_exact_404(tmp_path: Path) -> None:
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        resp = client.get("/api/news/daily-analysis-followups?date=2099-01-01&run_id=nope")

    assert resp.status_code == 404
