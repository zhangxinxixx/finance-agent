"""P2-03 Data Ingestion action contract tests."""

from __future__ import annotations

import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.main import api_ingestion_manual_upload, api_ingestion_source_retry, api_run_detail
from apps.api.schemas.data_source import DataSourceActionRequest, ManualUploadRequest
from database.models.execution import RunArtifact, ensure_execution_tables
from database.models.task import ensure_task_tables


def _make_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_task_tables(engine)
    ensure_execution_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_ingestion_retry_creates_traceable_task_run() -> None:
    session = _make_session()

    response = api_ingestion_source_retry(
        "cme_bulletin",
        body=DataSourceActionRequest(actor="codex", reason="refresh missing snapshot", request_id="retry-001"),
        db=session,
    )

    assert response.status == "accepted"
    assert response.action == "retry"
    assert response.source_key == "cme_bulletin"
    assert response.run_id is not None
    assert response.audit_id == "ingestion-action:cme_bulletin:retry-001"

    run = api_run_detail(response.run_id, db=session).model_dump(mode="json")
    assert run["task_type"] == "ingestion_retry"
    assert run["status"] == "queued"
    assert run["steps"][0]["task_kind"] == "retry"
    assert run["steps"][0]["source_refs"][0]["source_id"] == "cme_bulletin"


def test_manual_upload_registers_raw_artifact_and_requires_followup() -> None:
    session = _make_session()

    response = api_ingestion_manual_upload(
        body=ManualUploadRequest(
            source_key="cme_bulletin",
            file_name="daily-bulletin.pdf",
            sha256="abc123",
            actor="codex",
            reason="official fallback file",
            request_id="upload-001",
        ),
        db=session,
    )

    assert response.status == "manual_required"
    assert response.action == "manual_upload"
    assert response.run_id is not None
    assert response.data_status == "manual_required"
    assert response.artifact_refs[0].artifact_type == "raw_file"
    assert response.artifact_refs[0].file_path == "storage/raw/manual/cme_bulletin/daily-bulletin.pdf"

    run = api_run_detail(response.run_id, db=session).model_dump(mode="json")
    assert run["task_type"] == "manual_upload"
    assert run["status"] == "needs_review"
    assert run["steps"][0]["status"] == "needs_review"
    assert run["steps"][0]["output_refs"][0]["sha256"] == "abc123"
    artifacts = session.query(RunArtifact).filter(RunArtifact.run_id == uuid.UUID(run["run_id"])).all()
    assert len(artifacts) == 1
    assert artifacts[0].file_path == "storage/raw/manual/cme_bulletin/daily-bulletin.pdf"
    assert artifacts[0].storage_backend == "local_fs"
