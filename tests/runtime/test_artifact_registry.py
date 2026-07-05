from __future__ import annotations

import json
import uuid
from hashlib import sha256

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.runtime.artifact_storage import LocalFileSystemArtifactStorage
from apps.runtime.artifact_registry import register_artifact, register_step_artifacts
from database.models.execution import RunArtifact, ensure_execution_tables
from database.models.task import StepStatus, TaskRun, TaskStep, TaskStatus, ensure_task_tables


def _make_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_task_tables(engine)
    ensure_execution_tables(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return factory()


def test_local_artifact_storage_reads_text_and_bytes(tmp_path) -> None:
    storage = LocalFileSystemArtifactStorage(root=tmp_path)
    relative_path = "storage/test-artifact-storage/local-read.txt"
    artifact_path = storage.resolve(relative_path)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text("slice2-read", encoding="utf-8")

    assert storage.read_text(relative_path) == "slice2-read"
    assert storage.open_bytes(relative_path) == b"slice2-read"


def test_register_artifact_persists_canonical_metadata_and_file_stats(tmp_path) -> None:
    session = _make_session()
    run = TaskRun(name="premarket", status=TaskStatus.pending, snapshot_id="snap-registry-001")
    session.add(run)
    session.flush()
    content = "# Registry Report\n"
    file_path = f"storage/outputs/final_report/XAUUSD/2026-07-04/{run.id}/analysis.md"
    artifact_path = tmp_path / file_path
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(content, encoding="utf-8")

    row = register_artifact(
        session,
        run_id=str(run.id),
        artifact_type="analysis_md",
        file_path=file_path,
        source_refs=[
            {
                "source_id": "src-report-001",
                "source_name": "analysis_snapshot",
                "source_type": "snapshot",
                "snapshot_id": "snap-registry-001",
            }
        ],
        input_snapshot_ids={"analysis_snapshot": "snap-registry-001"},
        metadata={"source_key": "final_report"},
        storage=LocalFileSystemArtifactStorage(root=tmp_path),
    )
    session.commit()

    saved = session.query(RunArtifact).one()
    assert row is not None
    assert saved.artifact_id == row.artifact_id
    assert saved.task_id is None
    assert saved.file_path == file_path
    assert saved.sha256 == sha256(content.encode("utf-8")).hexdigest()
    assert saved.byte_size == len(content.encode("utf-8"))
    assert saved.content_type in {"text/markdown", "text/x-markdown"}
    assert saved.source_refs_data == [
        {
            "source_id": "src-report-001",
            "source_name": "analysis_snapshot",
            "source_type": "snapshot",
            "snapshot_id": "snap-registry-001",
        }
    ]
    metadata = saved.artifact_metadata
    assert metadata["layer"] == "outputs"
    assert metadata["domain"] == "final_report"
    assert metadata["trade_date"] == "2026-07-04"
    assert metadata["path_run_id"] == str(run.id)
    assert metadata["path_context"] == ["XAUUSD"]
    assert metadata["artifact_name"] == "analysis.md"
    assert metadata["canonical_path"] is True
    assert metadata["source_key"] == "final_report"


def test_register_artifact_rejects_non_run_partitioned_path_by_default() -> None:
    session = _make_session()
    run = TaskRun(name="premarket", status=TaskStatus.pending)
    session.add(run)
    session.flush()

    with pytest.raises(ValueError, match="canonical artifact path violation"):
        register_artifact(
            session,
            run_id=str(run.id),
            artifact_type="raw_file",
            file_path="storage/raw/macro/legacy.json",
        )

    assert session.query(RunArtifact).count() == 0


def test_register_artifact_rejects_missing_task_run_parent() -> None:
    session = _make_session()
    run_id = uuid.uuid4()

    with pytest.raises(ValueError, match="does not match an existing TaskRun"):
        register_artifact(
            session,
            run_id=str(run_id),
            artifact_type="raw_file",
            file_path=f"storage/raw/macro/2026-07-04/{run_id}/payload.json",
        )

    assert session.query(RunArtifact).count() == 0


def test_register_artifact_accepts_step_binding_and_dedupes(tmp_path) -> None:
    session = _make_session()
    run = TaskRun(name="premarket", status=TaskStatus.pending)
    session.add(run)
    session.flush()
    step = TaskStep(task_run_id=run.id, name="macro_features", status=StepStatus.success)
    session.add(step)
    session.flush()
    file_path = f"storage/features/macro/2026-07-04/{run.id}/macro_snapshot.json"
    artifact_path = tmp_path / file_path
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text('{"status":"ok"}', encoding="utf-8")

    first = register_artifact(
        session,
        run_id=str(run.id),
        step=step,
        artifact_type="feature_json",
        file_path=file_path,
        storage=LocalFileSystemArtifactStorage(root=tmp_path),
    )
    second = register_artifact(
        session,
        run_id=str(run.id),
        step=step,
        artifact_type="feature_json",
        file_path=file_path,
        storage=LocalFileSystemArtifactStorage(root=tmp_path),
    )
    session.commit()

    saved = session.query(RunArtifact).one()
    assert first is not None
    assert second is not None
    assert first.artifact_id == second.artifact_id == saved.artifact_id
    assert saved.task_id == step.id
    assert saved.artifact_metadata["canonical_path"] is True


def test_register_artifact_accepts_storage_root_relative_path(tmp_path) -> None:
    session = _make_session()
    run = TaskRun(name="premarket", status=TaskStatus.pending)
    session.add(run)
    session.flush()
    file_path = f"features/macro/2026-07-04/{run.id}/macro_snapshot.json"
    artifact_path = tmp_path / file_path
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text('{"status":"ok"}', encoding="utf-8")

    register_artifact(
        session,
        run_id=str(run.id),
        artifact_type="feature_json",
        file_path=file_path,
        storage=LocalFileSystemArtifactStorage(root=tmp_path),
    )
    session.commit()

    saved = session.query(RunArtifact).one()
    assert saved.file_path == file_path
    assert saved.artifact_metadata["layer"] == "features"
    assert saved.artifact_metadata["domain"] == "macro"
    assert saved.artifact_metadata["trade_date"] == "2026-07-04"
    assert saved.artifact_metadata["path_run_id"] == str(run.id)
    assert saved.artifact_metadata["path_context"] == []
    assert saved.artifact_metadata["artifact_name"] == "macro_snapshot.json"
    assert saved.artifact_metadata["canonical_path"] is True


def test_register_step_artifacts_rejects_mismatched_run_id() -> None:
    session = _make_session()
    run = TaskRun(name="premarket", status=TaskStatus.pending)
    session.add(run)
    session.flush()
    step = TaskStep(task_run_id=run.id, name="collect_macro", status=StepStatus.success)
    session.add(step)
    session.flush()

    with pytest.raises(ValueError, match="run artifact lineage conflict"):
        register_step_artifacts(
            session,
            run_id=str(uuid.uuid4()),
            step=step,
            output_refs=[
                {
                    "artifact_id": "art-conflict-001",
                    "artifact_type": "raw_file",
                    "file_path": "storage/raw/macro/conflict.json",
                    "sha256": "abc123",
                }
            ],
        )

    assert session.query(RunArtifact).count() == 0


def test_register_step_artifacts_rejects_conflicting_analysis_snapshot_lineage() -> None:
    session = _make_session()
    run = TaskRun(name="premarket", status=TaskStatus.pending, snapshot_id="snap-registry-001")
    session.add(run)
    session.flush()
    step = TaskStep(task_run_id=run.id, name="report_render", status=StepStatus.success)
    session.add(step)
    session.flush()

    with pytest.raises(ValueError, match="analysis_md artifact analysis_snapshot"):
        register_step_artifacts(
            session,
            run_id=str(run.id),
            step=step,
            output_refs=[
                {
                    "artifact_id": "art-conflict-002",
                    "artifact_type": "analysis_md",
                    "file_path": "storage/outputs/final_report/conflict.md",
                    "sha256": "def456",
                }
            ],
            source_refs=[
                {
                    "source_id": "src-analysis-snapshot-001",
                    "source_name": "analysis_snapshot",
                    "source_type": "snapshot",
                    "snapshot_id": "snap-registry-999",
                }
            ],
            input_snapshot_ids={
                "analysis_snapshot": "snap-registry-999",
                "coordinator": "snap-registry-001",
            },
        )

    assert session.query(RunArtifact).count() == 0


def test_register_step_artifacts_rejects_conflicting_analysis_snapshot_source_ref() -> None:
    session = _make_session()
    run = TaskRun(name="premarket", status=TaskStatus.pending, snapshot_id="snap-registry-001")
    session.add(run)
    session.flush()
    step = TaskStep(task_run_id=run.id, name="report_render", status=StepStatus.success)
    session.add(step)
    session.flush()

    with pytest.raises(ValueError, match="source_ref\\[analysis_snapshot\\]"):
        register_step_artifacts(
            session,
            run_id=str(run.id),
            step=step,
            output_refs=[
                {
                    "artifact_id": "art-conflict-003",
                    "artifact_type": "analysis_md",
                    "file_path": "storage/outputs/final_report/conflict-source.md",
                    "sha256": "ghi789",
                }
            ],
            source_refs=[
                {
                    "source_id": "src-analysis-snapshot-002",
                    "source_name": "analysis_snapshot",
                    "source_type": "snapshot",
                    "snapshot_id": "snap-registry-999",
                }
            ],
            input_snapshot_ids={
                "analysis_snapshot": "snap-registry-001",
                "coordinator": "snap-registry-001",
            },
        )

    assert session.query(RunArtifact).count() == 0


def test_register_step_artifacts_rejects_source_ref_without_identity() -> None:
    session = _make_session()
    run = TaskRun(name="premarket", status=TaskStatus.pending, snapshot_id="snap-registry-001")
    session.add(run)
    session.flush()
    step = TaskStep(task_run_id=run.id, name="collect_macro", status=StepStatus.success)
    session.add(step)
    session.flush()

    with pytest.raises(ValueError, match="source_refs\\[0\\] must include one of"):
        register_step_artifacts(
            session,
            run_id=str(run.id),
            step=step,
            output_refs=[
                {
                    "artifact_id": "art-invalid-source-001",
                    "artifact_type": "raw_file",
                    "file_path": "storage/raw/macro/invalid-source.json",
                    "sha256": "invalid-source",
                }
            ],
            source_refs=[{"status": "available"}],
        )

    assert session.query(RunArtifact).count() == 0


def test_register_step_artifacts_rejects_source_ref_without_trace_detail() -> None:
    session = _make_session()
    run = TaskRun(name="premarket", status=TaskStatus.pending, snapshot_id="snap-registry-001")
    session.add(run)
    session.flush()
    step = TaskStep(task_run_id=run.id, name="collect_macro", status=StepStatus.success)
    session.add(step)
    session.flush()

    with pytest.raises(ValueError, match="source_refs\\[0\\] must include one trace/detail field"):
        register_step_artifacts(
            session,
            run_id=str(run.id),
            step=step,
            output_refs=[
                {
                    "artifact_id": "art-invalid-source-002",
                    "artifact_type": "raw_file",
                    "file_path": "storage/raw/macro/invalid-source-detail.json",
                    "sha256": "invalid-source-detail",
                }
            ],
            source_refs=[{"source": "fred"}],
        )

    assert session.query(RunArtifact).count() == 0


def test_register_step_artifacts_accepts_legacy_source_ref_shape() -> None:
    session = _make_session()
    run = TaskRun(name="premarket", status=TaskStatus.pending, snapshot_id="snap-registry-001")
    session.add(run)
    session.flush()
    step = TaskStep(task_run_id=run.id, name="collect_macro", status=StepStatus.success)
    session.add(step)
    session.flush()

    register_step_artifacts(
        session,
        run_id=str(run.id),
        step=step,
        output_refs=[
            {
                "artifact_id": "art-legacy-source-001",
                "artifact_type": "raw_file",
                "file_path": "storage/raw/macro/legacy-source.json",
                "sha256": "legacy-source",
            }
        ],
        source_refs=[{"source": "fred", "symbol": "DGS10"}],
    )
    session.commit()

    saved = session.query(RunArtifact).one()
    assert json.loads(saved.source_refs or "[]") == [{"source": "fred", "symbol": "DGS10"}]


def test_register_step_artifacts_accepts_normalized_source_ref_shape() -> None:
    session = _make_session()
    run = TaskRun(name="premarket", status=TaskStatus.pending, snapshot_id="snap-registry-001")
    session.add(run)
    session.flush()
    step = TaskStep(task_run_id=run.id, name="collect_macro", status=StepStatus.success)
    session.add(step)
    session.flush()

    register_step_artifacts(
        session,
        run_id=str(run.id),
        step=step,
        output_refs=[
            {
                "artifact_id": "art-normalized-source-001",
                "artifact_type": "raw_file",
                "file_path": "storage/raw/macro/normalized-source.json",
                "sha256": "normalized-source",
            }
        ],
        source_refs=[
            {
                "source_id": "src-001",
                "source_name": "FRED",
                "source_type": "api",
                "status": "available",
                "endpoint": "https://api.stlouisfed.org/fred/series/observations",
            }
        ],
    )
    session.commit()

    saved = session.query(RunArtifact).one()
    assert json.loads(saved.source_refs or "[]")[0]["source_id"] == "src-001"


def test_register_step_artifacts_accepts_matching_run_id() -> None:
    session = _make_session()
    run = TaskRun(name="premarket", status=TaskStatus.pending, snapshot_id="snap-registry-001")
    session.add(run)
    session.flush()
    step = TaskStep(task_run_id=run.id, name="collect_macro", status=StepStatus.success)
    session.add(step)
    session.flush()

    rows = register_step_artifacts(
        session,
        run_id=str(run.id),
        step=step,
        output_refs=[
            {
                "artifact_id": "art-ok-001",
                "artifact_type": "raw_file",
                "file_path": "storage/raw/macro/ok.json",
                "sha256": "ok123",
            }
        ],
        source_refs=[
            {
                "source_id": "src-runtime-001",
                "source_name": "analysis_snapshot",
                "source_type": "snapshot",
                "snapshot_id": "snap-registry-001",
            }
        ],
        input_snapshot_ids={
            "analysis_snapshot": "snap-registry-001",
            "coordinator": "snap-registry-001",
            "macro": "snap-macro-001",
        },
    )
    session.commit()

    assert len(rows) == 1
    saved = session.query(RunArtifact).one()
    assert saved.run_id == run.id
    assert saved.task_id == step.id
    assert saved.file_path == "storage/raw/macro/ok.json"
    assert json.loads(saved.source_refs or "[]")[0]["source_id"] == "src-runtime-001"
    metadata = json.loads(saved.metadata_json or "{}")
    assert metadata["snapshot_id"] == "snap-registry-001"
    assert metadata["input_snapshot_ids"] == {
        "analysis_snapshot": "snap-registry-001",
        "coordinator": "snap-registry-001",
        "macro": "snap-macro-001",
    }
    assert metadata["lineage_kind"] == "source_input"
    assert metadata["lineage_status"] == "run_bound"


def test_register_step_artifacts_persists_structured_registry_metadata() -> None:
    session = _make_session()
    run = TaskRun(name="premarket", status=TaskStatus.pending, snapshot_id="snap-registry-001")
    session.add(run)
    session.flush()
    step = TaskStep(task_run_id=run.id, name="render_report", status=StepStatus.success)
    session.add(step)
    session.flush()

    register_step_artifacts(
        session,
        run_id=str(run.id),
        step=step,
        output_refs=[
            {
                "artifact_id": "art-structured-registry-001",
                "artifact_type": "analysis_md",
                "file_path": "storage/outputs/final_report/report.md",
                "storage_backend": "local_fs",
                "sha256": "a" * 64,
                "content_type": "text/markdown",
                "byte_size": 2048,
                "generated_at": "2026-05-26T10:00:00+00:00",
            }
        ],
        source_refs=[{"source_id": "src-report-001", "source_name": "analysis_snapshot", "source_type": "snapshot", "snapshot_id": "snap-registry-001"}],
        input_snapshot_ids={"analysis_snapshot": "snap-registry-001"},
    )
    session.commit()

    saved = session.query(RunArtifact).one()
    assert saved.content_type == "text/markdown"
    assert saved.byte_size == 2048
    assert saved.generated_at.isoformat() == "2026-05-26T10:00:00"
    assert saved.source_refs_data == [
        {"source_id": "src-report-001", "source_name": "analysis_snapshot", "source_type": "snapshot", "snapshot_id": "snap-registry-001"}
    ]
    assert saved.artifact_metadata["artifact_id"] == "art-structured-registry-001"
    assert saved.artifact_metadata["input_snapshot_ids"] == {"analysis_snapshot": "snap-registry-001"}
    assert json.loads(saved.source_refs or "[]") == saved.source_refs_data
    assert json.loads(saved.metadata_json or "{}") == saved.artifact_metadata


def test_register_step_artifacts_marks_structured_json_as_snapshot_bound() -> None:
    session = _make_session()
    run = TaskRun(name="premarket", status=TaskStatus.pending, snapshot_id="snap-registry-001")
    session.add(run)
    session.flush()
    step = TaskStep(task_run_id=run.id, name="report_render", status=StepStatus.success)
    session.add(step)
    session.flush()

    register_step_artifacts(
        session,
        run_id=str(run.id),
        step=step,
        output_refs=[
            {
                "artifact_id": "art-report-json-001",
                "artifact_type": "structured_json",
                "file_path": "storage/outputs/final_report/report_structured.json",
                "sha256": "json123",
            }
        ],
        input_snapshot_ids={
            "analysis_snapshot": "snap-registry-001",
            "coordinator": "snap-registry-001",
        },
    )
    session.commit()

    saved = session.query(RunArtifact).one()
    metadata = json.loads(saved.metadata_json or "{}")
    assert metadata["lineage_kind"] == "snapshot_bound"
    assert metadata["lineage_status"] == "bound"
    assert metadata["snapshot_id"] == "snap-registry-001"


def test_register_step_artifacts_keeps_raw_file_non_snapshot_inputs_compatible() -> None:
    session = _make_session()
    run = TaskRun(name="premarket", status=TaskStatus.pending, snapshot_id="snap-registry-001")
    session.add(run)
    session.flush()
    step = TaskStep(task_run_id=run.id, name="collect_macro", status=StepStatus.success)
    session.add(step)
    session.flush()

    register_step_artifacts(
        session,
        run_id=str(run.id),
        step=step,
        output_refs=[
            {
                "artifact_id": "art-raw-001",
                "artifact_type": "raw_file",
                "file_path": "storage/raw/macro/non-snapshot.json",
                "sha256": "raw123",
            }
        ],
        input_snapshot_ids={
            "raw_file_sha256": "raw-sha-abc",
            "parse_run_id": "parse-run-001",
        },
    )
    session.commit()

    saved = session.query(RunArtifact).one()
    metadata = json.loads(saved.metadata_json or "{}")
    assert metadata["lineage_kind"] == "source_input"
    assert metadata["lineage_status"] == "run_bound"
    assert metadata["input_snapshot_ids"] == {
        "raw_file_sha256": "raw-sha-abc",
        "parse_run_id": "parse-run-001",
    }
