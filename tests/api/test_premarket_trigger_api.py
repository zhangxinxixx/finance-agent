from __future__ import annotations

from datetime import UTC, datetime, timedelta
import importlib

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import apps.api.main as api_main
from apps.api.services import premarket_launch_service
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


def test_premarket_routes_delegate_to_launch_service(monkeypatch: pytest.MonkeyPatch) -> None:
    launch_service = importlib.import_module("apps.api.services.premarket_launch_service")
    calls: list[tuple[str, bool]] = []

    def _fake_preflight(*, force: bool = False, **_kwargs):
        calls.append(("preflight", force))
        return api_main.PremarketLaunchPreflightResponse(
            force=force,
            can_launch=True,
            blocking_reasons=[],
        )

    def _fake_launch(*, force: bool = False, **_kwargs):
        calls.append(("launch", force))
        return api_main.TaskCreateResponse(
            task_id="delegated-run-001",
            name="premarket",
            status="running",
        )

    monkeypatch.setattr(launch_service, "build_premarket_launch_preflight", _fake_preflight)
    monkeypatch.setattr(launch_service, "trigger_premarket_launch", _fake_launch)

    preflight = api_main.api_premarket_launch_preflight(force=True)
    launched = api_main.trigger_premarket(force=True)

    assert preflight.can_launch is True
    assert launched.task_id == "delegated-run-001"
    assert calls == [("preflight", True), ("launch", True)]


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
    monkeypatch.setattr(
        api_main.pipeline_contract_service,
        "build_premarket_pipeline_source_readiness",
        lambda: {
            "step_order": ["macro_collect"],
            "steps": [],
            "source_readiness_summary": {
                "decision_counts": {"ready": 1, "degraded_allowed": 0, "blocked": 0},
                "blocked_steps": [],
                "degraded_steps": [],
                "blocked_sources": [],
                "degraded_sources": [],
            },
        },
    )

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
    assert resp.source_readiness_summary == {
        "decision_counts": {"ready": 1, "degraded_allowed": 0, "blocked": 0},
        "blocked_steps": [],
        "degraded_steps": [],
        "blocked_sources": [],
        "degraded_sources": [],
    }
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
    monkeypatch.setattr(
        api_main.pipeline_contract_service,
        "build_premarket_pipeline_source_readiness",
        lambda: {"step_order": [], "steps": [], "source_readiness_summary": {"decision_counts": {"blocked": 0}}},
    )

    with pytest.raises(api_main.HTTPException) as exc_info:
        api_main.trigger_premarket()

    session.refresh(active_run)
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["reason"] == "legacy_active_task"
    assert exc_info.value.detail["message"].startswith("已有进行中的 premarket 任务")
    assert exc_info.value.detail["active_legacy_task"]["task_id"] == str(active_run.id)
    assert exc_info.value.detail["source_readiness_summary"] == {"decision_counts": {"blocked": 0}}
    assert active_run.status == TaskStatus.running


def test_trigger_premarket_blocks_when_dagster_run_is_active(monkeypatch: pytest.MonkeyPatch) -> None:
    session_factory, _session = _make_session_factory()
    monkeypatch.setattr(api_main, "SessionLocal", session_factory)
    monkeypatch.setattr(
        api_main.pipeline_contract_service,
        "build_premarket_pipeline_source_readiness",
        lambda: {"step_order": [], "steps": [], "source_readiness_summary": {"decision_counts": {"blocked": 1}}},
    )

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
    assert exc_info.value.detail["reason"] == "dagster_active_run"
    assert exc_info.value.detail["active_dagster_run"]["run_id"] == "dagster-active-001"
    assert exc_info.value.detail["source_readiness_summary"] == {"decision_counts": {"blocked": 1}}
    assert any("runsOrError" in query for query in calls)


def test_trigger_premarket_returns_structured_detail_when_dagster_launch_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory, _session = _make_session_factory()
    monkeypatch.setattr(api_main, "SessionLocal", session_factory)
    monkeypatch.setattr(
        api_main.pipeline_contract_service,
        "build_premarket_pipeline_source_readiness",
        lambda: {"step_order": [], "steps": [], "source_readiness_summary": {"decision_counts": {"blocked": 0}}},
    )

    def _fake_post(*args, **kwargs):
        query = kwargs.get("json", {}).get("query", "")
        if "runsOrError" in query:
            return _FakeDagsterResponse({"data": {"runsOrError": {"results": []}}})
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", _fake_post)

    with pytest.raises(api_main.HTTPException) as exc_info:
        api_main.trigger_premarket()

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail["reason"] == "dagster_unavailable"
    assert "Dagster unavailable" in exc_info.value.detail["message"]
    assert "connection refused" in exc_info.value.detail["dagster_check_error"]
    assert exc_info.value.detail["source_readiness_summary"] == {"decision_counts": {"blocked": 0}}


def test_premarket_preflight_ignores_stale_legacy_run_and_keeps_it_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    monkeypatch.setattr(
        api_main.pipeline_contract_service,
        "build_premarket_pipeline_source_readiness",
        lambda: {
            "step_order": ["macro_collect"],
            "steps": [],
            "source_readiness_summary": {
                "decision_counts": {"ready": 1, "degraded_allowed": 0, "blocked": 0},
                "blocked_steps": [],
                "degraded_steps": [],
                "blocked_sources": [],
                "degraded_sources": [],
            },
        },
    )
    monkeypatch.setattr(premarket_launch_service, "find_active_dagster_premarket_run", lambda _url: None)

    resp = api_main.api_premarket_launch_preflight()

    session.refresh(stale_run)
    assert resp.can_launch is True
    assert resp.blocking_reasons == []
    assert resp.active_legacy_task is None
    assert resp.stale_legacy_task_ids == [str(stale_run.id)]
    assert resp.source_readiness_summary == {
        "decision_counts": {"ready": 1, "degraded_allowed": 0, "blocked": 0},
        "blocked_steps": [],
        "degraded_steps": [],
        "blocked_sources": [],
        "degraded_sources": [],
    }
    assert stale_run.status == TaskStatus.running


def test_premarket_preflight_reports_active_legacy_task_blocker(monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.setattr(
        api_main.pipeline_contract_service,
        "build_premarket_pipeline_source_readiness",
        lambda: {"step_order": [], "steps": [], "source_readiness_summary": {"decision_counts": {}}},
    )
    monkeypatch.setattr(premarket_launch_service, "find_active_dagster_premarket_run", lambda _url: None)

    resp = api_main.api_premarket_launch_preflight()

    assert resp.can_launch is False
    assert resp.blocking_reasons == ["legacy_active_task"]
    assert resp.active_legacy_task is not None
    assert resp.active_legacy_task.task_id == str(active_run.id)
    assert resp.active_legacy_task.status == "running"
    assert resp.stale_legacy_task_ids == []


def test_premarket_preflight_blocks_when_source_readiness_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory, _session = _make_session_factory()

    monkeypatch.setattr(api_main, "SessionLocal", session_factory)
    monkeypatch.setattr(
        api_main.pipeline_contract_service,
        "build_premarket_pipeline_source_readiness",
        lambda: {
            "step_order": ["macro_collect"],
            "steps": [],
            "source_readiness_summary": {
                "decision_counts": {"ready": 0, "degraded_allowed": 0, "blocked": 1},
                "blocked_steps": ["macro_collect"],
                "degraded_steps": [],
                "blocked_sources": ["fred"],
                "degraded_sources": [],
            },
        },
    )
    monkeypatch.setattr(premarket_launch_service, "find_active_dagster_premarket_run", lambda _url: None)

    resp = api_main.api_premarket_launch_preflight()

    assert resp.can_launch is False
    assert resp.blocking_reasons == ["source_readiness_blocked"]
    assert resp.source_readiness_summary == {
        "decision_counts": {"ready": 0, "degraded_allowed": 0, "blocked": 1},
        "blocked_steps": ["macro_collect"],
        "degraded_steps": [],
        "blocked_sources": ["fred"],
        "degraded_sources": [],
    }


def test_premarket_preflight_force_true_keeps_blockers_visible_but_allows_launch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory, _session = _make_session_factory()

    monkeypatch.setattr(api_main, "SessionLocal", session_factory)
    monkeypatch.setattr(
        api_main.pipeline_contract_service,
        "build_premarket_pipeline_source_readiness",
        lambda: {"step_order": [], "steps": [], "source_readiness_summary": {"decision_counts": {}}},
    )
    monkeypatch.setattr(
        premarket_launch_service,
        "find_active_dagster_premarket_run",
        lambda _url: {"run_id": "dagster-active-001", "status": "STARTED"},
    )

    resp = api_main.api_premarket_launch_preflight(force=True)

    assert resp.force is True
    assert resp.can_launch is True
    assert resp.blocking_reasons == ["dagster_active_run"]
    assert resp.active_dagster_run is not None
    assert resp.active_dagster_run.run_id == "dagster-active-001"
    assert resp.active_dagster_run.status == "STARTED"


def test_trigger_premarket_blocks_when_source_readiness_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    session_factory, _session = _make_session_factory()

    monkeypatch.setattr(api_main, "SessionLocal", session_factory)
    monkeypatch.setattr(
        api_main.pipeline_contract_service,
        "build_premarket_pipeline_source_readiness",
        lambda: {
            "step_order": ["macro_collect"],
            "steps": [],
            "source_readiness_summary": {
                "decision_counts": {"ready": 0, "degraded_allowed": 0, "blocked": 2},
                "blocked_steps": ["macro_collect", "news_collect"],
                "degraded_steps": [],
                "blocked_sources": ["fred", "jin10"],
                "degraded_sources": [],
            },
        },
    )
    monkeypatch.setattr(premarket_launch_service, "find_active_dagster_premarket_run", lambda _url: None)

    def _unexpected_launch(*args, **kwargs):
        raise AssertionError("launchPipelineExecution should not run when source readiness is blocked")

    monkeypatch.setattr(httpx, "post", _unexpected_launch)

    with pytest.raises(api_main.HTTPException) as exc_info:
        api_main.trigger_premarket()

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["reason"] == "source_readiness_blocked"
    assert "source readiness blocked" in exc_info.value.detail["message"].lower()
    assert exc_info.value.detail["blocking_reasons"] == ["source_readiness_blocked"]
    assert exc_info.value.detail["source_readiness_summary"] == {
        "decision_counts": {"ready": 0, "degraded_allowed": 0, "blocked": 2},
        "blocked_steps": ["macro_collect", "news_collect"],
        "degraded_steps": [],
        "blocked_sources": ["fred", "jin10"],
        "degraded_sources": [],
    }


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
                                "stepKey": "premarket.composite_analysis_pipeline.strategy_card_op",
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
