"""FedWatch enrichment within the existing research merge/worker lifecycle."""

from copy import deepcopy
from datetime import UTC, datetime
import os
from pathlib import Path

from apps.features.macro.fedwatch import build_fedwatch_factors, build_fedwatch_health, build_fedwatch_view
from apps.runtime.immutable_artifact import immutable_json_item, write_immutable_artifact_bundle
from database.queries.fedwatch import save_fedwatch_snapshot
from database.queries.warehouse_fedwatch import get_fedwatch_warehouse_snapshot, get_latest_fedwatch_attempt


def fedwatch_settings(*, event_window=False):
    def integer(name, default, lower, upper):
        value = int(os.environ.get(name, default))
        if not lower <= value <= upper:
            raise ValueError("invalid_" + name)
        return value
    normal = integer("FEDWATCH_POLL_INTERVAL_MINUTES", 30, 5, 1440)
    event = integer("FEDWATCH_EVENT_POLL_INTERVAL_MINUTES", 5, 5, 60)
    sla = integer("FEDWATCH_EVENT_STALENESS_MINUTES" if event_window else "FEDWATCH_STALENESS_MINUTES",
                  15 if event_window else 60, 5, 1440)
    return {"poll_interval_minutes": event if event_window else normal,
            "allowed_staleness_seconds": sla * 60, "event_window": event_window}


def _time(value):
    value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("timezone_required")
    return value.astimezone(UTC)


def fedwatch_view(observed, *, as_of, latest_attempt=None, event_window=False):
    """Re-evaluate age at read time; cached factors never retain fresh status."""
    return build_fedwatch_view(observed, as_of=as_of, latest_attempt=latest_attempt,
                               settings=fedwatch_settings(event_window=event_window))


def refresh_fedwatch(session, *, storage_root, now=None, collector=None, target_collector=None,
                     force=False, event_window=False, scheduled_for=None, run_id=None):
    """Called from a recorded worker step; owns neither session nor commit."""
    if collector is None:
        from apps.collectors.macro.fedwatch_free import collect_fedwatch_free
        collector = collect_fedwatch_free
    if target_collector is None:
        from apps.collectors.fed.target import collect_fed_target
        target_collector = collect_fed_target
    from apps.data_layer.collection_ingestion import warehouse_availability

    availability = warehouse_availability(session)
    if availability["status"] != "ready":
        raise RuntimeError(availability.get("error_code", "DWH_UNAVAILABLE"))
    clock = _time(now) if now else datetime.now(UTC)
    latest = get_latest_fedwatch_attempt(session, as_of=clock.isoformat())
    settings = fedwatch_settings(event_window=event_window)
    warehouse_ingestion = {"status": "not_due"}
    due = force or not latest or (clock - _time(latest["collected_at"])).total_seconds() >= settings["poll_interval_minutes"] * 60
    if scheduled_for is not None:
        tick = _time(scheduled_for)
        if tick > clock:
            raise ValueError("fedwatch_schedule_in_future")
        # Scheduled slots must not drift with collection duration. A retry of
        # the same slot reuses an observation already collected after its tick.
        due = force or not latest or _time(latest["collected_at"]) < tick
    if due:
        target = target_collector(storage_root=storage_root, now=clock if now is not None else None)
        observed = collector(storage_root=storage_root, now=clock if now is not None else None)
        observed = deepcopy(observed)
        observed["target_reference"] = target.get("reference")
        observed["target_reference_health"] = {k: target.get(k) for k in ("status", "reason", "raw_artifact_ref")}
        if now is None:
            clock = datetime.now(UTC)  # all collected knowledge precedes the final snapshot cutoff
        validation = build_fedwatch_health(observed, as_of=clock.isoformat(),
                                          allowed_staleness_seconds=settings["allowed_staleness_seconds"])
        if observed.get("parse_status") == "ok" and validation["status"] in {"parse_failed", "missing"}:
            observed.update(parse_status="parse_failed", reason=validation.get("reason"),
                            rejected_source_as_of=observed.get("as_of"), as_of=None, rows=[])
        observed["quality_summary"] = deepcopy(validation.get("quality_summary"))
        root = Path(storage_root)
        identity = observed["snapshot_id"]
        # UUID identity is collector-owned; reject path traversal from adapters.
        from uuid import UUID
        UUID(identity)
        parsed_path = Path("parsed/fedwatch") / (identity + ".json")
        factor_path = Path("features/fedwatch") / (identity + ".json")
        observed["parsed_artifact_ref"] = str(parsed_path)
        observed["factor_artifact_ref"] = str(factor_path)
        save_fedwatch_snapshot(session, observed)
        from apps.data_layer.collection_ingestion import ingest_collection_records

        warehouse_ingestion = ingest_collection_records(
            session, "fedwatch", record_ids=[identity], storage_root=root, run_id=run_id,
        )
        if warehouse_ingestion.get("status") == "unavailable":
            raise RuntimeError(warehouse_ingestion.get("error_code", "DWH_UNAVAILABLE"))
        warehouse_input = get_fedwatch_warehouse_snapshot(session, as_of=clock.isoformat(), snapshot_id=identity)
        factor = build_fedwatch_factors(
            warehouse_input, as_of=clock.isoformat(),
            target_reference=(warehouse_input or {}).get("target_reference"),
            allowed_staleness_seconds=settings["allowed_staleness_seconds"],
        )
        write_immutable_artifact_bundle([immutable_json_item(root / parsed_path, observed),
                                        immutable_json_item(root / factor_path, factor)], storage_root=root)
        if warehouse_input is not None:
            save_fedwatch_snapshot(session, observed, factor=factor)
        latest = get_latest_fedwatch_attempt(session, as_of=clock.isoformat())
    valid = get_fedwatch_warehouse_snapshot(session, as_of=clock.isoformat())
    return {**fedwatch_view(valid, latest_attempt=latest, as_of=clock.isoformat(), event_window=event_window),
            "warehouse": warehouse_ingestion}


def enrich_fedwatch_snapshot(snapshot, *, storage_root, db_session, collector=None, target_collector=None):
    result = deepcopy(snapshot)
    view = refresh_fedwatch(db_session, storage_root=storage_root, collector=collector, target_collector=target_collector)
    result.setdefault("macro", {}).setdefault("data", {})["fedwatch"] = view
    if view.get("snapshot_id"):
        result.setdefault("input_snapshot_ids", {})["fedwatch"] = view["snapshot_id"]
    result.setdefault("source_refs", []).extend(view["source_refs"])
    result["snapshot_time"] = view["evaluated_at"]
    return result
