"""Data Ingestion immediate source test / preview contract tests."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api import main
from apps.api.schemas.data_source import DataSourceTestRequest
from database.models.execution import ExecutionEvent, RunArtifact, ensure_execution_tables
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


class _FakeMCPClient:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def list_flash(self):
        return {
            "status": 200,
            "data": {
                "items": [
                    {"id": "flash-1", "time": "2026-06-13 09:30:00", "content": "黄金突破关键位"},
                    {"id": "flash-2", "time": "2026-06-13 09:31:00", "content": "美联储官员讲话"},
                    {"id": "flash-3", "time": "2026-06-13 09:32:00", "content": "原油库存更新"},
                ]
            },
        }


def test_ingestion_source_test_runs_jin10_flash_probe_and_archives_preview(monkeypatch, tmp_path: Path) -> None:
    session = _make_session()
    monkeypatch.setattr("apps.api.services.ingestion_source_test_service._PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("apps.api.services.ingestion_source_test_service.Jin10MCPClient", _FakeMCPClient)

    response = main.api_ingestion_source_test(
        "jin10_mcp_flash",
        body=DataSourceTestRequest(actor="automation", reason="manual preview", request_id="probe-001", limit=2),
        db=session,
    )

    assert response.status == "ok"
    assert response.source_key == "jin10_mcp_flash"
    assert response.run_id is not None
    assert response.duration_ms >= 0
    assert response.summary["item_count"] == 3
    assert response.summary["sample_count"] == 2
    assert response.preview == [
        {"id": "flash-1", "published_at": "2026-06-13 09:30:00", "content_excerpt": "黄金突破关键位"},
        {"id": "flash-2", "published_at": "2026-06-13 09:31:00", "content_excerpt": "美联储官员讲话"},
    ]
    assert response.artifacts["raw_path"].startswith("storage/probes/ingestion/")
    assert response.artifacts["parsed_path"].startswith("storage/probes/ingestion/")
    assert (tmp_path / response.artifacts["raw_path"]).exists()
    parsed_payload = json.loads((tmp_path / response.artifacts["parsed_path"]).read_text(encoding="utf-8"))
    assert parsed_payload["source_key"] == "jin10_mcp_flash"
    assert parsed_payload["status"] == "ok"

    run = main.api_run_detail(response.run_id, db=session).model_dump(mode="json")
    assert run["task_type"] == "ingestion_source_test"
    assert run["status"] == "success"
    assert run["steps"][0]["task_kind"] == "source_probe"
    assert run["steps"][0]["source_refs"][0]["source_id"] == "jin10_mcp_flash"
    assert run["steps"][0]["artifact_refs"][0]["file_path"] == response.artifacts["raw_path"]

    events = (
        session.query(ExecutionEvent)
        .filter(ExecutionEvent.run_id == uuid.UUID(response.run_id))
        .order_by(ExecutionEvent.created_at.asc(), ExecutionEvent.event_type.asc())
        .all()
    )
    event_types = [event.event_type for event in events]
    assert "RUN_STARTED" in event_types
    assert "RUN_FINISHED" in event_types
    assert "TASK_STARTED" in event_types
    assert "TASK_FINISHED" in event_types
    artifacts = session.query(RunArtifact).filter(RunArtifact.run_id == uuid.UUID(response.run_id)).all()
    assert {artifact.file_path for artifact in artifacts} >= {
        response.artifacts["raw_path"],
        response.artifacts["parsed_path"],
    }


@dataclass
class _DatacenterFetchResult:
    status: str = "schema_changed"
    slug: str = "dc_etf_gold"
    raw_html_path: str = "storage/probes/ingestion/2026-06-13/jin10_datacenter_reports/run/shell.html"
    raw_js_path: str = "storage/probes/ingestion/2026-06-13/jin10_datacenter_reports/run/latest.js"
    error_message: str = "dataCenter_data assignment not found"

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "slug": self.slug,
            "raw_html_path": self.raw_html_path,
            "raw_js_path": self.raw_js_path,
            "error_message": self.error_message,
            "source_refs": [{"source_key": "jin10_datacenter_reports", "status": self.status}],
        }


def test_ingestion_source_test_returns_datacenter_schema_changed(monkeypatch, tmp_path: Path) -> None:
    session = _make_session()
    monkeypatch.setattr("apps.api.services.ingestion_source_test_service._PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "apps.api.services.ingestion_source_test_service.fetch_datacenter_report",
        lambda **kwargs: _DatacenterFetchResult(),
    )

    response = main.api_ingestion_source_test(
        "jin10_datacenter_reports",
        body=DataSourceTestRequest(actor="automation", reason="datacenter probe", request_id="probe-dc", limit=3),
        db=session,
    )

    assert response.status == "schema_changed"
    assert response.data_status == "partial"
    assert response.summary["slug"] == "dc_etf_gold"
    assert response.summary["reason_code"] == "schema_changed"
    assert response.preview == []


def test_ingestion_source_test_does_not_auto_fetch_svip_reports(monkeypatch, tmp_path: Path) -> None:
    session = _make_session()
    monkeypatch.setattr("apps.api.services.ingestion_source_test_service._PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "apps.api.services.ingestion_source_test_service.DEFAULT_JIN10_BROWSER_PROFILE",
        tmp_path / "missing-profile",
    )

    response = main.api_ingestion_source_test(
        "jin10_svip_reports",
        body=DataSourceTestRequest(actor="automation", reason="svip probe", request_id="probe-svip"),
        db=session,
    )

    assert response.status == "login_required"
    assert response.data_status == "manual_required"
    assert response.summary["auto_fetch"] is False
    assert "browser_profile" in response.summary["reason"]
    assert response.preview == []
