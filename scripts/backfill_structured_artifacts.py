"""Read-only compatibility preview of registered structured artifacts."""

# ruff: noqa: E402 -- direct CLI bootstrap adds the project root before imports.
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import inspect

from apps.data_layer.structured_artifacts import (
    DEFAULT_MAX_BYTES,
    preview_structured_artifact,
)
from apps.runtime.artifact_storage import LocalFileSystemArtifactStorage
from database.models.execution import RunArtifact
from database.queries.structured_artifacts import list_structured_artifacts


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Disabled: use the typed warehouse backfill for writes.")
    parser.add_argument("--run-id", action="append", default=[])
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--after", help="Exclusive artifact UUID cursor from the previous batch.")
    parser.add_argument("--storage-root", default=str(PROJECT_ROOT / "storage"))
    parser.add_argument("--status", choices=["persisted", "rejected", "unavailable", "not_applicable"])
    parser.add_argument("--error", help="Retry only this fixed persistence error code.")
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    return parser


def backfill_batch(
    *,
    session_factory,
    storage,
    run_ids=(),
    limit=100,
    after=None,
    apply=False,
    max_bytes=DEFAULT_MAX_BYTES,
    status=None,
    error=None,
):
    if apply:
        raise ValueError("whole_json_backfill_disabled_use_warehouse")
    if not 1 <= limit <= 1000 or max_bytes <= 0:
        raise ValueError("invalid_batch_bounds")
    run_ids = [str(uuid.UUID(str(value))) for value in run_ids]
    if after is not None:
        after = str(uuid.UUID(str(after)))
    summary = {
        "dry_run": True,
        "scanned": 0,
        "persisted": 0,
        "rejected": 0,
        "unavailable": 0,
        "not_applicable": 0,
        "skipped": 0,
        "written": 0,
        "next_cursor": None,
        "has_more": False,
        "audit_run_id": None,
        "errors": {},
    }
    with session_factory() as db:
        inspector = inspect(db.connection())
        columns = (
            {c["name"] for c in inspector.get_columns("run_artifacts")}
            if inspector.has_table("run_artifacts")
            else set()
        )
        required = {c.name for c in RunArtifact.__table__.columns}
        if not required.issubset(columns):
            summary["error"] = "structured_artifact_migration_required"
            return summary
        rows = list_structured_artifacts(db, run_ids=run_ids, limit=limit, after=after, status=status, error=error)
        if not rows:
            return summary
        summary["next_cursor"] = str(rows[-1].artifact_id)
        summary["has_more"] = bool(
            list_structured_artifacts(
                db, run_ids=run_ids, limit=1, after=summary["next_cursor"], status=status, error=error
            )
        )
        for row in rows:
            result = preview_structured_artifact(row, storage, max_bytes=max_bytes)
            summary["scanned"] += 1
            summary[result.status] += 1
            if result.status == "persisted" and not result.changed:
                summary["skipped"] += 1
            if result.error:
                summary["errors"][result.error] = summary["errors"].get(result.error, 0) + 1
        # The context manager closes the read-only session even on exception.
    return summary


def main(argv=None, *, session_factory=None, project_root=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.apply:
        parser.error("whole_json_backfill_disabled_use_backfill_data_warehouse")
    root = Path(project_root or PROJECT_ROOT).resolve()
    raw_storage = Path(args.storage_root).expanduser()
    if raw_storage.is_symlink() or not raw_storage.is_dir():
        parser.error("storage_root_invalid")
    storage_root = raw_storage.resolve()
    try:
        storage_root.relative_to(root / "storage")
    except ValueError:
        parser.error("storage_root_outside_project_storage")
    if session_factory is None:
        from database.models.engine import SessionLocal

        session_factory = SessionLocal
    try:
        summary = backfill_batch(
            session_factory=session_factory,
            storage=LocalFileSystemArtifactStorage(root=storage_root),
            run_ids=args.run_id,
            limit=args.limit,
            after=args.after,
            apply=args.apply,
            max_bytes=args.max_bytes,
            status=args.status,
            error=args.error,
        )
    except Exception:
        # Driver exceptions can contain payload bind values or connection credentials.
        print(json.dumps({"error": "structured_artifact_batch_failed", "dry_run": not args.apply}))
        return 1
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 2 if summary.get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
