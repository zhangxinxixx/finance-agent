"""Writer guards keep output-cleanup tombstones authoritative."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.runtime.artifact_registry import register_artifact
from apps.runtime.artifact_storage import LocalFileSystemArtifactStorage
from database.models.analysis import AgentOutput, FinalAnalysisResult, ensure_analysis_tables
from database.models.execution import RunArtifact, ensure_execution_tables
from database.models.report import ReportArtifact, ReportItem, ensure_report_tables
from database.models.task import TaskRun, TaskStatus, ensure_task_tables
from database.queries.analysis import upsert_agent_output, upsert_final_analysis_result
from database.queries.report import upsert_report_artifact, upsert_report_item


def _session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    ensure_analysis_tables(engine)
    ensure_report_tables(engine)
    ensure_task_tables(engine)
    ensure_execution_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _marker(run_id: str = "purged-run") -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": "purged",
        "reason_codes": ["quality_gate_failed"],
        "purged_at": "2026-10-12T00:00:00Z",
        "original_payload_sha256": "a" * 64,
        "run_id": run_id,
    }


def _agent_payload(snapshot_id: str = "snapshot-1", run_id: str = "run-1") -> dict:
    return {
        "snapshot_id": snapshot_id,
        "analysis_snapshot_db_id": None,
        "asset": "XAUUSD",
        "trade_date": "2026-10-12",
        "run_id": run_id,
        "agent_name": "macro_agent",
        "module": "macro",
        "version": "1.0",
        "status": "success",
        "bias": "neutral",
        "confidence": 0.5,
        "input_snapshot_ids": {},
        "source_refs": [],
        "key_findings": [],
        "risk_points": [],
        "watchlist": [],
        "invalid_conditions": [],
        "summary": "new summary",
        "payload": {"output_cleanup": _marker(run_id)},
    }


def _final_payload(run_id: str = "run-final") -> dict:
    return {
        "asset": "XAUUSD",
        "trade_date": "2026-10-12",
        "run_id": run_id,
        "snapshot_id": None,
        "analysis_snapshot_db_id": None,
        "final_bias": "neutral",
        "confidence": 0.5,
        "market_state": "unknown",
        "scenario_summary": "new summary",
        "is_trade_instruction": False,
        "input_snapshot_ids": {},
        "source_refs": [],
        "source_agent_outputs": [],
        "risk_points": [],
        "watchlist": [],
        "invalid_conditions": [],
        "strategy_card": {},
        "run_summaries": {},
        "payload": {"output_cleanup": _marker(run_id)},
    }


def test_agent_output_tombstone_cannot_be_re_registered() -> None:
    session = _session()
    old = AgentOutput(
        id="agent-purged",
        snapshot_id="snapshot-1",
        asset="XAUUSD",
        trade_date=date(2026, 10, 12),
        run_id="run-1",
        agent_name="macro_agent",
        module="macro",
        version="1.0",
        status="failed",
        bias="neutral",
        confidence=0.0,
        source_refs=[],
        key_findings=[],
        risk_points=[],
        watchlist=[],
        invalid_conditions=[],
        summary="old summary",
        payload={"output_cleanup": _marker("run-1")},
        payload_sha256="a" * 64,
    )
    session.add(old)
    session.commit()

    with pytest.raises(ValueError, match="OUTPUT_PURGED"):
        upsert_agent_output(session, _agent_payload())

    saved = session.get(AgentOutput, "agent-purged")
    assert saved is not None
    assert saved.status == "failed"
    assert saved.payload == {"output_cleanup": _marker("run-1")}


def test_final_result_tombstone_cannot_be_re_registered() -> None:
    session = _session()
    session.add(
        FinalAnalysisResult(
            id="final-purged",
            asset="XAUUSD",
            trade_date=date(2026, 10, 12),
            run_id="run-final",
            final_bias="neutral",
            confidence=0.0,
            is_trade_instruction=False,
            input_snapshot_ids={},
            source_refs=[],
            source_agent_outputs=[],
            risk_points=[],
            watchlist=[],
            invalid_conditions=[],
            strategy_card={},
            run_summaries={},
            payload={"output_cleanup": _marker("run-final")},
            payload_sha256="a" * 64,
        )
    )
    session.commit()

    with pytest.raises(ValueError, match="OUTPUT_PURGED"):
        upsert_final_analysis_result(session, _final_payload(), paths={})

    saved = session.get(FinalAnalysisResult, "final-purged")
    assert saved is not None
    assert saved.payload == {"output_cleanup": _marker("run-final")}


def test_report_item_purged_states_cannot_be_re_registered() -> None:
    session = _session()
    session.add(
        ReportItem(
            report_id="report-purged",
            family="final_report_markdown",
            report_type="final_report",
            title="purged",
            data_status="unavailable",
            lifecycle_status="purged",
            source_refs=[],
            report_metadata={"output_cleanup": _marker()},
        )
    )
    session.commit()

    with pytest.raises(ValueError, match="OUTPUT_PURGED"):
        upsert_report_item(
            session,
            {
                "report_id": "report-purged",
                "family": "final_report_markdown",
                "report_type": "final_report",
                "title": "replacement",
                "data_status": "live",
                "lifecycle_status": "generated",
                "source_refs": [],
                "metadata": {},
            },
        )

    saved = session.get(ReportItem, "report-purged")
    assert saved is not None
    assert saved.data_status == "unavailable"
    assert saved.lifecycle_status == "purged"
    assert saved.report_metadata == {"output_cleanup": _marker()}


def test_unavailable_report_without_cleanup_marker_can_be_recovered() -> None:
    session = _session()
    session.add(
        ReportItem(
            report_id="report-recoverable",
            family="final_report_markdown",
            report_type="final_report",
            title="temporarily unavailable",
            data_status="unavailable",
            lifecycle_status="generated",
            source_refs=[],
            report_metadata={},
        )
    )
    session.commit()

    row = upsert_report_item(
        session,
        {
            "report_id": "report-recoverable",
            "family": "final_report_markdown",
            "report_type": "final_report",
            "title": "recovered",
            "data_status": "live",
            "lifecycle_status": "generated",
            "source_refs": [],
            "metadata": {},
        },
    )

    assert row.data_status == "live"
    assert row.lifecycle_status == "generated"


def test_report_artifact_and_tombstoned_parent_cannot_be_re_registered() -> None:
    session = _session()
    session.add(
        ReportItem(
            report_id="report-parent-purged",
            family="final_report_markdown",
            report_type="final_report",
            title="purged",
            data_status="unavailable",
            lifecycle_status="purged",
            source_refs=[],
            report_metadata={"output_cleanup": _marker()},
        )
    )
    session.add(
        ReportItem(
            report_id="report-artifact-purged",
            family="final_report_markdown",
            report_type="final_report",
            title="artifact tombstone parent",
            data_status="live",
            lifecycle_status="generated",
            source_refs=[],
            report_metadata={},
        )
    )
    session.add(
        ReportArtifact(
            artifact_id="artifact-purged",
            report_id="report-artifact-purged",
            artifact_type="analysis_md",
            file_path="storage/outputs/final_report/XAUUSD/2026-10-12/run/final.md",
            status="purged",
            source_refs=[],
            artifact_metadata={"output_cleanup": _marker()},
        )
    )
    session.commit()

    with pytest.raises(ValueError, match="OUTPUT_PURGED"):
        upsert_report_artifact(
            session,
            {
                "artifact_id": "artifact-purged",
                "report_id": "report-artifact-purged",
                "artifact_type": "analysis_md",
                "file_path": "storage/outputs/final_report/XAUUSD/2026-10-12/run/final.md",
                "status": "generated",
                "source_refs": [],
            },
        )

    saved_artifact = session.get(ReportArtifact, "artifact-purged")
    assert saved_artifact is not None
    assert saved_artifact.status == "purged"
    assert saved_artifact.artifact_metadata == {"output_cleanup": _marker()}

    with pytest.raises(ValueError, match="OUTPUT_PURGED"):
        upsert_report_artifact(
            session,
            {
                "artifact_id": "new-artifact",
                "report_id": "report-parent-purged",
                "artifact_type": "analysis_md",
                "file_path": "storage/outputs/final_report/XAUUSD/2026-10-12/run/new.md",
                "status": "generated",
                "source_refs": [],
            },
        )


def test_run_artifact_tombstone_blocks_same_identity_but_new_run_is_allowed(tmp_path: Path) -> None:
    session = _session()
    old_run = TaskRun(name="old", status=TaskStatus.success)
    new_run = TaskRun(name="new", status=TaskStatus.success)
    session.add_all([old_run, new_run])
    session.flush()
    old_path = f"storage/outputs/final_report/XAUUSD/2026-10-12/{old_run.id}/final.md"
    old_file = tmp_path / old_path
    old_file.parent.mkdir(parents=True, exist_ok=True)
    old_file.write_text("old", encoding="utf-8")
    session.add(
        RunArtifact(
            artifact_id=uuid4(),
            run_id=old_run.id,
            task_id=None,
            artifact_type="analysis_md",
            file_path=old_path,
            storage_backend="local_fs",
            sha256="a" * 64,
            byte_size=3,
            generated_at=datetime.now(timezone.utc),
            artifact_metadata={"output_cleanup": _marker(str(old_run.id))},
            metadata_json='{"output_cleanup":{"schema_version":1,"status":"purged"}}',
            structured_status="purged",
        )
    )
    session.commit()
    storage = LocalFileSystemArtifactStorage(root=tmp_path)

    with pytest.raises(ValueError, match="OUTPUT_PURGED"):
        register_artifact(
            session,
            run_id=str(old_run.id),
            artifact_type="analysis_md",
            file_path=old_path,
            storage=storage,
        )

    saved_old = session.scalar(select(RunArtifact).where(RunArtifact.run_id == old_run.id))
    assert saved_old is not None
    assert saved_old.structured_status == "purged"
    assert saved_old.artifact_metadata == {"output_cleanup": _marker(str(old_run.id))}

    new_path = f"storage/outputs/final_report/XAUUSD/2026-10-12/{new_run.id}/final.md"
    new_file = tmp_path / new_path
    new_file.parent.mkdir(parents=True, exist_ok=True)
    new_file.write_text("new", encoding="utf-8")
    row = register_artifact(
        session,
        run_id=str(new_run.id),
        artifact_type="analysis_md",
        file_path=new_path,
        storage=storage,
    )
    session.commit()

    assert row is not None
    assert session.scalar(select(RunArtifact).where(RunArtifact.run_id == new_run.id)) is not None
