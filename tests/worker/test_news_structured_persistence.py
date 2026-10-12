from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.worker.news_artifact_registration import build_news_artifact_refs, persist_dagster_news_summary
from apps.worker.pipelines.news import NewsPipelineState, run_news_step
from apps.worker.artifact_registration import register_runner_step_artifacts
from apps.runtime.artifact_storage import LocalFileSystemArtifactStorage
from database.models.execution import RunArtifact, ensure_execution_tables
from database.models.task import TaskRun, TaskStep, TaskStatus, StepStatus, ensure_task_tables
from tests.worker.test_news_pipeline import _fake_collectors, _FixedNewsDatetime
from tests.helpers.warehouse import create_collection_schema


@pytest.mark.parametrize("adapter", ["dagster", "worker"])
def test_news_producer_manifests_register_metadata_with_real_step_lineage(tmp_path, monkeypatch, adapter):
    engine = create_engine("sqlite://")
    ensure_task_tables(engine)
    ensure_execution_tables(engine)
    create_collection_schema(engine)
    monkeypatch.setattr(
        "apps.runtime.artifact_registry.get_artifact_storage",
        lambda backend_name=None: LocalFileSystemArtifactStorage(root=tmp_path),
    )
    state = NewsPipelineState()
    with Session(engine) as db:
        run = TaskRun(name="premarket", status=TaskStatus.running)
        db.add(run)
        db.flush()
        steps = {}
        for name in ["news_collect", "news_feature", "news_brief"]:
            steps[name] = TaskStep(task_run_id=run.id, name=name, status=StepStatus.pending)
            db.add(steps[name])
        db.flush()
        with (
            patch("apps.worker.pipelines.news._collectors", return_value=_fake_collectors()),
            patch("apps.worker.pipelines.news.datetime", _FixedNewsDatetime),
            patch("apps.worker.pipelines.news.get_data_source_statuses", return_value={"sources": []}),
            patch("apps.api.services.source_service.get_data_source_status_index", return_value={}),
        ):
            monkeypatch.setenv("NEWS_WEB_SEARCH_FALLBACK_ENABLED", "false")
            for name in steps:
                summary = run_news_step(name, state, storage_root=tmp_path, run_id=str(run.id), db_session=db)
                assert summary["artifact_refs"]
                if adapter == "dagster":
                    persist_dagster_news_summary(db, run_id=str(run.id), summary=summary, storage_root=tmp_path)
                else:
                    register_runner_step_artifacts(db, run_id=str(run.id), step=steps[name], summary=summary)
        db.commit()
        rows = db.query(RunArtifact).all()
        paths = {row.file_path for row in rows}
        assert all(str(tmp_path / path) in paths for path in state.artifact_paths.values())
        for row in rows:
            assert row.run_id == run.id and row.task_id in {step.id for step in steps.values()}
            assert row.sha256
            assert row.structured_payload is None
            assert row.structured_payload_sha256 is None
            assert row.structured_status is None
        assert any("analysis" in Path(row.file_path).parts for row in rows)
        assert any(Path(row.file_path).name == "gold_event_mainlines.json" for row in rows)
        # Repeat registration cannot add rows or change metadata.
        before = {row.artifact_id: (row.file_path, row.sha256, row.task_id) for row in rows}
        if adapter == "dagster":
            persist_dagster_news_summary(db, run_id=str(run.id), summary=summary, storage_root=tmp_path)
        else:
            register_runner_step_artifacts(db, run_id=str(run.id), step=steps["news_brief"], summary=summary)
        db.commit()
        assert before == {row.artifact_id: (row.file_path, row.sha256, row.task_id) for row in db.query(RunArtifact)}


def test_missing_lineage_does_not_synthesize_steps(tmp_path):
    engine = create_engine("sqlite://")
    ensure_task_tables(engine)
    ensure_execution_tables(engine)
    with Session(engine) as db:
        run = TaskRun(name="producer", status=TaskStatus.success)
        db.add(run)
        db.flush()
        with pytest.raises(ValueError, match="task_step_missing"):
            persist_dagster_news_summary(
                db, run_id=str(run.id), summary={"step": "news_feature", "artifact_refs": []}, storage_root=tmp_path
            )
        assert db.query(TaskStep).count() == db.query(RunArtifact).count() == 0


def test_manifest_rejects_escape_and_ignores_non_producer_keys(tmp_path):
    assert (
        build_news_artifact_refs(
            step_name="news_feature", paths={"unrelated": "../../secret.json"}, storage_root=tmp_path, run_id="run"
        )
        == []
    )
    with pytest.raises(ValueError, match="path_invalid"):
        build_news_artifact_refs(
            step_name="news_feature",
            paths={"event_candidates": "../../secret.json"},
            storage_root=tmp_path,
            run_id="run",
        )
