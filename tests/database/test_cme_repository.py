from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from apps.parsers.cme.pdf_parser import CmePdfParseResult, parse_pg64_pdf
from database.models.cme import CmeOptionRow, CmeParseRun, CmeRawFile
from database.queries.cme import (
    ensure_cme_tables,
    get_cme_option_rows,
    get_latest_cme_raw_file,
    ingest_cme_parse_result,
)


PDF_PATH = Path("storage/raw/cme/daily_bulletin/2026-05-06/Section64_Metals_Option_Products_2026-05-06.pdf")


def _resolve_pdf_path() -> Path:
    if PDF_PATH.exists():
        return PDF_PATH
    pytest.skip("CME PDF fixture is not available")


def _make_session(tmp_path: Path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'cme.db').as_posix()}", echo=False)
    ensure_cme_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_cme_parse_result_can_be_ingested_and_metadata_is_preserved(tmp_path: Path) -> None:
    pdf_path = _resolve_pdf_path()
    parse_result = parse_pg64_pdf(pdf_path, product="OG", expiries={"JUN26", "JUL26"})

    session = _make_session(tmp_path)
    try:
        result = ingest_cme_parse_result(session, raw_pdf_path=pdf_path, parse_result=parse_result)
        session.commit()

        raw_file = session.scalar(select(CmeRawFile).where(CmeRawFile.id == result.raw_file_id))
        parse_run = session.scalar(select(CmeParseRun).where(CmeParseRun.raw_file_id == result.raw_file_id))
        rows = session.scalars(select(CmeOptionRow).where(CmeOptionRow.raw_file_id == result.raw_file_id)).all()
    finally:
        session.close()

    assert result.detail_rows_count == len(parse_result.detail_rows)
    assert result.total_rows == result.detail_rows_count
    assert result.inserted_rows == result.total_rows
    assert result.existing_rows == 0
    assert result.inserted_rows == len(rows)
    assert result.warnings_count == len(parse_result.warnings)
    assert raw_file is not None
    assert raw_file.report_date == "2026-05-06"
    assert raw_file.sha256 == result.sha256
    assert parse_run is not None
    assert json.loads(parse_run.warnings_json) == parse_result.warnings
    assert json.loads(parse_run.notes_json) == parse_result.notes


def test_duplicate_ingest_is_idempotent(tmp_path: Path) -> None:
    pdf_path = _resolve_pdf_path()
    parse_result = parse_pg64_pdf(pdf_path, product="OG", expiries={"JUN26", "JUL26"})

    session = _make_session(tmp_path)
    try:
        first = ingest_cme_parse_result(session, raw_pdf_path=pdf_path, parse_result=parse_result)
        session.commit()
        second = ingest_cme_parse_result(session, raw_pdf_path=pdf_path, parse_result=parse_result)
        session.commit()

        raw_file_count = session.scalar(select(func.count()).select_from(CmeRawFile))
        row_count = session.scalar(select(func.count()).select_from(CmeOptionRow))
        parse_run_count = session.scalar(select(func.count()).select_from(CmeParseRun))
    finally:
        session.close()

    assert first.total_rows == len(parse_result.detail_rows)
    assert first.inserted_rows == first.total_rows
    assert first.existing_rows == 0
    assert second.inserted_rows == 0
    assert second.total_rows == first.total_rows
    assert second.existing_rows == first.total_rows
    assert raw_file_count == 1
    assert row_count == first.total_rows
    assert parse_run_count == 1


def test_newer_raw_file_with_same_contract_keys_is_blocked(tmp_path: Path) -> None:
    pdf_path = _resolve_pdf_path()
    parse_result = parse_pg64_pdf(pdf_path, product="OG", expiries={"JUN26", "JUL26"})
    conflict_pdf = tmp_path / "conflict" / pdf_path.name
    conflict_pdf.parent.mkdir(parents=True, exist_ok=True)
    conflict_pdf.write_bytes(pdf_path.read_bytes() + b"\n% conflicting raw file\n")

    session = _make_session(tmp_path)
    try:
        first = ingest_cme_parse_result(session, raw_pdf_path=pdf_path, parse_result=parse_result)
        session.commit()

        with pytest.raises(ValueError, match="CME ingest blocked because a different raw file already owns"):
            ingest_cme_parse_result(session, raw_pdf_path=conflict_pdf, parse_result=parse_result)
        session.rollback()

        row_count = session.scalar(select(func.count()).select_from(CmeOptionRow))
        raw_file_count = session.scalar(select(func.count()).select_from(CmeRawFile))
        parse_run_count = session.scalar(select(func.count()).select_from(CmeParseRun))
    finally:
        session.close()

    assert first.total_rows == row_count
    assert raw_file_count == 1
    assert parse_run_count == 1


def test_conflicting_raw_file_block_has_no_commit_side_effect(tmp_path: Path) -> None:
    """Conflict detection must happen before a new raw file is flushed.

    The worker runner catches step exceptions and commits the task-step failure.
    This regression test simulates that path: even if a caller catches the
    conflict and commits instead of rolling back, no orphan CmeRawFile may be
    persisted for the conflicting PDF.
    """
    pdf_path = _resolve_pdf_path()
    parse_result = parse_pg64_pdf(pdf_path, product="OG", expiries={"JUN26", "JUL26"})
    conflict_pdf = tmp_path / "conflict" / pdf_path.name
    conflict_pdf.parent.mkdir(parents=True, exist_ok=True)
    conflict_pdf.write_bytes(pdf_path.read_bytes() + b"\n% conflicting raw file\n")

    session = _make_session(tmp_path)
    try:
        first = ingest_cme_parse_result(session, raw_pdf_path=pdf_path, parse_result=parse_result)
        session.commit()

        with pytest.raises(ValueError, match="CME ingest blocked because a different raw file already owns"):
            ingest_cme_parse_result(session, raw_pdf_path=conflict_pdf, parse_result=parse_result)
        # Simulate runner-style exception handling: record the failure and commit
        # instead of rolling back the whole session.
        session.commit()

        row_count = session.scalar(select(func.count()).select_from(CmeOptionRow))
        raw_file_count = session.scalar(select(func.count()).select_from(CmeRawFile))
        parse_run_count = session.scalar(select(func.count()).select_from(CmeParseRun))
    finally:
        session.close()

    assert first.total_rows == row_count
    assert raw_file_count == 1
    assert parse_run_count == 1


def test_latest_query_and_option_row_filters_return_og_jun_jul_rows(tmp_path: Path) -> None:
    pdf_path = _resolve_pdf_path()
    parse_result = parse_pg64_pdf(pdf_path, product="OG", expiries={"JUN26", "JUL26"})

    session = _make_session(tmp_path)
    try:
        ingest_cme_parse_result(session, raw_pdf_path=pdf_path, parse_result=parse_result)
        session.commit()

        latest = get_latest_cme_raw_file(session, product="OG")
        rows = get_cme_option_rows(session, report_date="2026-05-06", product="OG", expiries={"JUN26", "JUL26"})
    finally:
        session.close()

    assert latest is not None
    assert latest.report_date == "2026-05-06"
    assert latest.section == "Section64_Metals_Option_Products"
    assert rows
    assert {row.expiry for row in rows} == {"JUN26", "JUL26"}
    assert all(row.product_code == "OG" for row in rows)


def test_duplicate_contracts_raise_before_insert(tmp_path: Path) -> None:
    pdf_path = _resolve_pdf_path()
    parse_result = parse_pg64_pdf(pdf_path, product="OG", expiries={"JUN26", "JUL26"})
    duplicate_row = parse_result.detail_rows[0]
    duplicate_result = CmePdfParseResult(
        trade_date=parse_result.trade_date,
        bulletin=parse_result.bulletin,
        status=parse_result.status,
        product=parse_result.product,
        detail_rows=[*parse_result.detail_rows, replace(duplicate_row)],
        summary_rows=parse_result.summary_rows,
        notes=parse_result.notes,
        warnings=parse_result.warnings,
    )

    session = _make_session(tmp_path)
    try:
        with pytest.raises(ValueError, match="Duplicate CME detail row key"):
            ingest_cme_parse_result(session, raw_pdf_path=pdf_path, parse_result=duplicate_result)
        session.rollback()
        row_count = session.scalar(select(func.count()).select_from(CmeOptionRow))
        raw_file_count = session.scalar(select(func.count()).select_from(CmeRawFile))
        parse_run_count = session.scalar(select(func.count()).select_from(CmeParseRun))
    finally:
        session.close()

    assert row_count == 0
    assert raw_file_count == 0
    assert parse_run_count == 0


def test_cli_smoke_ingests_into_sqlite(tmp_path: Path) -> None:
    pdf_path = _resolve_pdf_path()
    parse_result = parse_pg64_pdf(pdf_path, product="OG", expiries={"JUN26", "JUL26"})
    expected_total_rows = len(parse_result.detail_rows)
    db_path = tmp_path / "nested" / "cme_ingest_smoke.db"
    cmd = [
        sys.executable,
        "scripts/ingest_cme_snapshot.py",
        "--pdf",
        str(pdf_path),
        "--product",
        "OG",
        "--expiries",
        "JUN26,JUL26",
        "--database-url",
        f"sqlite:///{db_path.as_posix()}",
    ]
    completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
    payload = json.loads(completed.stdout.strip())
    expected_warnings_count = len(parse_result.warnings)

    assert payload["report_date"] == "2026-05-06"
    assert payload["inserted_rows"] > 0
    assert payload["total_rows"] == expected_total_rows
    assert payload["inserted_rows"] == payload["total_rows"]
    assert payload["existing_rows"] == 0
    assert payload["detail_rows_count"] == expected_total_rows
    assert payload["warnings_count"] == expected_warnings_count
    assert payload["raw_file_id"]
    assert db_path.exists()
