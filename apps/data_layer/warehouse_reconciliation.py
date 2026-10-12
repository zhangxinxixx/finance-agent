"""Strictly bounded reuse checks for warehouse maintenance scans."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
import json
from uuid import UUID

from sqlalchemy import func, select

from database.models.warehouse import (
    CandleFact,
    LoadBatch,
    MacroFact,
    NewsEventFact,
    NewsTriggerFact,
    ProducerRunDimension,
)


def rejected_input_sha256(dataset, record, producer_context):
    """source_sha256 namespace: maintenance-rejected-input-v1 (never raw SHA).

    Encode the entire source record, including transient numeric lineage, and
    current producer context. Unsupported values disable reuse, not validation.
    Type tags preserve invalid/nonfinite values without lossy string coercion.
    """
    def encode(value):
        if value is None or type(value) in (bool, int, str):
            return [type(value).__name__, value]
        if isinstance(value, (float, Decimal, datetime, date, UUID)):
            return [type(value).__name__, str(value)]
        if isinstance(value, list):
            return ["list", [encode(item) for item in value]]
        if isinstance(value, dict) and all(isinstance(key, str) for key in value):
            return ["dict", [[key, encode(value[key])] for key in sorted(value)]]
        raise TypeError("unsupported rejection fingerprint input")

    try:
        payload = encode(["maintenance-rejected-input-v1", dataset, record, producer_context])
        return sha256(json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()
    except (TypeError, ValueError):
        return None


def reusable_rejected_maintenance_batches(session, dataset, prepared, *, transform_version):
    """Only latest pure rejections with a full input digest and no linked facts."""
    if dataset not in {"macro", "candles"} or not prepared:
        return {}
    prepared = [(attrs, producer, facts) for attrs, producer, facts in prepared
                if attrs.get("source_sha256") and facts
                and all(isinstance(fact, str) for fact in facts)]
    if not prepared:
        return {}
    cursors = [attrs["source_cursor"] for attrs, _, _ in prepared]
    latest_ids = (
        select(func.max(LoadBatch.id))
        .where(LoadBatch.dataset == dataset, LoadBatch.source_cursor.in_(cursors))
        .group_by(LoadBatch.source_cursor)
    )
    latest = {row.source_cursor: row for row in session.scalars(
        select(LoadBatch).where(LoadBatch.id.in_(latest_ids))
    )}
    if not latest:
        return {}
    ids = [row.id for row in latest.values()]
    linked = set()
    for model in (MacroFact, CandleFact, NewsEventFact, NewsTriggerFact):
        linked.update(session.scalars(select(model.batch_id).where(model.batch_id.in_(ids))))
    producer_ids = {batch.producer_run_id for batch in latest.values() if batch.producer_run_id is not None}
    producers = {row.id: row for row in session.scalars(
        select(ProducerRunDimension).where(ProducerRunDimension.id.in_(producer_ids))
    )}
    reusable = {}
    for attrs, producer, facts in prepared:
        batch = latest.get(attrs["source_cursor"])
        if batch is None:
            continue
        dimension = producers.get(batch.producer_run_id)
        if producer is None:
            if batch.producer_run_id is not None:
                continue
        elif dimension is None or any(
            getattr(dimension, field) != producer[field]
            for field in ("run_id", "verified", "producer_date", "started_at")
        ):
            continue
        if (batch.status != "rejected" or batch.inserted != 0 or batch.skipped != 0
                or batch.id in linked or batch.processed != len(facts)
                or batch.rejected != len(facts) or batch.error_code != facts[-1]
                or batch.transform_version != transform_version
                or any(getattr(batch, field) != attrs.get(field) for field in _BATCH_INPUT_FIELDS)):
            continue
        reusable[attrs["source_cursor"]] = batch
    return reusable


_BATCH_INPUT_FIELDS = (
    "source_artifact_path",
    "source_sha256",
    "as_of",
    "producer_date",
    "schema_version",
    "rule_version",
    "quality_status",
    "source_event_count",
    "source_trigger_count",
    "source_rejected_count",
)


def reusable_maintenance_batches(session, dataset, prepared, *, transform_version):
    """Return latest successful batches proven equivalent to prepared inputs.

    Preparation has already rerun current mapping, source-policy, quality and
    version validation. This check deliberately considers only the newest
    batch for each source cursor, so an earlier success cannot hide a later
    rejection. It is maintenance-only and intentionally limited to the two
    single-fact numeric datasets whose equality can be established exactly.
    """
    if dataset not in {"macro", "candles"} or not prepared:
        return {}

    cursors = [attrs["source_cursor"] for attrs, _, _ in prepared]
    latest_ids = (
        select(func.max(LoadBatch.id))
        .where(LoadBatch.dataset == dataset, LoadBatch.source_cursor.in_(cursors))
        .group_by(LoadBatch.source_cursor)
    )
    latest = {
        batch.source_cursor: batch
        for batch in session.scalars(select(LoadBatch).where(LoadBatch.id.in_(latest_ids)))
    }

    fact_model = MacroFact if dataset == "macro" else CandleFact
    fact_versions = set(
        session.execute(
            select(
                fact_model.source_record_id,
                fact_model.version_sha256,
                fact_model.producer_run_id,
            ).where(fact_model.source_record_id.in_(cursors))
        ).all()
    )

    producer_runs = {
        str(producer["run_id"])
        for _, producer, _ in prepared
        if producer is not None
    }
    producers = (
        {
            row.run_id: row
            for row in session.scalars(
                select(ProducerRunDimension).where(ProducerRunDimension.run_id.in_(producer_runs))
            )
        }
        if producer_runs
        else {}
    )

    reusable = {}
    for attrs, producer, facts in prepared:
        cursor = attrs["source_cursor"]
        batch = latest.get(cursor)
        if batch is None or any(isinstance(fact, str) for fact in facts):
            continue
        producer_id = None
        if producer is not None:
            dimension = producers.get(str(producer["run_id"]))
            if dimension is None or any(
                getattr(dimension, field) != producer[field]
                for field in ("verified", "producer_date", "started_at")
            ):
                continue
            producer_id = dimension.id
        versions = [fact[2] for fact in facts]
        if (
            batch.status != "loaded"
            or batch.rejected != 0
            or batch.error_code is not None
            or batch.transform_version != transform_version
            or batch.producer_run_id != producer_id
            or batch.processed != len(facts)
            or batch.inserted + batch.skipped != len(facts)
            or any(getattr(batch, field) != attrs.get(field) for field in _BATCH_INPUT_FIELDS)
            or any((cursor, version, producer_id) not in fact_versions for version in versions)
        ):
            continue
        reusable[cursor] = batch
    return reusable
