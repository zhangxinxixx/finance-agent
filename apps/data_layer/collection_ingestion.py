"""One ingestion boundary for existing worker and scheduler collection paths.

Collectors own source acquisition, ODS repositories own normalized source rows,
and this module loads versioned warehouse facts in the caller's transaction.
No DDL, commits, network calls or file deletion happen here.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from apps.data_layer.warehouse_etl import DATASETS, WarehouseError, load_warehouse
from database.models.warehouse import LoadBatch, WarehouseBase


REQUIRED_REVISION = "20261010_0013"
PAGE_SIZE = 1000


def warehouse_availability(session: Session | None) -> dict[str, Any]:
    """Allow staged migration, but never label an unmigrated database loaded."""
    if not isinstance(session, Session):
        return {"status": "unavailable", "error_code": "DWH_SESSION_REQUIRED"}
    from database.models.raw_source import RawSourceBase
    from database.models import warehouse_sources as _source_models  # noqa: F401
    from database.models import warehouse_sync as _sync_models  # noqa: F401

    with session.no_autoflush:
        tables = set(inspect(session.connection()).get_table_names())
    required = set(WarehouseBase.metadata.tables) | set(RawSourceBase.metadata.tables) | {"task_runs", "task_steps"}
    missing = sorted(required - tables)
    if missing:
        return {"status": "unavailable", "error_code": "DWH_SCHEMA_MISSING",
                "required_revision": REQUIRED_REVISION, "missing_tables": missing}
    inspector = inspect(session.connection())
    missing_columns = {}
    for name in ("dwh_fact_macro", "dwh_fact_candle", "dwh_fedwatch_context", "dwh_fedwatch_source_evidence"):
        columns = {column["name"] for column in inspector.get_columns(name)}
        absent = sorted(set(WarehouseBase.metadata.tables[name].columns.keys()) - columns)
        if absent:
            missing_columns[name] = absent
    if missing_columns:
        return {"status": "unavailable", "error_code": "DWH_SCHEMA_MISSING",
                "required_revision": REQUIRED_REVISION, "missing_columns": missing_columns}
    return {"status": "ready"}


def _empty_summary(dataset: str) -> dict[str, Any]:
    return {"dataset": dataset, "status": "loaded", "processed": 0, "planned": 0,
            "inserted": 0, "skipped": 0, "rejected": 0, "load_batch_ids": [],
            "task_run_ids": [], "error_codes": [], "raw_registered": 0,
            "raw_ready": 0, "raw_expired": 0, "raw_blocked": []}


def _merge(summary: dict, part: dict) -> None:
    for key in ("processed", "planned", "inserted", "skipped", "rejected"):
        summary[key] += int(part.get(key, 0))
    summary["load_batch_ids"].extend(part.get("load_batch_ids") or [])
    if part.get("task_run_id"):
        summary["task_run_ids"].append(part["task_run_id"])
    summary["error_codes"] = sorted(set(summary["error_codes"]) | set(part.get("error_codes") or []))
    if summary["rejected"]:
        summary["status"] = "partial" if summary["planned"] else "rejected"


def ingest_collection_records(
    session: Session,
    dataset: str,
    *,
    record_ids: Iterable[str],
    storage_root: Path,
    run_id: str | None = None,
    raw_sources: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Load exactly the just-persisted records, including corrections/late data.

    A source-id high water mark would miss corrections and late UUIDs. Runtime
    producers pass the actual affected IDs; bounded backfills retain their own
    explicit scan cursor. Empty IDs must never accidentally select the full DB.
    """
    availability = warehouse_availability(session)
    if availability["status"] != "ready":
        return {"dataset": dataset, **availability}
    supplied_ids = list(record_ids)
    if any(not isinstance(value, (str, UUID)) or not str(value).strip() for value in supplied_ids):
        raise WarehouseError("DWH_RECORD_IDS_INVALID")
    ids = list(dict.fromkeys(str(value) for value in supplied_ids))
    from apps.data_layer.warehouse_sources import load_source_warehouse

    loader = load_warehouse if dataset in DATASETS else load_source_warehouse
    summary = _empty_summary(dataset)
    session.flush()
    for offset in range(0, len(ids), PAGE_SIZE):
        part = loader(session, dataset, record_ids=ids[offset:offset + PAGE_SIZE],
                      limit=PAGE_SIZE, storage_root=storage_root, dry_run=False)
        _merge(summary, part)
        if part.get("processed", 0) != len(ids[offset:offset + PAGE_SIZE]):
            summary["status"] = "partial" if summary["planned"] else "rejected"
            summary["error_codes"] = sorted(set(summary["error_codes"]) | {"DWH_RECORDS_MISSING"})
    sources = list(raw_sources)
    known_paths = {source.get("raw_path") for source in sources}
    sources.extend(source for source in collection_raw_sources(session, dataset, ids)
                   if source["raw_path"] not in known_paths)
    _register_sources(session, summary, sources, storage_root=storage_root, run_id=run_id)
    return summary


def ingest_news_collection(
    session: Session,
    items: Iterable[Any],
    *,
    run_id: str | None,
    storage_root: Path,
    source_refs: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    availability = warehouse_availability(session)
    if availability["status"] != "ready":
        return {"dataset": "news-items", **availability}
    if not run_id:
        return {"dataset": "news-items", "status": "unavailable", "error_code": "DWH_PRODUCER_REQUIRED"}
    from apps.data_layer.warehouse_sources import load_news_items

    values = [item.to_dict() if hasattr(item, "to_dict") else dict(item) for item in items]
    summary = _empty_summary("news-items")
    for offset in range(0, len(values), PAGE_SIZE):
        _merge(summary, load_news_items(session, values[offset:offset + PAGE_SIZE],
                                       run_id=run_id, storage_root=storage_root, dry_run=False))
    sources: dict[str, dict] = {}
    for item in values:
        path = item.get("raw_path")
        if not path:
            continue
        source = sources.setdefault(path, {"raw_path": path, "source_key": item.get("source_key"),
                                           "source_url": item.get("url"), "collected_at": item.get("fetched_at"),
                                           "expected_records": 0})
        source["expected_records"] += 1
    for ref in source_refs:
        path = ref.get("raw_path") or ref.get("raw_artifact_ref")
        if path and path not in sources:
            sources[path] = {"raw_path": path, "source_key": ref.get("source_key") or ref.get("source"),
                             "source_url": ref.get("source_url") or ref.get("url"),
                             "collected_at": ref.get("retrieved_at") or ref.get("fetched_at") or ref.get("collected_at")}
    _register_sources(session, summary, sources.values(), storage_root=storage_root, run_id=run_id)
    return summary


def ingest_news_artifacts(session, artifacts, *, storage_root, run_id):
    """Shared by both Dagster and the compatibility worker after registration."""
    datasets = {"event_candidates.json": "news-events", "daily_analysis_triggers.json": "news-triggers"}
    selected = defaultdict(list)
    for artifact in artifacts:
        dataset = datasets.get(Path(artifact.file_path).name)
        if dataset:
            selected[dataset].append(str(artifact.artifact_id))
    return {dataset: ingest_collection_records(session, dataset, record_ids=ids,
                                               storage_root=storage_root, run_id=run_id)
            for dataset, ids in selected.items()}


def macro_raw_sources(rows):
    """Capture provenance before ODS rows are updated by a later collection."""
    sources = {}
    seen = set()
    for row in rows:
        if row.id in seen or not row.raw_path:
            continue
        seen.add(row.id)
        source = sources.setdefault(row.raw_path, {"raw_path": row.raw_path,
                                                   "source_key": row.source_key,
                                                   "source_url": row.source_url,
                                                   "collected_at": row.retrieved_at,
                                                   "expected_records": 0})
        source["expected_records"] += 1
    return list(sources.values())


def collection_raw_sources(session, dataset, record_ids):
    """Project declared ODS file references, including multi-response envelopes.

    Source metadata is used transiently for lineage, never copied as a blob.
    Failed collections/partial loads remain cataloged but cannot earn a receipt.
    """
    from sqlalchemy import func
    from database.models.analysis import MacroObservation, MarketCandle
    from database.models.cme import CmeRawFile, CmeOptionRow
    from database.models.fedwatch import FedWatchRawSnapshot, FedWatchMeetingSnapshot, FedWatchProbability, FedWatchFutures
    from database.models.cme_settlement import CmeSettlementSnapshot, CmeSettlementContract

    if not record_ids or dataset not in {"macro", "candles", "cme-options", "fedwatch", "settlement"}:
        return []
    result = {}

    def add(path, *, cursor, source, url, collected, expected, sha=None, purpose="primary", producer=None):
        if not path:
            return
        descriptor = result.setdefault(path, {"raw_path": path, "source_key": source, "source_url": url,
                                               "collected_at": collected, "expected_records": 0,
                                               "sha256": sha, "purpose": purpose, "source_cursors": [],
                                               "producer_run_id": producer})
        if cursor not in descriptor["source_cursors"]:
            descriptor["expected_records"] += expected
            descriptor["source_cursors"].append(cursor)

    for offset in range(0, len(record_ids), PAGE_SIZE):
        ids = record_ids[offset:offset + PAGE_SIZE]
        if dataset == "macro":
            rows = session.scalars(select(MacroObservation).where(MacroObservation.id.in_(ids)))
            for row in rows:
                add(row.raw_path, cursor=row.id, source=row.source_key, url=row.source_url,
                    collected=row.retrieved_at, expected=1, producer=row.run_id)
                for ref in row.source_refs or []:
                    if not isinstance(ref, dict):
                        continue
                    for key in ("raw_archive_path", "raw_artifact_ref", "raw_path"):
                        path = ref.get(key)
                        if path and path != row.raw_path:
                            add(path, cursor=row.id, source=row.source_key, url=ref.get("source_url") or row.source_url,
                                collected=row.retrieved_at, expected=1, sha=ref.get("sha256") if key == "raw_path" else None,
                                purpose="source_evidence", producer=row.run_id)
        elif dataset == "candles":
            for row in session.scalars(select(MarketCandle).where(MarketCandle.id.in_(ids))):
                ref = row.source_ref or {}
                add(row.raw_path, cursor=row.id, source=row.source, url=ref.get("source_url"),
                    collected=ref.get("retrieved_at") or ref.get("collected_at"), expected=1,
                    sha=ref.get("sha256"), producer=ref.get("producer_run_id"))
        elif dataset == "cme-options":
            for row in session.scalars(select(CmeRawFile).where(CmeRawFile.id.in_(ids))):
                count = session.scalar(select(func.count()).select_from(CmeOptionRow).where(CmeOptionRow.raw_file_id == row.id))
                add(row.raw_path, cursor=row.id, source=row.source, url=row.source_url,
                    collected=row.retrieved_at, expected=count, sha=row.sha256)
        elif dataset == "fedwatch":
            for row in session.scalars(select(FedWatchRawSnapshot).where(FedWatchRawSnapshot.snapshot_id.in_(ids))):
                count = session.scalar(select(func.count()).select_from(FedWatchProbability).join(
                    FedWatchMeetingSnapshot, FedWatchProbability.meeting_snapshot_id == FedWatchMeetingSnapshot.id
                ).where(FedWatchMeetingSnapshot.snapshot_id == row.snapshot_id))
                count += session.scalar(select(func.count()).select_from(FedWatchFutures).where(FedWatchFutures.snapshot_id == row.snapshot_id))
                # content_hash belongs to the primary response, not manifest.json.
                add(row.raw_artifact_ref, cursor=row.snapshot_id, source=row.source, url=row.source_url,
                    collected=row.collected_at, expected=count, purpose="manifest")
                for ref in row.source_refs or []:
                    if not isinstance(ref, dict):
                        continue
                    add(ref.get("raw_artifact_ref") or ref.get("raw_path"), cursor=row.snapshot_id,
                        source=row.source, url=ref.get("source_url"), collected=ref.get("collected_at") or row.collected_at,
                        expected=count, sha=ref.get("content_hash") or ref.get("sha256"), purpose="response")
                target = (row.snapshot_metadata or {}).get("target_reference") or {}
                for ref in target.get("source_refs") or []:
                    if not isinstance(ref, dict):
                        continue
                    add(ref.get("raw_artifact_ref") or ref.get("raw_path"), cursor=row.snapshot_id,
                        source=ref.get("source") or row.source, url=ref.get("source_url"),
                        collected=ref.get("retrieved_at") or row.collected_at,
                        expected=count, sha=ref.get("content_hash") or ref.get("sha256"), purpose="source_evidence")
        else:
            for row in session.scalars(select(CmeSettlementSnapshot).where(CmeSettlementSnapshot.snapshot_id.in_(ids))):
                source = row.payload or {}
                count = session.scalar(select(func.count()).select_from(CmeSettlementContract).where(CmeSettlementContract.snapshot_id == row.snapshot_id))
                add(source.get("raw_artifact_ref"), cursor=row.snapshot_id, source=source.get("source"),
                    url=source.get("source_url"), collected=row.observed_at, expected=count, sha=source.get("content_hash"))
    return list(result.values())


def _raw_key(path: str | Path | None, storage_root: Path) -> str | None:
    if not path:
        return None
    from apps.runtime.storage_paths import remap_storage_path
    try:
        candidate = remap_storage_path(path, storage_root=storage_root)
    except ValueError:
        return None
    if candidate.is_absolute():
        try:
            candidate = candidate.relative_to(storage_root.absolute())
        except ValueError:
            return None
    if candidate.parts[:1] == ("storage",):
        candidate = Path(*candidate.parts[1:])
    if candidate.parts[:1] != ("raw",) or ".." in candidate.parts:
        return None
    return candidate.as_posix()


def _collected_at(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
        if not isinstance(stamp, datetime):
            return None
        # Legacy typed ODS DateTime columns use UTC on SQLite roundtrip.
        return stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp.astimezone(UTC)
    except ValueError:
        return None


def _register_sources(session, summary, sources, *, storage_root, run_id):
    from database.queries.raw_source import (
        has_completed_retention_tombstone,
        register_raw_file,
        record_raw_file_load,
    )
    from database.models.warehouse_sync import BatchSourceFile

    root = Path(storage_root).absolute()
    by_path: dict[str, list[LoadBatch]] = defaultdict(list)
    by_cursor = {}
    batch_ids = summary["load_batch_ids"]
    for offset in range(0, len(batch_ids), PAGE_SIZE):
        for batch in session.scalars(select(LoadBatch).where(LoadBatch.id.in_(batch_ids[offset:offset + PAGE_SIZE]))):
            by_cursor[batch.source_cursor] = batch
            key = _raw_key(batch.source_artifact_path, root)
            if key:
                by_path[key].append(batch)
    seen = set()
    for source in sources:
        path = _raw_key(source.get("raw_path"), root)
        if not path or path in seen:
            continue
        seen.add(path)
        summary.setdefault("raw_expired", 0)
        try:
            expired = has_completed_retention_tombstone(
                session,
                storage_root=root,
                raw_path=path,
                expected_sha256=source.get("sha256"),
            )
        except (ValueError, OSError):
            # Unsafe roots/paths remain catalog failures. They must not be
            # mistaken for an audited expiry or roll back already-loaded facts.
            summary["raw_blocked"].append(
                {"raw_path": path, "reason": "RAW_REGISTRATION_REJECTED"}
            )
            continue
        if expired:
            summary["raw_expired"] += 1
            continue
        collected = _collected_at(source.get("collected_at"))
        if not collected or not source.get("source_key"):
            summary["raw_blocked"].append({"raw_path": path, "reason": "RAW_SOURCE_METADATA_MISSING"})
            continue
        # Catalog errors cannot roll back successful financial facts, and a
        # missing receipt can only prevent deletion, never authorize it.
        connection = session.connection()
        if connection.dialect.name == "sqlite" and not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql("BEGIN")
        try:
            with session.begin_nested():
                raw = register_raw_file(session, storage_root=root, raw_path=path,
                                        source_key=source["source_key"], source_url=source.get("source_url"),
                                        collected_at=collected, producer_run_id=run_id or source.get("producer_run_id"),
                                        expected_sha256=source.get("sha256"))
            summary["raw_registered"] += 1
        except (ValueError, OSError):
            summary["raw_blocked"].append({"raw_path": path, "reason": "RAW_REGISTRATION_REJECTED"})
            continue
        try:
            with session.begin_nested():
                batches = [by_cursor[cursor] for cursor in source.get("source_cursors", []) if cursor in by_cursor]
                if not batches:
                    batches = by_path.get(path, [])
                for batch in batches:
                    if batch.status != "loaded" or batch.rejected:
                        continue
                    link = session.get(BatchSourceFile, (batch.id, path))
                    if link is None:
                        session.add(BatchSourceFile(batch_id=batch.id, raw_path=path, storage_root=str(root.resolve()),
                                                   sha256=raw.sha256, byte_size=raw.byte_size, source_key=raw.source_key,
                                                   source_url=raw.source_url, collected_at=collected,
                                                   purpose=source.get("purpose", "primary"),
                                                   batch_source_path=batch.source_artifact_path,
                                                   batch_source_sha256=batch.source_sha256,
                                                   batch_source_cursor=batch.source_cursor))
                session.flush()
                expected = source.get("expected_records")
                loaded = sum(batch.inserted + batch.skipped for batch in batches)
                rejected = sum(batch.rejected for batch in batches)
                if batches and expected is not None and expected == loaded and not rejected:
                    record_raw_file_load(session, raw_file_id=raw.id, dataset=summary["dataset"],
                                         expected_records=expected, loaded_records=loaded, rejected_records=0,
                                         load_batch_ids=[batch.id for batch in batches])
                    summary["raw_ready"] += 1
                else:
                    summary["raw_blocked"].append({"raw_path": path, "reason": "RAW_WAREHOUSE_COVERAGE_INCOMPLETE"})
        except (ValueError, OSError):
            summary["raw_blocked"].append({"raw_path": path, "reason": "RAW_REGISTRATION_REJECTED"})
