"""Build a read-only XAU/USD provider shadow-run summary for one trade date."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Sequence

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.monitoring.xauusd_shadow_summary import (  # noqa: E402
    build_xauusd_shadow_summary,
    default_shadow_output_path,
    write_xauusd_shadow_summary,
)
from database.models.engine import DATABASE_URL, SessionLocal  # noqa: E402


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    database_url = args.database_url or DATABASE_URL
    storage_root = Path(args.storage_root)
    output = Path(args.output) if args.output else default_shadow_output_path(storage_root=storage_root, trade_date=args.date)
    session_factory = _session_factory(database_url)
    with session_factory() as session:
        payload = build_xauusd_shadow_summary(
            session,
            trade_date=args.date,
            storage_root=storage_root,
            as_of=_parse_as_of(args.as_of),
            include_current_in_rollup=not args.dry_run,
        )
    if args.dry_run:
        print(json.dumps({"dry_run": True, "output_path": str(output), "summary": payload}, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if payload.get("finalization", {}).get("finalized") is not True:
        print(
            json.dumps(
                {
                    "error": "sample_window_not_finalized",
                    "trade_date": args.date,
                    "hint": "use --dry-run for an intraday preview and write only after the UTC day finalization grace",
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    written_path, created = write_xauusd_shadow_summary(payload, output_path=output)
    print(json.dumps({"dry_run": False, "created": created, "output_path": str(written_path), "summary": payload}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="Trade date in YYYY-MM-DD (UTC sample window).")
    parser.add_argument("--storage-root", required=True, help="Storage root containing monitoring artifacts.")
    parser.add_argument("--database-url", default="", help="Optional SQLAlchemy database URL; defaults to DATABASE_URL.")
    parser.add_argument("--output", default="", help="Optional summary artifact path; defaults under --storage-root.")
    parser.add_argument("--as-of", default="", help="Optional ISO timestamp used to determine finalization.")
    parser.add_argument("--dry-run", action="store_true", help="Read and print a summary without writing an artifact.")
    return parser


def _session_factory(database_url: str):
    if database_url == DATABASE_URL:
        return SessionLocal
    return sessionmaker(bind=create_engine(database_url), expire_on_commit=False)


def _parse_as_of(value: str) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


if __name__ == "__main__":
    raise SystemExit(main())
