"""Persist only named FedWatch context; probabilities remain separate facts."""

from sqlalchemy import select

from apps.data_layer.warehouse_etl import digest, fail, number, string, timestamp
from database.models.warehouse_fedwatch import FedWatchContextFact, FedWatchSourceEvidence
from database.numeric_source_policy import require_formal_numeric_source


def prepare_fedwatch_context(record):
    metadata = record.get("snapshot_metadata") or {}
    if not isinstance(metadata, dict):
        fail("DWH_MAPPING_INVALID")
    coverage = metadata.get("coverage") or {}
    if not isinstance(coverage, dict):
        fail("DWH_MAPPING_INVALID")
    window = coverage.get("source_time_window") or {}
    target = metadata.get("target_reference") or {}
    if not isinstance(window, dict) or not isinstance(target, dict):
        fail("DWH_MAPPING_INVALID")
    for name in ("available_tab_count", "captured_tab_count"):
        count = coverage.get(name)
        if count is not None and (type(count) is not int or not 0 <= count < 2**31):
            fail("DWH_NUMBER_INVALID")
    if coverage.get("all_future_meetings") is not None and type(coverage["all_future_meetings"]) is not bool:
        fail("DWH_MAPPING_INVALID")
    fields = dict(
        source_snapshot_id=record["snapshot_id"], source=record["source"], source_url=record["source_url"],
        collected_at=timestamp(record["collected_at"]), source_as_of=timestamp(record["as_of"]),
        collector_version=record["collector_version"], http_status=record["http_status"],
        content_hash=record["content_hash"], raw_artifact_ref=record["raw_artifact_ref"],
        parse_status=record["parse_status"], reason=record.get("reason"),
        transport=string(metadata.get("transport"), length=64),
        source_window_start=timestamp(window.get("start")), source_window_end=timestamp(window.get("end")),
        available_tab_count=coverage.get("available_tab_count"), captured_tab_count=coverage.get("captured_tab_count"),
        all_future_meetings=coverage.get("all_future_meetings"),
        target_present=metadata.get("target_reference") is not None,
        target_lower=number(target.get("lower")), target_upper=number(target.get("upper")),
        target_rate_unit=string(target.get("rate_unit"), length=32),
        target_effective_at=timestamp(target.get("effective_at")),
        target_published_at=timestamp(target.get("published_at")),
        target_timestamp_precision=string(target.get("timestamp_precision"), length=32),
        target_availability_convention=string(target.get("availability_convention")),
    )
    refs = []
    for scope, items in (("market", record.get("source_refs") or []), ("target", target.get("source_refs") or [])):
        if not isinstance(items, list):
            fail("DWH_MAPPING_INVALID")
        for ordinal, ref in enumerate(items):
            if not isinstance(ref, dict):
                fail("DWH_MAPPING_INVALID")
            if ref.get("hash_verified_at_ingestion") is not None and type(ref["hash_verified_at_ingestion"]) is not bool:
                fail("DWH_MAPPING_INVALID")
            try:
                require_formal_numeric_source(ref.get("source") or record["source"], ref, ref.get("raw_path"))
            except ValueError:
                fail("DWH_NUMERIC_SOURCE_FORBIDDEN")
            refs.append(dict(
                scope=scope, ordinal=ordinal, source=string(ref.get("source"), length=128),
                source_url=string(ref.get("source_url")),
                retrieved_at=timestamp(ref.get("retrieved_at") or ref.get("collected_at")),
                raw_artifact_ref=string(ref.get("raw_artifact_ref")), raw_path=string(ref.get("raw_path")),
                sha256=string(ref.get("sha256"), length=64), content_hash=string(ref.get("content_hash"), length=64),
                source_tier=string(ref.get("source_tier"), length=64),
                capture_kind=string(ref.get("capture_kind"), length=64),
                hash_verified_at_ingestion=ref.get("hash_verified_at_ingestion"),
            ))
    return fields, refs, digest({"fields": fields, "references": refs})


def persist_fedwatch_context(session, prepared, *, batch_id):
    fields, refs, version = prepared
    existing = session.scalar(select(FedWatchContextFact.id).where(
        FedWatchContextFact.source_snapshot_id == fields["source_snapshot_id"],
        FedWatchContextFact.version_sha256 == version,
    ))
    if existing is not None:
        return existing
    row = FedWatchContextFact(**fields, version_sha256=version, batch_id=batch_id)
    session.add(row)
    session.flush([row])
    session.add_all(FedWatchSourceEvidence(context_id=row.id, **ref) for ref in refs)
    session.flush()
    return row.id
