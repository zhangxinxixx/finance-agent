"""Read-only preview of explicit news manifests from verified SQL snapshots."""

# ruff: noqa: E402 -- direct CLI bootstrap adds the project root before imports.
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select

from apps.data_layer.structured_artifacts import preview_structured_artifact
from apps.runtime.artifact_storage import LocalFileSystemArtifactStorage
from apps.worker.news_artifact_registration import build_news_artifact_refs
from database.models.analysis import AnalysisSnapshot
from database.models.execution import RunArtifact
from database.models.task import TaskStep


def _snapshot_manifest(snapshot):
    digest = hashlib.sha256(json.dumps(snapshot.payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if digest != snapshot.payload_sha256 or snapshot.payload.get("run_id") != snapshot.run_id:
        raise ValueError("news_source_snapshot_identity_invalid")
    news = snapshot.payload.get("news") or {}
    if isinstance(news.get("data"), dict):
        news = news["data"]
    paths = dict(news.get("artifact_paths") or {})
    brief = news.get("daily_brief_output") or {}
    if brief.get("input_snapshot_path"):
        paths.setdefault("daily_brief_input_snapshot", brief["input_snapshot_path"])
    if brief.get("artifact_path"):
        markdown = Path(brief["artifact_path"])
        paths.setdefault("daily_brief_markdown", str(markdown))
        paths.setdefault("daily_brief_json", str(markdown.with_suffix(".json")))
    for value in paths.values():
        if snapshot.run_id not in Path(value).parts:
            raise ValueError("news_artifact_producer_run_mismatch")
    return paths


def _resolved_key(storage, file_path):
    path = Path(file_path)
    if not path.is_absolute():
        if path.parts and path.parts[0] == "storage":
            path = Path(*path.parts[1:])
        path = storage.root / path
    return str(path.resolve())


def backfill_news_batch(*, session_factory, storage_root, run_ids, apply=False, limit=20):
    if apply:
        raise ValueError("whole_json_backfill_disabled_use_warehouse")
    if not 1 <= len(run_ids) <= limit <= 100:
        raise ValueError("news_batch_bounds_invalid")
    run_ids = list(dict.fromkeys(str(uuid.UUID(str(value))) for value in run_ids))
    storage = LocalFileSystemArtifactStorage(root=Path(storage_root))
    result = {
        "dry_run": True,
        "producer_runs": run_ids,
        "planned": 0,
        "registered": 0,
        "persisted": 0,
        "rejected": 0,
        "unavailable": 0,
        "not_applicable": 0,
        "existing": 0,
        "gaps": [],
        "audit_run_id": None,
    }
    with session_factory() as db:
        snapshots = list(db.scalars(select(AnalysisSnapshot).where(AnalysisSnapshot.run_id.in_(run_ids)).limit(limit)))
        found = {snapshot.run_id for snapshot in snapshots}
        result["gaps"].extend(
            {"run_id": run_id, "error": "news_source_snapshot_missing"} for run_id in run_ids if run_id not in found
        )
        for snapshot in snapshots:
            try:
                paths = _snapshot_manifest(snapshot)
            except ValueError:
                result["gaps"].append({"run_id": snapshot.run_id, "error": "news_source_snapshot_invalid"})
                continue
            run_uuid = uuid.UUID(snapshot.run_id)
            original_rows = list(db.scalars(select(RunArtifact).where(RunArtifact.run_id == run_uuid)))
            existing = {
                _resolved_key(storage, row.file_path): row
                for row in sorted(original_rows, key=lambda row: bool(row.sha256))
            }
            for stage in ["news_collect", "news_feature", "news_brief"]:
                step = db.scalar(select(TaskStep).where(TaskStep.task_run_id == run_uuid, TaskStep.name == stage))
                if step is None:
                    result["gaps"].append(
                        {"run_id": snapshot.run_id, "error": "news_original_task_step_missing", "stage": stage}
                    )
                    continue
                refs = build_news_artifact_refs(
                    step_name=stage, paths=paths, storage_root=storage.root, run_id=snapshot.run_id
                )
                for ref in refs:
                    row = existing.get(_resolved_key(storage, ref["file_path"]))
                    if row is not None:
                        result["existing"] += 1
                    else:
                        result["planned"] += 1
                        row = RunArtifact(
                            run_id=run_uuid,
                            storage_backend="local_fs",
                            file_path=ref["file_path"],
                            sha256=ref["sha256"],
                            content_type=ref["content_type"],
                        )
                    status = preview_structured_artifact(row, storage)
                    result[status.status] += 1
    return result


def main(argv=None, *, session_factory=None, project_root=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--run-id", action="append", required=True)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--storage-root", default=str(PROJECT_ROOT / "storage"))
    args = parser.parse_args(argv)
    if args.apply:
        parser.error("whole_json_backfill_disabled_use_backfill_data_warehouse")
    root = Path(project_root or PROJECT_ROOT).resolve()
    raw_storage = Path(args.storage_root).expanduser()
    if raw_storage.is_symlink() or raw_storage.resolve() != root / "storage" or not raw_storage.is_dir():
        parser.error("news_storage_root_invalid")
    if session_factory is None:
        from database.models.engine import SessionLocal

        session_factory = SessionLocal
    try:
        result = backfill_news_batch(
            session_factory=session_factory,
            storage_root=raw_storage.resolve(),
            run_ids=args.run_id,
            apply=args.apply,
            limit=args.limit,
        )
    except Exception:
        print(json.dumps({"error": "news_structured_batch_failed", "dry_run": not args.apply}))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
