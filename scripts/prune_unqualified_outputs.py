"""Preview or apply bounded cleanup of explicitly failed research outputs."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.data_layer.output_retention import (
    OutputRetentionError,
    apply_unqualified_outputs,
    preview_unqualified_outputs,
)


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def main(argv=None, session_factory=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-root", required=True, type=Path)
    parser.add_argument("--run-id", action="append", dest="run_ids")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    engine = None
    try:
        if args.apply and not args.run_ids:
            raise OutputRetentionError("OUTPUT_CLEANUP_RUN_IDS_REQUIRED")
        if session_factory is None:
            # Use only the process environment.  This command never loads dotenv.
            database_url = os.environ.get("DATABASE_URL")
            if not database_url:
                raise OutputRetentionError("OUTPUT_CLEANUP_DATABASE_URL_REQUIRED")
            engine = create_engine(database_url, echo=False, hide_parameters=True)
            session_factory = sessionmaker(bind=engine, expire_on_commit=False)
        if args.apply:
            result = apply_unqualified_outputs(
                session_factory,
                storage_root=args.storage_root,
                run_ids=args.run_ids,
                limit=args.limit,
            )
        else:
            with session_factory() as session:
                result = preview_unqualified_outputs(
                    session,
                    storage_root=args.storage_root,
                    run_ids=args.run_ids,
                    limit=args.limit,
                )
                session.rollback()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, default=_json_default))
        return 0
    except OutputRetentionError as exc:
        print(
            json.dumps(
                {"dry_run": not args.apply, "error_code": str(exc)},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    except Exception:
        # Do not expose SQLAlchemy connection strings or driver exception text.
        print(
            json.dumps(
                {"dry_run": not args.apply, "error_code": "OUTPUT_CLEANUP_FAILED"},
                sort_keys=True,
            )
        )
        return 2
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
