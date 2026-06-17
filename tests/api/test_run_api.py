"""Phase 2 run API tests for TaskRun/TaskStep observability."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.main import api_run_artifacts, api_run_detail, api_run_steps, api_runs
from apps.api.schemas.common import TaskStatus as ApiTaskStatus
from apps.api.services.task_service import map_task_status_to_api
from database.models.task import StepStatus, TaskRun, TaskStatus, TaskStep, ensure_task_tables


def _make_session() -> tuple[Session, sessionmaker]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_task_tables(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return factory(), factory


def _seed_run(session: Session, *, status: TaskStatus = TaskStatus.pending) -> TaskRun:
    run = TaskRun(
        name="agent_task",
        task_type="agent_task",
        workspace_id="workspace-001",
        status=status,
        current_stage="analysis",
        progress=0.5,
        started_at=datetime(2026, 5, 26, 8, 0, tzinfo=UTC),
        ended_at=datetime(2026, 5, 26, 8, 1, tzinfo=UTC),
        total_cost_usd=1.25,
        token_in=120,
        token_out=240,
        snapshot_id="snap-001",
        final_result_id="final-001",
        error_summary="run degraded" if status == TaskStatus.stale else None,
        trade_date="2026-05-26",
    )
    session.add(run)
    session.flush()

    session.add(
        TaskStep(
            task_run_id=run.id,
            name="macro_collect",
            stage="collector",
            task_kind="collector",
            status=StepStatus.blocked,
            started_at=datetime(2026, 5, 26, 8, 0, tzinfo=UTC),
            finished_at=datetime(2026, 5, 26, 8, 0, 3, tzinfo=UTC),
            duration_ms=3000,
            input_refs=json.dumps(
                [
                    {
                        "artifact_id": "art-in-001",
                        "artifact_type": "raw_file",
                        "file_path": "storage/raw/macro/input.json",
                    }
                ]
            ),
            output_refs=json.dumps(
                [
                    {
                        "artifact_id": "art-out-001",
                        "artifact_type": "parsed_file",
                        "file_path": "storage/parsed/macro/output.json",
                    }
                ]
            ),
            artifact_refs=json.dumps(
                [
                    {
                        "artifact_id": "art-visual-001",
                        "artifact_type": "visual_html",
                        "file_path": "storage/outputs/reports/2026-05-26/run-001/visual.html",
                    }
                ]
            ),
            source_refs=json.dumps(
                [
                    {
                        "source_id": "src-001",
                        "source_name": "FRED",
                        "source_type": "api",
                        "data_date": "2026-05-26",
                    }
                ]
            ),
            output_ref="storage/parsed/macro/output.json",
            error="upstream blocked",
            error_type="upstream_failed",
            retry_count=2,
        )
    )
    session.commit()
    session.refresh(run)
    return run


def test_map_task_status_to_api_covers_phase2_states() -> None:
    assert map_task_status_to_api(TaskStatus.pending) == ApiTaskStatus.queued
    assert map_task_status_to_api(TaskStatus.blocked) == ApiTaskStatus.needs_review
    assert map_task_status_to_api(TaskStatus.stale) == ApiTaskStatus.degraded


def test_list_runs_uses_default_limit_20() -> None:
    session, _ = _make_session()
    for _ in range(25):
        _seed_run(session)

    payload = api_runs(db=session)

    assert len(payload["runs"]) == 20


def test_get_run_steps_returns_refs_and_retry_fields() -> None:
    session, _ = _make_session()
    run = _seed_run(session)

    payload = api_run_steps(str(run.id), db=session)
    assert payload["run_id"] == str(run.id)
    step = payload["steps"][0]
    assert step["status"] == "needs_review"
    assert step["input_refs"][0]["artifact_type"] == "raw_file"
    assert step["output_refs"][0]["artifact_type"] == "parsed_file"
    assert step["source_refs"][0]["source_id"] == "src-001"
    assert step["error_type"] == "upstream_failed"
    assert step["retry_count"] == 2


def test_get_run_artifacts_aggregates_output_refs_and_output_ref() -> None:
    session, _ = _make_session()
    run = _seed_run(session)

    payload = api_run_artifacts(str(run.id), db=session)
    artifact_ids = {item["artifact_id"] for item in payload["artifacts"]}
    assert {"art-out-001", "art-visual-001"} <= artifact_ids
    assert any(item["file_path"] == "storage/parsed/macro/output.json" for item in payload["artifacts"])


def test_get_run_detail_maps_public_status() -> None:
    session, _ = _make_session()
    run = _seed_run(session, status=TaskStatus.stale)

    payload = api_run_detail(str(run.id), db=session).model_dump(mode="json")
    assert payload["run_id"] == str(run.id)
    assert payload["task_id"] == str(run.id)
    assert payload["status"] == "degraded"
    assert payload["current_stage"] == "analysis"
