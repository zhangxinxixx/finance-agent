from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import apps.api.main as api_main
from database.models.task import TaskRun, TaskStatus, ensure_task_tables


def _make_session_factory() -> tuple[sessionmaker, Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_task_tables(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return factory, factory()


class _FakeDagsterResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def test_trigger_premarket_marks_stale_legacy_run_and_launches(monkeypatch: pytest.MonkeyPatch) -> None:
    session_factory, session = _make_session_factory()
    old_time = datetime.now(UTC) - timedelta(days=17)
    stale_run = TaskRun(
        name="premarket",
        status=TaskStatus.running,
        started_at=old_time,
        created_at=old_time,
        updated_at=old_time,
    )
    session.add(stale_run)
    session.commit()

    monkeypatch.setattr(api_main, "SessionLocal", session_factory)
    def _fake_post(*args, **kwargs):
        query = kwargs.get("json", {}).get("query", "")
        if "runsOrError" in query:
            return _FakeDagsterResponse({"data": {"runsOrError": {"results": []}}})
        return _FakeDagsterResponse(
            {
                "data": {
                    "launchPipelineExecution": {
                        "run": {"runId": "dagster-run-001", "status": "QUEUED"}
                    }
                }
            }
        )

    monkeypatch.setattr(httpx, "post", _fake_post)

    resp = api_main.trigger_premarket()

    session.refresh(stale_run)
    assert resp.task_id == "dagster-run-001"
    assert resp.status == "running"
    assert stale_run.status == TaskStatus.stale
    assert stale_run.ended_at is not None
    assert stale_run.error_summary is not None


def test_trigger_premarket_keeps_fresh_active_run_blocking(monkeypatch: pytest.MonkeyPatch) -> None:
    session_factory, session = _make_session_factory()
    fresh_time = datetime.now(UTC) - timedelta(minutes=15)
    active_run = TaskRun(
        name="premarket",
        status=TaskStatus.running,
        started_at=fresh_time,
        created_at=fresh_time,
        updated_at=fresh_time,
    )
    session.add(active_run)
    session.commit()

    monkeypatch.setattr(api_main, "SessionLocal", session_factory)

    with pytest.raises(api_main.HTTPException) as exc_info:
        api_main.trigger_premarket()

    session.refresh(active_run)
    assert exc_info.value.status_code == 409
    assert active_run.status == TaskStatus.running


def test_trigger_premarket_blocks_when_dagster_run_is_active(monkeypatch: pytest.MonkeyPatch) -> None:
    session_factory, _session = _make_session_factory()
    monkeypatch.setattr(api_main, "SessionLocal", session_factory)

    calls: list[str] = []

    def _fake_post(*args, **kwargs):
        query = kwargs.get("json", {}).get("query", "")
        calls.append(query)
        if "runsOrError" in query:
            return _FakeDagsterResponse(
                {
                    "data": {
                        "runsOrError": {
                            "results": [{"runId": "dagster-active-001", "status": "STARTED"}]
                        }
                    }
                }
            )
        raise AssertionError("launchPipelineExecution should not be called when Dagster already has an active run")

    monkeypatch.setattr(httpx, "post", _fake_post)

    with pytest.raises(api_main.HTTPException) as exc_info:
        api_main.trigger_premarket()

    assert exc_info.value.status_code == 409
    assert any("runsOrError" in query for query in calls)


def test_get_task_falls_back_to_dagster_run_when_legacy_task_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _session_factory, session = _make_session_factory()
    run_id = "754ace3d-fb00-47c8-bbd0-62a4776fe1b3"

    monkeypatch.setattr(api_main, "_database_reachable", lambda: False)

    def _fake_post(*args, **kwargs):
        query = kwargs.get("json", {}).get("query", "")
        assert "runOrError" in query
        return _FakeDagsterResponse(
            {
                "data": {
                    "runOrError": {
                        "__typename": "Run",
                        "runId": run_id,
                        "status": "SUCCESS",
                        "startTime": 1781683619.311475,
                        "endTime": 1781683772.2973607,
                        "stepStats": [
                            {
                                "stepKey": "premarket.merge_analysis_snapshot_op",
                                "status": "SUCCESS",
                                "startTime": 1781683763.0,
                                "endTime": 1781683764.4515185,
                            },
                            {
                                "stepKey": "premarket.c4_agent_pipeline.strategy_card_op",
                                "status": "SUCCESS",
                                "startTime": 1781683770.0,
                                "endTime": 1781683772.2973607,
                            },
                        ],
                    }
                }
            }
        )

    monkeypatch.setattr(httpx, "post", _fake_post)

    resp = api_main.get_task(run_id, db=session)

    assert resp.id == run_id
    assert resp.name == "premarket"
    assert resp.status == "success"
    assert [step.name for step in resp.steps] == [
        "merge_analysis_snapshot_op",
        "strategy_card_op",
    ]
    assert all(step.status == "success" for step in resp.steps)
