"""Read-only file validation retained for warehouse field extraction."""

import hashlib
import uuid
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from apps.data_layer.structured_artifacts import _inspect_artifact, persist_structured_artifact, DEFAULT_MAX_BYTES
from apps.runtime.artifact_registry import register_step_artifacts
from apps.runtime.artifact_storage import LocalFileSystemArtifactStorage
from database.models.execution import RunArtifact, ensure_execution_tables
from database.models.task import TaskRun, TaskStep, TaskStatus, StepStatus, ensure_task_tables


def make_row(tmp_path, content):
    target = tmp_path / "storage/features/test/2026-10-05/run/input.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    body = content.encode() if isinstance(content, str) else content
    target.write_bytes(body)
    return (
        RunArtifact(
            run_id=uuid.uuid4(),
            artifact_type="feature_json",
            file_path="features/test/2026-10-05/run/input.json",
            sha256=hashlib.sha256(body).hexdigest(),
            storage_backend="local_fs",
        ),
        target,
        LocalFileSystemArtifactStorage(root=tmp_path),
    )


def test_file_validation_returns_transient_body_without_mutating_registry(tmp_path):
    row, _, storage = make_row(tmp_path, '{"title":"黄金","status":"degraded"}')
    result, body, schema = _inspect_artifact(row, storage, max_bytes=DEFAULT_MAX_BYTES)
    assert result.status == "persisted" and body == {"title": "黄金", "status": "degraded"} and schema is None
    assert row.structured_payload is row.structured_payload_sha256 is row.structured_status is None
    with pytest.raises(ValueError, match="whole_json_storage_disabled"):
        persist_structured_artifact(row, storage)
    assert row.structured_payload is None


@pytest.mark.parametrize(
    "body,error",
    [
        ("{broken", "STRUCTURED_JSON_INVALID"),
        ('{"x":NaN}', "STRUCTURED_JSON_NONFINITE"),
        ('{"x":1e999}', "STRUCTURED_JSON_NONFINITE"),
        ("42", "STRUCTURED_JSON_ROOT_UNSUPPORTED"),
        (b"\xff", "STRUCTURED_UTF8_INVALID"),
        ('{"apiKey":"private-fixture"}', "STRUCTURED_SENSITIVE_CONTENT"),
        ('{"x":1,"x":2}', "STRUCTURED_JSON_INVALID"),
        ('{"x":"\\u0000"}', "STRUCTURED_JSON_NUL"),
        ('{"x":"\\ud800"}', "STRUCTURED_JSON_NUL"),
    ],
)
def test_bad_archive_cannot_become_warehouse_input(tmp_path, body, error):
    row, _, storage = make_row(tmp_path, body)
    result, parsed, _ = _inspect_artifact(row, storage, max_bytes=DEFAULT_MAX_BYTES)
    assert result.error == error and parsed is None and row.structured_payload is None


def test_archive_sha_and_path_guard(tmp_path):
    row, target, storage = make_row(tmp_path, "{}")
    row.sha256 = "0" * 64
    assert _inspect_artifact(row, storage, max_bytes=DEFAULT_MAX_BYTES)[0].error == "STRUCTURED_FILE_SHA_MISMATCH"
    row.sha256 = hashlib.sha256(b"{}").hexdigest()
    target.unlink()
    other = tmp_path / "outside.json"
    other.write_text("{}")
    target.symlink_to(other)
    assert _inspect_artifact(row, storage, max_bytes=DEFAULT_MAX_BYTES)[0].error == "STRUCTURED_PATH_ESCAPE"


def test_registry_registers_metadata_only_in_caller_transaction(tmp_path, monkeypatch):
    engine = create_engine("sqlite://")
    ensure_task_tables(engine)
    ensure_execution_tables(engine)
    with Session(engine) as db:
        run = TaskRun(name="test", status=TaskStatus.pending)
        db.add(run)
        db.flush()
        step = TaskStep(task_run_id=run.id, name="features", status=StepStatus.pending)
        db.add(step)
        db.flush()
        path = f"storage/features/test/2026-10-05/{run.id}/input.json"
        file = tmp_path / path
        file.parent.mkdir(parents=True)
        file.write_text('{"ready":false}')
        monkeypatch.setattr(
            "apps.runtime.artifact_registry.get_artifact_storage",
            lambda backend_name=None: LocalFileSystemArtifactStorage(root=tmp_path),
        )
        rows = register_step_artifacts(
            db, run_id=str(run.id), step=step, output_refs=[{"artifact_type": "feature_json", "file_path": path}]
        )
        assert len(rows) == 1 and rows[0].structured_payload is rows[0].structured_status is None
        assert rows[0].task_id == step.id and rows[0].run_id == run.id and rows[0].sha256
        db.rollback()
        assert db.query(RunArtifact).count() == 0
