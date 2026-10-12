"""Bounded typed loading for collected source domains.

The service never creates schema or commits.  JSON source bodies are inspected
only for the explicitly allow-listed fields that legacy ODS tables have not yet
split into columns.
"""

from __future__ import annotations

from dataclasses import is_dataclass
from datetime import UTC, date, datetime
from pathlib import Path
import re
from uuid import UUID, uuid4

from sqlalchemy import inspect, select

from apps.data_layer.warehouse_etl import (
    DimensionCache,
    WarehouseError,
    digest,
    fail,
    number,
    producer_info,
    string,
    timestamp,
)
from database.models.cme import CmeOptionRow, CmeParseRun, CmeRawFile
from database.models.cme_settlement import CmeSettlementContract, CmeSettlementSnapshot
from database.models.fedwatch import (
    FedWatchFutures,
    FedWatchMeetingSnapshot,
    FedWatchProbability,
    FedWatchRawSnapshot,
)
from database.models.task import StepStatus, TaskRun, TaskStatus, TaskStep
from database.models.warehouse import LoadBatch, ProducerRunDimension
from database.models.warehouse_sources import (
    SOURCE_WAREHOUSE_TABLES,
    CmeOptionFact,
    FedFundsSettlementFact,
    FedWatchFuturesFact,
    FedWatchProbabilityFact,
    NewsItemFact,
)
from database.numeric_source_policy import require_formal_numeric_source


SOURCE_DATASETS = ("cme-options", "fedwatch", "settlement")
TRANSFORM_VERSION = "warehouse-collected-sources-v1"
_FUTURES_NUMBERS = ("settlement", "price", "implied_rate", "change", "change_pct")
_FUTURES_INTEGERS = ("volume", "open_interest")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_NEWS_FIELDS = (
    "source_key", "source_name", "source_type", "feed_key", "title", "url", "domain",
    "published_at", "fetched_at", "summary", "source_language", "source_country", "event_type",
    "verification_status", "duplicate_key", "raw_path", "parsed_path",
)


def _integer(value, *, signed=False, required=False):
    if value is None:
        if required:
            fail()
        return None
    if type(value) is not int or not -(2**31) <= value < 2**31 or (not signed and value < 0):
        fail("DWH_NUMBER_INVALID")
    return value


def _boolean(value):
    if value is not None and type(value) is not bool:
        fail("DWH_MAPPING_INVALID")
    return value


def _date(value):
    if isinstance(value, datetime):
        fail("DWH_TIME_INVALID")
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    fail("DWH_TIME_INVALID")


def _formal_numeric_source(source, source_url=None, raw_path=None):
    try:
        require_formal_numeric_source(source, source_url, raw_path)
    except ValueError:
        fail("DWH_NUMERIC_SOURCE_FORBIDDEN")


def _sha256(value, *, required=False):
    value = string(value, required=required, length=64)
    if value is not None and _SHA256.fullmatch(value) is None:
        fail("DWH_HASH_INVALID")
    return value


def _ids(record_ids):
    if record_ids is None:
        return None
    if not isinstance(record_ids, (list, tuple, set, frozenset)) or len(record_ids) > 1000:
        fail("DWH_ARGUMENT_INVALID")
    result = []
    for value in record_ids:
        if not isinstance(value, (str, UUID)) or not str(value):
            fail("DWH_ARGUMENT_INVALID")
        result.append(str(value))
    return result


def _source_records(session, dataset, *, limit, after, record_ids):
    selected = _ids(record_ids)
    if dataset == "cme-options":
        model = CmeRawFile
        fields = (
            "id", "source", "source_url", "raw_path", "sha256", "report_date", "retrieved_at"
        )
    elif dataset == "fedwatch":
        model = FedWatchRawSnapshot
        fields = (
            "snapshot_id", "source", "collected_at", "as_of", "source_url", "collector_version",
            "http_status", "content_hash", "raw_artifact_ref", "parse_status", "source_refs",
            "reason", "snapshot_metadata",
        )
    else:
        model = CmeSettlementSnapshot
        fields = (
            "snapshot_id", "trade_date", "observed_at", "settlement_status", "data_status", "payload",
        )
    identity = model.id if dataset == "cme-options" else model.snapshot_id
    query = select(*(getattr(model, field) for field in fields)).order_by(identity)
    if selected is not None:
        query = query.where(identity.in_(selected))
    if after is not None:
        if not isinstance(after, str) or not after:
            fail("DWH_CURSOR_INVALID")
        query = query.where(identity > after)
    return [dict(row) for row in session.execute(query.limit(limit)).mappings()]


def _batch(cursor, *, path=None, sha=None, as_of=None, quality=None, schema=None, producer_date=None):
    return dict(
        source_cursor=str(cursor),
        source_artifact_path=path,
        source_sha256=sha,
        as_of=as_of,
        producer_date=producer_date,
        schema_version=schema,
        rule_version=None,
        quality_status=quality,
        source_event_count=None,
        source_trigger_count=None,
        source_rejected_count=None,
        single_source_count=None,
        multi_source_count=None,
        official_confirmed_count=None,
        unverified_count=None,
    )


def _cme_fact(record, row, *, source, source_url, raw_path, raw_sha, retrieved, parse_status, parsed_at):
    version_type = string(row["version_type"], required=True, length=16).upper()
    if version_type not in {"FINAL", "PRELIMINARY"}:
        fail("DWH_MAPPING_INVALID")
    trade_date, report_date = _date(row["trade_date"]), _date(row["report_date"])
    if report_date != _date(record["report_date"]) or trade_date != report_date:
        fail("DWH_IDENTITY_MISMATCH")
    if parse_status in {"FINAL", "PRELIMINARY"} and parse_status != version_type:
        fail("DWH_IDENTITY_MISMATCH")
    underlying = string(row["underlying"], length=16)
    if underlying and underlying.upper() == "XAUUSD":
        fail("DWH_ASSET_SOURCE_CONFLICT")
    values = {key: number(row[key]) for key in ("settlement", "delta", "pt_change")}
    values.update(
        open_interest=_integer(row["open_interest"]),
        oi_change=_integer(row["oi_change"], signed=True),
        total_volume=_integer(row["total_volume"]),
        block_volume=_integer(row["block_volume"]),
        pnt_volume=_integer(row["pnt_volume"]),
        globex_volume=_integer(row["globex_volume"]),
        outcry_volume=_integer(row["outcry_volume"]),
        exercises=_integer(row["exercises"]),
    )
    data = dict(
        source_record_id=string(row["id"], required=True, length=255),
        raw_path=raw_path,
        as_of=max(retrieved, parsed_at) if parsed_at else retrieved,
        quality_status=parse_status,
        source_raw_id=string(record["id"], required=True, length=36),
        source_url=source_url,
        raw_sha256=raw_sha,
        retrieved_at=retrieved,
        parse_status=parse_status,
        trade_date=trade_date,
        report_date=report_date,
        version_type=version_type,
        product_code=string(row["product_code"], required=True, length=16),
        underlying=underlying,
        expiry=string(row["expiry"], required=True, length=8),
        strike=_integer(row["strike"], required=True),
        option_type=string(row["option_type"], required=True, length=8),
        source_page=_integer(row["source_page"]),
        **values,
    )
    return CmeOptionFact, data, source, source_url, digest(data)


def _prepare_cme(session, record):
    source = string(record["source"], required=True, length=128)
    source_url = string(record["source_url"])
    raw_path = string(record["raw_path"], required=True)
    raw_sha = _sha256(record["sha256"], required=True)
    retrieved = timestamp(record["retrieved_at"])
    if retrieved is None:
        fail("DWH_TIME_INVALID")
    report_date = _date(record["report_date"])
    _formal_numeric_source(source, source_url, raw_path)
    parse = session.execute(
        select(CmeParseRun.status, CmeParseRun.created_at).where(CmeParseRun.raw_file_id == record["id"])
    ).one_or_none()
    parse_status = string(parse.status if parse else None, length=32)
    parsed_at = timestamp(parse.created_at) if parse else None
    rows = session.execute(
        select(
            CmeOptionRow.id,
            CmeOptionRow.trade_date,
            CmeOptionRow.report_date,
            CmeOptionRow.version_type,
            CmeOptionRow.product_code,
            CmeOptionRow.underlying,
            CmeOptionRow.expiry,
            CmeOptionRow.strike,
            CmeOptionRow.option_type,
            CmeOptionRow.settlement,
            CmeOptionRow.delta,
            CmeOptionRow.open_interest,
            CmeOptionRow.oi_change,
            CmeOptionRow.total_volume,
            CmeOptionRow.block_volume,
            CmeOptionRow.pnt_volume,
            CmeOptionRow.globex_volume,
            CmeOptionRow.outcry_volume,
            CmeOptionRow.exercises,
            CmeOptionRow.pt_change,
            CmeOptionRow.source_page,
        ).where(CmeOptionRow.raw_file_id == record["id"]).order_by(CmeOptionRow.id)
    ).mappings()
    facts, errors = [], []
    for row in rows:
        try:
            facts.append(
                _cme_fact(
                    record,
                    row,
                    source=source,
                    source_url=source_url,
                    raw_path=raw_path,
                    raw_sha=raw_sha,
                    retrieved=retrieved,
                    parse_status=parse_status,
                    parsed_at=parsed_at,
                )
            )
        except WarehouseError as exc:
            errors.append(str(exc))
    attrs = _batch(
        record["id"], path=raw_path, sha=raw_sha,
        as_of=max(retrieved, parsed_at) if parsed_at else retrieved, quality=parse_status,
        producer_date=report_date,
    )
    if not facts and not errors:
        errors.append("DWH_CME_EMPTY")
    return attrs, facts, errors


def _fedwatch_envelope(record):
    source = string(record["source"], required=True, length=128)
    source_url = string(record["source_url"], required=True)
    raw_path = string(record["raw_artifact_ref"])
    _formal_numeric_source(source, source_url, raw_path)
    _formal_numeric_source(source, record.get("source_refs"), raw_path)
    collected = timestamp(record["collected_at"])
    if collected is None:
        fail("DWH_TIME_INVALID")
    snapshot_as_of = timestamp(record["as_of"])
    parse_status = string(record["parse_status"], required=True, length=32)
    if parse_status == "ok" and snapshot_as_of is None:
        fail("DWH_TIME_INVALID")
    if snapshot_as_of is not None and snapshot_as_of > collected:
        fail("DWH_TIME_INVALID")
    return dict(
        source=source,
        source_url=source_url,
        raw_path=raw_path,
        collected_at=collected,
        snapshot_as_of=snapshot_as_of,
        collector_version=string(record["collector_version"], required=True, length=128),
        http_status=_integer(record["http_status"]),
        content_hash=_sha256(record["content_hash"]),
        parse_status=parse_status,
    )


def _fedwatch_probability_fact(row, envelope, snapshot_id):
    low, high, probability = (number(row[key], required=True) for key in ("target_low", "target_high", "probability"))
    if not (0 <= low <= high <= 100 and 0 <= probability <= 1):
        fail("DWH_NUMBER_INVALID")
    observed = timestamp(row["observation_as_of"])
    if observed is None or observed > envelope["collected_at"]:
        fail("DWH_TIME_INVALID")
    if envelope["snapshot_as_of"] is not None and observed > envelope["snapshot_as_of"]:
        fail("DWH_TIME_INVALID")
    data = dict(
        source_record_id=string(row["probability_id"], required=True, length=255),
        raw_path=envelope["raw_path"],
        as_of=observed,
        quality_status=envelope["parse_status"],
        source_snapshot_id=snapshot_id,
        source_meeting_id=string(row["meeting_id"], required=True, length=36),
        source_probability_id=string(row["probability_id"], required=True, length=36),
        source_url=envelope["source_url"],
        collector_version=envelope["collector_version"],
        http_status=envelope["http_status"],
        content_hash=envelope["content_hash"],
        raw_artifact_ref=envelope["raw_path"],
        parse_status=envelope["parse_status"],
        collected_at=envelope["collected_at"],
        snapshot_as_of=envelope["snapshot_as_of"],
        meeting_date=_date(row["meeting_date"]),
        contract_ref=string(row["contract_ref"], length=128),
        comparison_window=string(row["comparison_window"], required=True, length=16),
        observation_as_of=observed,
        target_low=low,
        target_high=high,
        probability=probability,
    )
    return FedWatchProbabilityFact, data, envelope["source"], envelope["source_url"], digest(data)


def _fedwatch_futures_fact(row, envelope, snapshot_id):
    payload = row["payload"]
    if not isinstance(payload, dict):
        fail("DWH_MAPPING_INVALID")
    _formal_numeric_source(envelope["source"], payload.get("source_refs") or payload.get("source_ref"))
    contract = string(row["contract_ref"] or payload.get("contract_ref"), required=True, length=128)
    observed = timestamp(row["as_of"] or payload.get("as_of"))
    if observed is not None and observed > envelope["collected_at"]:
        fail("DWH_TIME_INVALID")
    numeric = {key: number(payload.get(key)) for key in _FUTURES_NUMBERS}
    numeric.update({key: _integer(payload.get(key)) for key in _FUTURES_INTEGERS})
    data = dict(
        source_record_id=string(row["id"], required=True, length=255),
        raw_path=envelope["raw_path"],
        as_of=observed,
        quality_status=envelope["parse_status"],
        source_snapshot_id=snapshot_id,
        source_futures_id=string(row["id"], required=True, length=36),
        row_index=_integer(row["row_index"], required=True),
        source_url=envelope["source_url"],
        collector_version=envelope["collector_version"],
        http_status=envelope["http_status"],
        content_hash=envelope["content_hash"],
        raw_artifact_ref=envelope["raw_path"],
        parse_status=envelope["parse_status"],
        collected_at=envelope["collected_at"],
        snapshot_as_of=envelope["snapshot_as_of"],
        contract_ref=contract,
        observation_as_of=observed,
        **numeric,
    )
    return FedWatchFuturesFact, data, envelope["source"], envelope["source_url"], digest(data)


def _prepare_fedwatch(session, record):
    envelope = _fedwatch_envelope(record)
    snapshot_id = string(record["snapshot_id"], required=True, length=36)
    facts, errors = [], []
    probabilities = session.execute(
        select(
            FedWatchMeetingSnapshot.id.label("meeting_id"),
            FedWatchMeetingSnapshot.meeting_date,
            FedWatchMeetingSnapshot.contract_ref,
            FedWatchMeetingSnapshot.comparison_window,
            FedWatchMeetingSnapshot.as_of.label("observation_as_of"),
            FedWatchProbability.id.label("probability_id"),
            FedWatchProbability.target_low,
            FedWatchProbability.target_high,
            FedWatchProbability.probability,
        ).join(FedWatchProbability, FedWatchProbability.meeting_snapshot_id == FedWatchMeetingSnapshot.id)
        .where(FedWatchMeetingSnapshot.snapshot_id == snapshot_id)
        .order_by(FedWatchMeetingSnapshot.row_index, FedWatchProbability.row_index)
    ).mappings()
    for row in probabilities:
        try:
            facts.append(_fedwatch_probability_fact(row, envelope, snapshot_id))
        except WarehouseError as exc:
            errors.append(str(exc))
    futures = session.execute(
        select(
            FedWatchFutures.id,
            FedWatchFutures.row_index,
            FedWatchFutures.contract_ref,
            FedWatchFutures.as_of,
            FedWatchFutures.payload,
        ).where(FedWatchFutures.snapshot_id == snapshot_id).order_by(FedWatchFutures.row_index)
    ).mappings()
    futures_contracts = set()
    for row in futures:
        try:
            fact = _fedwatch_futures_fact(row, envelope, snapshot_id)
            contract = fact[1]["contract_ref"]
            if contract in futures_contracts:
                fail("DWH_IDENTITY_DUPLICATE")
            futures_contracts.add(contract)
            facts.append(fact)
        except WarehouseError as exc:
            errors.append(str(exc))
    attrs = _batch(
        snapshot_id,
        path=envelope["raw_path"],
        # This path names the collection manifest. content_hash names the
        # primary HTTP response; their file identities must not be conflated.
        sha=None,
        as_of=envelope["snapshot_as_of"],
        quality=envelope["parse_status"],
    )
    error = None if envelope["parse_status"] == "ok" else "DWH_SOURCE_COLLECTION_FAILED"
    if envelope["parse_status"] == "ok" and not facts and not errors:
        error = "DWH_SOURCE_EMPTY"
    if error:
        errors.append(error)
    return attrs, facts, errors


def _settlement_payload(record):
    payload = record["payload"]
    if not isinstance(payload, dict):
        fail("DWH_MAPPING_INVALID")
    # This allow-list is the only legacy JSON projection.  Diagnostics, rows,
    # source_refs, and arbitrary payload extensions never enter DWH facts.
    return {
        key: payload.get(key)
        for key in (
            "source", "source_type", "source_url", "schema_version", "collector_version",
            "parser_version", "collection_mode", "product_id", "instrument", "official_display_probability",
            "content_hash", "raw_artifact_ref", "manifest_ref", "http_status", "content_type", "bytes",
            "truncated", "latency_ms", "reason", "transport_error_code", "request_status", "data_status",
            "health", "source_update_time_raw", "source_time_timezone",
        )
    }


def _settlement_fact(row, *, source_fields, source, source_url, raw_path, snapshot_id, observed, trade_date,
                     phase, data_status, content_hash):
    contract = string(row["contract"], required=True, length=16)
    data = dict(
        source_record_id=f"{snapshot_id}:{contract}",
        raw_path=raw_path,
        as_of=observed,
        quality_status=data_status,
        source_snapshot_id=snapshot_id,
        source_url=source_url,
        source_type=string(source_fields["source_type"], length=64),
        product_id=_integer(source_fields["product_id"]),
        instrument=string(source_fields["instrument"], length=32),
        official_display_probability=_boolean(source_fields["official_display_probability"]),
        schema_version=string(source_fields["schema_version"], length=128),
        collector_version=string(source_fields["collector_version"], length=128),
        parser_version=string(source_fields["parser_version"], length=128),
        collection_mode=string(source_fields["collection_mode"], length=32),
        content_hash=content_hash,
        raw_artifact_ref=raw_path,
        manifest_ref=string(source_fields["manifest_ref"]),
        http_status=_integer(source_fields["http_status"]),
        content_type=string(source_fields["content_type"], length=255),
        source_bytes=_integer(source_fields["bytes"]),
        truncated=_boolean(source_fields["truncated"]),
        latency_ms=_integer(source_fields["latency_ms"]),
        reason=string(source_fields["reason"]),
        transport_error_code=_integer(source_fields["transport_error_code"]),
        trade_date=trade_date,
        observed_at=observed,
        source_update_time_raw=string(source_fields["source_update_time_raw"], length=255),
        source_time_timezone=string(source_fields["source_time_timezone"], length=64),
        settlement_status=phase,
        request_status=string(source_fields["request_status"], length=32),
        data_status=data_status,
        health=string(source_fields["health"], length=32),
        contract=contract,
        contract_month=_date(row["contract_month"]),
        settle=number(row["settle"]),
        volume=_integer(row["volume"]),
        open_interest=_integer(row["open_interest"]),
    )
    return FedFundsSettlementFact, data, source, source_url, digest(data)


def _prepare_settlement(session, record):
    source_fields = _settlement_payload(record)
    source = string(source_fields["source"], required=True, length=128)
    source_url = string(source_fields["source_url"])
    raw_path = string(source_fields["raw_artifact_ref"])
    _formal_numeric_source(source, source_url, raw_path)
    _formal_numeric_source(source, record["payload"].get("source_refs") or record["payload"].get("source_ref"))
    snapshot_id = string(record["snapshot_id"], required=True, length=36)
    observed = timestamp(record["observed_at"])
    if observed is None:
        fail("DWH_TIME_INVALID")
    trade_date = _date(record["trade_date"])
    phase = string(record["settlement_status"], length=16)
    if phase is not None and phase not in {"FINAL", "PRELIMINARY"}:
        fail("DWH_MAPPING_INVALID")
    data_status = string(record["data_status"], required=True, length=32)
    if source_fields["data_status"] is not None and source_fields["data_status"] != data_status:
        fail("DWH_IDENTITY_MISMATCH")
    if source != "cme_settlement" or source_fields["official_display_probability"] is not False:
        fail("DWH_SOURCE_QUALIFICATION_INVALID")
    content_hash = _sha256(source_fields["content_hash"])
    if data_status == "available" and (source_url is None or raw_path is None or content_hash is None):
        fail("DWH_SOURCE_LINEAGE_MISSING")
    facts, errors = [], []
    rows = session.execute(
        select(
            CmeSettlementContract.contract,
            CmeSettlementContract.contract_month,
            CmeSettlementContract.settle,
            CmeSettlementContract.volume,
            CmeSettlementContract.open_interest,
        ).where(CmeSettlementContract.snapshot_id == snapshot_id).order_by(CmeSettlementContract.contract)
    ).mappings()
    for row in rows:
        try:
            facts.append(
                _settlement_fact(
                    row,
                    source_fields=source_fields,
                    source=source,
                    source_url=source_url,
                    raw_path=raw_path,
                    snapshot_id=snapshot_id,
                    observed=observed,
                    trade_date=trade_date,
                    phase=phase,
                    data_status=data_status,
                    content_hash=content_hash,
                )
            )
        except WarehouseError as exc:
            errors.append(str(exc))
    attrs = _batch(
        snapshot_id, path=raw_path, sha=content_hash, as_of=observed,
        quality=data_status, schema=string(source_fields["schema_version"], length=128), producer_date=trade_date,
    )
    if data_status == "available" and not facts and not errors:
        errors.append("DWH_SOURCE_EMPTY")
    elif data_status in {"parse_failed", "unavailable"}:
        errors.append("DWH_SOURCE_COLLECTION_FAILED")
    return attrs, facts, errors


def _insert_fact(session, cache, model, data, source, source_url, version, batch, producer_id=None):
    existing = select(model.id).where(
        model.source_record_id == data["source_record_id"], model.version_sha256 == version
    )
    # Use the indexed source grain; probing only the shared lineage columns
    # makes a full CME backfill perform a table scan for every contract.
    for field in ("source_raw_id", "source_snapshot_id"):
        if field in data:
            existing = existing.where(getattr(model, field) == data[field])
    if model is NewsItemFact:
        existing = existing.where(model.producer_run_id == producer_id,
                                  model.duplicate_key == data["duplicate_key"])
    if session.scalar(existing) is not None:
        return False
    source_id = cache.source(source, source_url)
    session.add(
        model(
            **data,
            source_id=source_id,
            version_sha256=version,
            batch_id=batch.id,
            producer_run_id=producer_id,
        )
    )
    session.flush()
    return True


def _summary(dataset, dry_run, after=None):
    return dict(
        dataset=dataset,
        dry_run=dry_run,
        processed=0,
        planned=0,
        inserted=0,
        skipped=0,
        rejected=0,
        next_after=after,
        task_run_id=None,
        error_codes=[],
        load_batch_ids=[],
    )


def _audit(session, dataset):
    now, audit_id, step_id = datetime.now(UTC), uuid4(), uuid4()
    audit = TaskRun(
        id=audit_id,
        name="warehouse:" + dataset,
        task_type="warehouse_load",
        status=TaskStatus.running,
        started_at=now,
    )
    step = TaskStep(
        id=step_id,
        task_run_id=audit_id,
        name="field_etl",
        stage="warehouse_load",
        task_kind="warehouse_load",
        status=StepStatus.running,
        started_at=now,
    )
    session.add(audit)
    session.flush([audit])
    session.add(step)
    session.flush([step])
    return audit, step


def _finish_audit(summary, audit, step):
    audit.status = (
        TaskStatus.partial_success
        if summary["rejected"] and summary["planned"]
        else TaskStatus.failed
        if summary["rejected"]
        else TaskStatus.success
    )
    audit.ended_at = step.finished_at = datetime.now(UTC)
    step.status = StepStatus.failed if summary["rejected"] else StepStatus.success
    audit.error_summary = step.error = "DWH_INPUT_REJECTED" if summary["rejected"] else None


def _schema_check(session):
    inspector = inspect(session.connection())
    required = {table.name for table in SOURCE_WAREHOUSE_TABLES}
    required.update({"dwh_dim_source", "dwh_dim_producer_run", "dwh_load_batch", "task_runs", "task_steps"})
    if any(not inspector.has_table(table) for table in required):
        fail("DWH_SCHEMA_MISSING")


def _record_rejection(summary, code):
    summary["rejected"] += 1
    if code not in summary["error_codes"]:
        summary["error_codes"].append(code)


def _load_source_warehouse(session, dataset, *, limit, after, record_ids, storage_root, dry_run):
    del storage_root  # Paths are lineage here; file lifecycle belongs to raw retention.
    if dataset not in SOURCE_DATASETS or type(limit) is not int or not 1 <= limit <= 1000:
        fail("DWH_ARGUMENT_INVALID")
    if after is not None and record_ids is not None:
        fail("DWH_ARGUMENT_INVALID")
    summary = _summary(dataset, dry_run, after)
    with session.no_autoflush:
        if not dry_run:
            _schema_check(session)
        records = _source_records(session, dataset, limit=limit, after=after, record_ids=record_ids)
        prepared = []
        contexts = {}
        prepare = {
            "cme-options": _prepare_cme,
            "fedwatch": _prepare_fedwatch,
            "settlement": _prepare_settlement,
        }[dataset]
        for record in records:
            cursor = str(record.get("id", record.get("snapshot_id")))
            summary["processed"] += 1
            summary["next_after"] = cursor
            try:
                if dataset == "fedwatch":
                    from apps.data_layer.fedwatch_warehouse import prepare_fedwatch_context

                    contexts[cursor] = prepare_fedwatch_context(record)
                prepared.append(prepare(session, record))
            except WarehouseError as exc:
                prepared.append((_batch(cursor), [], [str(exc)]))
        if record_ids and not records:
            _record_rejection(summary, "DWH_SOURCE_RECORD_MISSING")
        if dry_run:
            for _, facts, errors in prepared:
                summary["planned"] += len(facts)
                for error in errors:
                    _record_rejection(summary, error)
            return summary
        audit, step = _audit(session, dataset)
        summary["task_run_id"] = str(audit.id)
        cache = DimensionCache(session)
        for attrs, facts, errors in prepared:
            batch = LoadBatch(
                dataset=dataset,
                producer_run_id=None,
                transform_version=TRANSFORM_VERSION,
                audit_task_run_id=str(audit.id),
                audit_task_step_id=str(step.id),
                status="loading",
                **attrs,
            )
            session.add(batch)
            session.flush([batch])
            summary["load_batch_ids"].append(batch.id)
            inserted = skipped = rejected = 0
            for model, data, source, source_url, version in facts:
                summary["planned"] += 1
                if _insert_fact(session, cache, model, data, source, source_url, version, batch):
                    inserted += 1
                else:
                    skipped += 1
            rejected = len(errors)
            if errors:
                batch.error_code = errors[0]
                for error in errors:
                    if error not in summary["error_codes"]:
                        summary["error_codes"].append(error)
            batch.processed = len(facts) + rejected
            batch.inserted, batch.skipped, batch.rejected = inserted, skipped, rejected
            batch.status = "partial" if rejected and facts else "rejected" if rejected else "loaded"
            if dataset == "fedwatch" and not errors:
                from apps.data_layer.fedwatch_warehouse import persist_fedwatch_context

                persist_fedwatch_context(session, contexts[attrs["source_cursor"]], batch_id=batch.id)
            summary["inserted"] += inserted
            summary["skipped"] += skipped
            summary["rejected"] += rejected
        _finish_audit(summary, audit, step)
        session.flush()
        return summary


def load_source_warehouse(
    session,
    dataset,
    *,
    limit=100,
    after=None,
    record_ids=None,
    storage_root=None,
    dry_run=True,
):
    """Load one bounded source-domain page without DDL or commit."""

    try:
        if dry_run:
            return _load_source_warehouse(
                session, dataset, limit=limit, after=after, record_ids=record_ids,
                storage_root=storage_root, dry_run=True,
            )
        connection = session.connection()
        if connection.dialect.name == "sqlite" and not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql("BEGIN")
        with session.begin_nested():
            return _load_source_warehouse(
                session, dataset, limit=limit, after=after, record_ids=record_ids,
                storage_root=storage_root, dry_run=False,
            )
    except WarehouseError:
        raise
    except Exception:
        raise WarehouseError("DWH_TRANSACTION_FAILED") from None


def _safe_lineage_path(value, storage_root):
    value = string(value)
    if value is None or storage_root is None:
        return value
    root = Path(storage_root).resolve()
    from apps.runtime.storage_paths import remap_storage_path
    try:
        candidate = remap_storage_path(value, storage_root=root)
    except ValueError:
        fail("DWH_PATH_INVALID")
    if not candidate.is_absolute() and candidate.parts[:1] == ("storage",):
        candidate = Path(*candidate.parts[1:])
    candidate = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        fail("DWH_PATH_INVALID")
    return value


def _news_mapping(item, storage_root):
    if is_dataclass(item):
        item = {field: getattr(item, field, None) for field in _NEWS_FIELDS}
    if not isinstance(item, dict):
        fail("DWH_MAPPING_INVALID")
    data = dict(
        source_key=string(item.get("source_key"), required=True, length=128),
        source_name=string(item.get("source_name"), required=True, length=255),
        source_type=string(item.get("source_type"), required=True, length=64),
        feed_key=string(item.get("feed_key"), required=True, length=128),
        title=string(item.get("title"), required=True),
        url=string(item.get("url"), required=True),
        domain=string(item.get("domain"), required=True, length=255),
        published_at=timestamp(item.get("published_at")),
        fetched_at=timestamp(item.get("fetched_at")),
        summary=string(item.get("summary")),
        source_language=string(item.get("source_language", item.get("language")), length=32),
        source_country=string(item.get("source_country", item.get("country")), length=32),
        event_type=string(item.get("event_type"), length=64),
        verification_status=string(item.get("verification_status"), required=True, length=64),
        duplicate_key=string(item.get("duplicate_key"), required=True, length=255),
        raw_path=_safe_lineage_path(item.get("raw_path"), storage_root),
        parsed_path=_safe_lineage_path(item.get("parsed_path"), storage_root),
    )
    if data["fetched_at"] is None:
        fail("DWH_TIME_INVALID")
    fact = dict(
        **data,
        source_record_id=data["duplicate_key"],
        as_of=data["fetched_at"],
        quality_status=data["verification_status"],
    )
    version = digest(data)
    return fact, version


def _load_news_items(session, items, *, run_id, storage_root, dry_run):
    from apps.data_layer.news_warehouse import NewsContextError, prepare_news_context, persist_news_context
    if not isinstance(items, (list, tuple)) or len(items) > 100000:
        fail("DWH_ARGUMENT_INVALID")
    if run_id is None:
        fail("DWH_ARGUMENT_INVALID")
    run_text = string(str(run_id) if run_id is not None else None, required=True, length=255)
    summary = _summary("news-items", dry_run)
    with session.no_autoflush:
        if not dry_run:
            _schema_check(session)
        producer = producer_info(session, run_text)
        prepared = []
        for item in items:
            summary["processed"] += 1
            try:
                fact, version = _news_mapping(item, storage_root)
                context = prepare_news_context(item)
                prepared.append((fact, digest([version, context.context_sha256]), context, None))
            except (WarehouseError, NewsContextError) as exc:
                prepared.append((None, None, None, str(exc)))
        if dry_run:
            for fact, _, _, error in prepared:
                if error:
                    _record_rejection(summary, error)
                else:
                    summary["planned"] += 1
            return summary
        audit, step = _audit(session, "news-items")
        summary["task_run_id"] = str(audit.id)
        cache = DimensionCache(session)
        producer_attrs = dict(producer)
        producer_key = dict(run_id=producer_attrs.pop("run_id"))
        producer_id = cache.get(ProducerRunDimension, producer_key, producer_attrs).id
        if not prepared:
            prepared.append((None, None, None, None))
        for ordinal, (fact, version, context, error) in enumerate(prepared):
            cursor = fact["duplicate_key"] if fact else f"{run_text}:{ordinal}"
            batch = LoadBatch(
                dataset="news-items",
                producer_run_id=producer_id,
                transform_version=TRANSFORM_VERSION,
                audit_task_run_id=str(audit.id),
                audit_task_step_id=str(step.id),
                status="loading",
                **_batch(
                    cursor,
                    path=fact["raw_path"] if fact else None,
                    as_of=fact["fetched_at"] if fact else None,
                    quality=fact["verification_status"] if fact else None,
                    producer_date=producer["producer_date"],
                ),
            )
            session.add(batch)
            session.flush([batch])
            summary["load_batch_ids"].append(batch.id)
            if error:
                batch.processed, batch.inserted, batch.skipped, batch.rejected = 1, 0, 0, 1
                batch.status, batch.error_code = "rejected", error
                _record_rejection(summary, error)
                continue
            if fact is None:  # Explicit empty collection audit.
                batch.processed = batch.inserted = batch.skipped = batch.rejected = 0
                batch.status = "loaded"
                continue
            summary["planned"] += 1
            source_key, source_name, source_type = fact["source_key"], fact["source_name"], fact["source_type"]
            cache.source(source_key, source_type=source_type, name=source_name)
            inserted = _insert_fact(
                session,
                cache,
                NewsItemFact,
                fact,
                source_key,
                None,
                version,
                batch,
                producer_id,
            )
            fact_id = session.scalar(select(NewsItemFact.id).where(
                NewsItemFact.producer_run_id == producer_id,
                NewsItemFact.duplicate_key == fact["duplicate_key"],
                NewsItemFact.version_sha256 == version,
            ))
            persist_news_context(session, context, news_fact_id=fact_id)
            batch.processed, batch.rejected = 1, 0
            batch.inserted, batch.skipped = (1, 0) if inserted else (0, 1)
            batch.status = "loaded"
            summary["inserted" if inserted else "skipped"] += 1
        _finish_audit(summary, audit, step)
        session.flush()
        return summary


def load_news_items(session, items, *, run_id, storage_root=None, dry_run=True):
    """Load RawNewsItem objects or named-field dictionaries without raw payloads."""

    try:
        if dry_run:
            return _load_news_items(
                session, items, run_id=run_id, storage_root=storage_root, dry_run=True
            )
        connection = session.connection()
        if connection.dialect.name == "sqlite" and not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql("BEGIN")
        with session.begin_nested():
            return _load_news_items(
                session, items, run_id=run_id, storage_root=storage_root, dry_run=False
            )
    except WarehouseError:
        raise
    except Exception:
        raise WarehouseError("DWH_TRANSACTION_FAILED") from None
