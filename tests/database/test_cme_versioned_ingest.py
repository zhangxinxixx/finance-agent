from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from apps.parsers.cme.pdf_parser import CmePdfDetailRow, CmePdfParseResult
from database.models.cme import CmeOptionRow, CmeRawFile
from database.models.task import Base
from database.queries.cme import ingest_cme_parse_result


def _parse(status: str) -> CmePdfParseResult:
    row = CmePdfDetailRow(
        trade_date="2026-09-04",
        product="OG",
        expiry="OCT26",
        strike=4500,
        option_type="CALL",
        settlement=100.0,
        delta=0.5,
        open_interest=100,
        oi_change=10,
        total_volume=20,
        block_volume=1,
        pnt_volume=1,
        globex_volume=10,
        outcry_volume=8,
        exercises=0,
        pt_change=1.0,
    )
    return CmePdfParseResult(
        trade_date="2026-09-04",
        bulletin="PG64 versioned fixture",
        status=status,
        product="OG",
        detail_rows=[row],
        summary_rows=[],
        notes={},
        warnings=[],
    )


def test_prelim_and_final_are_version_level_idempotent_and_retained(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'cme.db').as_posix()}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    prelim_pdf = tmp_path / "prelim.pdf"
    final_pdf = tmp_path / "final.pdf"
    prelim_pdf.write_bytes(b"versioned-prelim")
    final_pdf.write_bytes(b"versioned-final")

    try:
        prelim = ingest_cme_parse_result(session, raw_pdf_path=prelim_pdf, parse_result=_parse("PRELIMINARY"))
        session.commit()
        final = ingest_cme_parse_result(session, raw_pdf_path=final_pdf, parse_result=_parse("FINAL"))
        session.commit()
        duplicate_final = ingest_cme_parse_result(session, raw_pdf_path=final_pdf, parse_result=_parse("FINAL"))
        session.commit()

        rows = session.scalars(
            select(CmeOptionRow).where(
                CmeOptionRow.report_date == "2026-09-04",
                CmeOptionRow.product_code == "OG",
            )
        ).all()
        by_version = {version: sum(row.version_type == version for row in rows) for version in ("PRELIMINARY", "FINAL")}
        raw_file_count = session.scalar(select(func.count()).select_from(CmeRawFile))
        from apps.worker.pipelines.cme import _selected_cme_lineage

        from tests.helpers.warehouse import create_collection_schema
        from apps.data_layer.warehouse_sources import load_source_warehouse
        from database.queries.warehouse_cme import get_cme_option_rows as get_dwd_options

        create_collection_schema(engine)
        loaded = load_source_warehouse(session, "cme-options", dry_run=False, limit=100)
        assert loaded["rejected"] == 0
        selected = get_dwd_options(session, report_date="2026-09-04", product="OG")
        assert {row.version_type for row in selected} == {"FINAL"}
        lineage = _selected_cme_lineage(session, selected)
        assert lineage["raw_file_ids"] == [final.raw_file_id]
        assert lineage["raw_file_sha256s"] == [final.sha256]
        assert lineage["source_refs"][0]["raw_path"] == final_pdf.as_posix()
    finally:
        session.close()

    assert prelim.inserted_rows == 1
    assert final.inserted_rows == 1
    assert final.replaced_rows == 1
    assert duplicate_final.inserted_rows == 0
    assert by_version == {"PRELIMINARY": 1, "FINAL": 1}
    assert raw_file_count == 2


def test_ingest_preserves_caller_transaction_and_rollback(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'rollback.db'}")
    Base.metadata.create_all(engine)
    pdf = tmp_path / "prelim.pdf"
    pdf.write_bytes(b"rollback-fixture")
    with sessionmaker(bind=engine)() as session:
        ingest_cme_parse_result(session, raw_pdf_path=pdf, parse_result=_parse("PRELIMINARY"))
        assert session.in_transaction()
        session.rollback()
        assert session.scalar(select(func.count()).select_from(CmeRawFile)) == 0
        assert session.scalar(select(func.count()).select_from(CmeOptionRow)) == 0
