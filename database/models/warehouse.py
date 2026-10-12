"""Portable, typed DWD schema. No source bodies are persisted here."""

from __future__ import annotations

from datetime import date, datetime, UTC
from decimal import Decimal
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, Index
from sqlalchemy.types import TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class UTCDateTime(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class WarehouseBase(DeclarativeBase):
    pass


class DateDimension(WarehouseBase):
    __tablename__ = "dwh_dim_date"
    date_key: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[date] = mapped_column(Date, unique=True)
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    day: Mapped[int] = mapped_column(Integer)
    weekday: Mapped[int] = mapped_column(Integer)


class SourceDimension(WarehouseBase):
    __tablename__ = "dwh_dim_source"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_key: Mapped[str] = mapped_column(String(128), unique=True)
    source_type: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str | None] = mapped_column(String(255))
    url: Mapped[str | None] = mapped_column(Text)


class AssetDimension(WarehouseBase):
    __tablename__ = "dwh_dim_asset"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(128), unique=True)


class MetricDimension(WarehouseBase):
    __tablename__ = "dwh_dim_metric"
    __table_args__ = (UniqueConstraint("source_id", "symbol", "unit", "frequency", name="uq_dwh_metric"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("dwh_dim_source.id"))
    symbol: Mapped[str] = mapped_column(String(128))
    # Empty string is the canonical unknown unit/frequency natural-key component.
    unit: Mapped[str] = mapped_column(String(64))
    frequency: Mapped[str] = mapped_column(String(64))


class ProducerRunDimension(WarehouseBase):
    __tablename__ = "dwh_dim_producer_run"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(255), unique=True)
    verified: Mapped[bool] = mapped_column(Boolean)
    producer_date: Mapped[date | None] = mapped_column(Date)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class LoadBatch(WarehouseBase):
    __tablename__ = "dwh_load_batch"
    __table_args__ = (Index("ix_dwh_batch_dataset_cursor", "dataset", "source_cursor"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset: Mapped[str] = mapped_column(String(32))
    source_cursor: Mapped[str] = mapped_column(String(255))
    producer_run_id: Mapped[int | None] = mapped_column(ForeignKey("dwh_dim_producer_run.id"))
    source_artifact_path: Mapped[str | None] = mapped_column(Text)
    source_sha256: Mapped[str | None] = mapped_column(String(64))
    as_of: Mapped[datetime | None] = mapped_column(UTCDateTime())
    producer_date: Mapped[date | None] = mapped_column(Date)
    schema_version: Mapped[str | None] = mapped_column(String(128))
    rule_version: Mapped[str | None] = mapped_column(String(128))
    quality_status: Mapped[str | None] = mapped_column(String(64))
    source_event_count: Mapped[int | None] = mapped_column(Integer)
    source_trigger_count: Mapped[int | None] = mapped_column(Integer)
    source_rejected_count: Mapped[int | None] = mapped_column(Integer)
    single_source_count: Mapped[int | None] = mapped_column(Integer)
    multi_source_count: Mapped[int | None] = mapped_column(Integer)
    official_confirmed_count: Mapped[int | None] = mapped_column(Integer)
    unverified_count: Mapped[int | None] = mapped_column(Integer)
    load_time: Mapped[datetime] = mapped_column(UTCDateTime(), default=lambda: datetime.now(UTC))
    transform_version: Mapped[str] = mapped_column(String(64))
    processed: Mapped[int] = mapped_column(Integer, default=0)
    inserted: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32))
    error_code: Mapped[str | None] = mapped_column(String(64))
    # Explicit external lineage: task metadata is intentionally independent.
    audit_task_run_id: Mapped[str] = mapped_column(String(36), index=True)
    audit_task_step_id: Mapped[str] = mapped_column(String(36))


class FactLineage:
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("dwh_load_batch.id"))
    producer_run_id: Mapped[int | None] = mapped_column(ForeignKey("dwh_dim_producer_run.id"), index=True)
    version_sha256: Mapped[str] = mapped_column(String(64))
    source_record_id: Mapped[str] = mapped_column(String(255))
    raw_path: Mapped[str | None] = mapped_column(Text)
    as_of: Mapped[datetime | None] = mapped_column(UTCDateTime())
    quality_status: Mapped[str | None] = mapped_column(String(64))


class MacroFact(FactLineage, WarehouseBase):
    __tablename__ = "dwh_fact_macro"
    __table_args__ = (
        UniqueConstraint("metric_id", "date_key", "version_sha256", name="uq_dwh_macro_version"),
        Index("ix_dwh_macro_date_metric", "date_key", "metric_id"),
        Index("ix_dwh_macro_source_record", "source_record_id"),
        Index("ix_dwh_macro_pit", "metric_id", "date_key", "retrieved_at", "id"),
    )
    metric_id: Mapped[int] = mapped_column(ForeignKey("dwh_dim_metric.id"))
    date_key: Mapped[int] = mapped_column(ForeignKey("dwh_dim_date.date_key"))
    value: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    unit: Mapped[str | None] = mapped_column(String(64))
    retrieved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    # Fact-local provenance is immutable for a revision.  SourceDimension.url
    # remains a Type-1 catalog description and must not rewrite history.
    source_url: Mapped[str | None] = mapped_column(Text)
    previous_value: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    reference_period: Mapped[str | None] = mapped_column(String(64))
    previous_reference_period: Mapped[str | None] = mapped_column(String(64))
    raw_artifact_id: Mapped[str | None] = mapped_column(String(255))
    parsed_artifact_id: Mapped[str | None] = mapped_column(String(255))


class CandleFact(FactLineage, WarehouseBase):
    __tablename__ = "dwh_fact_candle"
    __table_args__ = (
        UniqueConstraint(
            "asset_id", "source_id", "timeframe", "open_time", "version_sha256", name="uq_dwh_candle_version"
        ),
        Index("ix_dwh_candle_asset_time", "asset_id", "timeframe", "open_time"),
        Index("ix_dwh_candle_source_time", "source_id", "open_time"),
        Index("ix_dwh_candle_source_record", "source_record_id"),
        Index(
            "ix_dwh_candle_pit",
            "asset_id",
            "source_id",
            "timeframe",
            "open_time",
            "retrieved_at",
            "updated_at",
            "created_at",
            "id",
        ),
    )
    asset_id: Mapped[int] = mapped_column(ForeignKey("dwh_dim_asset.id"))
    source_id: Mapped[int] = mapped_column(ForeignKey("dwh_dim_source.id"))
    date_key: Mapped[int] = mapped_column(ForeignKey("dwh_dim_date.date_key"))
    timeframe: Mapped[str] = mapped_column(String(16))
    open_time: Mapped[datetime] = mapped_column(UTCDateTime())
    open: Mapped[Decimal] = mapped_column(Numeric(38, 12))
    high: Mapped[Decimal] = mapped_column(Numeric(38, 12))
    low: Mapped[Decimal] = mapped_column(Numeric(38, 12))
    close: Mapped[Decimal] = mapped_column(Numeric(38, 12))
    volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    # These are source/ODS timestamps, not warehouse load timestamps.  They
    # remain nullable because historical rows cannot be upgraded by inference.
    retrieved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    # Typed projection of the numeric source reference used by identity and
    # source-role gates.  No JSON/EAV source-reference bag is persisted.
    provider: Mapped[str | None] = mapped_column(String(128))
    provider_symbol: Mapped[str | None] = mapped_column(String(128))
    provider_timeframe: Mapped[str | None] = mapped_column(String(64))
    instrument_type: Mapped[str | None] = mapped_column(String(64))
    source_role: Mapped[str | None] = mapped_column(String(64))
    source_url: Mapped[str | None] = mapped_column(Text)
    source_reference: Mapped[str | None] = mapped_column(Text)
    reference_status: Mapped[str | None] = mapped_column(String(64))
    evidence_scope: Mapped[str | None] = mapped_column(String(64))
    source_tier: Mapped[str | None] = mapped_column(String(64))
    identity_guard: Mapped[str | None] = mapped_column(String(64))


class NewsEventFact(FactLineage, WarehouseBase):
    __tablename__ = "dwh_fact_news_event"
    producer_run_id: Mapped[int] = mapped_column(ForeignKey("dwh_dim_producer_run.id"), index=True)
    __table_args__ = (
        UniqueConstraint("producer_run_id", "event_id", "version_sha256", name="uq_dwh_event_version"),
        Index("ix_dwh_event_time_type", "event_time", "event_type"),
    )
    event_id: Mapped[str] = mapped_column(String(255))
    date_key: Mapped[int | None] = mapped_column(ForeignKey("dwh_dim_date.date_key"))
    primary_news_item_id: Mapped[str | None] = mapped_column(String(255))
    event_type: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str | None] = mapped_column(String(64))
    event_time: Mapped[datetime | None] = mapped_column(UTCDateTime())
    direction: Mapped[str | None] = mapped_column(String(64))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(18, 12))
    verification_status: Mapped[str | None] = mapped_column(String(64))
    need_verification: Mapped[bool | None] = mapped_column(Boolean)
    source_count: Mapped[int | None] = mapped_column(Integer)
    evidence: Mapped[str | None] = mapped_column(Text)
    duplicate_group: Mapped[str | None] = mapped_column(String(255))
    independent_source_count: Mapped[int | None] = mapped_column(Integer)
    independent_domain_count: Mapped[int | None] = mapped_column(Integer)
    authoritative_source_count: Mapped[int | None] = mapped_column(Integer)
    evidence_scope: Mapped[str | None] = mapped_column(String(64))
    full_text_available: Mapped[bool | None] = mapped_column(Boolean)


class NewsTriggerFact(FactLineage, WarehouseBase):
    __tablename__ = "dwh_fact_news_trigger"
    producer_run_id: Mapped[int] = mapped_column(ForeignKey("dwh_dim_producer_run.id"), index=True)
    __table_args__ = (
        UniqueConstraint("producer_run_id", "trigger_id", "version_sha256", name="uq_dwh_trigger_version"),
        Index("ix_dwh_trigger_time_status", "created_at", "status"),
    )
    trigger_id: Mapped[str] = mapped_column(String(255))
    date_key: Mapped[int | None] = mapped_column(ForeignKey("dwh_dim_date.date_key"))
    source_id: Mapped[int | None] = mapped_column(ForeignKey("dwh_dim_source.id"), index=True)
    trigger_type: Mapped[str | None] = mapped_column(String(64))
    priority: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    source_news_item_id: Mapped[str | None] = mapped_column(String(255))
    source_event_id: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    event_type: Mapped[str | None] = mapped_column(String(64))
    impact_path: Mapped[str | None] = mapped_column(Text)
    gold_impact: Mapped[str | None] = mapped_column(String(64))
    evidence: Mapped[str | None] = mapped_column(Text)
    verification_status: Mapped[str | None] = mapped_column(String(64))
    rule_version: Mapped[str | None] = mapped_column(String(128))
    source_count: Mapped[int | None] = mapped_column(Integer)
    trigger_score: Mapped[Decimal | None] = mapped_column(Numeric(18, 12))
    relevance_score: Mapped[Decimal | None] = mapped_column(Numeric(18, 12))
    relevance_decision: Mapped[str | None] = mapped_column(String(64))


class EventAsset(WarehouseBase):
    __tablename__ = "dwh_bridge_event_asset"
    event_id: Mapped[int] = mapped_column(ForeignKey("dwh_fact_news_event.id"), primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("dwh_dim_asset.id"), primary_key=True, index=True)


class TriggerAsset(WarehouseBase):
    __tablename__ = "dwh_bridge_trigger_asset"
    trigger_id: Mapped[int] = mapped_column(ForeignKey("dwh_fact_news_trigger.id"), primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("dwh_dim_asset.id"), primary_key=True, index=True)


class SourceReference:
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("dwh_dim_source.id"), index=True)
    source_ref: Mapped[str | None] = mapped_column(Text)
    raw_path: Mapped[str | None] = mapped_column(Text)
    parsed_path: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    retrieved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    status: Mapped[str | None] = mapped_column(String(64))
    content_scope: Mapped[str | None] = mapped_column(String(64))


class EventSourceReference(SourceReference, WarehouseBase):
    __tablename__ = "dwh_event_source_ref"
    __table_args__ = (UniqueConstraint("event_id", "ordinal", name="uq_dwh_event_ref"),)
    event_id: Mapped[int] = mapped_column(ForeignKey("dwh_fact_news_event.id"), index=True)


class TriggerSourceReference(SourceReference, WarehouseBase):
    __tablename__ = "dwh_trigger_source_ref"
    __table_args__ = (UniqueConstraint("trigger_id", "ordinal", name="uq_dwh_trigger_ref"),)
    trigger_id: Mapped[int] = mapped_column(ForeignKey("dwh_fact_news_trigger.id"), index=True)


class TriggerAction(WarehouseBase):
    __tablename__ = "dwh_trigger_action"
    trigger_id: Mapped[int] = mapped_column(ForeignKey("dwh_fact_news_trigger.id"), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    action: Mapped[str] = mapped_column(String(255))


class TriggerReason(WarehouseBase):
    __tablename__ = "dwh_trigger_reason"
    trigger_id: Mapped[int] = mapped_column(ForeignKey("dwh_fact_news_trigger.id"), primary_key=True)
    reason_code: Mapped[str] = mapped_column(String(128), primary_key=True)


class TriggerTopic(WarehouseBase):
    __tablename__ = "dwh_trigger_topic"
    trigger_id: Mapped[int] = mapped_column(ForeignKey("dwh_fact_news_trigger.id"), primary_key=True)
    topic: Mapped[str] = mapped_column(String(128), primary_key=True)


def ensure_warehouse_tables(bind) -> None:
    """Explicit opt-in: only create new warehouse tables, never alter legacy schema."""
    from sqlalchemy.orm import Session

    if isinstance(bind, Session):
        bind = bind.connection()
    WarehouseBase.metadata.create_all(bind=bind, checkfirst=True)
