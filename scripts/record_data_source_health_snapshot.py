from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.api.services.source_service import get_data_source_health_latest  # noqa: E402
from apps.scheduler.source_health import record_daily_source_health_snapshot  # noqa: E402
from database.models.engine import DATABASE_URL, SessionLocal  # noqa: E402


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    database_url = args.database_url or DATABASE_URL

    if args.dry_run:
        payload = get_data_source_health_latest(date=args.date)
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "snapshot_date": payload.get("snapshot_date"),
                    "overall_status": payload.get("overall_status"),
                    "planned_items": len(payload.get("items") or []),
                    "counts": payload.get("counts") or {},
                    "database_url": _display_database_url(database_url),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0

    session_factory = _session_factory(database_url)
    _ensure_sqlite_parent(database_url)
    payload = record_daily_source_health_snapshot(session_factory=session_factory, snapshot_date=args.date)
    print(
        json.dumps(
            {
                "dry_run": False,
                "snapshot_date": payload.get("snapshot_date"),
                "overall_status": payload.get("overall_status"),
                "persisted_items": len(payload.get("items") or []),
                "counts": payload.get("counts") or {},
                "database_url": _display_database_url(database_url),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record a persisted daily data-source health snapshot.")
    parser.add_argument("--date", default=None, help="Snapshot date in YYYY-MM-DD. Defaults to today in UTC.")
    parser.add_argument("--dry-run", action="store_true", help="Print the planned snapshot without writing to the database.")
    parser.add_argument("--database-url", default="", help="Optional SQLAlchemy database URL. Defaults to DATABASE_URL.")
    return parser


def _session_factory(database_url: str):
    if database_url == DATABASE_URL:
        return SessionLocal
    engine = create_engine(database_url)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _ensure_sqlite_parent(database_url: str) -> None:
    url = make_url(database_url)
    if url.drivername.startswith("sqlite") and url.database not in (None, "", ":memory:"):
        Path(url.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def _display_database_url(database_url: str) -> str:
    try:
        return make_url(database_url).render_as_string(hide_password=True)
    except Exception:
        return "<invalid database url>"


if __name__ == "__main__":
    raise SystemExit(main())
