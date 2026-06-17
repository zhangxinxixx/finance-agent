from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.services.daily_analysis_trigger_service import (
    get_daily_analysis_triggers,
    get_daily_analysis_triggers_latest,
)

client = TestClient(app)

_PROJECT_ROOT_PATCH = "apps.api.services.daily_analysis_trigger_service._PROJECT_ROOT"


def _write_triggers(root: Path, *, date: str, run_id: str, title: str) -> Path:
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
                        "suggested_actions": ["fetch_detail_page", "run_jin10_daily_analysis"],
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


def test_get_daily_analysis_triggers_latest_picks_latest_run(tmp_path: Path) -> None:
    _write_triggers(tmp_path, date="2026-06-10", run_id="run-old", title="旧触发器")
    latest_path = _write_triggers(tmp_path, date="2026-06-11", run_id="run-new", title="新触发器")

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        payload = get_daily_analysis_triggers_latest()

    assert payload is not None
    assert payload["date"] == "2026-06-11"
    assert payload["run_id"] == "run-new"
    assert payload["artifact_path"] == latest_path.relative_to(tmp_path).as_posix()
    assert payload["trigger_count"] == 1
    assert payload["priority_counts"] == {"high": 1}
    assert payload["source_key_counts"] == {"jin10_feishu": 1}
    assert payload["triggers"][0]["source_title"] == "新触发器"


def test_get_daily_analysis_triggers_exact_missing_returns_none(tmp_path: Path) -> None:
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        assert get_daily_analysis_triggers(date="2099-01-01", run_id="missing") is None


def test_api_daily_analysis_triggers_latest_200(tmp_path: Path) -> None:
    _write_triggers(tmp_path, date="2026-06-11", run_id="run-news", title="重点触发器")

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        resp = client.get("/api/news/daily-analysis-triggers/latest")

    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] == "run-news"
    assert data["trigger_count"] == 1
    assert data["triggers"][0]["trigger_type"] == "jin10_daily_analysis"


def test_api_daily_analysis_triggers_exact_404(tmp_path: Path) -> None:
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        resp = client.get("/api/news/daily-analysis-triggers?date=2099-01-01&run_id=nope")

    assert resp.status_code == 404
