from __future__ import annotations

import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.runtime.artifact_storage import LOCAL_FS_STORAGE_BACKEND, LocalFileSystemArtifactStorage
from apps.runtime import task_recorder as task_recorder_module
from apps.runtime.task_recorder import TaskRecorder
from database.models.execution import ExecutionEvent, RunArtifact, ensure_execution_tables
from database.models.task import TaskRun, TaskStatus, ensure_task_tables


def _make_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_task_tables(engine)
    ensure_execution_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_task_recorder_emits_run_and_artifact_events(monkeypatch) -> None:
    factory = _make_factory()
    monkeypatch.setattr(task_recorder_module, "SessionLocal", factory)

    with TaskRecorder(task_type="macro_collect", task_name="FRED 采集", trade_date="2026-06-18") as rec:
        rec.step("collect_fred", status="running", stage="collector", task_kind="collector")
        rec.step(
            "collect_fred",
            status="success",
            stage="collector",
            task_kind="collector",
            output_refs=[
                {
                    "artifact_id": "art-001",
                    "artifact_type": "raw_file",
                    "file_path": "storage/raw/macro/fred.json",
                }
            ],
            output_ref="storage/raw/macro/fred.json",
        )

    with factory() as session:
        events = session.query(ExecutionEvent).order_by(ExecutionEvent.created_at.asc()).all()
        artifacts = session.query(RunArtifact).order_by(RunArtifact.created_at.asc()).all()

    event_types = [event.event_type for event in events]
    assert "RUN_STARTED" in event_types
    assert "RUN_STATUS_CHANGED" in event_types
    assert "TASK_STARTED" in event_types
    assert "TASK_STATUS_CHANGED" in event_types
    assert "TASK_FINISHED" in event_types
    assert "ARTIFACT_WRITTEN" in event_types
    assert event_types.count("ARTIFACT_WRITTEN") == 1
    assert event_types[-1] == "RUN_FINISHED"
    assert [artifact.file_path for artifact in artifacts] == ["storage/raw/macro/fred.json"]
    assert artifacts[0].artifact_type == "raw_file"
    assert artifacts[0].storage_backend == LOCAL_FS_STORAGE_BACKEND


def test_task_recorder_emits_failed_event(monkeypatch) -> None:
    factory = _make_factory()
    monkeypatch.setattr(task_recorder_module, "SessionLocal", factory)

    try:
        with TaskRecorder(task_type="macro_collect", task_name="FRED 采集") as rec:
            rec.step("collect_fred", status="running", stage="collector")
            raise RuntimeError("collector exploded")
    except RuntimeError:
        pass

    with factory() as session:
        events = session.query(ExecutionEvent).order_by(ExecutionEvent.created_at.asc()).all()

    event_types = [event.event_type for event in events]
    assert "TASK_STARTED" in event_types
    assert "TASK_STATUS_CHANGED" in event_types
    assert "RUN_FAILED" in event_types


def test_task_recorder_rolls_up_a_blocked_step_to_a_blocked_run(monkeypatch) -> None:
    factory = _make_factory()
    monkeypatch.setattr(task_recorder_module, "SessionLocal", factory)

    with TaskRecorder(task_type="quality_gate", task_name="Quality Gate") as rec:
        rec.step("validate_inputs", status="blocked", stage="quality_gate", error="source unavailable")

    with factory() as session:
        run = session.query(TaskRun).one()

    assert run.status == TaskStatus.blocked


def test_task_recorder_registers_blocked_preview_artifact(monkeypatch) -> None:
    factory = _make_factory()
    monkeypatch.setattr(task_recorder_module, "SessionLocal", factory)

    with TaskRecorder(task_type="event_sla", task_name="Event SLA", trade_date="2026-07-08") as rec:
        rec.step(
            "build_trading_strategy",
            status="blocked",
            stage="event_sla",
            output_refs=[
                {
                    "artifact_type": "structured_json",
                    "path": "storage/outputs/event_sla/2026-07-08/preview/trading_strategy.json",
                    "quality_status": "preview",
                    "usable_for": ["observation"],
                    "blocked_for": ["actionable_strategy"],
                    "execution_mode": "blocked_by_quality_gate",
                }
            ],
            source_refs=[
                {
                    "source": "jin10_report",
                    "source_ref": "event:preview",
                    "data_date": "2026-07-08",
                }
            ],
        )

    with factory() as session:
        artifact = session.query(RunArtifact).one()
        event = session.query(ExecutionEvent).filter(ExecutionEvent.event_type == "ARTIFACT_WRITTEN").one()

    assert artifact.artifact_metadata["quality_status"] == "preview"
    assert artifact.artifact_metadata["usable_for"] == ["observation"]
    assert artifact.artifact_metadata["blocked_for"] == ["actionable_strategy"]
    assert artifact.artifact_metadata["execution_mode"] == "blocked_by_quality_gate"
    assert json.loads(event.payload or "{}")["step_status"] == "blocked"


def test_task_recorder_registers_skipped_reused_artifact(monkeypatch) -> None:
    factory = _make_factory()
    monkeypatch.setattr(task_recorder_module, "SessionLocal", factory)

    with TaskRecorder(task_type="event_sla", task_name="Event SLA", trade_date="2026-07-08") as rec:
        rec.step(
            "parse_content",
            status="skipped",
            stage="event_sla",
            output_refs=[
                {
                    "artifact_type": "parsed_file",
                    "path": "storage/parsed/cme/2026-07-08/run-1/cme_parse_result.json",
                    "quality_status": "reused",
                    "usable_for": ["source_evidence"],
                    "blocked_for": [],
                    "execution_mode": "reused_existing_artifact",
                }
            ],
            source_refs=[
                {
                    "source": "cme_gold_options_bulletin",
                    "source_ref": "event:cme-1",
                    "data_date": "2026-07-08",
                }
            ],
        )

    with factory() as session:
        artifact = session.query(RunArtifact).one()

    assert artifact.artifact_metadata["quality_status"] == "reused"
    assert artifact.artifact_metadata["execution_mode"] == "reused_existing_artifact"


def test_local_artifact_storage_supports_relative_and_absolute_paths(tmp_path) -> None:
    storage = LocalFileSystemArtifactStorage(root=tmp_path)
    relative_path = "storage/features/demo/output.json"
    relative_target = tmp_path / relative_path
    relative_target.parent.mkdir(parents=True, exist_ok=True)
    relative_target.write_text("{\"ok\": true}", encoding="utf-8")

    absolute_target = tmp_path / "absolute.json"
    absolute_target.write_text("{\"value\": 1}", encoding="utf-8")

    assert storage.exists(relative_path) is True
    assert storage.resolve(relative_path) == relative_target
    assert storage.resolve(str(absolute_target)) == absolute_target
    assert storage.compute_sha256(relative_path) is not None
    assert storage.compute_sha256(str(absolute_target)) is not None
