"""CME repository helpers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from apps.parsers.cme.pdf_parser import CmePdfDetailRow, CmePdfParseResult
from database.models.cme import CmeOptionRow, CmeParseRun, CmeRawFile
from database.models.task import Base

DEFAULT_CME_SOURCE = "cme_daily_bulletin"


@dataclass(frozen=True)
class CmeIngestResult:
    raw_file_id: str
    report_date: str
    inserted_rows: int
    existing_rows: int
    total_rows: int
    warnings_count: int
    detail_rows_count: int
    summary_rows_count: int
    parse_run_id: str
    sha256: str
    replaced_rows: int = 0
    version_type: str = "PRELIMINARY"
    warnings: list[str] = field(default_factory=list)
    notes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["notes"] = self.notes
        payload["warnings"] = self.warnings
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


def ensure_cme_tables(bind_or_session: Engine | Session) -> None:
    bind = _resolve_bind(bind_or_session)
    Base.metadata.create_all(
        bind=bind,
        tables=[
            CmeRawFile.__table__,
            CmeOptionRow.__table__,
            CmeParseRun.__table__,
        ],
    )
    _migrate_cme_version_type(bind_or_session)


def create_cme_tables(bind: Engine | Session) -> None:
    ensure_cme_tables(bind)


def _resolve_version_type(parse_result: CmePdfParseResult) -> str:
    """Normalize parse_result.status to a version_type value."""
    raw = (parse_result.status or "").strip().upper()
    if raw == "FINAL":
        return "FINAL"
    return "PRELIMINARY"


def ingest_cme_parse_result(
    session: Session,
    *,
    raw_pdf_path: Path,
    parse_result: CmePdfParseResult,
    source_url: str | None = None,
    section: str = "Section64_Metals_Option_Products",
) -> CmeIngestResult:
    raw_bytes = raw_pdf_path.read_bytes()
    sha256 = hashlib.sha256(raw_bytes).hexdigest()
    ensure_cme_tables(session)
    _ensure_unique_detail_rows(parse_result.detail_rows)

    version_type = _resolve_version_type(parse_result)
    raw_file = session.scalar(select(CmeRawFile).where(CmeRawFile.sha256 == sha256))

    total_rows = len(parse_result.detail_rows)
    existing_rows = {
        (row.product_code, row.expiry, row.strike, row.option_type): row
        for row in session.scalars(
            select(CmeOptionRow).where(
                CmeOptionRow.report_date == parse_result.trade_date,
                CmeOptionRow.product_code == parse_result.product,
            )
        )
    }

    # Determine if existing rows are PRELIM or FINAL
    existing_version: str | None = None
    if existing_rows:
        first_row = next(iter(existing_rows.values()))
        existing_version = first_row.version_type

    # PRELIM → FINAL transition: keep both, don't delete PRELIM rows
    # FINAL rows will be preferred by get_cme_option_rows (default behavior)
    replaced_rows = 0
    if existing_version == "PRELIMINARY" and version_type == "FINAL":
        # FINAL is coming in alongside existing PRELIM — keep PRELIM for backtracking
        # Just clear existing_rows so we insert FINAL as new rows
        replaced_rows = len(existing_rows)
        existing_rows.clear()

    if existing_rows and raw_file is None and existing_version == version_type:
        raise ValueError(
            "CME ingest blocked because a different raw file already owns "
            f"{parse_result.trade_date} {parse_result.product} {version_type} rows"
        )

    existing_raw_file_id = ""
    if existing_rows:
        first_existing_row = next(iter(existing_rows.values()))
        existing_raw_file_id = first_existing_row.raw_file_id

    # Skip if already ingested with same version or trying to ingest PRELIM when FINAL exists
    skip_ingest = False
    if existing_version == version_type:
        # Same version already exists — skip
        skip_ingest = True
    elif existing_version == "FINAL" and version_type == "PRELIMINARY":
        # FINAL already exists, skip PRELIM
        skip_ingest = True

    if skip_ingest:
        parse_run_raw_file_id = raw_file.id if raw_file is not None else existing_raw_file_id
        parse_run = session.scalar(select(CmeParseRun).where(CmeParseRun.raw_file_id == parse_run_raw_file_id))
        parse_run_id = parse_run.id if parse_run else ""
        return CmeIngestResult(
            raw_file_id=parse_run_raw_file_id,
            report_date=parse_result.trade_date,
            inserted_rows=0,
            existing_rows=total_rows,
            total_rows=total_rows,
            warnings_count=len(parse_result.warnings),
            detail_rows_count=len(parse_result.detail_rows),
            summary_rows_count=len(parse_result.summary_rows),
            parse_run_id=parse_run_id,
            sha256=sha256,
            replaced_rows=replaced_rows,
            version_type=version_type,
            warnings=list(parse_result.warnings),
            notes=dict(parse_result.notes),
        )

    if raw_file is None:
        raw_file = CmeRawFile(
            source=DEFAULT_CME_SOURCE,
            section=section,
            source_url=source_url,
            raw_path=raw_pdf_path.as_posix(),
            sha256=sha256,
            report_date=parse_result.trade_date,
            bytes=len(raw_bytes),
            retrieved_at=_parse_iso_datetime(parse_result.notes.get("retrieved_at")) if parse_result.notes.get("retrieved_at") else _now_utc(),
        )
        session.add(raw_file)
        session.flush()

    inserted_rows = 0
    for detail_row in parse_result.detail_rows:
        key = (detail_row.product, detail_row.expiry, detail_row.strike, detail_row.option_type)
        existing_row = existing_rows.get(key)
        if existing_row is not None:
            continue
        session.add(_build_option_row(raw_file_id=raw_file.id, parse_result=parse_result, row=detail_row, version_type=version_type))
        inserted_rows += 1

    parse_run = session.scalar(select(CmeParseRun).where(CmeParseRun.raw_file_id == raw_file.id))
    warnings_json = json.dumps(parse_result.warnings, ensure_ascii=False, sort_keys=True)
    notes_json = json.dumps(parse_result.notes, ensure_ascii=False, sort_keys=True)
    if parse_run is None:
        parse_run = CmeParseRun(
            raw_file_id=raw_file.id,
            status=parse_result.status,
            detail_rows_count=len(parse_result.detail_rows),
            summary_rows_count=len(parse_result.summary_rows),
            warnings_json=warnings_json,
            notes_json=notes_json,
        )
        session.add(parse_run)
        session.flush()
    else:
        parse_run.status = parse_result.status
        parse_run.detail_rows_count = len(parse_result.detail_rows)
        parse_run.summary_rows_count = len(parse_result.summary_rows)
        parse_run.warnings_json = warnings_json
        parse_run.notes_json = notes_json
        session.flush()

    return CmeIngestResult(
        raw_file_id=raw_file.id,
        report_date=parse_result.trade_date,
        inserted_rows=inserted_rows,
        existing_rows=total_rows - inserted_rows,
        total_rows=total_rows,
        warnings_count=len(parse_result.warnings),
        detail_rows_count=len(parse_result.detail_rows),
        summary_rows_count=len(parse_result.summary_rows),
        parse_run_id=parse_run.id,
        sha256=sha256,
        replaced_rows=replaced_rows,
        version_type=version_type,
        warnings=list(parse_result.warnings),
        notes=dict(parse_result.notes),
    )


def get_latest_cme_raw_file(session: Session, *, product: str | None = None) -> CmeRawFile | None:
    statement = select(CmeRawFile)
    if product is not None:
        statement = statement.where(
            CmeRawFile.id.in_(
                select(CmeOptionRow.raw_file_id).where(CmeOptionRow.product_code == product)
            )
        )
    statement = statement.order_by(CmeRawFile.report_date.desc(), CmeRawFile.created_at.desc(), CmeRawFile.id.desc()).limit(1)
    return session.scalar(statement)


def get_cme_option_rows(
    session: Session,
    *,
    report_date: str | None = None,
    product: str = "OG",
    expiries: set[str] | None = None,
    version_type: str | None = None,
) -> list[CmeOptionRow]:
    """Get CME option rows, defaulting to FINAL over PRELIMINARY.

    When ``version_type`` is None (default), returns FINAL rows if any exist
    for the given report_date, otherwise falls back to PRELIMINARY rows.
    Pass ``version_type='PRELIMINARY'`` to explicitly get PRELIMINARY rows.
    """
    statement = select(CmeOptionRow).where(CmeOptionRow.product_code == product)
    if report_date is not None:
        statement = statement.where(CmeOptionRow.report_date == report_date)
    if expiries:
        statement = statement.where(CmeOptionRow.expiry.in_(sorted(expiries)))
    if version_type is not None:
        statement = statement.where(CmeOptionRow.version_type == version_type)
    statement = statement.order_by(CmeOptionRow.expiry, CmeOptionRow.strike, CmeOptionRow.option_type)
    rows = list(session.scalars(statement))

    if version_type is None and report_date is not None:
        final_rows = [r for r in rows if r.version_type == "FINAL"]
        if final_rows:
            return final_rows
    return rows


def _build_option_row(
    *,
    raw_file_id: str,
    parse_result: CmePdfParseResult,
    row: CmePdfDetailRow,
    version_type: str = "PRELIMINARY",
) -> CmeOptionRow:
    return CmeOptionRow(
        raw_file_id=raw_file_id,
        trade_date=parse_result.trade_date,
        report_date=parse_result.trade_date,
        version_type=version_type,
        product_code=row.product,
        underlying="GC",
        expiry=row.expiry,
        strike=row.strike,
        option_type=row.option_type,
        settlement=row.settlement,
        delta=row.delta,
        open_interest=row.open_interest,
        oi_change=row.oi_change,
        total_volume=row.total_volume,
        block_volume=row.block_volume,
        pnt_volume=row.pnt_volume,
        globex_volume=row.globex_volume,
        outcry_volume=row.outcry_volume,
        exercises=row.exercises,
        pt_change=row.pt_change,
        source_page=None,
    )


def _ensure_unique_detail_rows(detail_rows: list[CmePdfDetailRow]) -> None:
    seen: set[tuple[str, str, int, str]] = set()
    duplicates: list[tuple[str, str, int, str]] = []
    for row in detail_rows:
        key = (row.product, row.expiry, row.strike, row.option_type)
        if key in seen:
            duplicates.append(key)
            continue
        seen.add(key)

    if duplicates:
        formatted = ", ".join(
            f"{product} {expiry} {strike} {option_type}"
            for product, expiry, strike, option_type in duplicates
        )
        raise ValueError(f"Duplicate CME detail row key(s) in parse result: {formatted}")


def _migrate_cme_version_type(bind_or_session: Engine | Session) -> None:
    """Add version_type column to cme_option_rows if it doesn't exist.

    Handles both PostgreSQL (production) and SQLite (tests).
    Existing rows default to 'PRELIMINARY'.
    """
    if isinstance(bind_or_session, Session):
        conn = bind_or_session.connection()
    else:
        with bind_or_session.connect() as conn:
            _run_version_type_migration(conn)
            return
    _run_version_type_migration(conn)


def _run_version_type_migration(conn) -> None:
    dialect_name = conn.engine.dialect.name
    has_column = False
    if dialect_name == "postgresql":
        result = conn.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                "WHERE table_name='cme_option_rows' AND column_name='version_type')"
            )
        )
        has_column = result.scalar()
    elif dialect_name == "sqlite":
        result = conn.execute(text("PRAGMA table_info('cme_option_rows')"))
        has_column = any(row[1] == "version_type" for row in result.fetchall())

    if has_column:
        return

    if dialect_name == "postgresql":
        conn.execute(text("ALTER TABLE cme_option_rows ADD COLUMN version_type VARCHAR(16) NOT NULL DEFAULT 'PRELIMINARY'"))
        # Drop old unique constraint if it still has the old shape
        conn.execute(text("ALTER TABLE cme_option_rows DROP CONSTRAINT IF EXISTS uq_cme_option_row"))
        conn.execute(text(
            "ALTER TABLE cme_option_rows ADD CONSTRAINT uq_cme_option_row "
            "UNIQUE (report_date, product_code, expiry, strike, option_type, version_type)"
        ))
        conn.commit()
    elif dialect_name == "sqlite":
        # SQLite doesn't support DROP CONSTRAINT; rebuild table
        # For test environments, just add the column
        conn.execute(text("ALTER TABLE cme_option_rows ADD COLUMN version_type VARCHAR(16) NOT NULL DEFAULT 'PRELIMINARY'"))
        conn.commit()


def _resolve_bind(bind_or_session: Engine | Session) -> Engine:
    if isinstance(bind_or_session, Session):
        bind = bind_or_session.get_bind()
        if bind is None:
            raise ValueError("Session is not bound to an engine.")
        return bind
    return bind_or_session


def _now_utc():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def _parse_iso_datetime(value: str | None):
    if value is None:
        return _now_utc()
    from datetime import datetime

    return datetime.fromisoformat(value)


# ═══════════════════════════════════════════════════════════════════════
# P4-06: Multi-date queries for wall calibration
# ═══════════════════════════════════════════════════════════════════════


def get_cme_option_rows_multi_date(
    session: Session,
    *,
    trade_dates: list[str],
    product: str = "OG",
    prefer_final: bool = True,
) -> dict[str, list[CmeOptionRow]]:
    """Fetch CME option rows for multiple trade dates, preferring FINAL.

    Returns a dict mapping trade_date → list of CmeOptionRow, where each date's
    rows are FINAL-preferred when ``prefer_final=True``. Dates with no rows
    are omitted from the result.

    This is the foundation for P4-06 multi-day wall calibration: OI deltas,
    wall migration, and roll detection across consecutive trading days.
    """
    # Query all rows for the given dates
    statement = (
        select(CmeOptionRow)
        .where(CmeOptionRow.product_code == product)
        .where(CmeOptionRow.trade_date.in_(trade_dates))
        .order_by(CmeOptionRow.trade_date, CmeOptionRow.expiry, CmeOptionRow.strike, CmeOptionRow.option_type)
    )
    all_rows = list(session.scalars(statement))

    # Group by trade_date, apply FINAL preference
    by_date: dict[str, list[CmeOptionRow]] = {}
    for row in all_rows:
        by_date.setdefault(row.trade_date, []).append(row)

    if prefer_final:
        for date, rows in by_date.items():
            final_rows = [r for r in rows if r.version_type == "FINAL"]
            if final_rows:
                by_date[date] = final_rows

    return by_date


def get_available_cme_trade_dates(
    session: Session,
    *,
    product: str = "OG",
    limit: int = 10,
) -> list[str]:
    """Return recent distinct trade dates with CME option rows, newest first."""
    from sqlalchemy import distinct

    statement = (
        select(distinct(CmeOptionRow.trade_date))
        .where(CmeOptionRow.product_code == product)
        .order_by(CmeOptionRow.trade_date.desc())
        .limit(limit)
    )
    return [row[0] for row in session.execute(statement).fetchall()]
