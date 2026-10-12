"""Explicit bounded warehouse backfill; default is a write-free preview."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from apps.data_layer.warehouse_etl import DATASETS, WarehouseError, load_warehouse
from apps.data_layer.warehouse_sources import SOURCE_DATASETS, load_source_warehouse
from database.models.task import TaskRun, TaskStep, TaskStatus, StepStatus


def main(argv=None, session_factory=None, project_root=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, choices=(*DATASETS, *SOURCE_DATASETS))
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--after")
    parser.add_argument("--record-id", action="append", help="Load only these source IDs, including late rows/corrections.")
    parser.add_argument("--run-id")
    parser.add_argument("--storage-root", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    base = dict(
        dataset=args.dataset,
        dry_run=not args.apply,
        processed=0,
        planned=0,
        inserted=0,
        skipped=0,
        rejected=0,
        next_after=args.after,
        task_run_id=None,
    )
    owned_engine = None
    try:
        if not 1 <= args.limit <= 1000:
            raise WarehouseError("DWH_ARGUMENT_INVALID")
        if session_factory is None:
            # Require explicit environment, no dotenv loading and no production fallback.
            url = os.environ.get("DATABASE_URL")
            if not url:
                raise WarehouseError("DWH_DATABASE_URL_REQUIRED")
            owned_engine = create_engine(url, echo=False, hide_parameters=True)
            session_factory = sessionmaker(owned_engine)
        # An explicit project root may establish the trusted root. No runtime root is inferred.
        root = args.storage_root if args.storage_root is not None else project_root
        with session_factory() as session:
            try:
                loader = load_warehouse if args.dataset in DATASETS else load_source_warehouse
                options = {"limit": args.limit, "after": args.after, "storage_root": root, "dry_run": not args.apply}
                if args.record_id is not None:
                    options["record_ids"] = args.record_id
                if args.run_id is not None:
                    if args.dataset not in DATASETS:
                        raise WarehouseError("DWH_ARGUMENT_INVALID")
                    options["run_id"] = args.run_id
                result = loader(
                    session,
                    args.dataset,
                    **options,
                )
                if args.apply:
                    session.commit()
                else:
                    session.rollback()
            except Exception as exc:
                session.rollback()
                code = str(exc) if isinstance(exc, WarehouseError) else "DWH_TRANSACTION_FAILED"
                result = dict(base, error_code=code)
                # A failed transaction gets only a real independent failed audit, no fake batch success.
                if args.apply and code == "DWH_TRANSACTION_FAILED":
                    try:
                        inspector = inspect(session.connection())
                        if inspector.has_table("task_runs") and inspector.has_table("task_steps"):
                            uid, sid, now = uuid4(), uuid4(), datetime.now(UTC)
                            session.add(
                                TaskRun(
                                    id=uid,
                                    name="warehouse:" + args.dataset,
                                    task_type="warehouse_load",
                                    status=TaskStatus.failed,
                                    started_at=now,
                                    ended_at=now,
                                    error_summary=code,
                                )
                            )
                            session.flush()
                            session.add(
                                TaskStep(
                                    id=sid,
                                    task_run_id=uid,
                                    name="field_etl",
                                    stage="warehouse_load",
                                    task_kind="warehouse_load",
                                    status=StepStatus.failed,
                                    started_at=now,
                                    finished_at=now,
                                    error=code,
                                )
                            )
                            session.commit()
                            result["task_run_id"] = str(uid)
                    except Exception:
                        session.rollback()
                print(json.dumps(result))
                return 2
        print(json.dumps(result))
        return 1 if result["rejected"] else 0
    except Exception as exc:
        print(
            json.dumps(dict(base, error_code=str(exc) if isinstance(exc, WarehouseError) else "DWH_TRANSACTION_FAILED"))
        )
        return 2
    finally:
        if owned_engine is not None:
            owned_engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
