"""Tests for CME worker pipeline.

Covers:
- CmePipelineState creation and field defaults
- run_cme_step dispatches to correct step functions
- Individual step logic with mocked dependencies
- Full pipeline chain from download → parse → ingest → options analysis
- Error handling: step failure propagation, partial_success path
- run_premarket integration (with SQLite, no real PDF download)
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.parsers.cme.pdf_parser import (
    CmePdfDetailRow,
    CmePdfParseResult,
    CmePdfSummaryRow,
)
from apps.premarket import PREMARKET_STEP_ORDER
from apps.worker.pipelines.cme import (
    CME_STEPS,
    CmePipelineState,
    run_cme_step,
)
from database.models.task import Base, StepStatus, TaskRun, TaskStatus, TaskStep
from database.queries.cme import ensure_cme_tables


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "options"
SAMPLE_ROWS_PATH = FIXTURES / "sample_option_rows.json"


def _make_db_session(tmp_path: Path):
    """Create a SQLite session with all tables."""
    engine = create_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}", echo=False)
    Base.metadata.create_all(engine)
    ensure_cme_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _make_sample_parse_result() -> CmePdfParseResult:
    """Create a minimal parse result for testing ingest without real PDF."""
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
        ),
        CmePdfDetailRow(
            trade_date="2026-05-06",
            product="OG",
            expiry="JUN26",
            strike=3400,
            option_type="PUT",
            settlement=5.0,
            delta=0.1,
            open_interest=200,
            oi_change=-5,
            total_volume=30,
            block_volume=0,
            pnt_volume=0,
            globex_volume=15,
            outcry_volume=5,
            exercises=0,
            pt_change=-0.5,
        ),
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
        ),
        CmePdfSummaryRow(
            expiry="JUN26",
            option_type="PUT",
            open_interest=200,
            oi_change=-5,
            total_volume=30,
            block_volume=0,
            pnt_volume=0,
            globex_volume=15,
            outcry_volume=5,
            exercises=0,
        ),
    ]
    return CmePdfParseResult(
        trade_date="2026-05-06",
        bulletin="PG64 Bulletin #1234",
        status="PRELIMINARY",
        product="OG",
        detail_rows=detail_rows,
        summary_rows=summary_rows,
        notes={"source_file": "test.pdf"},
        warnings=[],
    )


# ---------------------------------------------------------------------------
# Unit tests — CmePipelineState
# ---------------------------------------------------------------------------


class TestCmePipelineState:
    def test_defaults(self):
        state = CmePipelineState()
        assert state.raw_file is None
        assert state.parse_result is None
        assert state.ingest_result is None
        assert state.snapshot_dict is None
        assert state.report_md is None
        assert state.step_summaries == {}

    def test_step_summaries_updates(self):
        state = CmePipelineState()
        state.step_summaries["cme_download"] = {"status": "success"}
        assert state.step_summaries["cme_download"]["status"] == "success"


# ---------------------------------------------------------------------------
# Unit tests — run_cme_step dispatch
# ---------------------------------------------------------------------------


class TestRunCmeStepDispatch:
    def test_unknown_step_raises(self):
        state = CmePipelineState()
        db = MagicMock()
        with pytest.raises(ValueError, match="Unknown CME step"):
            run_cme_step("nonexistent_step", state, db=db)

    def test_cme_steps_are_well_defined(self):
        assert CME_STEPS == {"cme_download", "cme_parse", "cme_ingest", "option_wall"}


# ---------------------------------------------------------------------------
# Unit tests — individual step logic (mocked)
# ---------------------------------------------------------------------------


class TestStepDownload:
    def test_download_sets_raw_file(self):
        mock_raw = MagicMock()
        mock_raw.report_date = "2026-05-06"
        mock_raw.sha256 = "abc123"
        mock_raw.bytes = 1000
        mock_raw.raw_path = "storage/raw/cme/daily_bulletin/2026-05-06/test.pdf"
        mock_raw.source_url = "https://example.com"

        state = CmePipelineState()
        with patch("apps.worker.pipelines.cme.download_cme_pdf", return_value=mock_raw) as mock_dl:
            summary = run_cme_step(
                "cme_download", state, db=MagicMock(), storage_root=Path("."),
            )

        mock_dl.assert_called_once()
        assert state.raw_file is mock_raw
        assert summary["step"] == "cme_download"
        assert summary["status"] == "success"
        assert summary["report_date"] == "2026-05-06"
        assert summary["sha256"] == "abc123"


class TestStepParse:
    def test_parse_requires_download(self):
        state = CmePipelineState()
        with pytest.raises(RuntimeError, match="cme_parse requires cme_download"):
            run_cme_step("cme_parse", state, db=MagicMock())

    def test_parse_uses_pdf_path(self, tmp_path):
        # Create a mock PDF file
        pdf_dir = tmp_path / "raw"
        pdf_dir.mkdir(parents=True)
        pdf_file = pdf_dir / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 test")

        mock_raw = MagicMock()
        mock_raw.raw_path = "raw/test.pdf"

        mock_parse = _make_sample_parse_result()

        state = CmePipelineState()
        state.raw_file = mock_raw

        with patch("apps.worker.pipelines.cme.parse_pg64_pdf", return_value=mock_parse) as mock_p:
            summary = run_cme_step(
                "cme_parse", state, db=MagicMock(), storage_root=tmp_path,
            )

        mock_p.assert_called_once_with(pdf_file, product="OG")
        assert state.parse_result is mock_parse
        assert summary["detail_rows"] == 2
        assert summary["summary_rows"] == 2


class TestStepIngest:
    def test_ingest_requires_parse(self):
        state = CmePipelineState()
        state.raw_file = MagicMock()
        with pytest.raises(RuntimeError, match="cme_ingest requires cme_parse"):
            run_cme_step("cme_ingest", state, db=MagicMock())

    def test_ingest_writes_summary_json(self, tmp_path):
        mock_raw = MagicMock()
        mock_raw.raw_path = "raw/test.pdf"
        mock_raw.source_url = "https://example.com"

        mock_parse_result = _make_sample_parse_result()

        mock_ingest_result = MagicMock()
        mock_ingest_result.report_date = "2026-05-06"
        mock_ingest_result.raw_file_id = "abc-123"
        mock_ingest_result.inserted_rows = 2
        mock_ingest_result.existing_rows = 0
        mock_ingest_result.total_rows = 2
        mock_ingest_result.to_dict.return_value = {
            "report_date": "2026-05-06",
            "inserted_rows": 2,
            "total_rows": 2,
        }

        pdf_path = tmp_path / "raw" / "test.pdf"
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(b"%PDF-1.4 test")

        state = CmePipelineState()
        state.raw_file = mock_raw
        state.parse_result = mock_parse_result

        db = MagicMock()

        with patch("apps.worker.pipelines.cme.ingest_cme_parse_result", return_value=mock_ingest_result) as mock_ing:
            summary = run_cme_step(
                "cme_ingest", state, db=db, storage_root=tmp_path, run_id="run-a",
            )

        mock_ing.assert_called_once()
        assert state.ingest_result is mock_ingest_result
        assert summary["status"] == "success"
        assert summary["inserted_rows"] == 2

        # Verify summary JSON was written
        summary_path = tmp_path / "outputs" / "cme" / "2026-05-06" / "run-a" / "cme_ingest_summary.json"
        assert summary_path.exists()
        content = json.loads(summary_path.read_text())
        assert content["report_date"] == "2026-05-06"


class TestStepOptionsAnalysis:
    def test_options_requires_ingest(self):
        state = CmePipelineState()
        with pytest.raises(RuntimeError, match="option_wall requires cme_ingest"):
            run_cme_step("option_wall", state, db=MagicMock())

    def test_options_skips_when_no_rows(self, tmp_path):
        mock_ingest_result = MagicMock()
        mock_ingest_result.report_date = "2026-05-06"

        state = CmePipelineState()
        state.ingest_result = mock_ingest_result

        db = MagicMock()

        with patch("apps.worker.pipelines.cme.get_cme_option_rows", return_value=[]):
            summary = run_cme_step(
                "option_wall", state, db=db, storage_root=tmp_path,
            )

        assert summary["status"] == "skipped"
        assert "No option rows" in summary["reason"]

    def test_options_writes_json_and_md(self, tmp_path):
        """Test options analysis writes both JSON and MD files using real snapshot logic."""
        mock_ingest_result = MagicMock()
        mock_ingest_result.report_date = "2026-05-06"

        # Create mock option rows with all needed attributes
        mock_rows = []
        for row_data in json.loads(SAMPLE_ROWS_PATH.read_text())[:5]:
            mock_row = MagicMock()
            for k, v in row_data.items():
                setattr(mock_row, k, v)
            mock_rows.append(mock_row)

        state = CmePipelineState()
        state.ingest_result = mock_ingest_result

        db = MagicMock()

        with patch("apps.worker.pipelines.cme.get_cme_option_rows", return_value=mock_rows):
            summary = run_cme_step(
                "option_wall", state, db=db, storage_root=tmp_path, run_id="run-a",
            )

        assert summary["status"] == "success"
        assert summary["trade_date"] == "2026-05-06"
        assert summary["product"] == "OG"
        assert "walls_count" in summary
        assert "intent_type" in summary

        # Verify files were written
        json_path = tmp_path / "features" / "cme" / "2026-05-06" / "run-a" / "options_analysis.json"
        md_path = tmp_path / "outputs" / "cme" / "2026-05-06" / "run-a" / "options_analysis.md"
        visual_json_path = tmp_path / "outputs" / "cme" / "2026-05-06" / "run-a" / "options_visual_report.json"
        visual_html_path = tmp_path / "outputs" / "cme" / "2026-05-06" / "run-a" / "options_visual_report.html"
        assert json_path.exists()
        assert md_path.exists()
        assert visual_json_path.exists()
        assert visual_html_path.exists()

        json_content = json.loads(json_path.read_text())
        assert json_content["trade_date"] == "2026-05-06"
        assert "intent" in json_content

        md_content = md_path.read_text()
        assert "CME 黄金期权结构分析报告" in md_content

        # Verify state
        assert state.snapshot_dict is not None
        assert state.report_md is not None


# ---------------------------------------------------------------------------
# Integration test — full pipeline chain
# ---------------------------------------------------------------------------


class TestFullPipelineChain:
    def test_download_parse_ingest_options_chain(self, tmp_path):
        """Test the full pipeline chain with mocked download and parse."""
        mock_raw = MagicMock()
        mock_raw.report_date = "2026-05-06"
        mock_raw.sha256 = "abc123"
        mock_raw.bytes = 1000
        mock_raw.raw_path = "raw/test.pdf"
        mock_raw.source_url = "https://example.com"

        mock_parse_result = _make_sample_parse_result()

        # Create mock option rows for the options analysis step
        sample_rows = json.loads(SAMPLE_ROWS_PATH.read_text())[:5]
        mock_option_rows = []
        for row_data in sample_rows:
            mock_row = MagicMock()
            for k, v in row_data.items():
                setattr(mock_row, k, v)
            mock_option_rows.append(mock_row)

        # Create the PDF file for the parse step
        pdf_path = tmp_path / "raw" / "test.pdf"
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(b"%PDF-1.4 test")

        db = MagicMock()
        state = CmePipelineState()

        # Step 1: Download
        with patch("apps.worker.pipelines.cme.download_cme_pdf", return_value=mock_raw):
            s1 = run_cme_step("cme_download", state, db=db, storage_root=tmp_path, run_id="run-chain-a")
        assert s1["status"] == "success"
        assert state.raw_file is mock_raw

        # Step 2: Parse
        with patch("apps.worker.pipelines.cme.parse_pg64_pdf", return_value=mock_parse_result):
            s2 = run_cme_step("cme_parse", state, db=db, storage_root=tmp_path, run_id="run-chain-a")
        assert s2["status"] == "success"
        assert state.parse_result is mock_parse_result

        # Step 3: Ingest
        mock_ingest_result = MagicMock()
        mock_ingest_result.report_date = "2026-05-06"
        mock_ingest_result.to_dict.return_value = {"report_date": "2026-05-06", "inserted_rows": 2}

        with patch("apps.worker.pipelines.cme.ingest_cme_parse_result", return_value=mock_ingest_result):
            s3 = run_cme_step("cme_ingest", state, db=db, storage_root=tmp_path, run_id="run-chain-a")
        assert s3["status"] == "success"
        assert state.ingest_result is mock_ingest_result

        # Step 4: Options analysis
        with patch("apps.worker.pipelines.cme.get_cme_option_rows", return_value=mock_option_rows):
            s4 = run_cme_step("option_wall", state, db=db, storage_root=tmp_path, run_id="run-chain-a")
        assert s4["status"] == "success"
        assert state.snapshot_dict is not None
        assert state.report_md is not None

        # Verify all outputs
        parsed_dir = tmp_path / "parsed" / "cme" / "2026-05-06" / "run-chain-a"
        features_dir = tmp_path / "features" / "cme" / "2026-05-06" / "run-chain-a"
        out_dir = tmp_path / "outputs" / "cme" / "2026-05-06" / "run-chain-a"
        assert (parsed_dir / "cme_parse_result.json").exists()
        assert (out_dir / "cme_ingest_summary.json").exists()
        assert (features_dir / "options_analysis.json").exists()
        assert (out_dir / "options_analysis.md").exists()
        assert (out_dir / "options_visual_report.json").exists()
        assert (out_dir / "options_visual_report.html").exists()

        # Verify step_summaries
        assert len(state.step_summaries) == 4
        assert set(state.step_summaries.keys()) == CME_STEPS

    def test_same_date_runs_keep_history(self, tmp_path):
        """Repeated same-date CME runs land in distinct run directories."""
        mock_raw = MagicMock()
        mock_raw.report_date = "2026-05-06"
        mock_raw.sha256 = "abc123"
        mock_raw.bytes = 1000
        mock_raw.raw_path = "raw/test.pdf"
        mock_raw.source_url = "https://example.com"
        mock_parse_result = _make_sample_parse_result()

        sample_rows = json.loads(SAMPLE_ROWS_PATH.read_text())[:5]
        mock_option_rows = []
        for row_data in sample_rows:
            mock_row = MagicMock()
            for k, v in row_data.items():
                setattr(mock_row, k, v)
            mock_option_rows.append(mock_row)

        pdf_path = tmp_path / "raw" / "test.pdf"
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(b"%PDF-1.4 test")

        db = MagicMock()

        def run_chain(run_id: str) -> tuple[Path, Path]:
            state = CmePipelineState()
            with patch("apps.worker.pipelines.cme.download_cme_pdf", return_value=mock_raw):
                run_cme_step("cme_download", state, db=db, storage_root=tmp_path, run_id=run_id)
            with patch("apps.worker.pipelines.cme.parse_pg64_pdf", return_value=mock_parse_result):
                run_cme_step("cme_parse", state, db=db, storage_root=tmp_path, run_id=run_id)

            mock_ingest_result = MagicMock()
            mock_ingest_result.report_date = "2026-05-06"
            mock_ingest_result.raw_file_id = 1
            mock_ingest_result.to_dict.return_value = {"report_date": "2026-05-06", "inserted_rows": 2}

            with patch("apps.worker.pipelines.cme.ingest_cme_parse_result", return_value=mock_ingest_result):
                run_cme_step("cme_ingest", state, db=db, storage_root=tmp_path, run_id=run_id)
            with patch("apps.worker.pipelines.cme.get_cme_option_rows", return_value=mock_option_rows):
                summary = run_cme_step("option_wall", state, db=db, storage_root=tmp_path, run_id=run_id)
            return Path(summary["json_path"]), Path(summary["md_path"])

        json_a, md_a = run_chain("run-a")
        json_b, md_b = run_chain("run-b")

        assert json_a.exists()
        assert md_a.exists()
        assert json_b.exists()
        assert md_b.exists()
        assert json_a != json_b
        assert md_a != md_b

        payload_a = json.loads(json_a.read_text(encoding="utf-8"))
        payload_b = json.loads(json_b.read_text(encoding="utf-8"))
        payload_a.pop("generated_at", None)
        payload_b.pop("generated_at", None)
        assert payload_a == payload_b


# ---------------------------------------------------------------------------
# Status mapping tests (P3-REVIEW-FIX-05 blockers 1 & 3)
# ---------------------------------------------------------------------------


class TestStatusMapping:
    """Verify the parse status → source_status mapping and provenance."""

    def _make_state_with_parse_status(
        self, parse_status: str
    ) -> tuple[CmePipelineState, MagicMock, MagicMock, MagicMock, list]:
        """Return (state, mock_raw, mock_ingest_result, mock_db, mock_option_rows)."""
        mock_raw = MagicMock()
        mock_raw.report_date = "2026-05-06"
        mock_raw.sha256 = "abc123"
        mock_raw.source_url = "https://example.com/bulletin.pdf"
        mock_raw.raw_path = "raw/test.pdf"

        mock_parse = _make_sample_parse_result()
        # Override the status for test purposes
        mock_parse = CmePdfParseResult(
            trade_date=mock_parse.trade_date,
            bulletin=mock_parse.bulletin,
            status=parse_status,
            product=mock_parse.product,
            detail_rows=mock_parse.detail_rows,
            summary_rows=mock_parse.summary_rows,
            notes=mock_parse.notes,
            warnings=mock_parse.warnings,
        )

        mock_ingest_result = MagicMock()
        mock_ingest_result.report_date = "2026-05-06"
        mock_ingest_result.raw_file_id = "raw-abc-123"
        mock_ingest_result.parse_run_id = "parse-run-xyz-456"
        mock_ingest_result.to_dict.return_value = {
            "report_date": "2026-05-06",
            "inserted_rows": 2,
            "raw_file_id": "raw-abc-123",
            "parse_run_id": "parse-run-xyz-456",
        }

        state = CmePipelineState()
        state.raw_file = mock_raw
        state.parse_result = mock_parse
        state.ingest_result = mock_ingest_result

        sample_rows = json.loads(SAMPLE_ROWS_PATH.read_text())[:5]
        mock_option_rows = []
        for row_data in sample_rows:
            mock_row = MagicMock()
            for k, v in row_data.items():
                setattr(mock_row, k, v)
            mock_option_rows.append(mock_row)

        db = MagicMock()
        return state, mock_raw, mock_ingest_result, db, mock_option_rows

    def test_final_status_propagates_to_option_wall_summary(self, tmp_path):
        """FINAL must reach the snapshot, not be overridden to PRELIM_assumed."""
        state, _, _, db, mock_option_rows = self._make_state_with_parse_status("FINAL")

        with patch(
            "apps.worker.pipelines.cme.get_cme_option_rows",
            return_value=mock_option_rows,
        ):
            summary = run_cme_step(
                "option_wall", state, db=db, storage_root=tmp_path, run_id="run-final",
            )

        assert summary["data_source_status"] == "FINAL"
        assert summary["data_quality_categories"]["prelim_data"] == 0
        # Verify the JSON artifact also carries FINAL
        json_path = (
            tmp_path / "features" / "cme"
            / "2026-05-06" / "run-final" / "options_analysis.json"
        )
        payload = json.loads(json_path.read_text())
        assert payload["data_source"]["status"] == "FINAL"

    def test_preliminary_status_normalizes_to_prelim_in_option_wall(self, tmp_path):
        """PRELIMINARY from parser normalises to PRELIM in snapshot."""
        state, _, _, db, mock_option_rows = self._make_state_with_parse_status("PRELIMINARY")

        with patch(
            "apps.worker.pipelines.cme.get_cme_option_rows",
            return_value=mock_option_rows,
        ):
            summary = run_cme_step(
                "option_wall", state, db=db, storage_root=tmp_path, run_id="run-prelim",
            )

        # _map_parse_status normalises PRELIMINARY → PRELIM
        assert summary["data_source_status"] == "PRELIM"
        assert summary["data_quality_categories"]["prelim_data"] > 0

    def test_unknown_status_falls_back_to_prelim_assumed(self, tmp_path):
        """UNKNOWN or missing parse → PRELIM_assumed with prelim_data counting."""
        state, _, _, db, mock_option_rows = self._make_state_with_parse_status("UNKNOWN")

        with patch(
            "apps.worker.pipelines.cme.get_cme_option_rows",
            return_value=mock_option_rows,
        ):
            summary = run_cme_step(
                "option_wall", state, db=db, storage_root=tmp_path, run_id="run-unknown",
            )

        assert summary["data_source_status"] == "PRELIM_assumed"
        # PRELIM_assumed starts with PRELIM, so counts as prelim_data
        assert summary["data_quality_categories"]["prelim_data"] > 0

    def test_input_snapshot_ids_include_parse_run_id(self, tmp_path):
        """input_snapshot_ids must carry parse_run_id when available."""
        state, _, _, db, mock_option_rows = self._make_state_with_parse_status("FINAL")

        with patch(
            "apps.worker.pipelines.cme.get_cme_option_rows",
            return_value=mock_option_rows,
        ):
            summary = run_cme_step(
                "option_wall", state, db=db, storage_root=tmp_path, run_id="run-provenance",
            )

        assert summary["input_snapshot_ids"]["parse_run_id"] == "parse-run-xyz-456"
        assert "raw_file_sha256" in summary["input_snapshot_ids"]
        assert "raw_file_id" in summary["input_snapshot_ids"]

    def test_input_snapshot_ids_no_parse_run_id_if_unavailable(self, tmp_path):
        """When ingest_result lacks parse_run_id, it must not be invented."""
        state, _, _, db, mock_option_rows = self._make_state_with_parse_status("FINAL")
        state.ingest_result.parse_run_id = None  # simulate missing

        with patch(
            "apps.worker.pipelines.cme.get_cme_option_rows",
            return_value=mock_option_rows,
        ):
            summary = run_cme_step(
                "option_wall", state, db=db, storage_root=tmp_path, run_id="run-no-parse",
            )

        assert "parse_run_id" not in summary["input_snapshot_ids"]


# ---------------------------------------------------------------------------
# Integration test — run_premarket
# ---------------------------------------------------------------------------


class TestRunPremarket:
    def _make_task_with_steps(self, db, step_names):
        task = TaskRun(name="premarket", status=TaskStatus.pending)
        db.add(task)
        db.flush()

        for name in step_names:
            step = TaskStep(task_run_id=task.id, name=name, status=StepStatus.pending)
            db.add(step)

        db.commit()
        return task

    def test_cme_steps_succeed(self, tmp_path):
        """Test that run_premarket marks CME steps as success with mocked pipeline."""
        db = _make_db_session(tmp_path)
        task = self._make_task_with_steps(
            db,
            ["macro_collect", "cme_download", "cme_parse", "cme_ingest", "option_wall", "report_render"],
        )

        # Mock the entire CME pipeline
        mock_step_results = {
            "cme_download": {"step": "cme_download", "status": "success"},
            "cme_parse": {"step": "cme_parse", "status": "success"},
            "cme_ingest": {"step": "cme_ingest", "status": "success"},
            "option_wall": {"step": "option_wall", "status": "success"},
        }

        def mock_run_step(step_name, state, **kwargs):
            return mock_step_results[step_name]

        def mock_macro_step(step_name, state, **kwargs):
            return {"step": step_name, "status": "success"}

        with (
            patch("apps.worker.pipelines.cme.run_cme_step", side_effect=mock_run_step),
            patch("apps.worker.pipelines.macro.run_macro_step", side_effect=mock_macro_step),
        ):
            from apps.worker.runner import run_premarket
            result = run_premarket(db, task.id, storage_root=tmp_path)

        assert result == TaskStatus.success

        # Verify task and step states
        db.refresh(task)
        assert task.status == TaskStatus.success

        for step in task.steps:
            assert step.status == StepStatus.success
            assert step.finished_at is not None
            assert step.started_at is not None

    def test_cme_failure_produces_partial_success(self, tmp_path):
        """Test that a CME step failure produces partial_success when other steps succeed."""
        db = _make_db_session(tmp_path)
        task = self._make_task_with_steps(
            db,
            ["macro_collect", "cme_download", "cme_parse", "cme_ingest", "option_wall", "report_render"],
        )

        def mock_run_step(step_name, state, **kwargs):
            if step_name == "cme_download":
                raise RuntimeError("Network error: CME download failed")
            return {"step": step_name, "status": "success"}

        def mock_macro_step(step_name, state, **kwargs):
            return {"step": step_name, "status": "success"}

        with (
            patch("apps.worker.pipelines.cme.run_cme_step", side_effect=mock_run_step),
            patch("apps.worker.pipelines.macro.run_macro_step", side_effect=mock_macro_step),
        ):
            from apps.worker.runner import run_premarket
            result = run_premarket(db, task.id, storage_root=tmp_path)

        assert result == TaskStatus.partial_success

        # Verify the download step failed but others succeeded
        db.refresh(task)
        assert task.status == TaskStatus.partial_success

        steps_by_name = {s.name: s for s in task.steps}
        assert steps_by_name["cme_download"].status == StepStatus.failed
        assert steps_by_name["cme_download"].error == "Network error: CME download failed"
        assert steps_by_name["macro_collect"].status == StepStatus.success
        assert steps_by_name["report_render"].status == StepStatus.success

    def test_runner_orders_steps_deterministically(self, tmp_path):
        """Task steps execute in canonical business order even if DB returns them shuffled."""
        db = _make_db_session(tmp_path)
        shuffled_names = [
            "strategy_card",
            "news_brief",
            "news_feature",
            "news_collect",
            "report_render",
            "option_wall",
            "cme_ingest",
            "cme_parse",
            "macro_feature",
            "cme_download",
            "macro_collect",
        ]
        task = self._make_task_with_steps(db, shuffled_names)

        timestamps = [
            datetime(2026, 5, 6, 9, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=i)
            for i in range(len(shuffled_names) * 2)
        ]

        def mock_run_cme_step(step_name, state, **kwargs):
            return {"step": step_name, "status": "success"}

        def mock_run_macro_step(step_name, state, **kwargs):
            return {"step": step_name, "status": "success"}

        def mock_run_news_step(step_name, state, **kwargs):
            return {"step": step_name, "status": "success"}

        with (
            patch("apps.worker.pipelines.cme.run_cme_step", side_effect=mock_run_cme_step),
            patch("apps.worker.pipelines.macro.run_macro_step", side_effect=mock_run_macro_step),
            patch("apps.worker.pipelines.news.run_news_step", side_effect=mock_run_news_step),
            patch("apps.worker.runner._now", side_effect=timestamps),
        ):
            from apps.worker.runner import run_premarket

            result = run_premarket(db, task.id, storage_root=tmp_path)

        assert result == TaskStatus.success

        db.refresh(task)
        ordered_step_names = [step.name for step in sorted(task.steps, key=lambda step: step.started_at)]
        assert ordered_step_names == list(PREMARKET_STEP_ORDER)

    def test_skipped_summary_maps_to_skipped_step(self, tmp_path):
        """A pipeline summary with skipped status should persist as skipped, not success."""
        db = _make_db_session(tmp_path)
        task = self._make_task_with_steps(
            db,
            ["macro_collect", "macro_feature", "cme_download", "cme_parse", "cme_ingest", "option_wall", "report_render"],
        )

        def mock_run_cme_step(step_name, state, **kwargs):
            if step_name == "option_wall":
                return {"step": step_name, "status": "skipped", "reason": "No option rows"}
            return {"step": step_name, "status": "success"}

        def mock_run_macro_step(step_name, state, **kwargs):
            return {"step": step_name, "status": "success"}

        with (
            patch("apps.worker.pipelines.cme.run_cme_step", side_effect=mock_run_cme_step),
            patch("apps.worker.pipelines.macro.run_macro_step", side_effect=mock_run_macro_step),
        ):
            from apps.worker.runner import run_premarket

            result = run_premarket(db, task.id, storage_root=tmp_path)

        assert result == TaskStatus.success
        db.refresh(task)
        steps_by_name = {s.name: s for s in task.steps}
        assert steps_by_name["option_wall"].status == StepStatus.skipped
        assert steps_by_name["option_wall"].error is None
        assert task.status == TaskStatus.success

    def test_single_failed_step_marks_task_failed(self, tmp_path):
        """If every executed step fails, the task should end in failed rather than partial_success."""
        db = _make_db_session(tmp_path)
        task = self._make_task_with_steps(db, ["cme_download"])

        def mock_run_cme_step(step_name, state, **kwargs):
            raise RuntimeError("Network error: CME download failed")

        with patch("apps.worker.pipelines.cme.run_cme_step", side_effect=mock_run_cme_step):
            from apps.worker.runner import run_premarket

            result = run_premarket(db, task.id, storage_root=tmp_path)

        assert result == TaskStatus.failed
        db.refresh(task)
        assert task.status == TaskStatus.failed
        assert task.steps[0].status == StepStatus.failed
        assert task.steps[0].error == "Network error: CME download failed"

    def test_partial_success_summary_marks_task_partial_success(self, tmp_path):
        """A pipeline partial_success summary keeps the step non-failed but downgrades the task."""
        db = _make_db_session(tmp_path)
        task = self._make_task_with_steps(db, ["macro_collect", "cme_download", "report_render"])

        def mock_run_cme_step(step_name, state, **kwargs):
            return {"step": step_name, "status": "partial_success", "warning": "some contracts unavailable"}

        def mock_run_macro_step(step_name, state, **kwargs):
            return {"step": step_name, "status": "success"}

        with (
            patch("apps.worker.pipelines.cme.run_cme_step", side_effect=mock_run_cme_step),
            patch("apps.worker.pipelines.macro.run_macro_step", side_effect=mock_run_macro_step),
        ):
            from apps.worker.runner import run_premarket

            result = run_premarket(db, task.id, storage_root=tmp_path)

        assert result == TaskStatus.partial_success
        db.refresh(task)
        steps_by_name = {s.name: s for s in task.steps}
        assert task.status == TaskStatus.partial_success
        assert steps_by_name["cme_download"].status == StepStatus.success
        assert steps_by_name["cme_download"].error is None

    def test_unknown_summary_status_marks_step_failed(self, tmp_path):
        """Unknown pipeline statuses must fail closed instead of being treated as success."""
        db = _make_db_session(tmp_path)
        task = self._make_task_with_steps(db, ["cme_download"])

        def mock_run_cme_step(step_name, state, **kwargs):
            return {"step": step_name, "status": "mystery"}

        with patch("apps.worker.pipelines.cme.run_cme_step", side_effect=mock_run_cme_step):
            from apps.worker.runner import run_premarket

            result = run_premarket(db, task.id, storage_root=tmp_path)

        assert result == TaskStatus.failed
        db.refresh(task)
        assert task.status == TaskStatus.failed
        assert task.steps[0].status == StepStatus.failed
        assert task.steps[0].error == "Unknown pipeline summary status: mystery"

    def test_task_not_found_returns_failed(self, tmp_path):
        """Test that a non-existent task_id returns TaskStatus.failed."""
        db = _make_db_session(tmp_path)
        import uuid as _uuid
        from apps.worker.runner import run_premarket
        result = run_premarket(db, _uuid.uuid4(), storage_root=tmp_path)
        assert result == TaskStatus.failed
