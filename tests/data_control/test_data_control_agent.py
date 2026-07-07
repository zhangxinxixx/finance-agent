from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.data_control import data_control_agent
from apps.data_control.data_control_agent import run_data_control_agent
from apps.runtime import task_recorder as task_recorder_module
from database.models.execution import RunArtifact, ensure_execution_tables
from database.models.task import ensure_task_tables


OBSERVED_AT = datetime(2026, 7, 8, 10, 15, tzinfo=timezone.utc)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _seed_storage(storage_root: Path) -> None:
    _write_json(storage_root / "outputs" / "jin10" / "quotes_cache.json", {"updated_at": "2026-07-08T10:14:00+00:00"})
    _write_json(storage_root / "outputs" / "jin10" / "flash_cache.json", {"updated_at": "2026-07-08T09:30:00+00:00"})
    _write_json(storage_root / "raw" / "jin10" / "2026-07-08" / "index.json", {"items": ["223556"]})
    _write_json(storage_root / "parsed" / "jin10" / "2026-07-08" / "index.json", {"items": ["223556"]})
    _write_json(storage_root / "outputs" / "jin10" / "2026-07-08" / "analysis.json", {"status": "partial"})
    _write_json(
        storage_root / "outputs" / "jin10" / "2026-07-08" / "223556" / "agent_analysis_report.json",
        {
            "content_access": {
                "report_type": "research",
                "series": "master_review",
                "content_scope": "preview",
                "body_complete": False,
                "vip_locked": True,
            }
        },
    )
    _write_json(
        storage_root / "monitoring" / "2026-07-08" / "downstream_readiness.json",
        {
            "trade_date": "2026-07-08",
            "readiness": "blocked",
            "can_run_full_analysis": False,
            "can_run_research_distillation": False,
            "allowed_outputs": ["market snapshot", "limited daily analysis"],
            "blocked_outputs": ["full analysis", "knowledge distillation"],
            "blocking_issues": [{"source_key": "jin10_svip_reports", "reason_code": "jin10_report_preview_or_incomplete"}],
        },
    )


def test_data_control_agent_writes_hourly_plans_and_notification_request(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    _seed_storage(storage_root)

    result = run_data_control_agent(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        record_task_run=False,
    )

    artifacts = result["artifacts"]
    assert (storage_root / artifacts["data_availability_snapshot"]).is_file()
    assert (storage_root / artifacts["collection_plan"]).is_file()
    assert (storage_root / artifacts["processing_plan"]).is_file()
    assert (storage_root / artifacts["hourly_report_json"]).is_file()
    assert (storage_root / artifacts["hourly_report_md"]).is_file()

    availability = json.loads((storage_root / artifacts["data_availability_snapshot"]).read_text(encoding="utf-8"))
    states = {item["source_key"]: item["state"] for item in availability["items"]}
    assert states["jin10_mcp_market"] == "available"
    assert states["jin10_mcp_flash"] == "stale"
    assert states["jin10_daily_report"] == "waiting"
    assert states["jin10_datacenter_reports"] == "missing"

    collection_plan = json.loads((storage_root / artifacts["collection_plan"]).read_text(encoding="utf-8"))
    assert any(item["source_key"] == "jin10_mcp_flash" and item["state"] == "stale" for item in collection_plan["actions"])
    assert any(item["source_key"] == "jin10_daily_report" and item["state"] == "waiting" for item in collection_plan["actions"])

    processing_plan = json.loads((storage_root / artifacts["processing_plan"]).read_text(encoding="utf-8"))
    assert "jin10_reports_raw_to_parsed" in processing_plan["ready_steps"]
    assert "jin10_reports_outputs_to_agent_outputs" in processing_plan["ready_steps"]
    assert any(item["reason_code"] == "downstream_quality_gate_blocked" for item in processing_plan["blocked_steps"])

    report = json.loads((storage_root / artifacts["hourly_report_json"]).read_text(encoding="utf-8"))
    assert report["status"] == "blocked"
    assert report["main_analysis_readiness"] == "blocked"
    assert report["knowledge_distillation_readiness"] == "blocked"
    assert report["notification_request"]["kind"] == "hourly_report"
    assert report["notification_request"]["severity"] == "critical"
    assert report["notification_request"]["facts"]["status"] == "blocked"


def test_data_control_agent_records_task_run_when_enabled(tmp_path, monkeypatch) -> None:
    storage_root = tmp_path / "storage"
    _seed_storage(storage_root)
    calls: list[dict] = []

    class Recorder:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

        def step(self, step_name: str, **kwargs):
            calls.append({"step_name": step_name, **kwargs})

        def run_id(self):
            return "dc-run-1"

    def fake_record_task(**kwargs):
        calls.append({"record_task": kwargs})
        return Recorder()

    monkeypatch.setattr(data_control_agent, "record_task", fake_record_task)

    result = run_data_control_agent(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        record_task_run=True,
    )

    assert result["task_run_id"] == "dc-run-1"
    assert calls[0]["record_task"]["task_type"] == "data_control_agent"
    assert calls[1]["step_name"] == "write_data_control_artifacts"
    assert calls[1]["output_refs"][0]["artifact_type"] == "data_availability_snapshot"
    assert calls[1]["source_refs"][0]["source_ref"] == "data-control:2026-07-08"
    assert calls[1]["source_refs"][1]["source_ref"] == "monitoring:2026-07-08:downstream_readiness"


def test_data_control_agent_registers_artifacts_with_traceable_source_refs(tmp_path, monkeypatch) -> None:
    storage_root = tmp_path / "storage"
    _seed_storage(storage_root)
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_task_tables(engine)
    ensure_execution_tables(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(task_recorder_module, "SessionLocal", factory)

    result = run_data_control_agent(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        record_task_run=True,
    )

    assert result["task_run_id"] is not None
    with factory() as session:
        artifacts = session.query(RunArtifact).all()

    assert len(artifacts) == 5
    assert artifacts[0].source_refs_data == [
        {
            "source": "data_control_agent",
            "source_ref": "data-control:2026-07-08",
            "data_date": "2026-07-08",
        },
        {
            "source": "data_quality_monitor",
            "source_ref": "monitoring:2026-07-08:downstream_readiness",
            "data_date": "2026-07-08",
        },
    ]
