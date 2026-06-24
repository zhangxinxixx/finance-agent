from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.parsers.cme.pdf_parser import parse_pg64_pdf  # noqa: E402
from database.models.engine import DATABASE_URL, SessionLocal  # noqa: E402
from database.queries.cme import ingest_cme_parse_result  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse and ingest a CME PG64 Daily Bulletin PDF.")
    parser.add_argument("--pdf", required=True, help="Path to the PG64 PDF")
    parser.add_argument("--product", default="OG", help="Product code to parse")
    parser.add_argument(
        "--expiries",
        default="",
        help="Comma-separated expiry filter, e.g. JUN26,JUL26",
    )
    parser.add_argument(
        "--database-url",
        default="",
        help="Optional SQLAlchemy database URL. Defaults to DATABASE_URL.",
    )
    parser.add_argument(
        "--section",
        default="Section64_Metals_Option_Products",
        help="CME section name for the raw file record.",
    )
    parser.add_argument("--source-url", default=None, help="Optional source URL to persist with the raw file.")
    args = parser.parse_args()

    expiries = {item.strip().upper() for item in args.expiries.split(",") if item.strip()}

    try:
        parse_result = parse_pg64_pdf(Path(args.pdf), product=args.product, expiries=expiries or None)
    except Exception as exc:
        print(f"cme parse failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    database_url = args.database_url or DATABASE_URL
    session_factory = _session_factory(database_url)
    _ensure_sqlite_parent(database_url)

    with session_factory() as session:
        try:
            ingest_result = ingest_cme_parse_result(
                session,
                raw_pdf_path=Path(args.pdf),
                parse_result=parse_result,
                source_url=args.source_url,
                section=args.section,
            )
            session.commit()
        except Exception:
            session.rollback()
            raise

    print(
        json.dumps(
            {
                "raw_file_id": ingest_result.raw_file_id,
                "report_date": ingest_result.report_date,
                "inserted_rows": ingest_result.inserted_rows,
                "existing_rows": ingest_result.existing_rows,
                "total_rows": ingest_result.total_rows,
                "warnings_count": ingest_result.warnings_count,
                "detail_rows_count": ingest_result.detail_rows_count,
                "summary_rows_count": ingest_result.summary_rows_count,
                "parse_run_id": ingest_result.parse_run_id,
                "sha256": ingest_result.sha256,
                "warnings": ingest_result.warnings,
                "notes": ingest_result.notes,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def _session_factory(database_url: str):
    if database_url == DATABASE_URL:
        return SessionLocal
    engine = create_engine(database_url, echo=False)
    return sessionmaker(bind=engine)


def _ensure_sqlite_parent(database_url: str) -> None:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return
    db_path = Path(url.database)
    if db_path.parent != Path("."):
        db_path.parent.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    main()
