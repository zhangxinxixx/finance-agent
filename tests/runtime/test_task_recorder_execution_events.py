from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.runtime.artifact_storage import LOCAL_FS_STORAGE_BACKEND, LocalFileSystemArtifactStorage
from apps.runtime import task_recorder as task_recorder_module
from apps.runtime.task_recorder import TaskRecorder
from database.models.execution import ExecutionEvent, RunArtifact, ensure_execution_tables
from database.models.task import ensure_task_tables


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
