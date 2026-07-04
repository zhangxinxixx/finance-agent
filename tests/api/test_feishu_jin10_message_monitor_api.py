from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.main import app
from apps.api.services.feishu_jin10_message_monitor_service import (
    get_feishu_jin10_message_monitor,
    get_feishu_jin10_message_monitor_latest,
    list_feishu_jin10_message_monitor_dates,
)
from database.models.task import StepStatus, TaskRun, TaskStatus, TaskStep, ensure_task_tables

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
                            "message_id": "om_221733",
                            "chat_id": "oc_test",
                            "sender_name": "金十新闻",
                            "message_type": "post",
                            "content": "另一条可执行的跟进消息。",
                            "links": ["https://xnews.jin10.com/details/221733?j=test"],
                            "published_at": f"{date}T00:30:00+00:00",
                            "source_marker": "来自金十数据APP重要推送",
                        },
                        "looks_like_jin10": True,
                        "relevance_decision": {
                            "decision": "candidate",
                            "score": 0.64,
                            "reasons": ["gold_watchlist"],
                            "asset_tags": ["XAUUSD"],
                            "topic_tags": ["gold"],
                            "event_type_hint": "macro_watch",
                            "need_detail_fetch": False,
                            "need_verification": False,
                        },
                    },
                    {
                        "message": {
                            "message_id": "om_flash",
                            "chat_id": "oc_test",
                            "sender_name": "金十新闻",
                            "message_type": "post",
                            "content": "WTI 原油短线下挫。",
                            "links": ["https://flash.jin10.com/detail/20260612010101000100?j=test"],
                            "published_at": f"{date}T00:10:00+00:00",
                            "source_marker": "来自金十数据APP重要推送",
                        },
                        "looks_like_jin10": True,
                        "relevance_decision": {
                            "decision": "candidate",
                            "score": 0.52,
                            "reasons": ["oil_watchlist"],
                            "asset_tags": ["WTI"],
                            "topic_tags": ["oil"],
                            "event_type_hint": "oil_move",
                            "need_detail_fetch": False,
                            "need_verification": False,
                        },
                    },
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


def _write_raw_report(root: Path, *, date: str, run_id: str) -> None:
    path = root / "storage" / "outputs" / "jin10" / date / run_id / "raw_article_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "source_url": "https://xnews.jin10.com/details/221732",
                "title": "每日金银报告",
                "report_type": "daily",
                "source_refs": [
                    {
                        "asset_type": "meta_json",
                        "source_url": "https://xnews.jin10.com/details/221732",
                        "category_code": "270",
                        "path": "jin10/daily/221732/meta.json",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _make_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_task_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _seed_task(
    session: Session,
    *,
    date: str,
    source_url: str,
    task_status: TaskStatus,
    step_status: StepStatus,
    blocked_reason: str | None = None,
) -> None:
    run = TaskRun(
        name="daily_analysis_followup",
        task_type="daily_analysis_followup",
        status=task_status,
        current_stage="news_followup",
        progress=0.5,
        trade_date=date,
        error_summary=blocked_reason if task_status == TaskStatus.blocked else None,
    )
    session.add(run)
    session.flush()
    session.add(
        TaskStep(
            task_run_id=run.id,
            name="daily_analysis_followup",
            stage="news_followup",
            task_kind="jin10_daily_analysis",
            status=step_status,
            input_json=json.dumps({"source_url": source_url}, ensure_ascii=False),
            blocked_reason=blocked_reason,
            step_order=0,
        )
    )
    session.commit()


def _seed_tasks(session: Session, *, date: str) -> None:
    _seed_task(
        session,
        date=date,
        source_url="https://xnews.jin10.com/details/221732?j=test",
        task_status=TaskStatus.blocked,
        step_status=StepStatus.blocked,
        blocked_reason="Upstream detail fetch blocked",
    )
    _seed_task(
        session,
        date=date,
        source_url="https://xnews.jin10.com/details/221733?j=test",
        task_status=TaskStatus.pending,
        step_status=StepStatus.pending,
    )


def test_get_feishu_jin10_message_monitor_joins_filter_trigger_and_brief(tmp_path: Path) -> None:
    _write_parsed_messages(tmp_path, date="2026-06-12")
    _write_features(tmp_path, date="2026-06-12", run_id="run-news")
    _write_raw_report(tmp_path, date="2026-06-12", run_id="run-report")
    session = _make_session()
    _seed_tasks(session, date="2026-06-12")

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        payload = get_feishu_jin10_message_monitor(date="2026-06-12", db=session)

    assert payload is not None
    assert payload["as_of"] == "2026-06-12T03:01:00+00:00"
    assert payload["latest_published_at"] == "2026-06-12T02:26:01+00:00"
    assert payload["message_count"] == 3
    assert payload["accepted_count"] == 3
    assert payload["high_value_count"] == 1
    assert payload["triggered_count"] == 1
    assert payload["status_counts"] == {"high_value": 1, "candidate": 2}
    assert payload["access_status_counts"] == {"vip_locked": 1}
    assert payload["task_status_counts"] == {"blocked": 1, "pending": 1}
    assert payload["blocked_count"] == 1
    assert payload["actionable_count"] == 2
    assert payload["data_quality"]["report_url_count"] == 1
    target = next(item for item in payload["messages"] if item["message_id"] == "om_221732")
    assert target["filter_status"] == "high_value"
    assert target["content_kind"] == "article"
    assert target["title"] == "美伊冲突结束预期升温，降息空间压缩，金价上行空间收窄。"
    assert target["report_tags"] == ["金银日报"]
    assert target["trigger"]["priority"] == "high"
    assert target["article_brief"]["brief_id"] == "brief:221732"
    assert target["article_brief"]["display_bucket"] == "VIP预览"
    assert target["article_brief"]["access_status"] == "vip_locked"
    assert target["article_brief"]["analysis_summary"] == "该文章只抓到 VIP 预览内容。"
    assert target["article_brief"]["source_refs"] == []
    assert target["task"]["status"] == "blocked"
    assert target["task"]["blocked"] is True
    assert target["task"]["blocked_reason"] == "Upstream detail fetch blocked"
    assert target["blocked"] is True
    assert target["actionable"] is False
    actionable = next(item for item in payload["messages"] if item["message_id"] == "om_221733")
    assert actionable["filter_status"] == "candidate"
    assert actionable["content_kind"] == "article"
    assert actionable["report_tags"] == []
    assert actionable["task"]["status"] == "pending"
    assert actionable["task"]["blocked"] is False
    assert actionable["blocked"] is False
    assert actionable["actionable"] is True
    flash = next(item for item in payload["messages"] if item["message_id"] == "om_flash")
    assert flash["filter_status"] == "candidate"
    assert flash["content_kind"] == "flash"
    assert flash["trigger"] is None
    assert flash["article_brief"] is None
    assert flash["task"] is None
    assert flash["report_tags"] == []
    assert flash["blocked"] is False
    assert flash["actionable"] is True


def test_api_feishu_jin10_message_monitor_returns_payload() -> None:
    with mock.patch(
        "apps.api.main.get_feishu_jin10_message_monitor",
        return_value={
            "status": "available",
            "date": "2026-06-12",
            "as_of": "2026-06-12T03:01:00+00:00",
            "latest_published_at": "2026-06-12T02:26:01+00:00",
            "message_count": 1,
            "accepted_count": 1,
            "high_value_count": 1,
            "triggered_count": 1,
            "brief_count": 1,
            "task_count": 1,
            "status_counts": {"high_value": 1},
            "access_status_counts": {"vip_locked": 1},
            "task_status_counts": {"blocked": 1},
            "blocked_count": 1,
            "actionable_count": 0,
            "messages": [],
        },
    ):
        resp = client.get("/api/news/feishu-jin10/messages?date=2026-06-12")

    assert resp.status_code == 200
    body = resp.json()
    assert body["date"] == "2026-06-12"
    assert body["as_of"] == "2026-06-12T03:01:00+00:00"
    assert body["blocked_count"] == 1


def test_api_feishu_jin10_message_monitor_returns_empty_payload_when_artifact_missing(tmp_path: Path) -> None:
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        payload = get_feishu_jin10_message_monitor(date="2026-06-12")

    assert payload["status"] == "empty"
    assert payload["date"] == "2026-06-12"
    assert payload["as_of"] is None
    assert payload["latest_published_at"] is None
    assert payload["message_count"] == 0
    assert payload["status_counts"] == {}
    assert payload["access_status_counts"] == {}
    assert payload["task_status_counts"] == {}
    assert payload["blocked_count"] == 0
    assert payload["actionable_count"] == 0
    assert payload["messages"] == []


def test_api_feishu_jin10_message_monitor_http_empty_payload() -> None:
    with mock.patch(
        "apps.api.main.get_feishu_jin10_message_monitor",
        return_value={
            "status": "empty",
            "date": "2026-06-12",
            "as_of": None,
            "latest_published_at": None,
            "message_count": 0,
            "accepted_count": 0,
            "high_value_count": 0,
            "triggered_count": 0,
            "brief_count": 0,
            "task_count": 0,
            "status_counts": {},
            "access_status_counts": {},
            "task_status_counts": {},
            "blocked_count": 0,
            "actionable_count": 0,
            "source_refs": [],
            "messages": [],
            "data_quality": {"warning_count": 0},
        },
    ):
        resp = client.get("/api/news/feishu-jin10/messages?date=2026-06-12")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "empty"
    assert body["messages"] == []


def test_get_feishu_jin10_message_monitor_latest_picks_latest_available_date(tmp_path: Path) -> None:
    _write_parsed_messages(tmp_path, date="2026-06-12")
    _write_parsed_messages(tmp_path, date="2026-06-17")

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        payload = get_feishu_jin10_message_monitor_latest()

    assert payload is not None
    assert payload["date"] == "2026-06-17"
    assert payload["message_count"] == 3


def test_list_feishu_jin10_message_monitor_dates_returns_descending_dates(tmp_path: Path) -> None:
    _write_parsed_messages(tmp_path, date="2026-06-12")
    _write_parsed_messages(tmp_path, date="2026-06-17")

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        payload = list_feishu_jin10_message_monitor_dates()

    assert payload == ["2026-06-17", "2026-06-12"]


def test_api_feishu_jin10_message_monitor_latest_returns_payload() -> None:
    with mock.patch(
        "apps.api.main.get_feishu_jin10_message_monitor_latest",
        return_value={
            "status": "available",
            "date": "2026-06-17",
            "as_of": "2026-06-17T08:07:28+00:00",
            "latest_published_at": "2026-06-17T08:03:02+00:00",
            "message_count": 60,
            "accepted_count": 28,
            "high_value_count": 13,
            "triggered_count": 19,
            "brief_count": 0,
            "task_count": 0,
            "status_counts": {"candidate": 15, "high_value": 13},
            "access_status_counts": {},
            "task_status_counts": {},
            "blocked_count": 0,
            "actionable_count": 28,
            "source_refs": [],
            "messages": [],
            "data_quality": {"warning_count": 0},
        },
    ):
        resp = client.get("/api/news/feishu-jin10/messages/latest")

    assert resp.status_code == 200
    body = resp.json()
    assert body["date"] == "2026-06-17"
    assert body["message_count"] == 60


def test_api_feishu_jin10_message_monitor_dates_returns_payload() -> None:
    with mock.patch("apps.api.main.list_feishu_jin10_message_monitor_dates", return_value=["2026-06-17", "2026-06-12"]):
        resp = client.get("/api/news/feishu-jin10/dates")

    assert resp.status_code == 200
    assert resp.json() == {"dates": ["2026-06-17", "2026-06-12"]}


def test_api_feishu_jin10_message_monitor_latest_returns_404_when_missing() -> None:
    with mock.patch("apps.api.main.get_feishu_jin10_message_monitor_latest", return_value=None):
        resp = client.get("/api/news/feishu-jin10/messages/latest")

    assert resp.status_code == 404
