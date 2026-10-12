"""Bounded, caller-transaction-owned ETL. Source bodies are transient input only."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import inspect, select, exists, and_, or_
from sqlalchemy.orm import aliased
from apps.data_layer.structured_artifacts import _inspect_artifact, DEFAULT_MAX_BYTES
from apps.runtime.artifact_storage import LocalFileSystemArtifactStorage
from database.models.analysis import MacroObservation, MarketCandle
from database.models.execution import RunArtifact
from database.models.task import TaskRun, TaskStep, TaskStatus, StepStatus
from database.numeric_source_policy import is_formal_numeric_source
from database.models.warehouse import (
    WarehouseBase,
    DateDimension,
    SourceDimension,
    AssetDimension,
    MetricDimension,
    ProducerRunDimension,
    LoadBatch,
    MacroFact,
    CandleFact,
    NewsEventFact,
    NewsTriggerFact,
    EventAsset,
    TriggerAsset,
    EventSourceReference,
    TriggerSourceReference,
    TriggerAction,
    TriggerReason,
    TriggerTopic,
)

TRANSFORM_VERSION = "warehouse-collection-v3"
DATASETS = ("macro", "candles", "news-events", "news-triggers")


class WarehouseError(ValueError):
    """Only a fixed safe code is exposed to operators."""


def fail(code="DWH_MAPPING_INVALID"):
    raise WarehouseError(code)


def string(value, *, required=False, length=None):
    if value is None:
        if required:
            fail()
        return None
    if not isinstance(value, str) or "\x00" in value or (required and not value.strip()):
        fail()
    if length and len(value) > length:
        fail()
    return value


def number(value, *, required=False):
    if value is None:
        if required:
            fail("DWH_NUMBER_INVALID")
        return None
    if isinstance(value, bool):
        fail("DWH_NUMBER_INVALID")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        fail("DWH_NUMBER_INVALID")
    if not result.is_finite() or abs(result) >= Decimal("1e26"):
        fail("DWH_NUMBER_INVALID")
    return result


def integer(value):
    if value is None:
        return None
    if type(value) is not int or value < 0 or value > 2147483647:
        fail()
    return value


def timestamp(value):
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            fail("DWH_TIME_INVALID")
    if not isinstance(value, datetime):
        fail("DWH_TIME_INVALID")
    # Existing SQLite typed tables return naive timestamps, whose documented basis is UTC.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def strings(value, length=128):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 1000:
        fail()
    return [string(v, required=True, length=length) for v in value]


def quality(value):
    if value is None:
        return {}
    if not isinstance(value, dict):
        fail()
    return value


def digest(values):
    # Canonical explicit typed-field digest, never a persisted body or load timestamp.
    def canonical(v):
        if isinstance(v, datetime):
            return timestamp(v).isoformat()
        if isinstance(v, (date, Decimal, UUID)):
            return str(v)
        return v

    return sha256(json.dumps(values, sort_keys=True, default=canonical, allow_nan=False).encode()).hexdigest()


MACRO_FIELDS = (
    "id",
    "source_key",
    "symbol",
    "observation_date",
    "value",
    "unit",
    "frequency",
    "source_url",
    "raw_path",
    "raw_artifact_id",
    "parsed_artifact_id",
    "retrieved_at",
    "run_id",
)
CANDLE_FIELDS = (
    "id",
    "asset",
    "source",
    "timeframe",
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "raw_path",
    "created_at",
    "updated_at",
)
ARTIFACT_FIELDS = ("artifact_id", "run_id", "file_path", "storage_backend", "sha256", "content_type", "generated_at")


def _record_id_filter(values, *, uuid_values=False):
    if values is None:
        return None
    if not isinstance(values, (list, tuple, set, frozenset)) or len(values) > 1000:
        fail("DWH_ARGUMENT_INVALID")
    normalized = []
    for value in values:
        if not isinstance(value, (str, UUID)) or not str(value):
            fail("DWH_ARGUMENT_INVALID")
        try:
            normalized.append(UUID(str(value)) if uuid_values else str(value))
        except ValueError:
            fail("DWH_ARGUMENT_INVALID")
    return normalized


def source_records(session, dataset, limit, after=None, run_id=None, record_ids=None):
    if dataset in ("macro", "candles"):
        model, fields = (MacroObservation, MACRO_FIELDS) if dataset == "macro" else (MarketCandle, CANDLE_FIELDS)
        refs = model.source_refs if dataset == "macro" else model.source_ref
        query = select(*(getattr(model, f) for f in fields), refs.label("_numeric_lineage")).order_by(model.id)
        selected_ids = _record_id_filter(record_ids)
        if selected_ids is not None:
            query = query.where(model.id.in_(selected_ids))
        if after:
            query = query.where(model.id > after)
        return [dict(r) for r in session.execute(query.limit(limit)).mappings()]
    filename = "event_candidates.json" if dataset == "news-events" else "daily_analysis_triggers.json"
    newer = aliased(RunArtifact)
    # Choose the newest registration per producer + logical filename, including bad aliases.
    query = (
        select(*(getattr(RunArtifact, f) for f in ARTIFACT_FIELDS))
        .where(
            RunArtifact.file_path.endswith("/" + filename),
            ~exists(
                select(newer.artifact_id).where(
                    newer.run_id == RunArtifact.run_id,
                    newer.file_path.endswith("/" + filename),
                    or_(
                        newer.created_at > RunArtifact.created_at,
                        and_(newer.created_at == RunArtifact.created_at, newer.artifact_id > RunArtifact.artifact_id),
                    ),
                )
            ),
        )
        .order_by(RunArtifact.artifact_id)
    )
    try:
        selected_ids = _record_id_filter(record_ids, uuid_values=True)
        if selected_ids is not None:
            query = query.where(RunArtifact.artifact_id.in_(selected_ids))
        if after:
            query = query.where(RunArtifact.artifact_id > UUID(after))
        if run_id:
            query = query.where(RunArtifact.run_id == UUID(str(run_id)))
    except ValueError:
        fail("DWH_CURSOR_INVALID")
    return [dict(r) for r in session.execute(query.limit(limit)).mappings()]


def producer_info(session, run_id):
    if not run_id:
        return None
    run_id = string(str(run_id), required=True, length=255)
    try:
        uid = UUID(run_id)
    except ValueError:
        return dict(run_id=run_id, verified=False, producer_date=None, started_at=None)
    row = (
        session.execute(select(TaskRun.trade_date, TaskRun.started_at).where(TaskRun.id == uid)).first()
        if inspect(session.connection()).has_table("task_runs")
        else None
    )
    producer_date = None
    if row and row.trade_date:
        try:
            producer_date = date.fromisoformat(row.trade_date)
        except ValueError:
            pass
    return dict(
        run_id=run_id,
        verified=row is not None,
        producer_date=producer_date,
        started_at=timestamp(row.started_at) if row else None,
    )


def reference_mapping(ref):
    if not isinstance(ref, dict):
        fail()
    data = {
        k: string(ref.get(k), length=64 if k in ("status", "content_scope") else None)
        for k in ("source_ref", "raw_path", "parsed_path", "url", "status", "content_scope")
    }
    data["source_key"] = string(ref.get("source_key", ref.get("source")), length=128)
    data["url"] = string(ref.get("url") or ref.get("source_url"))
    data["source_type"] = string(ref.get("source_type"), length=64)
    data["source_name"] = string(ref.get("source_name"), length=255)
    data["retrieved_at"] = timestamp(ref.get("retrieved_at", ref.get("fetched_at")))
    data["published_at"] = timestamp(ref.get("published_at"))
    return data


def news_item_mapping(item, dataset, rule_version):
    if not isinstance(item, dict):
        fail()
    event = dataset == "news-events"
    identity = "event_id" if event else "trigger_id"
    data = {identity: string(item.get(identity), required=True, length=255)}
    fields = (
        {
            "primary_news_item_id": "primary_news_item_id",
            "event_type": "event_type",
            "status": "event_status",
            "direction": "direction",
            "verification_status": "verification_status",
            "evidence": "evidence_text",
            "duplicate_group": "duplicate_group",
        }
        if event
        else {
            "trigger_type": "trigger_type",
            "priority": "priority",
            "status": "status",
            "source_news_item_id": "source_news_item_id",
            "source_event_id": "source_event_id",
            "title": "source_title",
            "url": "source_url",
            "event_type": "event_type",
            "impact_path": "impact_path",
            "gold_impact": "gold_impact",
            "evidence": "evidence_text",
            "verification_status": "verification_status",
        }
    )
    for target, source in fields.items():
        length = (
            None
            if target in ("evidence", "title", "url", "impact_path")
            else (255 if target.endswith("_id") or target == "duplicate_group" else 32 if target == "priority" else 64)
        )
        data[target] = string(item.get(source), length=length)
    q = quality(item.get("data_quality"))
    data["quality_status"] = string(q.get("status"), length=64)
    # Trigger verification is present in original quality for current producer schemas.
    if not event and data["verification_status"] is None:
        data["verification_status"] = string(q.get("verification_status"), length=64)
    data["event_time" if event else "created_at"] = timestamp(item.get("event_time" if event else "created_at"))
    if event:
        data["confidence"] = number(item.get("confidence"))
        if data["confidence"] is not None and not 0 <= data["confidence"] <= 1:
            fail("DWH_NUMBER_INVALID")
        data["source_count"] = integer(item.get("source_count"))
        if item.get("need_verification") is not None and type(item["need_verification"]) is not bool:
            fail()
        data["need_verification"] = item.get("need_verification")
        for k in ("independent_source_count", "independent_domain_count", "authoritative_source_count"):
            data[k] = integer(q.get(k))
        data["evidence_scope"] = string(q.get("evidence_scope"), length=64)
        if q.get("full_text_available") is not None and type(q["full_text_available"]) is not bool:
            fail()
        data["full_text_available"] = q.get("full_text_available")
    else:
        data["rule_version"] = rule_version
        data["source_count"] = integer(q.get("source_count"))
        for k in ("trigger_score", "relevance_score"):
            data[k] = number(q.get(k))
            if data[k] is not None and abs(data[k]) >= Decimal("1e6"):
                fail("DWH_NUMBER_INVALID")
        data["relevance_decision"] = string(q.get("relevance_decision"), length=64)
    refs = item.get("source_refs", [])
    if not isinstance(refs, list) or len(refs) > 1000:
        fail()
    children = dict(assets=strings(item.get("asset_tags")), refs=[reference_mapping(r) for r in refs])
    if not event:
        children.update(
            actions=strings(item.get("suggested_actions"), 255),
            reasons=strings(item.get("reason_codes")),
            topics=strings(item.get("topic_tags")),
        )
        children["source_key"] = string(item.get("source_key"), length=128)
    return data, children


def prepare_record(session, dataset, record, storage_root, producer_cache):
    numeric_quality = None
    lineage = None
    if dataset in ("macro", "candles"):
        # Legacy ODS can predate the news-only policy. Validate lineage too,
        # then discard the transient JSON reference; never store it as a fact.
        record = dict(record)
        lineage = record.pop("_numeric_lineage", None)
        source = record.get("source_key", record.get("source"))
        if not is_formal_numeric_source(source, (lineage, record.get("source_url")), record.get("raw_path")):
            fail("DWH_NUMERIC_SOURCE_FORBIDDEN")
        references = lineage if isinstance(lineage, list) else [lineage]
        statuses = {str(ref["quality_status"]) for ref in references
                    if isinstance(ref, dict) and ref.get("quality_status")}
        numeric_quality = string(next(iter(statuses)) if len(statuses) == 1 else "mixed" if statuses else None, length=64)
    run_key = str(record["run_id"]) if record.get("run_id") else None
    if run_key not in producer_cache:
        producer_cache[run_key] = producer_info(session, record.get("run_id"))
    producer = producer_cache[run_key]
    batch = dict(
        source_cursor=str(record.get("id", record.get("artifact_id"))),
        source_artifact_path=record.get("raw_path"),
        source_sha256=None,
        as_of=None,
        producer_date=producer["producer_date"] if producer else None,
        schema_version=None,
        rule_version=None,
        quality_status=None,
        source_event_count=None,
        source_trigger_count=None,
        source_rejected_count=None,
    )
    if dataset == "macro":
        source = string(record["source_key"], required=True, length=128)
        symbol = string(record["symbol"], required=True, length=128)
        observed = record["observation_date"]
        if not isinstance(observed, date):
            fail("DWH_TIME_INVALID")
        data = dict(
            value=number(record["value"]),
            unit=string(record["unit"], length=64),
            retrieved_at=timestamp(record["retrieved_at"]),
            source_url=string(record["source_url"]),
            raw_artifact_id=string(record["raw_artifact_id"], length=255),
            parsed_artifact_id=string(record["parsed_artifact_id"], length=255),
        )
        data.update(
            source_record_id=record["id"],
            raw_path=string(record["raw_path"]),
            as_of=data["retrieved_at"],
            quality_status=numeric_quality,
        )
        reference_fields = {}
        for key in ("previous_value", "reference_period", "previous_reference_period"):
            values = {
                number(ref[key]) if key == "previous_value" else string(ref[key], length=64)
                for ref in (lineage if isinstance(lineage, list) else [])
                if isinstance(ref, dict) and ref.get(key) is not None
            }
            if len(values) > 1:
                fail("DWH_SOURCE_CONTEXT_CONFLICT")
            reference_fields[key] = next(iter(values), None)
        data.update(reference_fields)
        children = dict(
            source=source,
            symbol=symbol,
            frequency=string(record["frequency"], length=64),
            source_url=string(record["source_url"]),
            observed=observed,
        )
        version_fields = dict(record, value=data["value"], retrieved_at=data["retrieved_at"])
        # ``source_url`` existed in the legacy digest but was not persisted on
        # the fact.  A non-empty immutable copy is therefore an explicit new
        # evidence version; an empty column must not churn historical rows.
        if data["source_url"] is not None:
            version_fields["fact_source_url"] = data["source_url"]
        if any(value is not None for value in reference_fields.values()):
            version_fields["reference_context"] = reference_fields
        if numeric_quality is not None:
            version_fields["quality_status"] = numeric_quality
        version = digest(version_fields)
        batch.update(as_of=data["as_of"], source_sha256=version)
        return batch, producer, [(data, children, version)]
    if dataset == "candles":
        opened = timestamp(record["open_time"])
        if opened is None:
            fail("DWH_TIME_INVALID")
        data = {k: number(record[k], required=k != "volume") for k in ("open", "high", "low", "close", "volume")}
        if (
            data["high"] < max(data["open"], data["close"], data["low"])
            or data["low"] > min(data["open"], data["close"])
            or (data["volume"] is not None and data["volume"] < 0)
        ):
            fail("DWH_NUMBER_INVALID")
        data.update(
            open_time=opened,
            timeframe=string(record["timeframe"], required=True, length=16),
            source_record_id=record["id"],
            raw_path=string(record["raw_path"]),
            as_of=None,
            quality_status=numeric_quality,
            created_at=timestamp(record["created_at"]),
            updated_at=timestamp(record["updated_at"]),
        )
        reference = lineage if isinstance(lineage, dict) else {}
        data.update(
            retrieved_at=timestamp(reference.get("retrieved_at")),
            provider=string(reference.get("provider"), length=128),
            provider_symbol=string(
                reference.get("provider_symbol") or reference.get("ticker") or reference.get("symbol"),
                length=128,
            ),
            provider_timeframe=string(reference.get("provider_timeframe"), length=64),
            instrument_type=string(reference.get("instrument_type"), length=64),
            source_role=string(reference.get("source_role") or reference.get("provider_role"), length=64),
            source_url=string(reference.get("source_url")),
            source_reference=string(reference.get("reference")),
            reference_status=string(reference.get("status"), length=64),
            evidence_scope=string(reference.get("evidence_scope"), length=64),
            source_tier=string(reference.get("source_tier"), length=64),
            identity_guard=string(reference.get("identity_guard"), length=64),
        )
        children = dict(
            source=string(record["source"], required=True, length=128),
            asset=string(record["asset"], required=True, length=128),
            observed=opened.date(),
        )
        # This provider identifies GC futures. Preserve conflicting source rows,
        # but never publish their prices as XAUUSD spot warehouse facts.
        if children["source"] == "yahoo_finance_gc_f" and children["asset"] != "GC":
            fail("DWH_ASSET_SOURCE_CONFLICT")
        if isinstance(lineage, dict) and children["asset"] == "XAUUSD":
            if (str(lineage.get("instrument_type", "")).startswith("futures")
                    or lineage.get("provider_symbol") == "GC=F"):
                fail("DWH_ASSET_SOURCE_CONFLICT")
        version_fields = dict(record, **data)
        typed_evidence = {
            key: data[key]
            for key in (
                "retrieved_at",
                "provider",
                "provider_symbol",
                "provider_timeframe",
                "instrument_type",
                "source_role",
                "source_url",
                "source_reference",
                "reference_status",
                "evidence_scope",
                "source_tier",
                "identity_guard",
            )
            if data[key] is not None
        }
        if typed_evidence:
            version_fields["typed_source_evidence"] = typed_evidence
        version = digest(version_fields)
        batch["source_sha256"] = version
        return batch, None, [(data, children, version)]
    if storage_root is None:
        fail("DWH_TRUSTED_ROOT_REQUIRED")
    storage = LocalFileSystemArtifactStorage(root=Path(storage_root))
    row = SimpleNamespace(**record)
    result, payload, schema = _inspect_artifact(row, storage, max_bytes=DEFAULT_MAX_BYTES)
    if result.status != "persisted":
        fail(result.error or "DWH_ARTIFACT_INVALID")
    # Resolve again only for identity; inspector already rejects symlinks/escapes.
    parts = Path(record["file_path"]).parts
    try:
        pos = parts.index("features")
        tail = parts[pos:]
        path_date = date.fromisoformat(tail[2])
        expected = "event_candidates.json" if dataset == "news-events" else "daily_analysis_triggers.json"
        if len(tail) != 5 or tail[1] != "news" or tail[4] != expected or str(UUID(tail[3])) != str(record["run_id"]):
            fail("DWH_IDENTITY_MISMATCH")
    except (ValueError, IndexError):
        fail("DWH_IDENTITY_MISMATCH")
    if not isinstance(payload, dict):
        fail()
    if payload.get("run_id") is not None and str(payload["run_id"]) != str(record["run_id"]):
        fail("DWH_IDENTITY_MISMATCH")
    if payload.get("retrieved_date") is not None and payload["retrieved_date"] != path_date.isoformat():
        fail("DWH_IDENTITY_MISMATCH")
    if producer and producer["producer_date"] and producer["producer_date"] != path_date:
        fail("DWH_IDENTITY_MISMATCH")
    batch.update(
        source_artifact_path=record["file_path"],
        source_sha256=record["sha256"],
        as_of=timestamp(payload.get("as_of")),
        producer_date=path_date,
        schema_version=schema,
        rule_version=string(payload.get("rule_version"), length=128),
    )
    q = quality(payload.get("data_quality"))
    batch.update(
        quality_status=string(q.get("status"), length=64),
        source_event_count=integer(q.get("event_candidate_count")),
        source_trigger_count=integer(q.get("trigger_count", payload.get("trigger_count"))),
        source_rejected_count=integer(q.get("rejected_event_count")),
    )
    for k in ("single_source_count", "multi_source_count", "official_confirmed_count", "unverified_count"):
        batch[k] = integer(q.get(k))
    key = "event_candidates" if dataset == "news-events" else "triggers"
    items = payload.get(key)
    if not isinstance(items, list) or len(items) > 100000:
        fail()
    facts = []
    identities = set()
    for item in items:
        try:
            data, children = news_item_mapping(item, dataset, batch["rule_version"])
            identity = data["event_id" if dataset == "news-events" else "trigger_id"]
            if identity in identities:
                fail("DWH_IDENTITY_DUPLICATE")
            identities.add(identity)
            data.update(source_record_id=str(record["artifact_id"]), raw_path=record["file_path"], as_of=batch["as_of"])
            facts.append((data, children, record["sha256"]))
        except WarehouseError as exc:
            facts.append(str(exc))
    return batch, producer, facts


class DimensionCache:
    def __init__(self, session):
        self.session, self.cache = session, {}
        self.existing_news = {}
        self.existing_source_versions = set()

    def get(self, model, key, attrs=None):
        cache_key = (model, tuple(sorted(key.items())))
        if cache_key in self.cache:
            return self.cache[cache_key]
        row = self.session.scalar(select(model).filter_by(**key))
        if row is None:
            row = model(**key, **(attrs or {}))
            self.session.add(row)
            self.session.flush([row])
        self.cache[cache_key] = row
        return row

    def source(self, key, url=None, source_type=None, name=None):
        row = self.get(SourceDimension, dict(source_key=key), dict(url=url, source_type=source_type, name=name))
        # Type 1 descriptions: retain known values when this record is unknown.
        for attr, value in (("url", url), ("source_type", source_type), ("name", name)):
            if value is not None:
                setattr(row, attr, value)
        return row.id

    def day(self, observed):
        if observed is None:
            return None
        key = int(observed.strftime("%Y%m%d"))
        self.get(
            DateDimension,
            dict(date_key=key),
            dict(date=observed, year=observed.year, month=observed.month, day=observed.day, weekday=observed.weekday()),
        )
        return key


def insert_fact(session, cache, dataset, data, children, version, batch, producer_id):
    if not dataset.startswith("news-") and (data["source_record_id"], version) in cache.existing_source_versions:
        return False
    if dataset.startswith("news-"):
        model = NewsEventFact if dataset == "news-events" else NewsTriggerFact
        identity = "event_id" if dataset == "news-events" else "trigger_id"
        existing_key = (model, producer_id, version)
        if existing_key not in cache.existing_news:
            cache.existing_news[existing_key] = set(
                session.scalars(
                    select(getattr(model, identity)).where(
                        model.producer_run_id == producer_id, model.version_sha256 == version
                    )
                )
            )
        if data[identity] in cache.existing_news[existing_key]:
            return False
    data = dict(data, version_sha256=version, batch_id=batch.id, producer_run_id=producer_id)
    if dataset == "macro":
        sid = cache.source(children["source"], children["source_url"])
        metric = cache.get(
            MetricDimension,
            dict(
                source_id=sid, symbol=children["symbol"], unit=data["unit"] or "", frequency=children["frequency"] or ""
            ),
        )
        data.update(metric_id=metric.id, date_key=cache.day(children["observed"]))
        model, keys = MacroFact, ("metric_id", "date_key", "version_sha256")
    elif dataset == "candles":
        data.update(
            source_id=cache.source(children["source"]),
            asset_id=cache.get(AssetDimension, dict(code=children["asset"])).id,
            date_key=cache.day(children["observed"]),
        )
        model, keys = CandleFact, ("asset_id", "source_id", "timeframe", "open_time", "version_sha256")
    else:
        event = dataset == "news-events"
        instant = data["event_time" if event else "created_at"]
        data["date_key"] = cache.day(instant.date() if instant else None)
        if not event:
            data["source_id"] = cache.source(children["source_key"]) if children["source_key"] else None
        model = NewsEventFact if event else NewsTriggerFact
        keys = ("producer_run_id", "event_id" if event else "trigger_id", "version_sha256")
    if (
        not dataset.startswith("news-")
        and session.scalar(select(model.id).filter_by(**{k: data[k] for k in keys})) is not None
    ):
        return False
    fact = model(**data)
    session.add(fact)
    session.flush([fact])
    if dataset.startswith("news-"):
        cache.existing_news[existing_key].add(data[identity])
        event = dataset == "news-events"
        parent = dict(event_id=fact.id) if event else dict(trigger_id=fact.id)
        bridge = EventAsset if event else TriggerAsset
        for code in set(children["assets"]):
            session.add(bridge(**parent, asset_id=cache.get(AssetDimension, dict(code=code)).id))
        refmodel = EventSourceReference if event else TriggerSourceReference
        for ordinal, ref in enumerate(children["refs"]):
            ref = dict(ref)
            skey = ref.pop("source_key")
            stype, name = ref.pop("source_type"), ref.pop("source_name")
            session.add(
                refmodel(
                    **parent,
                    ordinal=ordinal,
                    source_id=cache.source(skey, source_type=stype, name=name) if skey else None,
                    **ref,
                )
            )
        if not event:
            for ordinal, action in enumerate(children["actions"]):
                session.add(TriggerAction(**parent, ordinal=ordinal, action=action))
            for reason in set(children["reasons"]):
                session.add(TriggerReason(**parent, reason_code=reason))
            for topic in set(children["topics"]):
                session.add(TriggerTopic(**parent, topic=topic))
    return True


def _load_warehouse(
    session,
    dataset,
    *,
    limit=100,
    after=None,
    run_id=None,
    record_ids=None,
    storage_root=None,
    dry_run=True,
    reuse_unchanged_successful=False,
    reuse_unchanged_rejected=False,
):
    """No commit or DDL. Caller owns transaction, including independent load audit.

    limit bounds source rows (or newest registered artifacts), not emitted facts.
    Dry runs validate fields/files but deliberately perform no dimension/fact writes.
    """
    if (
        dataset not in DATASETS
        or type(limit) is not int
        or not 1 <= limit <= 1000
        or type(reuse_unchanged_successful) is not bool
        or (reuse_unchanged_successful and dataset not in {"macro", "candles"})
        or type(reuse_unchanged_rejected) is not bool
        or (reuse_unchanged_rejected and dataset not in {"macro", "candles"})
    ):
        fail("DWH_ARGUMENT_INVALID")
    if run_id and not dataset.startswith("news-"):
        fail("DWH_ARGUMENT_INVALID")
    if after is not None and record_ids is not None:
        fail("DWH_ARGUMENT_INVALID")
    summary = dict(
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
        reused_batches=0,
        reused_rejected_batches=0,
    )
    with session.no_autoflush:
        if not dry_run:
            inspector = inspect(session.connection())
            if any(not inspector.has_table(t) for t in (*WarehouseBase.metadata.tables, "task_runs", "task_steps")):
                fail("DWH_SCHEMA_MISSING")
        records = source_records(session, dataset, limit, after, run_id, record_ids)
        prepared, producer_cache = [], {}
        for record in records:
            cursor = str(record.get("id", record.get("artifact_id")))
            summary["processed"] += 1
            summary["next_after"] = cursor
            try:
                prepared.append(prepare_record(session, dataset, record, storage_root, producer_cache))
            except WarehouseError as exc:
                prepared.append(
                    (
                        dict(
                            source_cursor=cursor,
                            source_artifact_path=record.get("file_path", record.get("raw_path")),
                            source_sha256=record.get("sha256"),
                        ),
                        producer_cache.get(str(record["run_id"])) if record.get("run_id") else None,
                        [str(exc)],
                    )
                )
        if reuse_unchanged_rejected:
            from apps.data_layer.warehouse_reconciliation import rejected_input_sha256

            rejection_contexts = dict(producer_cache)
            for record, (attrs, _, facts) in zip(records, prepared):
                if facts and all(isinstance(fact, str) for fact in facts):
                    # Source policy may fail before producer preparation. Resolve
                    # its current context for the digest without changing the reject.
                    try:
                        run_key = str(record["run_id"]) if record.get("run_id") else None
                        if run_key not in rejection_contexts:
                            rejection_contexts[run_key] = producer_info(session, record.get("run_id"))
                        attrs["source_sha256"] = rejected_input_sha256(dataset, record, rejection_contexts[run_key])
                    except WarehouseError:
                        attrs["source_sha256"] = None
        if dry_run:
            for _, _, facts in prepared:
                for fact in facts:
                    if isinstance(fact, str):
                        summary["rejected"] += 1
                        if fact not in summary["error_codes"]:
                            summary["error_codes"].append(fact)
                    else:
                        summary["planned"] += 1
            return summary
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
        summary["task_run_id"] = str(audit_id)
        cache = DimensionCache(session)
        if dataset in ("macro", "candles"):
            model = MacroFact if dataset == "macro" else CandleFact
            ids = [attrs["source_cursor"] for attrs, _, _ in prepared]
            if ids:
                cache.existing_source_versions = set(
                    session.execute(
                        select(model.source_record_id, model.version_sha256).where(model.source_record_id.in_(ids))
                    ).all()
                )
        reusable = {}
        if reuse_unchanged_successful:
            from apps.data_layer.warehouse_reconciliation import reusable_maintenance_batches

            reusable = reusable_maintenance_batches(
                session,
                dataset,
                prepared,
                transform_version=TRANSFORM_VERSION,
            )
        rejected_reusable = {}
        if reuse_unchanged_rejected:
            from apps.data_layer.warehouse_reconciliation import reusable_rejected_maintenance_batches

            rejected_reusable = reusable_rejected_maintenance_batches(
                session, dataset, prepared, transform_version=TRANSFORM_VERSION,
            )
        for attrs, producer, facts in prepared:
            reused_rejection = rejected_reusable.get(attrs["source_cursor"])
            if reused_rejection is not None:
                summary["rejected"] += len(facts)
                summary["reused_rejected_batches"] += 1
                summary["load_batch_ids"].append(reused_rejection.id)
                for error in facts:
                    if error not in summary["error_codes"]:
                        summary["error_codes"].append(error)
                continue
            reused = reusable.get(attrs["source_cursor"])
            if reused is not None:
                summary["planned"] += len(facts)
                summary["skipped"] += len(facts)
                summary["reused_batches"] += 1
                summary["load_batch_ids"].append(reused.id)
                continue
            producer_id = None
            if producer:
                producer = dict(producer)
                key = dict(run_id=producer.pop("run_id"))
                producer_id = cache.get(ProducerRunDimension, key, producer).id
            batch = LoadBatch(
                dataset=dataset,
                producer_run_id=producer_id,
                transform_version=TRANSFORM_VERSION,
                audit_task_run_id=str(audit_id),
                audit_task_step_id=str(step_id),
                status="loading",
                **attrs,
            )
            session.add(batch)
            session.flush([batch])
            summary["load_batch_ids"].append(batch.id)
            inserted = skipped = rejected = 0
            for fact in facts:
                if isinstance(fact, str):
                    rejected += 1
                    batch.error_code = fact
                    if fact not in summary["error_codes"]:
                        summary["error_codes"].append(fact)
                    continue
                data, children, version = fact
                summary["planned"] += 1
                if insert_fact(session, cache, dataset, data, children, version, batch, producer_id):
                    inserted += 1
                else:
                    skipped += 1
            batch.processed, batch.inserted, batch.skipped, batch.rejected = len(facts), inserted, skipped, rejected
            batch.status = "partial" if rejected and inserted + skipped else "rejected" if rejected else "loaded"
            for k, v in (("inserted", inserted), ("skipped", skipped), ("rejected", rejected)):
                summary[k] += v
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
        session.flush()
        return summary


def load_warehouse(session, dataset, **kwargs):
    """Use a savepoint for apply so caught transaction failures leave no partial ETL.

    Does not commit caller work. Caller should flush unrelated pending work first.
    """
    try:
        if kwargs.get("dry_run", True):
            return _load_warehouse(session, dataset, **kwargs)
        conn = session.connection()
        if conn.dialect.name == "sqlite":
            # sqlite3 legacy transaction mode does not BEGIN for SELECT. A bare
            # SAVEPOINT would otherwise commit on RELEASE, violating caller ownership.
            raw = conn.connection.driver_connection
            if not raw.in_transaction:
                conn.exec_driver_sql("BEGIN")
        with session.begin_nested():
            return _load_warehouse(session, dataset, **kwargs)
    except WarehouseError:
        raise
    except Exception:
        raise WarehouseError("DWH_TRANSACTION_FAILED") from None
