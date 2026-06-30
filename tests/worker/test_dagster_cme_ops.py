from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.collectors.cme.downloader import CmeRawFile
from apps.parsers.cme.pdf_parser import CmePdfDetailRow, CmePdfParseResult, CmePdfSummaryRow
from apps.worker.pipelines.cme import CmePipelineState
from dagster_finance.ops.cme import CmeConfig, cme_download_op, cme_ingest_op, cme_parse_op, option_wall_op
from database.models.execution import ExecutionEvent, RunArtifact, ensure_execution_tables
from database.models.task import TaskRun, TaskStatus, ensure_task_tables
from database.queries.cme import CmeIngestResult

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "options"
SAMPLE_ROWS_PATH = FIXTURES / "sample_option_rows.json"


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


def _option_rows() -> list[MagicMock]:
    rows = []
    for row_data in json.loads(SAMPLE_ROWS_PATH.read_text(encoding="utf-8"))[:5]:
        row = MagicMock()
        for key, value in row_data.items():
            setattr(row, key, value)
        rows.append(row)
    return rows


def _raw_file(tmp_path: Path) -> CmeRawFile:
    raw_path = Path("raw") / "cme" / "daily_bulletin" / "2026-05-06" / "section64.pdf"
    target = tmp_path / raw_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"%PDF-1.4 fixture")
    return CmeRawFile(
        source="cme",
        section="Section64_Metals_Option_Products.pdf",
        source_url="https://www.cmegroup.com/daily_bulletin/current/Section64_Metals_Option_Products.pdf",
        raw_path=raw_path.as_posix(),
        sha256="abc123",
        report_date="2026-05-06",
        bytes=1024,
        retrieved_at="2026-05-06T12:00:00+00:00",
        date_source="fixture",
    )


def _parse_result() -> CmePdfParseResult:
    detail_rows = [
        CmePdfDetailRow(
            trade_date="2026-05-06",
            product="OG",
            expiry="JUN26",
            strike=3400,
            option_type="CALL",
            settlement=200.0,
            delta=0.9,
            open_interest=100,
            oi_change=10,
            total_volume=50,
            block_volume=5,
            pnt_volume=3,
            globex_volume=20,
            outcry_volume=10,
            exercises=0,
            pt_change=2.0,
        )
    ]
    summary_rows = [
        CmePdfSummaryRow(
            expiry="JUN26",
            option_type="CALL",
            open_interest=100,
            oi_change=10,
            total_volume=50,
            block_volume=5,
            pnt_volume=3,
            globex_volume=20,
            outcry_volume=10,
            exercises=0,
        )
    ]
    return CmePdfParseResult(
        trade_date="2026-05-06",
        bulletin="PG64 Bulletin #1234",
        status="PRELIMINARY",
        product="OG",
        detail_rows=detail_rows,
        summary_rows=summary_rows,
        notes={"source_file": "section64.pdf"},
        warnings=[],
    )


def _cme_state() -> CmePipelineState:
    return CmePipelineState(
        raw_file=CmeRawFile(
            source="cme",
            section="Section64_Metals_Option_Products.pdf",
            source_url="https://www.cmegroup.com/daily_bulletin/current/Section64_Metals_Option_Products.pdf",
            raw_path="raw/cme/daily_bulletin/2026-05-06/section64.pdf",
            sha256="abc123",
            report_date="2026-05-06",
            bytes=1024,
            retrieved_at="2026-05-06T12:00:00+00:00",
            date_source="fixture",
        ),
        ingest_result=CmeIngestResult(
            raw_file_id="raw-file-1",
            report_date="2026-05-06",
            inserted_rows=5,
            existing_rows=0,
            total_rows=5,
            warnings_count=0,
            detail_rows_count=5,
            summary_rows_count=0,
            parse_run_id="parse-run-1",
            sha256="abc123",
        ),
    )


def test_option_wall_op_registers_cme_option_artifacts_in_run_artifact_registry(tmp_path) -> None:
    session = _make_session()
    run_id = uuid.uuid4()
    session.add(
        TaskRun(
            id=run_id,
            name="premarket_job",
            task_type="premarket",
            status=TaskStatus.running,
            snapshot_id="cme-options:2026-05-06",
            trade_date="2026-05-06",
        )
    )
    session.commit()
    context = SimpleNamespace(
        run_id=str(run_id),
        resources=SimpleNamespace(db_session=session),
        log=SimpleNamespace(info=lambda *_args, **_kwargs: None, warning=lambda *_args, **_kwargs: None),
    )

    with (
        patch("apps.worker.pipelines.cme.get_cme_option_rows", return_value=_option_rows()),
        patch("apps.worker.pipelines.cme.get_available_cme_trade_dates", return_value=[]),
    ):
        option_wall_op.compute_fn.decorated_fn(
            context,
            _cme_state(),
            CmeConfig(storage_root=str(tmp_path)),
        )

    artifacts = session.query(RunArtifact).order_by(RunArtifact.file_path.asc()).all()
    assert {artifact.run_id for artifact in artifacts} == {run_id}
    assert {Path(artifact.file_path).name for artifact in artifacts} == {
        "options_analysis.json",
        "options_analysis.md",
        "options_visual_report.html",
        "options_visual_report.json",
    }
    assert {artifact.artifact_type for artifact in artifacts} == {"analysis_md", "feature_json", "visual_html"}
    assert all(artifact.source_refs_data for artifact in artifacts)
    assert all(artifact.artifact_metadata["input_snapshot_ids"]["parse_run_id"] == "parse-run-1" for artifact in artifacts)


def test_cme_dagster_download_parse_ingest_ops_register_written_artifacts(tmp_path) -> None:
    session = _make_session()
    run_id = uuid.uuid4()
    session.add(
        TaskRun(
            id=run_id,
            name="premarket_job",
            task_type="premarket",
            status=TaskStatus.running,
            trade_date="2026-05-06",
        )
    )
    session.commit()
    context = SimpleNamespace(
        run_id=str(run_id),
        resources=SimpleNamespace(db_session=session),
        log=SimpleNamespace(info=lambda *_args, **_kwargs: None, warning=lambda *_args, **_kwargs: None),
    )

    with (
        patch("apps.worker.pipelines.cme.download_cme_pdf", return_value=_raw_file(tmp_path)),
        patch("apps.worker.pipelines.cme.parse_pg64_pdf", return_value=_parse_result()),
        patch(
            "apps.worker.pipelines.cme.ingest_cme_parse_result",
            return_value=CmeIngestResult(
                raw_file_id="raw-file-1",
                report_date="2026-05-06",
                inserted_rows=1,
                existing_rows=0,
                total_rows=1,
                warnings_count=0,
                detail_rows_count=1,
                summary_rows_count=1,
                parse_run_id="parse-run-1",
                sha256="abc123",
            ),
        ),
    ):
        state = cme_download_op.compute_fn.decorated_fn(context, CmePipelineState(), CmeConfig(storage_root=str(tmp_path)))
        state = cme_parse_op.compute_fn.decorated_fn(context, state, CmeConfig(storage_root=str(tmp_path)))
        cme_ingest_op.compute_fn.decorated_fn(context, state, CmeConfig(storage_root=str(tmp_path)))

    artifacts = session.query(RunArtifact).order_by(RunArtifact.file_path.asc()).all()
    assert {artifact.run_id for artifact in artifacts} == {run_id}
    assert {Path(artifact.file_path).name for artifact in artifacts} == {
        "cme_ingest_summary.json",
        "cme_parse_result.json",
        "section64.pdf",
    }
    assert {artifact.artifact_type for artifact in artifacts} == {"feature_json", "parsed_file", "raw_file"}
    assert all(artifact.source_refs_data for artifact in artifacts)
    artifacts_by_name = {Path(artifact.file_path).name: artifact for artifact in artifacts}
    assert artifacts_by_name["section64.pdf"].artifact_metadata["lineage_kind"] == "source_input"
    assert artifacts_by_name["cme_parse_result.json"].artifact_metadata["input_snapshot_ids"]["raw_file_sha256"] == "abc123"
    assert artifacts_by_name["cme_ingest_summary.json"].artifact_metadata["input_snapshot_ids"]["parse_run_id"] == "parse-run-1"


def test_cme_dagster_download_parse_ingest_ops_emit_standard_timeline_events(tmp_path) -> None:
    session = _make_session()
    run_id = uuid.uuid4()
    session.add(
        TaskRun(
            id=run_id,
            name="premarket_job",
            task_type="premarket",
            status=TaskStatus.running,
            trade_date="2026-05-06",
        )
    )
    session.commit()
    context = SimpleNamespace(
        run_id=str(run_id),
        resources=SimpleNamespace(db_session=session),
        log=SimpleNamespace(info=lambda *_args, **_kwargs: None, warning=lambda *_args, **_kwargs: None),
    )

    with (
        patch("apps.worker.pipelines.cme.download_cme_pdf", return_value=_raw_file(tmp_path)),
        patch("apps.worker.pipelines.cme.parse_pg64_pdf", return_value=_parse_result()),
        patch(
            "apps.worker.pipelines.cme.ingest_cme_parse_result",
            return_value=CmeIngestResult(
                raw_file_id="raw-file-1",
                report_date="2026-05-06",
                inserted_rows=1,
                existing_rows=0,
                total_rows=1,
                warnings_count=0,
                detail_rows_count=1,
                summary_rows_count=1,
                parse_run_id="parse-run-1",
                sha256="abc123",
            ),
        ),
    ):
        state = cme_download_op.compute_fn.decorated_fn(context, CmePipelineState(), CmeConfig(storage_root=str(tmp_path)))
        state = cme_parse_op.compute_fn.decorated_fn(context, state, CmeConfig(storage_root=str(tmp_path)))
        cme_ingest_op.compute_fn.decorated_fn(context, state, CmeConfig(storage_root=str(tmp_path)))

    events = session.query(ExecutionEvent).filter(ExecutionEvent.run_id == run_id).all()
    standard_events = {
        event.event_type: json.loads(event.payload)
        for event in events
        if event.event_type in {"SOURCE_COLLECTED", "DATA_PARSED", "FEATURE_COMPUTED"}
    }

    assert set(standard_events) == {"SOURCE_COLLECTED", "DATA_PARSED", "FEATURE_COMPUTED"}
    assert standard_events["SOURCE_COLLECTED"] == {
        "source": "cme_daily_bulletin",
        "raw_path": "raw/cme/daily_bulletin/2026-05-06/section64.pdf",
        "report_date": "2026-05-06",
        "sha256": "abc123",
    }
    assert standard_events["DATA_PARSED"] == {
        "source": "cme_daily_bulletin",
        "parsed_path": str(tmp_path / "parsed" / "cme" / "2026-05-06" / str(run_id) / "cme_parse_result.json"),
        "trade_date": "2026-05-06",
        "detail_rows": 1,
        "summary_rows": 1,
    }
    assert standard_events["FEATURE_COMPUTED"] == {
        "source": "cme_daily_bulletin",
        "summary_path": str(tmp_path / "outputs" / "cme" / "2026-05-06" / str(run_id) / "cme_ingest_summary.json"),
        "report_date": "2026-05-06",
        "detail_rows": 1,
        "summary_rows": 1,
        "total_rows": 1,
    }
