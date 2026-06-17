from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.services.feishu_jin10_message_monitor_service import get_feishu_jin10_message_monitor

client = TestClient(app)

_PROJECT_ROOT_PATCH = "apps.api.services.feishu_jin10_message_monitor_service._PROJECT_ROOT"


def _write_parsed_messages(root: Path, *, date: str) -> None:
    path = root / "storage" / "parsed" / "news" / "jin10_feishu" / date / "messages-test.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "source_key": "jin10_feishu",
                "chat_id": "oc_test",
                "retrieved_date": date,
                "messages": [
                    {
                        "message": {
                            "message_id": "om_221732",
                            "chat_id": "oc_test",
                            "sender_name": "金十新闻",
                            "message_type": "post",
                            "content": "美伊冲突结束预期升温，降息空间压缩，金价上行空间收窄。",
                            "links": ["https://xnews.jin10.com/details/221732?j=test"],
                            "published_at": f"{date}T02:26:01+00:00",
                            "source_marker": "来自金十数据APP重要推送",
                        },
                        "looks_like_jin10": True,
                        "relevance_decision": {
                            "decision": "high_value",
                            "score": 0.92,
                            "reasons": ["gold_direct", "rates_macro_path"],
                            "asset_tags": ["XAUUSD"],
                            "topic_tags": ["gold", "rates"],
                            "event_type_hint": "fed_hawkish",
                            "need_detail_fetch": True,
                            "need_verification": True,
                        },
                    },
                    {
                        "message": {
                            "message_id": "om_low",
                            "chat_id": "oc_test",
                            "sender_name": "金十新闻",
                            "message_type": "post",
                            "content": "普通商品合同消息。",
                            "links": ["https://flash.jin10.com/detail/1"],
                            "published_at": f"{date}T01:00:00+00:00",
                            "source_marker": "来自金十数据APP重要推送",
                        },
                        "looks_like_jin10": True,
                        "relevance_decision": {"decision": "archive_only", "score": 0.12},
                    },
                ],
                "items": [
                    {
                        "source_key": "jin10_feishu",
                        "title": "美伊冲突结束预期升温，降息空间压缩，金价上行空间收窄。",
                        "url": "https://xnews.jin10.com/details/221732?j=test",
                        "domain": "xnews.jin10.com",
                        "event_type": "fed_hawkish",
                        "duplicate_key": "news:jin10_feishu:221732",
                        "verification_status": "single_source",
                        "raw_payload": {
                            "message_id": "om_221732",
                            "relevance_decision": {
                                "decision": "high_value",
                                "score": 0.92,
                                "reasons": ["gold_direct", "rates_macro_path"],
                                "asset_tags": ["XAUUSD"],
                                "topic_tags": ["gold", "rates"],
                                "event_type_hint": "fed_hawkish",
                                "need_detail_fetch": True,
                                "need_verification": True,
                            },
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_features(root: Path, *, date: str, run_id: str) -> None:
    base = root / "storage" / "features" / "news" / date / run_id
    base.mkdir(parents=True, exist_ok=True)
    url = "https://xnews.jin10.com/details/221732?j=test"
    (base / "daily_analysis_triggers.json").write_text(
        json.dumps(
            {
                "as_of": f"{date}T03:00:00+00:00",
                "rule_version": "jin10-daily-analysis-trigger-v2",
                "trigger_count": 1,
                "triggers": [
                    {
                        "trigger_id": "trigger:221732",
                        "trigger_type": "jin10_daily_analysis",
                        "priority": "high",
                        "status": "queued",
                        "source_url": url,
                        "event_type": "fed_hawkish",
                        "reason_codes": ["gold_daily_topic", "fed_inflation_path"],
                        "suggested_actions": ["fetch_detail_page", "run_jin10_daily_analysis"],
                        "data_quality": {"trigger_score": 1.0},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (base / "jin10_article_briefs.json").write_text(
        json.dumps(
            {
                "as_of": f"{date}T03:01:00+00:00",
                "rule_version": "jin10-article-briefs-v1",
                "brief_count": 1,
                "briefs": [
                    {
                        "brief_id": "brief:221732",
                        "source_url": url,
                        "headline": "冲突再次接近终点，但黄金的上行空间可能已不及战前",
                        "article_class": "vip_market_reference",
                        "display_bucket": "VIP预览",
                        "access_status": "vip_locked",
                        "analysis_summary": "该文章只抓到 VIP 预览内容。",
                        "detail_artifacts": {"parsed_path": "parsed/news/jin10_detail_pages/2026-06-12/221732.json"},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_get_feishu_jin10_message_monitor_joins_filter_trigger_and_brief(tmp_path: Path) -> None:
    _write_parsed_messages(tmp_path, date="2026-06-12")
    _write_features(tmp_path, date="2026-06-12", run_id="run-news")

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        payload = get_feishu_jin10_message_monitor(date="2026-06-12")

    assert payload is not None
    assert payload["message_count"] == 2
    assert payload["accepted_count"] == 1
    assert payload["triggered_count"] == 1
    target = next(item for item in payload["messages"] if item["message_id"] == "om_221732")
    assert target["filter_status"] == "high_value"
    assert target["accepted_item"]["duplicate_key"] == "news:jin10_feishu:221732"
    assert target["trigger"]["priority"] == "high"
    assert target["article_brief"]["access_status"] == "vip_locked"
    low = next(item for item in payload["messages"] if item["message_id"] == "om_low")
    assert low["filter_status"] == "archive_only"
    assert low["trigger"] is None


def test_api_feishu_jin10_message_monitor_returns_payload() -> None:
    with mock.patch(
        "apps.api.main.get_feishu_jin10_message_monitor",
        return_value={"status": "available", "date": "2026-06-12", "message_count": 1, "messages": []},
    ):
        resp = client.get("/api/news/feishu-jin10/messages?date=2026-06-12")

    assert resp.status_code == 200
    assert resp.json()["date"] == "2026-06-12"


def test_api_feishu_jin10_message_monitor_returns_empty_payload_when_artifact_missing(tmp_path: Path) -> None:
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        payload = get_feishu_jin10_message_monitor(date="2026-06-12")

    assert payload["status"] == "empty"
    assert payload["date"] == "2026-06-12"
    assert payload["message_count"] == 0
    assert payload["messages"] == []


def test_api_feishu_jin10_message_monitor_http_empty_payload() -> None:
    with mock.patch(
        "apps.api.main.get_feishu_jin10_message_monitor",
        return_value={
            "status": "empty",
            "date": "2026-06-12",
            "message_count": 0,
            "accepted_count": 0,
            "triggered_count": 0,
            "brief_count": 0,
            "task_count": 0,
            "source_refs": [],
            "messages": [],
            "data_quality": {"warning_count": 0, "warnings": []},
        },
    ):
        resp = client.get("/api/news/feishu-jin10/messages?date=2026-06-12")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "empty"
    assert body["messages"] == []
