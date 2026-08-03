from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.api.schemas.common import DataStatus, ReportLifecycleStatus
from apps.api.services import report_service
from database.models.analysis import ensure_analysis_tables
from database.models.report import ReportArtifact, ReportItem, ensure_report_tables
from database.models.task import TaskRun, TaskStatus, ensure_task_tables


def _session_factory() -> sessionmaker:
    engine = create_engine("sqlite:///:memory:")
    ensure_analysis_tables(engine)
    ensure_report_tables(engine)
    ensure_task_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _seed_macro_report(
    session,
    root: Path,
    *,
    run_id: str,
    status: TaskStatus,
    publish_allowed: bool | None = None,
) -> str:
    report_id = f"macro_report:{run_id}"
    relative_path = f"storage/outputs/macro/2026-08-03/{run_id}/macro_full_report.md"
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Macro\n", encoding="utf-8")
    if publish_allowed is not None:
        quality_path = (
            root
            / "storage"
            / "analysis"
            / "gold_mainlines"
            / "2026-08-03"
            / run_id
            / "quality_gate_result.json"
        )
        quality_path.parent.mkdir(parents=True, exist_ok=True)
        quality_path.write_text(f'{{"publish_allowed": {str(publish_allowed).lower()}}}', encoding="utf-8")
    session.add(TaskRun(id=uuid.UUID(run_id), name="premarket", status=status))
    session.add(
        ReportItem(
            report_id=report_id,
            family="macro_report",
            report_type="macro_report",
            title="XAUUSD macro",
            asset="XAUUSD",
            trade_date=date(2026, 8, 3),
            run_id=run_id,
            data_status="live",
            lifecycle_status="generated",
            source_refs=[],
        )
    )
    session.add(
        ReportArtifact(
            artifact_id=f"{report_id}:analysis",
            report_id=report_id,
            artifact_type="analysis_md",
            file_path=relative_path,
            status="generated",
            is_primary=True,
        )
    )
    session.commit()
    return report_id


def _seed_canonical_lineage(root: Path, *, run_id: str, valid: bool = True) -> None:
    snapshot_id = f"XAUUSD:2026-08-03:{run_id}"
    snapshot_path = (
        root
        / "storage"
        / "features"
        / "snapshots"
        / "XAUUSD"
        / "2026-08-03"
        / run_id
        / "premarket_snapshot.json"
    )
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(
        json.dumps(
            {
                "asset": "XAUUSD",
                "trade_date": "2026-08-03",
                "run_id": run_id,
                "snapshot_id": snapshot_id if valid else "XAUUSD:2026-08-03:wrong",
                "input_snapshot_ids": {"macro": f"macro:2026-08-03:{run_id}"},
                "source_refs": [
                    {
                        "source": "fred",
                        "source_url": "https://api.stlouisfed.org/fred/series/observations?series_id=DGS10",
                        "raw_path": "raw/macro/DGS10.json",
                        "retrieved_at": "2026-08-03T05:36:35Z",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    quality_path = (
        root
        / "storage"
        / "analysis"
        / "gold_mainlines"
        / "2026-08-03"
        / run_id
        / "quality_gate_result.json"
    )
    quality_path.parent.mkdir(parents=True, exist_ok=True)
    quality_path.write_text(
        json.dumps(
            {
                "publish_allowed": True,
                "trade_date": "2026-08-03",
                "run_id": run_id,
                "snapshot_id": snapshot_id,
            }
        ),
        encoding="utf-8",
    )


def test_failed_premarket_intermediate_report_is_not_live_authority(tmp_path: Path, monkeypatch) -> None:
    factory = _session_factory()
    run_id = "b204d78b-82a5-46bc-9913-f681c92a51ff"
    with factory() as session:
        report_id = _seed_macro_report(session, tmp_path, run_id=run_id, status=TaskStatus.failed)
        monkeypatch.setattr(report_service, "_PROJECT_ROOT", tmp_path)

        detail = report_service.get_report_detail(session, report_id)

    assert detail is not None
    assert detail.data_status == DataStatus.unavailable
    assert detail.lifecycle_status == ReportLifecycleStatus.needs_review
    assert {warning.code for warning in detail.warnings} >= {"upstream-task-not-successful"}


def test_report_index_hides_failed_premarket_but_keeps_success(tmp_path: Path, monkeypatch) -> None:
    factory = _session_factory()
    failed_id = "b204d78b-82a5-46bc-9913-f681c92a51ff"
    success_id = "c3515c79-3985-4702-b907-4bf0582ff978"
    with factory() as session:
        _seed_macro_report(session, tmp_path, run_id=failed_id, status=TaskStatus.failed)
        success_report_id = _seed_macro_report(
            session,
            tmp_path,
            run_id=success_id,
            status=TaskStatus.success,
            publish_allowed=True,
        )
        _seed_canonical_lineage(tmp_path, run_id=success_id)

    monkeypatch.setattr(report_service, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(report_service, "_try_db_session", factory)

    report_ids = {item["report_id"] for item in report_service.list_reports_index()["reports"]}

    assert f"macro_report:{failed_id}" not in report_ids
    assert success_report_id in report_ids


def test_quality_gate_blocked_successful_run_is_not_report_authority(tmp_path: Path, monkeypatch) -> None:
    factory = _session_factory()
    run_id = "c3515c79-3985-4702-b907-4bf0582ff978"
    with factory() as session:
        report_id = _seed_macro_report(
            session,
            tmp_path,
            run_id=run_id,
            status=TaskStatus.success,
            publish_allowed=False,
        )
        monkeypatch.setattr(report_service, "_PROJECT_ROOT", tmp_path)
        detail = report_service.get_report_detail(session, report_id)

    monkeypatch.setattr(report_service, "_try_db_session", factory)
    report_ids = {item["report_id"] for item in report_service.list_reports_index()["reports"]}

    assert detail is not None
    assert detail.data_status == DataStatus.unavailable
    assert {warning.code for warning in detail.warnings} >= {"quality-gate-blocked"}
    assert report_id not in report_ids


def test_allowed_macro_report_projects_exact_canonical_snapshot_lineage(
    tmp_path: Path, monkeypatch
) -> None:
    factory = _session_factory()
    run_id = "cfdb6579-ebcd-4913-b693-e38702323295"
    with factory() as session:
        report_id = _seed_macro_report(
            session,
            tmp_path,
            run_id=run_id,
            status=TaskStatus.success,
            publish_allowed=True,
        )
        _seed_canonical_lineage(tmp_path, run_id=run_id)
        monkeypatch.setattr(report_service, "_PROJECT_ROOT", tmp_path)

        detail = report_service.get_report_detail(session, report_id)

    assert detail is not None
    assert detail.data_status == DataStatus.partial
    assert detail.snapshot_id == f"XAUUSD:2026-08-03:{run_id}"
    assert detail.input_snapshot_ids == [f"macro:2026-08-03:{run_id}"]
    assert detail.source_refs[0].source_name == "fred"
    assert "api.stlouisfed.org" in detail.source_refs[0].url


def test_allowed_macro_report_without_valid_canonical_lineage_fails_closed(
    tmp_path: Path, monkeypatch
) -> None:
    factory = _session_factory()
    run_id = "cfdb6579-ebcd-4913-b693-e38702323295"
    with factory() as session:
        report_id = _seed_macro_report(
            session,
            tmp_path,
            run_id=run_id,
            status=TaskStatus.success,
            publish_allowed=True,
        )
        _seed_canonical_lineage(tmp_path, run_id=run_id, valid=False)
        monkeypatch.setattr(report_service, "_PROJECT_ROOT", tmp_path)

        detail = report_service.get_report_detail(session, report_id)

    assert detail is not None
    assert detail.data_status == DataStatus.unavailable
    assert detail.lifecycle_status == ReportLifecycleStatus.needs_review
    assert {warning.code for warning in detail.warnings} >= {"macro-lineage-unavailable"}
