"""Runtime aliases must preserve hashes without escaping configured storage."""
import hashlib
import uuid

import pytest

from apps.data_layer.structured_artifacts import _inspect_artifact, DEFAULT_MAX_BYTES
from apps.runtime.artifact_storage import LocalFileSystemArtifactStorage
from apps.runtime.storage_paths import project_artifact_path, remap_storage_path
from database.models.execution import RunArtifact


def test_explicit_runtime_storage_alias_and_missing_file_do_not_read_legacy(tmp_path, monkeypatch):
    app = tmp_path / "app"
    runtime = tmp_path / "runtime"
    legacy = tmp_path / "legacy"
    app.mkdir()
    runtime.mkdir()
    legacy.mkdir()
    (app / "storage").symlink_to(runtime, target_is_directory=True)
    rel = "features/news/2026-10-10/run/events.json"
    old = legacy / rel
    new = runtime / rel
    old.parent.mkdir(parents=True)
    new.parent.mkdir(parents=True)
    old.write_text('{"value":"old"}')
    new.write_text('{"value":"new"}')
    monkeypatch.setenv("FINANCE_AGENT_STORAGE_ROOT", str(runtime))
    monkeypatch.setenv("FINANCE_AGENT_LEGACY_STORAGE_ROOTS", str(legacy))
    row = RunArtifact(run_id=uuid.uuid4(), artifact_type="feature_json", file_path=str(old),
                      sha256=hashlib.sha256(new.read_bytes()).hexdigest(), storage_backend="local_fs")
    storage = LocalFileSystemArtifactStorage(root=app)
    result, body, _ = _inspect_artifact(row, storage, max_bytes=DEFAULT_MAX_BYTES)
    assert result.status == "persisted" and body == {"value": "new"}
    assert str(project_artifact_path(old, project_root=app)).startswith(str(app / "storage"))
    new.unlink()
    assert _inspect_artifact(row, storage, max_bytes=DEFAULT_MAX_BYTES)[0].error == "STRUCTURED_FILE_MISSING"
    assert old.is_file()


def test_unconfigured_symlink_and_path_escape_are_rejected(tmp_path, monkeypatch):
    monkeypatch.delenv("FINANCE_AGENT_STORAGE_ROOT", raising=False)
    monkeypatch.delenv("FINANCE_AGENT_LEGACY_STORAGE_ROOTS", raising=False)
    for path in ("../features/a.json", str(tmp_path / "a/../b.json")):
        with pytest.raises(ValueError):
            remap_storage_path(path, storage_root=tmp_path)
    app = tmp_path / "app"
    app.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    (app / "storage").symlink_to(external, target_is_directory=True)
    row = RunArtifact(run_id=uuid.uuid4(), artifact_type="feature_json", file_path="storage/features/a.json",
                      sha256="a" * 64, storage_backend="local_fs")
    result, _, _ = _inspect_artifact(row, LocalFileSystemArtifactStorage(root=app), max_bytes=DEFAULT_MAX_BYTES)
    assert result.error == "STRUCTURED_PATH_ESCAPE"
