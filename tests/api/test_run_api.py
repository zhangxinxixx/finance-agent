"""Phase 2 run API tests for TaskRun/TaskStep observability."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.main import (
    api_artifact_detail,
    api_run_artifacts,
    api_run_detail,
    api_run_events,
    api_run_steps,
    api_runs,
)
from apps.api.schemas.common import TaskStatus as ApiTaskStatus
from apps.api.services.task_service import map_task_status_to_api
from database.models.execution import ExecutionEvent, RunArtifact, ensure_execution_tables
from database.models.report import ensure_report_tables
from database.models.task import StepStatus, TaskRun, TaskStatus, TaskStep, ensure_task_tables


def _make_session() -> tuple[Session, sessionmaker]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_task_tables(engine)
    ensure_execution_tables(engine)
    ensure_report_tables(engine)
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


def test_get_run_artifacts_prefers_registry_rows_when_present() -> None:
    session, _ = _make_session()
    run = _seed_run(session)
    step = session.query(TaskStep).filter(TaskStep.task_run_id == run.id).one()
    session.add(
        RunArtifact(
            run_id=run.id,
            task_id=step.id,
            artifact_type="feature_json",
            file_path="storage/features/macro/rollup.json",
            sha256="sha-rollup-001",
        )
    )
    session.commit()

    payload = api_run_artifacts(str(run.id), db=session)

    assert [item["file_path"] for item in payload["artifacts"]] == ["storage/features/macro/rollup.json"]
    assert payload["artifacts"][0]["artifact_type"] == "feature_json"
    assert payload["artifacts"][0]["storage_backend"] == "local_fs"
    assert payload["artifacts"][0]["sha256"] == "sha-rollup-001"


def test_run_detail_and_artifacts_dedupe_registry_lineage_by_file_path() -> None:
    session, _ = _make_session()
    run = _seed_run(session, status=TaskStatus.success)
    first_step = session.query(TaskStep).filter(TaskStep.task_run_id == run.id).one()
    second_step = TaskStep(
        task_run_id=run.id,
        name="macro_publish",
        stage="renderer",
        task_kind="renderer",
        status=StepStatus.success,
        started_at=datetime(2026, 5, 26, 8, 2, tzinfo=UTC),
        finished_at=datetime(2026, 5, 26, 8, 2, 2, tzinfo=UTC),
        duration_ms=2000,
        output_refs=json.dumps(
            [
                {
                    "artifact_id": "step-dup-output",
                    "artifact_type": "feature_json",
                    "file_path": "storage/features/macro/rollup.json",
                }
            ]
        ),
        artifact_refs=json.dumps(
            [
                {
                    "artifact_id": "step-dup-artifact",
                    "artifact_type": "feature_json",
                    "file_path": "storage/features/macro/rollup.json",
                }
            ]
        ),
        output_ref="storage/features/macro/rollup.json",
        source_refs=json.dumps(
            [
                {
                    "source_id": "src-step-dup-002",
                    "source_name": "FRED",
                    "source_type": "api",
                    "data_date": "2026-05-26",
                }
            ]
        ),
    )
    session.add(second_step)
    session.flush()
    first_registry_row = RunArtifact(
        run_id=run.id,
        task_id=first_step.id,
        artifact_type="feature_json",
        file_path="storage/features/macro/rollup.json",
        sha256="sha-keep-001",
        source_refs=json.dumps(
            [
                {
                    "source_id": "src-registry-keep",
                    "source_name": "FRED",
                    "source_type": "api",
                    "data_date": "2026-05-26",
                }
            ]
        ),
    )
    session.add(first_registry_row)
    session.flush()
    second_registry_row = RunArtifact(
        run_id=run.id,
        task_id=second_step.id,
        artifact_type="feature_json",
        file_path="storage/features/macro/rollup.json",
        sha256="sha-drop-002",
        source_refs=json.dumps(
            [
                {
                    "source_id": "src-registry-drop",
                    "source_name": "FRED",
                    "source_type": "api",
                    "data_date": "2026-05-26",
                }
            ]
        ),
    )
    session.add(second_registry_row)
    session.flush()
    session.commit()

    detail_payload = api_run_detail(str(run.id), db=session).model_dump(mode="json")
    artifacts_payload = api_run_artifacts(str(run.id), db=session)

    assert [item["file_path"] for item in artifacts_payload["artifacts"]] == ["storage/features/macro/rollup.json"]
    assert artifacts_payload["artifacts"][0]["artifact_id"] == str(first_registry_row.artifact_id)
    assert artifacts_payload["artifacts"][0]["sha256"] == "sha-keep-001"

    matching_artifacts = [
        item for item in detail_payload["artifact_refs"] if item["file_path"] == "storage/features/macro/rollup.json"
    ]
    assert len(matching_artifacts) == 1
    assert matching_artifacts[0]["artifact_id"] == str(first_registry_row.artifact_id)
    assert matching_artifacts[0]["sha256"] == "sha-keep-001"
    assert {item["source_id"] for item in detail_payload["source_refs"]} == {
        "src-registry-keep",
        "src-registry-drop",
    }

    steps_payload = api_run_steps(str(run.id), db=session)
    step_sources = {
        source["source_id"]
        for step_payload in steps_payload["steps"]
        for source in step_payload["source_refs"]
    }
    assert {"src-001", "src-step-dup-002"}.issubset(step_sources)


def test_get_artifact_detail_returns_registry_context() -> None:
    session, _ = _make_session()
    run = _seed_run(session)
    step = session.query(TaskStep).filter(TaskStep.task_run_id == run.id).one()
    row = RunArtifact(
        run_id=run.id,
        task_id=step.id,
        artifact_type="feature_json",
        file_path="storage/features/macro/rollup.json",
        sha256="sha-rollup-001",
        source_refs=json.dumps(
            [
                {
                    "source_id": "src-registry-001",
                    "source_name": "FRED",
                    "source_type": "api",
                    "data_date": "2026-05-26",
                }
            ]
        ),
        metadata_json=json.dumps(
            {
                "artifact_id": "legacy-art-001",
                "generated_at": "2026-05-26T08:00:05+00:00",
                "label": "macro rollup",
            }
        ),
    )
    session.add(row)
    session.commit()

    payload = api_artifact_detail(str(row.artifact_id), db=session).model_dump(mode="json")

    assert payload["run_id"] == str(run.id)
    assert payload["snapshot_id"] == "snap-001"
    assert payload["task_id"] == str(step.id)
    assert payload["task_name"] == "macro_collect"
    assert payload["stage"] == "collector"
    assert payload["input_refs"][0]["artifact_id"] == "art-in-001"
    assert payload["input_refs"][0]["artifact_type"] == "raw_file"
    assert payload["artifact"]["artifact_id"] == str(row.artifact_id)
    assert payload["artifact"]["artifact_type"] == "feature_json"
    assert payload["artifact"]["file_path"] == "storage/features/macro/rollup.json"
    assert payload["artifact"]["storage_backend"] == "local_fs"
    assert payload["artifact_refs"][0]["artifact_id"] == str(row.artifact_id)
    assert any(item["artifact_id"] == "art-out-001" for item in payload["artifact_refs"])
    assert any(item["artifact_id"] == "art-visual-001" for item in payload["artifact_refs"])
    assert {item["source_id"] for item in payload["source_refs"]} == {"src-registry-001", "src-001"}
    assert payload["metadata"]["label"] == "macro rollup"


def test_get_artifact_detail_falls_back_to_registry_metadata_snapshot_id() -> None:
    session, _ = _make_session()
    run = _seed_run(session)
    run.snapshot_id = None
    step = session.query(TaskStep).filter(TaskStep.task_run_id == run.id).one()
    row = RunArtifact(
        run_id=run.id,
        task_id=step.id,
        artifact_type="feature_json",
        file_path="storage/features/macro/fallback.json",
        sha256="sha-fallback-001",
        metadata_json=json.dumps(
            {
                "artifact_id": "fallback-art-001",
                "snapshot_id": "snap-metadata-001",
            }
        ),
    )
    session.add(row)
    session.commit()

    payload = api_artifact_detail(str(row.artifact_id), db=session).model_dump(mode="json")

    assert payload["run_id"] == str(run.id)
    assert payload["snapshot_id"] == "snap-metadata-001"
    assert payload["metadata"]["snapshot_id"] == "snap-metadata-001"


def test_get_artifact_detail_warns_when_registry_file_is_missing() -> None:
    session, _ = _make_session()
    run = _seed_run(session)
    step = session.query(TaskStep).filter(TaskStep.task_run_id == run.id).one()
    row = RunArtifact(
        run_id=run.id,
        task_id=step.id,
        artifact_type="feature_json",
        file_path="storage/features/macro/missing.json",
        sha256="sha-missing-001",
    )
    session.add(row)
    session.commit()

    payload = api_artifact_detail(str(row.artifact_id), db=session).model_dump(mode="json")

    missing_warnings = [warning for warning in payload["warnings"] if warning["code"] == "artifact-missing-file"]
    assert missing_warnings
    assert missing_warnings[0]["field"] == "storage/features/macro/missing.json"


def test_get_artifact_detail_warns_when_registry_metadata_snapshot_drifted() -> None:
    session, _ = _make_session()
    run = _seed_run(session)
    step = session.query(TaskStep).filter(TaskStep.task_run_id == run.id).one()
    row = RunArtifact(
        run_id=run.id,
        task_id=step.id,
        artifact_type="feature_json",
        file_path="storage/features/macro/drift.json",
        sha256="sha-drift-001",
        metadata_json=json.dumps(
            {
                "artifact_id": "drift-art-001",
                "snapshot_id": "snap-drift-001",
                "input_snapshot_ids": {
                    "analysis_snapshot": "snap-drift-001",
                    "coordinator": "snap-drift-001",
                },
            }
        ),
    )
    session.add(row)
    session.commit()

    payload = api_artifact_detail(str(row.artifact_id), db=session).model_dump(mode="json")

    warning_codes = {item["code"] for item in payload["warnings"]}
    assert payload["snapshot_id"] == "snap-001"
    assert payload["metadata"]["snapshot_id"] == "snap-drift-001"
    assert "artifact-lineage-snapshot-mismatch" in warning_codes
    assert "artifact-lineage-analysis_snapshot-mismatch" in warning_codes
    assert "artifact-lineage-coordinator-mismatch" in warning_codes


def test_get_artifact_detail_raises_404_for_missing_registry_row() -> None:
    session, _ = _make_session()

    with pytest.raises(HTTPException) as exc_info:
        api_artifact_detail("11111111-1111-1111-1111-111111111111", db=session)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Artifact not found"


def test_get_run_detail_maps_public_status() -> None:
    session, _ = _make_session()
    run = _seed_run(session, status=TaskStatus.stale)

    payload = api_run_detail(str(run.id), db=session).model_dump(mode="json")
    assert payload["run_id"] == str(run.id)
    assert payload["task_id"] == str(run.id)
    assert payload["status"] == "degraded"
    assert payload["current_stage"] == "analysis"


def test_run_list_and_detail_include_registry_artifact_and_source_refs() -> None:
    session, _ = _make_session()
    run = _seed_run(session, status=TaskStatus.success)
    step = session.query(TaskStep).filter(TaskStep.task_run_id == run.id).one()
    registry_row = RunArtifact(
        run_id=run.id,
        task_id=step.id,
        artifact_type="feature_json",
        file_path="storage/features/macro/rollup.json",
        sha256="sha-rollup-001",
        source_refs=json.dumps(
            [
                {
                    "source_id": "src-registry-001",
                    "source_name": "FRED",
                    "source_type": "api",
                    "data_date": "2026-05-26",
                }
            ]
        ),
    )
    session.add(registry_row)
    session.commit()

    detail_payload = api_run_detail(str(run.id), db=session).model_dump(mode="json")
    list_payload = api_runs(db=session)

    for payload in (detail_payload, list_payload["runs"][0]):
        assert any(item["artifact_id"] == str(registry_row.artifact_id) for item in payload["artifact_refs"])
        assert any(item["file_path"] == "storage/features/macro/rollup.json" for item in payload["artifact_refs"])
        assert any(item["source_id"] == "src-registry-001" for item in payload["source_refs"])
        assert all(item["artifact_id"] != "art-out-001" for item in payload["artifact_refs"])

    step_payload = api_run_steps(str(run.id), db=session)["steps"][0]
    assert any(item["artifact_id"] == "art-out-001" for item in step_payload["artifact_refs"])


def test_run_detail_reads_structured_registry_source_refs_without_legacy_text() -> None:
    session, _ = _make_session()
    run = _seed_run(session, status=TaskStatus.success)
    step = session.query(TaskStep).filter(TaskStep.task_run_id == run.id).one()
    registry_row = RunArtifact(
        run_id=run.id,
        task_id=step.id,
        artifact_type="feature_json",
        file_path="storage/features/macro/structured-source-refs.json",
        sha256="sha-structured-source-refs",
        source_refs_data=[
            {
                "source_id": "src-structured-001",
                "source_name": "FRED",
                "source_type": "api",
                "data_date": "2026-05-26",
                "endpoint": "https://api.stlouisfed.org/fred/series/observations",
            }
        ],
        source_refs=None,
    )
    session.add(registry_row)
    session.commit()

    detail_payload = api_run_detail(str(run.id), db=session).model_dump(mode="json")
    artifact_payload = api_artifact_detail(str(registry_row.artifact_id), db=session).model_dump(mode="json")

    assert any(item["source_id"] == "src-structured-001" for item in detail_payload["source_refs"])
    assert any(item["source_id"] == "src-structured-001" for item in artifact_payload["source_refs"])
    structured_source = next(item for item in artifact_payload["source_refs"] if item["source_id"] == "src-structured-001")
    assert structured_source["endpoint"] == "https://api.stlouisfed.org/fred/series/observations"


def test_run_detail_prefers_registry_lineage_over_step_implicit_refs() -> None:
    session, _ = _make_session()
    run = _seed_run(session, status=TaskStatus.success)
    step = session.query(TaskStep).filter(TaskStep.task_run_id == run.id).one()
    registry_row = RunArtifact(
        run_id=run.id,
        task_id=step.id,
        artifact_type="feature_json",
        file_path="storage/features/macro/registry-authoritative.json",
        sha256="sha-registry-authoritative",
        source_refs_data=[
            {
                "source_id": "src-registry-authoritative",
                "source_name": "FRED",
                "source_type": "api",
                "data_date": "2026-05-26",
            }
        ],
        source_refs=None,
    )
    session.add(registry_row)
    session.commit()

    detail_payload = api_run_detail(str(run.id), db=session).model_dump(mode="json")
    list_payload = api_runs(db=session)["runs"][0]

    for payload in (detail_payload, list_payload):
        assert [item["artifact_id"] for item in payload["artifact_refs"]] == [str(registry_row.artifact_id)]
        assert [item["source_id"] for item in payload["source_refs"]] == ["src-registry-authoritative"]

    step_payload = api_run_steps(str(run.id), db=session)["steps"][0]
    assert any(item["artifact_id"] == "art-out-001" for item in step_payload["artifact_refs"])
    assert any(item["source_id"] == "src-001" for item in step_payload["source_refs"])


def test_get_run_events_returns_sorted_timeline() -> None:
    session, _ = _make_session()
    run = _seed_run(session, status=TaskStatus.success)
    step = session.query(TaskStep).filter(TaskStep.task_run_id == run.id).one()
    session.add_all(
        [
            ExecutionEvent(
                run_id=run.id,
                task_id=None,
                event_type="RUN_STARTED",
                payload=json.dumps({"task_name": "agent_task"}),
                created_at=datetime(2026, 5, 26, 8, 0, tzinfo=UTC),
            ),
            ExecutionEvent(
                run_id=run.id,
                task_id=step.id,
                event_type="TASK_FAILED",
                payload=json.dumps({"step_name": step.name, "error_message": "upstream blocked"}),
                created_at=datetime(2026, 5, 26, 8, 0, 3, tzinfo=UTC),
            ),
        ]
    )
    session.commit()

    payload = api_run_events(str(run.id), db=session)

    assert payload["run_id"] == str(run.id)
    assert [event["event_type"] for event in payload["events"]] == ["RUN_STARTED", "TASK_FAILED"]
    assert payload["events"][1]["task_id"] == str(step.id)
    assert payload["events"][1]["payload"]["error_message"] == "upstream blocked"
