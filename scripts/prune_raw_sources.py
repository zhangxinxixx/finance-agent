"""Preview or apply bounded raw-source retention; dry-run is the default."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.data_layer.raw_retention import apply_raw_retention, preview_raw_retention
from apps.data_layer.warehouse_maintenance import enrich_raw_retention_result
from database.queries.raw_source import RawSourceError


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def _parse_as_of(value: str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise RawSourceError("RAW_RETENTION_NOW_INVALID")
        parsed = parsed.astimezone(UTC)
    except (AttributeError, TypeError, ValueError, OverflowError):
        raise RawSourceError("RAW_RETENTION_NOW_INVALID") from None
    if parsed > datetime.now(UTC):
        raise RawSourceError("RAW_RETENTION_NOW_FUTURE")
    return parsed


def main(argv=None, session_factory=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-root", required=True, type=Path)
    parser.add_argument("--retention-days", type=int, default=30)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument(
        "--as-of",
        metavar="ISO-8601",
        help="评估时点（UTC）；cutoff=as_of-retention_days，不能晚于当前时间",
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    engine = None
    try:
        as_of = _parse_as_of(args.as_of)
        if session_factory is None:
            # Explicit process configuration only. This command never loads dotenv.
            database_url = os.environ.get("DATABASE_URL")
            if not database_url:
                raise RawSourceError("RAW_RETENTION_DATABASE_URL_REQUIRED")
            engine = create_engine(database_url, echo=False, hide_parameters=True)
            session_factory = sessionmaker(engine, expire_on_commit=False)
        if args.apply:
            result = apply_raw_retention(
                session_factory,
                storage_root=args.storage_root,
                now=as_of,
                retention_days=args.retention_days,
                limit=args.limit,
            )
            result["dry_run"] = False
        else:
            with session_factory() as session:
                result = preview_raw_retention(
                    session,
                    storage_root=args.storage_root,
                    now=as_of,
                    retention_days=args.retention_days,
                    limit=args.limit,
                )
                session.rollback()
            result["dry_run"] = True
        result = enrich_raw_retention_result(result)
        result["as_of"] = as_of
        print(json.dumps(result, default=_json_default, sort_keys=True))
        return 0
    except RawSourceError as exc:
        print(json.dumps({"dry_run": not args.apply, "error_code": str(exc)}, sort_keys=True))
        return 2
    except Exception:
        print(json.dumps({"dry_run": not args.apply, "error_code": "RAW_RETENTION_FAILED"}, sort_keys=True))
        return 2
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
