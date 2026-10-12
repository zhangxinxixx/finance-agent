"""Bounded reconciliation and retention in the existing task control plane."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from apps.data_layer.collection_ingestion import (
    warehouse_availability, collection_raw_sources, _register_sources,
)
from apps.data_layer.warehouse_etl import DATASETS, WarehouseError, load_warehouse
from database.models.warehouse_sync import WarehouseSyncCursor
from database.models.warehouse import LoadBatch


RECONCILE_DATASETS = (*DATASETS, "cme-options", "fedwatch", "settlement")


def _retention_identity(item: dict[str, Any]) -> tuple[str, Any, Any]:
    if item.get("raw_path") or item.get("sha256"):
        return ("physical", item.get("raw_path"), item.get("sha256"))
    return ("catalog", item.get("raw_file_id") or item.get("id"), None)


def _retention_reason_file_identities(items: list[dict[str, Any]]) -> dict[str, set[tuple[str, Any, Any]]]:
    by_reason: dict[str, set[tuple[str, Any, Any]]] = {}
    for item in items:
        if not isinstance(item, dict) or not item.get("reason"):
            continue
        by_reason.setdefault(str(item["reason"]), set()).add(_retention_identity(item))
    return by_reason


def enrich_raw_retention_result(result: dict[str, Any]) -> dict[str, Any]:
    """Attach stable, operator-readable retention accounting to a page result.

    The retention engine deliberately returns the individual blocked/deleted
    identities so callers can audit a decision.  Maintenance and the CLI also
    need a compact summary, otherwise a large page is reduced to one opaque
    ``blocked_count``.  This helper only derives fields from the existing
    result; it never changes the eligibility decision or touches the database.

    ``inspected_count`` is owned by the retention engine and keeps its original
    meaning: catalog rows inspected in the bounded page.  The additional
    ``inspected_file_count`` counts distinct physical identities.  The catalog
    can contain multiple producer references for one physical file, so these
    values intentionally differ.
    """
    if not isinstance(result, dict):
        return result
    if not any(key in result for key in ("blocked", "candidates", "deleted")):
        return result

    enriched = dict(result)
    blocked = list(enriched.get("blocked") or [])
    candidates = list(enriched.get("candidates") or [])
    deleted = list(enriched.get("deleted") or [])
    reasons = Counter(
        str(item["reason"])
        for item in blocked
        if isinstance(item, dict) and item.get("reason")
    )
    # Preview exposes candidates; an apply page exposes its final blocked and
    # deleted outcomes.  Both sets represent all identities inspected by that
    # page, while reference_ids may contain several catalog rows for one file.
    inspected_items = candidates + blocked if "candidates" in enriched else blocked + deleted
    identities = {
        _retention_identity(item)
        for item in inspected_items
        if isinstance(item, dict)
    }
    enriched["inspected_file_count"] = len(identities)
    enriched["blocked_by_reason"] = dict(sorted(reasons.items()))
    enriched["blocked_reason_count_basis"] = "blocked_entries"
    enriched["blocked_file_count_by_reason"] = {
        reason: len(files)
        for reason, files in sorted(_retention_reason_file_identities(blocked).items())
    }
    return enriched


def reconcile_warehouse(session, *, storage_root, datasets=RECONCILE_DATASETS, page_size=500, max_pages=10, now=None):
    """Advance scan cursors in the same transaction as their loaded facts.

    Completed scans restart from the beginning on the next invocation. This
    discovers late IDs and corrections as well as newly appended records.
    Runtime collection uses exact affected IDs and does not wait for this scan.
    Caller commits; failures leave neither facts nor an advanced checkpoint.
    """
    if (type(page_size) is not int or not 1 <= page_size <= 1000
            or type(max_pages) is not int or not 1 <= max_pages <= 100
            or not datasets or any(dataset not in RECONCILE_DATASETS for dataset in datasets)):
        raise WarehouseError("DWH_ARGUMENT_INVALID")
    available = warehouse_availability(session)
    if available["status"] != "ready":
        return available
    from apps.data_layer.warehouse_sources import load_source_warehouse

    clock = now or datetime.now(UTC)
    if clock.tzinfo is None:
        raise WarehouseError("DWH_TIME_INVALID")
    results = []
    for dataset in dict.fromkeys(datasets):
        cursor = session.scalar(select(WarehouseSyncCursor).where(WarehouseSyncCursor.dataset == dataset).with_for_update())
        if cursor is None:
            cursor = WarehouseSyncCursor(dataset=dataset, cycle_started_at=clock, updated_at=clock)
            session.add(cursor)
            session.flush([cursor])
        elif cursor.cycle_completed_at is not None:
            cursor.after_cursor = None
            cursor.cycle_started_at = clock
            cursor.cycle_completed_at = None
        loader = load_warehouse if dataset in DATASETS else load_source_warehouse
        result = {"dataset": dataset, "processed": 0, "inserted": 0, "skipped": 0, "rejected": 0,
                  "pages": 0, "cycle_complete": False, "error_codes": []}
        for _ in range(max_pages):
            page = loader(session, dataset, limit=page_size, after=cursor.after_cursor,
                          storage_root=Path(storage_root), dry_run=False,
                          **({"reuse_unchanged_successful": True, "reuse_unchanged_rejected": True}
                             if dataset in {"macro", "candles"} else {}))
            # Reconciliation also establishes file receipts; importing facts
            # alone must not leave every historical source permanently untracked.
            batch_ids = page.get("load_batch_ids") or []
            ids = list(session.scalars(select(LoadBatch.source_cursor).where(LoadBatch.id.in_(batch_ids)))) if batch_ids else []
            page.update(raw_registered=0, raw_ready=0, raw_expired=0, raw_blocked=[])
            _register_sources(session, page, collection_raw_sources(session, dataset, ids),
                              storage_root=Path(storage_root), run_id=None)
            result["pages"] += 1
            for key in ("processed", "inserted", "skipped", "rejected"):
                result[key] += page[key]
            result["error_codes"] = sorted(set(result["error_codes"]) | set(page.get("error_codes") or []))
            result["raw_registered"] = result.get("raw_registered", 0) + page["raw_registered"]
            result["raw_ready"] = result.get("raw_ready", 0) + page["raw_ready"]
            result["raw_expired"] = result.get("raw_expired", 0) + page["raw_expired"]
            result["reused_batches"] = result.get("reused_batches", 0) + page.get("reused_batches", 0)
            result["reused_rejected_batches"] = result.get("reused_rejected_batches", 0) + page.get("reused_rejected_batches", 0)
            result.setdefault("raw_blocked", []).extend(page["raw_blocked"])
            cursor.after_cursor = page["next_after"]
            cursor.last_task_run_id = page["task_run_id"]
            cursor.updated_at = clock
            if page["processed"] < page_size:
                cursor.cycle_completed_at = clock
                result["cycle_complete"] = True
                break
        result["next_after"] = cursor.after_cursor
        results.append(result)
    session.flush()
    return {"status": "partial" if any(row["rejected"] for row in results) else "loaded", "datasets": results}


def run_warehouse_maintenance(session_factory, *, storage_root, page_size=500, max_pages=10, apply_retention=False, retention_days=30):
    storage_root = Path(storage_root).absolute()
    instant = datetime.now(UTC)
    with session_factory() as session:
        result = reconcile_warehouse(
            session,
            storage_root=storage_root,
            page_size=page_size,
            max_pages=max_pages,
            now=instant,
        )
        session.commit()
    if result["status"] == "unavailable":
        return result
    from apps.data_layer.raw_retention import apply_raw_retention, preview_raw_retention

    if apply_retention:
        pages = []
        for _ in range(max_pages):
            page = enrich_raw_retention_result(apply_raw_retention(
                session_factory,
                storage_root=storage_root,
                now=instant,
                retention_days=retention_days,
                limit=page_size,
            ))
            pages.append(page)
            if not page.get("scan_has_more", False):
                break
        retention = dict(pages[0])
        for key in ("candidate_count", "deleted_count", "blocked_count", "reconciled_count"):
            retention[key] = sum(int(page.get(key, 0)) for page in pages)
        for key in ("deleted", "blocked"):
            retention[key] = [item for page in pages for item in page.get(key, [])]
        catalog_scan_counts = [
            int(page["inspected_count"])
            for page in pages
            if "inspected_count" in page
        ]
        if catalog_scan_counts:
            retention["inspected_count"] = sum(catalog_scan_counts)
        else:
            # Apply pages expose final outcomes rather than the preview's raw
            # catalog row count; do not copy a stale page field into the
            # aggregate and give it an ambiguous meaning.
            retention.pop("inspected_count", None)
        reason_counts = Counter()
        reason_files: dict[str, set[tuple[str, Any, Any]]] = {}
        identities = set()
        for page in pages:
            # Entry counts are additive: repeated blocked decisions remain
            # useful evidence even when they refer to one physical file.
            reason_counts.update(page.get("blocked_by_reason") or {})
            for reason, files in _retention_reason_file_identities(page.get("blocked") or []).items():
                reason_files.setdefault(reason, set()).update(files)
            for item in (page.get("blocked") or []) + (page.get("deleted") or []):
                if not isinstance(item, dict):
                    continue
                identities.add(_retention_identity(item))
        retention["inspected_file_count"] = len(identities)
        retention["blocked_by_reason"] = dict(sorted(reason_counts.items()))
        retention["blocked_reason_count_basis"] = "blocked_entries"
        retention["blocked_file_count_by_reason"] = {
            reason: len(files) for reason, files in sorted(reason_files.items())
        }
        retention.update(
            pages=len(pages),
            task_run_ids=[page["task_run_id"] for page in pages],
            scan_wrapped=any(page.get("scan_wrapped", False) for page in pages),
            scan_has_more=pages[-1].get("scan_has_more", False),
            scan_next_cursor=pages[-1].get("scan_next_cursor"),
        )
    else:
        with session_factory() as session:
            retention = preview_raw_retention(session, storage_root=storage_root,
                                              now=instant, retention_days=retention_days, limit=page_size)
        retention = enrich_raw_retention_result(retention)
    return {**result, "raw_retention": retention}
