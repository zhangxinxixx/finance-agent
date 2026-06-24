from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest import mock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.main import api_create_daily_analysis_followup_tasks, api_run_detail
from database.models.task import TaskRun, TaskStep, ensure_task_tables

_TRIGGER_ROOT_PATCH = "apps.api.services.daily_analysis_trigger_service._PROJECT_ROOT"
_ARTICLE_ROOT_PATCH = "apps.api.services.jin10_article_brief_service._PROJECT_ROOT"


def _make_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_task_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


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
                        "source_key": "jin10_feishu",
                        "source_title": title,
                        "source_url": "https://xnews.jin10.com/details/trigger",
                        "source_event_id": "event:fed_hawkish:test",
                        "event_type": "fed_hawkish",
                        "impact_path": "strong_data_to_higher_for_longer",
                        "gold_impact": "bearish",
                        "evidence_text": "黄金和美联储主线仍需重点跟进。",
                        "reason_codes": ["gold_daily_topic", "fed_inflation_path"],
                        "suggested_actions": actions or ["fetch_detail_page", "run_jin10_daily_analysis"],
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
                        "suggested_actions": actions or ["show_in_news_flash", "queue_daily_analysis"],
                        "asset_tags": ["XAUUSD", "DXY"],
                        "topic_tags": ["gold", "inflation"],
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


def test_create_daily_analysis_followup_tasks_from_trigger(tmp_path: Path) -> None:
    session = _make_session()
    _write_triggers(tmp_path, date="2026-06-11", run_id="run-news", title="重点跟进")

    with mock.patch(_TRIGGER_ROOT_PATCH, tmp_path), mock.patch(_ARTICLE_ROOT_PATCH, tmp_path):
        response = api_create_daily_analysis_followup_tasks(date="2026-06-11", run_id="run-news", db=session)

    assert response["status"] == "accepted"
    assert response["queue_count"] == 1
    assert response["created_task_count"] == 1
    assert response["skipped_existing_count"] == 0

    run = api_run_detail(response["created_run_ids"][0], db=session).model_dump(mode="json")
    assert run["task_type"] == "daily_analysis_followup"
    assert run["status"] == "queued"
    assert run["trading_date"] == "2026-06-11"
    assert run["steps"][0]["task_kind"] == "jin10_daily_analysis"
    assert run["steps"][0]["input_refs"][0]["file_path"].endswith("daily_analysis_triggers.json")
    assert run["steps"][0]["source_refs"][0]["source_name"] == "jin10_feishu"
    step = session.query(TaskStep).filter(TaskStep.task_run_id == uuid.UUID(response["created_run_ids"][0])).one()
    followup = json.loads(step.input_json or "{}")["followup"]
    assert followup["title"] == "重点跟进"
    assert followup["source_title"] == "重点跟进"
    assert followup["evidence_text"] == "黄金和美联储主线仍需重点跟进。"
    assert followup["impact_path"] == "strong_data_to_higher_for_longer"
    assert followup["gold_impact"] == "bearish"


def test_create_daily_analysis_followup_tasks_from_article_brief_latest(tmp_path: Path) -> None:
    session = _make_session()
    _write_article_briefs(tmp_path, date="2026-06-12", run_id="run-brief", headline="文章跟进")

    with mock.patch(_TRIGGER_ROOT_PATCH, tmp_path), mock.patch(_ARTICLE_ROOT_PATCH, tmp_path):
        response = api_create_daily_analysis_followup_tasks(db=session)

    assert response["status"] == "accepted"
    assert response["date"] == "2026-06-12"
    assert response["run_id"] == "run-brief"
    assert response["created_task_count"] == 1

    run = api_run_detail(response["created_run_ids"][0], db=session).model_dump(mode="json")
    assert run["status"] == "queued"
    assert run["steps"][0]["task_name"] == "queue_daily_analysis"
    assert run["steps"][0]["input_refs"][0]["file_path"].endswith("jin10_article_briefs.json")


def test_create_daily_analysis_followup_tasks_is_idempotent_for_active_runs(tmp_path: Path) -> None:
    session = _make_session()
    _write_triggers(tmp_path, date="2026-06-11", run_id="run-news", title="重点跟进")

    with mock.patch(_TRIGGER_ROOT_PATCH, tmp_path), mock.patch(_ARTICLE_ROOT_PATCH, tmp_path):
        first = api_create_daily_analysis_followup_tasks(date="2026-06-11", run_id="run-news", db=session)
        second = api_create_daily_analysis_followup_tasks(date="2026-06-11", run_id="run-news", db=session)

    assert first["created_task_count"] == 1
    assert second["status"] == "deduped"
    assert second["created_task_count"] == 0
    assert second["skipped_existing_count"] == 1
    assert second["existing_run_ids"] == first["created_run_ids"]
    assert session.query(TaskRun).filter(TaskRun.task_type == "daily_analysis_followup").count() == 1


def test_create_daily_analysis_followup_tasks_returns_empty_when_no_actionable_followups(tmp_path: Path) -> None:
    session = _make_session()
    _write_triggers(
        tmp_path,
        date="2026-06-11",
        run_id="run-news",
        title="非动作触发",
        actions=["fetch_detail_page"],
    )

    with mock.patch(_TRIGGER_ROOT_PATCH, tmp_path), mock.patch(_ARTICLE_ROOT_PATCH, tmp_path):
        response = api_create_daily_analysis_followup_tasks(date="2026-06-11", run_id="run-news", db=session)

    assert response["status"] == "empty"
    assert response["queue_count"] == 0
    assert response["created_task_count"] == 0
    assert session.query(TaskRun).filter(TaskRun.task_type == "daily_analysis_followup").count() == 0


def test_create_daily_analysis_followup_tasks_exact_missing_raises_404(tmp_path: Path) -> None:
    session = _make_session()

    with (
        mock.patch(_TRIGGER_ROOT_PATCH, tmp_path),
        mock.patch(_ARTICLE_ROOT_PATCH, tmp_path),
        pytest.raises(HTTPException) as exc_info,
    ):
        api_create_daily_analysis_followup_tasks(date="2099-01-01", run_id="missing", db=session)

    assert exc_info.value.status_code == 404
