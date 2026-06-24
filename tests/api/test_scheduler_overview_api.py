from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.services.scheduler_service import get_scheduler_overview
from database.models.task import StepStatus, TaskRun, TaskStatus, TaskStep, ensure_task_tables


def _make_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_task_tables(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return factory()


def _seed_run(
    session: Session,
    *,
    name: str,
    task_type: str,
    trade_date: str,
    status: TaskStatus = TaskStatus.success,
) -> TaskRun:
    run = TaskRun(
        name=name,
        task_type=task_type,
        status=status,
        current_stage="collector",
        progress=1.0,
        trade_date=trade_date,
        started_at=datetime(2026, 6, 18, 8, 0, tzinfo=UTC),
        ended_at=datetime(2026, 6, 18, 8, 5, tzinfo=UTC),
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def _seed_step(
    session: Session,
    *,
    run: TaskRun,
    name: str,
    step_order: int,
    status: StepStatus = StepStatus.success,
) -> TaskStep:
    step = TaskStep(
        task_run_id=run.id,
        name=name,
        stage=name,
        task_kind=run.task_type,
        status=status,
        step_order=step_order,
    )
    session.add(step)
    session.commit()
    session.refresh(step)
    return step


def test_scheduler_overview_includes_input_source_matrix_and_log_coverage(monkeypatch) -> None:
    session = _make_session()
    macro_run = _seed_run(
        session,
        name="Macro collect backfill",
        task_type="macro_collect",
        trade_date="2026-06-18",
    )

    monkeypatch.setattr(
        "apps.api.services.scheduler_service.get_data_source_statuses",
        lambda: {
            "sources": [
                {
                    "source_key": "fred",
                    "source_name": "FRED",
                    "source_group": "macro",
                    "source_type": "api",
                    "access_method": "fred_api",
                    "status": "ok",
                    "configured": True,
                    "raw_ingested": True,
                    "parsed": True,
                    "analysis_ready": True,
                    "health_state": "healthy",
                    "readiness_state": "ready",
                    "gate_state": "open",
                    "gating_reason": None,
                    "latest_raw_time": "2026-06-18T08:00:00+00:00",
                    "latest_parsed_time": "2026-06-18T08:04:00+00:00",
                    "metadata": {
                        "frontend_label": "FRED 官方宏观主源",
                        "latest_raw_ref": {
                            "path": "storage/raw/macro/fred/2026-06-18/fred.json",
                            "published_at": "2026-06-18T08:00:00+00:00",
                        },
                        "latest_artifact_mtime": "2026-06-18T08:04:00+00:00",
                        "polling_strategy": {"mode": "scheduled_batch", "cadence": "daily"},
                        "database_tables": ["data_source_status", "analysis_snapshots.macro"],
                    },
                },
                {
                    "source_key": "jin10_flash",
                    "source_name": "Jin10 Flash",
                    "source_group": "news",
                    "source_type": "api",
                    "access_method": "jin10_mcp_list_flash",
                    "status": "ok",
                    "configured": True,
                    "raw_ingested": True,
                    "parsed": False,
                    "analysis_ready": False,
                    "health_state": "healthy",
                    "readiness_state": "degraded",
                    "gate_state": "degraded",
                    "gating_reason": None,
                    "latest_raw_time": "2026-06-18T08:03:00+00:00",
                    "latest_parsed_time": None,
                    "metadata": {
                        "frontend_label": "Jin10 实时快讯",
                        "latest_raw_ref": {
                            "path": "storage/outputs/jin10/flash_cache.json",
                            "published_at": "2026-06-18T08:03:00+00:00",
                        },
                        "latest_artifact_mtime": "2026-06-18T08:03:00+00:00",
                        "notes": "高频缓存源",
                    },
                },
            ]
        },
    )
    monkeypatch.setattr("apps.api.services.scheduler_service._build_task_stats", lambda db, since, now: {"success": 1, "failed": 0, "running": 0, "pending": 0, "other": 0})
    monkeypatch.setattr("apps.api.services.scheduler_service._build_daily_summary", lambda db, since, now: [])
    monkeypatch.setattr("apps.api.services.scheduler_service._get_data_source_status", lambda db: {"ok": 2, "error": 0, "not_connected": 0, "total": 2})
    monkeypatch.setattr("apps.api.services.scheduler_service._get_cron_job_status", lambda: [])
    monkeypatch.setattr("apps.api.services.scheduler_service._get_artifacts_summary", lambda: {"today_count": 0, "recent_outputs": []})
    monkeypatch.setattr("apps.api.services.scheduler_service._get_flash_stats", lambda: {"total": 0, "key_events": 0, "unanalyzed_key_events": 0})

    payload = get_scheduler_overview(session, days=30, limit=20)

    assert payload["input_source_summary"] == {"total": 2, "connected": 1, "data_only": 1, "waiting": 0}
    assert payload["summary"]["input_sources_connected"] == 1
    assert payload["summary"]["input_sources_data_only"] == 1

    by_key = {item["source_key"]: item for item in payload["input_source_matrix"]}
    fred = by_key["fred"]
    assert fred["source_label"] == "FRED 官方宏观主源"
    assert fred["task_log_status"] == "connected"
    assert "macro_collect" in fred["expected_task_types"]
    assert fred["latest_task_run"]["run_id"] == str(macro_run.id)
    assert fred["recent_task_types"] == ["macro_collect"]

    flash = by_key["jin10_flash"]
    assert flash["task_log_status"] == "data_only"
    assert flash["latest_task_run"] is None
    assert flash["latest_artifact"] == "storage/outputs/jin10/flash_cache.json"


def test_scheduler_overview_matches_jin10_refresh_tasks_to_input_sources(monkeypatch) -> None:
    session = _make_session()
    flash_run = _seed_run(
        session,
        name="Jin10 快讯刷新",
        task_type="jin10_refresh_jin10_flash",
        trade_date="2026-06-18",
    )

    monkeypatch.setattr(
        "apps.api.services.scheduler_service.get_data_source_statuses",
        lambda: {
            "sources": [
                {
                    "source_key": "jin10_flash",
                    "source_name": "Jin10 Flash",
                    "source_group": "news",
                    "source_type": "api",
                    "access_method": "jin10_mcp_list_flash",
                    "status": "ok",
                    "configured": True,
                    "raw_ingested": True,
                    "parsed": False,
                    "analysis_ready": False,
                    "health_state": "healthy",
                    "readiness_state": "ready",
                    "gate_state": "open",
                    "gating_reason": None,
                    "latest_raw_time": "2026-06-18T08:00:00+00:00",
                    "latest_parsed_time": None,
                    "metadata": {"frontend_label": "Jin10 实时快讯"},
                }
            ]
        },
    )
    monkeypatch.setattr("apps.api.services.scheduler_service._build_task_stats", lambda db, since, now: {"success": 1, "failed": 0, "running": 0, "pending": 0, "other": 0})
    monkeypatch.setattr("apps.api.services.scheduler_service._build_daily_summary", lambda db, since, now: [])
    monkeypatch.setattr("apps.api.services.scheduler_service._get_data_source_status", lambda db: {"ok": 1, "error": 0, "not_connected": 0, "total": 1})
    monkeypatch.setattr("apps.api.services.scheduler_service._get_cron_job_status", lambda: [])
    monkeypatch.setattr("apps.api.services.scheduler_service._get_artifacts_summary", lambda: {"today_count": 0, "recent_outputs": []})
    monkeypatch.setattr("apps.api.services.scheduler_service._get_flash_stats", lambda: {"total": 0, "key_events": 0, "unanalyzed_key_events": 0})

    payload = get_scheduler_overview(session, days=30, limit=20)

    item = payload["input_source_matrix"][0]
    assert item["source_key"] == "jin10_flash"
    assert item["task_log_status"] == "connected"
    assert item["latest_task_run"]["run_id"] == str(flash_run.id)
    assert item["recent_task_types"] == ["jin10_refresh_jin10_flash"]


def test_scheduler_overview_matches_premarket_step_logs_to_news_sources(monkeypatch) -> None:
    session = _make_session()
    premarket_run = _seed_run(
        session,
        name="主流程运行",
        task_type="premarket",
        trade_date="2026-06-21",
        status=TaskStatus.degraded,
    )
    _seed_step(session, run=premarket_run, name="news_collect", step_order=0)
    _seed_step(session, run=premarket_run, name="news_feature", step_order=1)
    _seed_step(session, run=premarket_run, name="news_brief", step_order=2)

    monkeypatch.setattr(
        "apps.api.services.scheduler_service.get_data_source_statuses",
        lambda: {
            "sources": [
                {
                    "source_key": "gdelt_news",
                    "source_name": "GDELT News",
                    "source_group": "news",
                    "source_type": "api",
                    "access_method": "gdelt",
                    "status": "ok",
                    "configured": True,
                    "raw_ingested": True,
                    "parsed": True,
                    "analysis_ready": False,
                    "health_state": "healthy",
                    "readiness_state": "ready",
                    "gate_state": "open",
                    "gating_reason": None,
                    "latest_raw_time": "2026-06-21T08:03:00+00:00",
                    "latest_parsed_time": "2026-06-21T08:04:00+00:00",
                    "metadata": {"frontend_label": "GDELT 新闻流"},
                }
            ]
        },
    )
    monkeypatch.setattr("apps.api.services.scheduler_service._build_task_stats", lambda db, since, now: {"success": 0, "failed": 1, "running": 0, "pending": 0, "other": 0})
    monkeypatch.setattr("apps.api.services.scheduler_service._build_daily_summary", lambda db, since, now: [])
    monkeypatch.setattr("apps.api.services.scheduler_service._get_data_source_status", lambda db: {"ok": 1, "error": 0, "not_connected": 0, "total": 1})
    monkeypatch.setattr("apps.api.services.scheduler_service._get_cron_job_status", lambda: [])
    monkeypatch.setattr("apps.api.services.scheduler_service._get_artifacts_summary", lambda: {"today_count": 0, "recent_outputs": []})
    monkeypatch.setattr("apps.api.services.scheduler_service._get_flash_stats", lambda: {"total": 0, "key_events": 0, "unanalyzed_key_events": 0})

    payload = get_scheduler_overview(session, days=30, limit=20)

    item = payload["input_source_matrix"][0]
    assert item["source_key"] == "gdelt_news"
    assert item["task_log_status"] == "connected"
    assert item["latest_task_run"]["run_id"] == str(premarket_run.id)
    assert item["recent_task_types"] == ["news_collect", "news_feature", "news_brief"]
