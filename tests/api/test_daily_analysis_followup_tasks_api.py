from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest import mock

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.main import api_create_daily_analysis_followup_tasks, api_run_detail
from apps.api.services.daily_analysis_followup_task_service import (
    DailyAnalysisFollowupDispatchError,
    launch_daily_analysis_followup_job,
)
from database.models.task import TaskRun, TaskStep, ensure_task_tables

_TRIGGER_ROOT_PATCH = "apps.api.services.daily_analysis_trigger_service._PROJECT_ROOT"
_ARTICLE_ROOT_PATCH = "apps.api.services.jin10_article_brief_service._PROJECT_ROOT"


@pytest.mark.parametrize("date,run_id", [("2026-10-11", None), (None, "selected"), ("", "selected"), ("2026-10-11", " ")])
def test_partial_selector_cannot_create_or_dispatch_a_different_latest_queue(date, run_id):
    with (
        mock.patch("apps.api.routes.news_routes.create_daily_analysis_followup_tasks") as create,
        mock.patch("apps.api.routes.news_routes.dispatch_daily_analysis_followup_tasks") as dispatch,
        pytest.raises(HTTPException) as error,
    ):
        api_create_daily_analysis_followup_tasks(date=date, run_id=run_id, db=mock.Mock())
    assert error.value.status_code == 422
    create.assert_not_called()
    dispatch.assert_not_called()


@pytest.fixture(autouse=True)
def _stub_followup_dagster_dispatch(monkeypatch: pytest.MonkeyPatch):
    calls: list[list[str]] = []

    def _fake_dispatch(task_ids):
        normalized = [str(task_id) for task_id in task_ids]
        calls.append(normalized)
        return {
            "dispatch_status": "dispatched",
            "task_ids": normalized,
            "dagster_run_id": f"test-followup-run-{len(calls)}",
            "dagster_status": "QUEUED",
            "dagster_job_name": "daily_analysis_followup_job",
        }

    monkeypatch.setattr(
        "apps.api.services.daily_analysis_followup_task_service.launch_daily_analysis_followup_job",
        _fake_dispatch,
    )
    return calls


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
    assert response["dispatch_status"] == "dispatched"
    assert response["task_ids"] == response["created_run_ids"]
    assert response["dagster_job_name"] == "daily_analysis_followup_job"
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
    assert second["task_ids"] == first["created_run_ids"]
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
    assert response["dispatch_status"] == "not_dispatched"
    assert response["task_ids"] == []
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


def test_followup_dispatch_failure_preserves_committed_task_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _make_session()
    _write_triggers(tmp_path, date="2026-06-11", run_id="run-news", title="派发失败")

    def _fail_dispatch(task_ids):
        raise DailyAnalysisFollowupDispatchError(
            status_code=502,
            reason="dagster_unavailable",
            message="Dagster unavailable: connection refused",
            cause="connection refused",
        )

    monkeypatch.setattr(
        "apps.api.services.daily_analysis_followup_task_service.launch_daily_analysis_followup_job",
        _fail_dispatch,
    )
    with (
        mock.patch(_TRIGGER_ROOT_PATCH, tmp_path),
        mock.patch(_ARTICLE_ROOT_PATCH, tmp_path),
        pytest.raises(HTTPException) as exc_info,
    ):
        api_create_daily_analysis_followup_tasks(date="2026-06-11", run_id="run-news", db=session)

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail["reason"] == "dagster_unavailable"
    assert exc_info.value.detail["dispatch_status"] == "unavailable"
    assert exc_info.value.detail["task_rows_preserved"] is True
    assert session.query(TaskRun).filter(TaskRun.task_type == "daily_analysis_followup").count() == 1
    assert session.query(TaskRun).one().status.value == "pending"


def test_launch_daily_analysis_followup_job_sends_explicit_ids_and_bounded_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = str(uuid.uuid4())
    response = mock.Mock()
    response.json.return_value = {
        "data": {
            "launchPipelineExecution": {
                "run": {"runId": "dagster-followup-001", "status": "QUEUED"}
            }
        }
    }
    response.raise_for_status.return_value = None
    calls: list[dict] = []

    def _post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return response

    monkeypatch.setattr(httpx, "post", _post)
    result = launch_daily_analysis_followup_job(
        [task_id, task_id],
        dagster_url="http://dagster.test/graphql",
        storage_root="/tmp/followup-storage",
        max_stage_steps=99,
    )

    assert result["dispatch_status"] == "dispatched"
    assert result["task_ids"] == [task_id]
    request = calls[0]["json"]
    assert request["variables"]["runConfigData"] == {
        "ops": {
            "daily_analysis_followup_op": {
                "config": {
                    "task_ids": [task_id],
                    "storage_root": "/tmp/followup-storage",
                    "max_stage_steps": 4,
                }
            }
        }
    }
    assert "$taskSetHash: String!" in request["query"]
    assert "task_scope" in request["query"]


def test_launch_daily_analysis_followup_job_reports_dagster_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(httpx, "post", mock.Mock(side_effect=httpx.ConnectError("connection refused")))

    with pytest.raises(DailyAnalysisFollowupDispatchError) as exc_info:
        launch_daily_analysis_followup_job([str(uuid.uuid4())], dagster_url="http://dagster.test/graphql")

    error = exc_info.value
    assert error.status_code == 502
    assert error.reason == "dagster_unavailable"
    assert "connection refused" in error.message
    assert error.detail(task_ids=["selected-task"])["task_rows_preserved"] is True


def test_followup_api_chunks_more_than_fifty_explicit_task_ids(
    monkeypatch: pytest.MonkeyPatch,
    _stub_followup_dagster_dispatch,
) -> None:
    task_ids = [str(uuid.uuid4()) for _ in range(51)]
    monkeypatch.setattr(
        "apps.api.routes.news_routes.create_daily_analysis_followup_tasks",
        lambda *_args, **_kwargs: {
            "status": "accepted",
            "queue_count": len(task_ids),
            "created_task_count": len(task_ids),
            "skipped_existing_count": 0,
            "created_run_ids": task_ids,
            "existing_run_ids": [],
        },
    )

    response = api_create_daily_analysis_followup_tasks(db=object())

    assert response["dispatch_status"] == "dispatched"
    assert response["task_ids"] == task_ids
    assert len(response["dagster_run_ids"]) == 2
    assert [len(item) for item in _stub_followup_dagster_dispatch] == [50, 1]


def test_followup_api_reports_partial_chunk_failure_and_preserves_remaining_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_ids = [str(uuid.uuid4()) for _ in range(51)]
    monkeypatch.setattr(
        "apps.api.routes.news_routes.create_daily_analysis_followup_tasks",
        lambda *_args, **_kwargs: {
            "status": "accepted",
            "queue_count": len(task_ids),
            "created_task_count": len(task_ids),
            "skipped_existing_count": 0,
            "created_run_ids": task_ids,
            "existing_run_ids": [],
        },
    )
    calls = 0

    def _dispatch(chunk):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "dispatch_status": "dispatched",
                "task_ids": list(chunk),
                "dagster_run_id": "first-run",
                "dagster_status": "QUEUED",
            }
        raise DailyAnalysisFollowupDispatchError(
            status_code=502,
            reason="dagster_unavailable",
            message="Dagster unavailable: second batch",
            cause="second batch",
        )

    monkeypatch.setattr(
        "apps.api.services.daily_analysis_followup_task_service.launch_daily_analysis_followup_job",
        _dispatch,
    )
    with pytest.raises(HTTPException) as exc_info:
        api_create_daily_analysis_followup_tasks(db=object())

    assert exc_info.value.status_code == 502
    detail = exc_info.value.detail
    assert detail["dispatch_status"] == "partial_failure"
    assert detail["dispatched_task_ids"] == task_ids[:50]
    assert detail["remaining_task_ids"] == task_ids[50:]
    assert detail["dagster_run_ids"] == ["first-run"]
    assert detail["task_rows_preserved"] is True
