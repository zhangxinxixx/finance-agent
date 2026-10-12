"""FedWatch indicator inputs from typed warehouse facts, without ODS bodies."""

from datetime import UTC, datetime

from sqlalchemy import func, select

from database.models.fedwatch import FedWatchRawSnapshot
from database.models.warehouse import LoadBatch
from database.models.warehouse_fedwatch import FedWatchContextFact, FedWatchSourceEvidence
from database.models.warehouse_sources import FedWatchFuturesFact, FedWatchProbabilityFact


def _instant(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    return value.astimezone(UTC)


def _iso(value):
    if isinstance(value, datetime) and value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat() if value is not None else None


def get_latest_fedwatch_attempt(session, *, as_of):
    """Operational metadata only; failed collection events remain observable."""
    row = session.execute(select(
        FedWatchRawSnapshot.snapshot_id, FedWatchRawSnapshot.collected_at,
        FedWatchRawSnapshot.parse_status, FedWatchRawSnapshot.reason,
    ).where(FedWatchRawSnapshot.collected_at <= _instant(as_of)).order_by(
        FedWatchRawSnapshot.collected_at.desc(), FedWatchRawSnapshot.snapshot_id.desc(),
    ).limit(1)).mappings().first()
    if row is None:
        return None
    return {**dict(row), "collected_at": _iso(row["collected_at"])}


def get_fedwatch_warehouse_snapshot(session, *, as_of, snapshot_id=None):
    cutoff = _instant(as_of)
    query = select(FedWatchContextFact).join(LoadBatch).where(
        FedWatchContextFact.collected_at <= cutoff,
        FedWatchContextFact.source_as_of <= cutoff,
        FedWatchContextFact.parse_status == "ok", LoadBatch.status == "loaded",
    )
    if snapshot_id is not None:
        query = query.where(FedWatchContextFact.source_snapshot_id == snapshot_id)
    context = session.scalar(query.order_by(
        FedWatchContextFact.source_as_of.desc(), FedWatchContextFact.collected_at.desc(),
        FedWatchContextFact.id.desc(),
    ).limit(1))
    if context is None:
        return None
    probabilities = _latest_rows(session, FedWatchProbabilityFact, context, cutoff, (
        "meeting_date", "comparison_window", "target_low", "target_high",
    ))
    futures = _latest_rows(session, FedWatchFuturesFact, context, cutoff, ("contract_ref",))
    references = {"market": [], "target": []}
    for ref in session.scalars(select(FedWatchSourceEvidence).where(
        FedWatchSourceEvidence.context_id == context.id,
    ).order_by(FedWatchSourceEvidence.scope, FedWatchSourceEvidence.ordinal)):
        fields = ("source", "source_url", "raw_artifact_ref", "raw_path", "sha256", "content_hash",
                  "source_tier", "capture_kind", "hash_verified_at_ingestion")
        item = {key: getattr(ref, key) for key in fields if getattr(ref, key) is not None}
        if ref.retrieved_at is not None:
            item["retrieved_at"] = _iso(ref.retrieved_at)
        references[ref.scope].append(item)
    result = {
        "snapshot_id": context.source_snapshot_id, "source": context.source, "source_url": context.source_url,
        "collected_at": _iso(context.collected_at), "as_of": _iso(context.source_as_of),
        "collector_version": context.collector_version, "http_status": context.http_status,
        "content_hash": context.content_hash, "raw_artifact_ref": context.raw_artifact_ref,
        "parse_status": context.parse_status, "reason": context.reason, "transport": context.transport,
        "source_refs": references["market"],
        "coverage": {"source_time_window": {"start": _iso(context.source_window_start),
                                               "end": _iso(context.source_window_end)},
                     "available_tab_count": context.available_tab_count,
                     "captured_tab_count": context.captured_tab_count,
                     "all_future_meetings": context.all_future_meetings},
        "rows": [{"meeting_date": row.meeting_date.isoformat(), "contract_ref": row.contract_ref,
                  "comparison_window": row.comparison_window, "as_of": _iso(row.observation_as_of),
                  "target_low": float(row.target_low), "target_high": float(row.target_high),
                  "probability": float(row.probability)} for row in probabilities],
        "futures": [{"contract_ref": row.contract_ref, "as_of": _iso(row.observation_as_of),
                     **{key: float(getattr(row, key)) if getattr(row, key) is not None else None
                        for key in ("settlement", "price", "implied_rate", "change", "change_pct")},
                     "volume": row.volume, "open_interest": row.open_interest} for row in futures],
        "warehouse_context_id": context.id, "warehouse_context_version": context.version_sha256,
    }
    if context.target_present:
        result["target_reference"] = {
            "lower": float(context.target_lower) if context.target_lower is not None else None,
            "upper": float(context.target_upper) if context.target_upper is not None else None,
            "rate_unit": context.target_rate_unit, "effective_at": _iso(context.target_effective_at),
            "published_at": _iso(context.target_published_at), "source_refs": references["target"],
            "timestamp_precision": context.target_timestamp_precision,
            "availability_convention": context.target_availability_convention,
        }
        if context.target_timestamp_precision is None:
            result["target_reference"].pop("timestamp_precision")
    return result


def _latest_rows(session, model, context, cutoff, grain):
    ranked = select(model.id.label("id"), func.row_number().over(
        partition_by=[getattr(model, field) for field in grain], order_by=model.id.desc(),
    ).label("rank")).where(
        model.source_snapshot_id == context.source_snapshot_id,
        model.collected_at <= cutoff, model.snapshot_as_of <= cutoff,
    ).subquery()
    return list(session.scalars(select(model).join(ranked, model.id == ranked.c.id).where(
        ranked.c.rank == 1,
    ).order_by(*(getattr(model, field) for field in grain))))
