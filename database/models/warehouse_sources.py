"""Typed warehouse facts for collected source domains.

The source ODS models use the task metadata.  These facts deliberately keep
only named business fields and explicit lineage on ``WarehouseBase``.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.models.warehouse import FactLineage, UTCDateTime, WarehouseBase


class CmeOptionFact(FactLineage, WarehouseBase):
    __tablename__ = "dwh_fact_cme_option"
    __table_args__ = (
        UniqueConstraint(
            "source_raw_id",
            "product_code",
            "expiry",
            "strike",
            "option_type",
            "version_type",
            "version_sha256",
            name="uq_dwh_cme_option_version",
        ),
        CheckConstraint("version_type IN ('FINAL','PRELIMINARY')", name="ck_dwh_cme_option_phase"),
        CheckConstraint("strike >= 0", name="ck_dwh_cme_option_strike"),
        CheckConstraint("open_interest IS NULL OR open_interest >= 0", name="ck_dwh_cme_option_oi"),
        CheckConstraint("total_volume IS NULL OR total_volume >= 0", name="ck_dwh_cme_option_volume"),
        Index("ix_dwh_cme_option_trade_product", "trade_date", "product_code"),
        Index("ix_dwh_cme_option_expiry_strike", "expiry", "strike", "option_type"),
    )

    source_id: Mapped[int] = mapped_column(ForeignKey("dwh_dim_source.id"), index=True)
    source_raw_id: Mapped[str] = mapped_column(String(36), index=True)
    source_url: Mapped[str | None] = mapped_column(Text)
    raw_sha256: Mapped[str] = mapped_column(String(64), index=True)
    retrieved_at: Mapped[datetime] = mapped_column(UTCDateTime())
    parse_status: Mapped[str | None] = mapped_column(String(32))
    trade_date: Mapped[date] = mapped_column(Date)
    report_date: Mapped[date] = mapped_column(Date)
    version_type: Mapped[str] = mapped_column(String(16), index=True)
    product_code: Mapped[str] = mapped_column(String(16))
    underlying: Mapped[str | None] = mapped_column(String(16))
    expiry: Mapped[str] = mapped_column(String(8))
    strike: Mapped[int] = mapped_column(Integer)
    option_type: Mapped[str] = mapped_column(String(8))
    settlement: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    delta: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    open_interest: Mapped[int | None] = mapped_column(Integer)
    oi_change: Mapped[int | None] = mapped_column(Integer)
    total_volume: Mapped[int | None] = mapped_column(Integer)
    block_volume: Mapped[int | None] = mapped_column(Integer)
    pnt_volume: Mapped[int | None] = mapped_column(Integer)
    globex_volume: Mapped[int | None] = mapped_column(Integer)
    outcry_volume: Mapped[int | None] = mapped_column(Integer)
    exercises: Mapped[int | None] = mapped_column(Integer)
    pt_change: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    source_page: Mapped[int | None] = mapped_column(Integer)


class FedWatchProbabilityFact(FactLineage, WarehouseBase):
    __tablename__ = "dwh_fact_fedwatch_probability"
    __table_args__ = (
        UniqueConstraint(
            "source_snapshot_id",
            "meeting_date",
            "comparison_window",
            "target_low",
            "target_high",
            "version_sha256",
            name="uq_dwh_fedwatch_probability_version",
        ),
        CheckConstraint("target_low >= 0 AND target_low <= target_high", name="ck_dwh_fedwatch_target_low"),
        CheckConstraint("target_high <= 100", name="ck_dwh_fedwatch_target_high"),
        CheckConstraint("probability >= 0 AND probability <= 1", name="ck_dwh_fedwatch_probability"),
        Index("ix_dwh_fedwatch_meeting_window", "meeting_date", "comparison_window"),
        Index("ix_dwh_fedwatch_snapshot", "source_snapshot_id"),
    )

    source_id: Mapped[int] = mapped_column(ForeignKey("dwh_dim_source.id"), index=True)
    source_snapshot_id: Mapped[str] = mapped_column(String(36))
    source_meeting_id: Mapped[str] = mapped_column(String(36))
    source_probability_id: Mapped[str] = mapped_column(String(36))
    source_url: Mapped[str] = mapped_column(Text)
    collector_version: Mapped[str] = mapped_column(String(128))
    http_status: Mapped[int | None] = mapped_column(Integer)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    raw_artifact_ref: Mapped[str | None] = mapped_column(Text)
    parse_status: Mapped[str] = mapped_column(String(32))
    collected_at: Mapped[datetime] = mapped_column(UTCDateTime())
    snapshot_as_of: Mapped[datetime | None] = mapped_column(UTCDateTime())
    meeting_date: Mapped[date] = mapped_column(Date)
    contract_ref: Mapped[str | None] = mapped_column(String(128))
    comparison_window: Mapped[str] = mapped_column(String(16))
    observation_as_of: Mapped[datetime] = mapped_column(UTCDateTime())
    target_low: Mapped[Decimal] = mapped_column(Numeric(18, 12))
    target_high: Mapped[Decimal] = mapped_column(Numeric(18, 12))
    probability: Mapped[Decimal] = mapped_column(Numeric(18, 12))


class FedWatchFuturesFact(FactLineage, WarehouseBase):
    __tablename__ = "dwh_fact_fedwatch_futures"
    __table_args__ = (
        UniqueConstraint(
            "source_snapshot_id", "contract_ref", "version_sha256", name="uq_dwh_fedwatch_futures_version"
        ),
        CheckConstraint("volume IS NULL OR volume >= 0", name="ck_dwh_fedwatch_futures_volume"),
        CheckConstraint("open_interest IS NULL OR open_interest >= 0", name="ck_dwh_fedwatch_futures_oi"),
        Index("ix_dwh_fedwatch_futures_contract", "contract_ref", "observation_as_of"),
        Index("ix_dwh_fedwatch_futures_snapshot", "source_snapshot_id"),
    )

    source_id: Mapped[int] = mapped_column(ForeignKey("dwh_dim_source.id"), index=True)
    source_snapshot_id: Mapped[str] = mapped_column(String(36))
    source_futures_id: Mapped[str] = mapped_column(String(36))
    row_index: Mapped[int] = mapped_column(Integer)
    source_url: Mapped[str] = mapped_column(Text)
    collector_version: Mapped[str] = mapped_column(String(128))
    http_status: Mapped[int | None] = mapped_column(Integer)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    raw_artifact_ref: Mapped[str | None] = mapped_column(Text)
    parse_status: Mapped[str] = mapped_column(String(32))
    collected_at: Mapped[datetime] = mapped_column(UTCDateTime())
    snapshot_as_of: Mapped[datetime | None] = mapped_column(UTCDateTime())
    contract_ref: Mapped[str] = mapped_column(String(128))
    observation_as_of: Mapped[datetime | None] = mapped_column(UTCDateTime())
    settlement: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    price: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    implied_rate: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    change: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    change_pct: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    volume: Mapped[int | None] = mapped_column(Integer)
    open_interest: Mapped[int | None] = mapped_column(Integer)


class FedFundsSettlementFact(FactLineage, WarehouseBase):
    __tablename__ = "dwh_fact_fed_funds_settlement"
    __table_args__ = (
        UniqueConstraint(
            "source_snapshot_id", "contract", "version_sha256", name="uq_dwh_fed_funds_settlement_version"
        ),
        CheckConstraint(
            "settlement_status IS NULL OR settlement_status IN ('FINAL','PRELIMINARY')",
            name="ck_dwh_fed_funds_settlement_phase",
        ),
        CheckConstraint("volume IS NULL OR volume >= 0", name="ck_dwh_fed_funds_settlement_volume"),
        CheckConstraint("open_interest IS NULL OR open_interest >= 0", name="ck_dwh_fed_funds_settlement_oi"),
        Index("ix_dwh_fed_funds_trade_contract", "trade_date", "contract"),
        Index("ix_dwh_fed_funds_contract_month", "contract_month"),
    )

    source_id: Mapped[int] = mapped_column(ForeignKey("dwh_dim_source.id"), index=True)
    source_snapshot_id: Mapped[str] = mapped_column(String(36), index=True)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str | None] = mapped_column(String(64))
    product_id: Mapped[int | None] = mapped_column(Integer)
    instrument: Mapped[str | None] = mapped_column(String(32))
    official_display_probability: Mapped[bool | None] = mapped_column(Boolean)
    schema_version: Mapped[str | None] = mapped_column(String(128))
    collector_version: Mapped[str | None] = mapped_column(String(128))
    parser_version: Mapped[str | None] = mapped_column(String(128))
    collection_mode: Mapped[str | None] = mapped_column(String(32))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    raw_artifact_ref: Mapped[str | None] = mapped_column(Text)
    manifest_ref: Mapped[str | None] = mapped_column(Text)
    http_status: Mapped[int | None] = mapped_column(Integer)
    content_type: Mapped[str | None] = mapped_column(String(255))
    source_bytes: Mapped[int | None] = mapped_column(Integer)
    truncated: Mapped[bool | None] = mapped_column(Boolean)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)
    transport_error_code: Mapped[int | None] = mapped_column(Integer)
    trade_date: Mapped[date] = mapped_column(Date)
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime())
    source_update_time_raw: Mapped[str | None] = mapped_column(String(255))
    source_time_timezone: Mapped[str | None] = mapped_column(String(64))
    settlement_status: Mapped[str | None] = mapped_column(String(16), index=True)
    request_status: Mapped[str | None] = mapped_column(String(32))
    data_status: Mapped[str] = mapped_column(String(32))
    health: Mapped[str | None] = mapped_column(String(32))
    contract: Mapped[str] = mapped_column(String(16))
    contract_month: Mapped[date] = mapped_column(Date)
    settle: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    volume: Mapped[int | None] = mapped_column(Integer)
    open_interest: Mapped[int | None] = mapped_column(Integer)


class NewsItemFact(FactLineage, WarehouseBase):
    __tablename__ = "dwh_fact_news_item"
    __table_args__ = (
        UniqueConstraint(
            "producer_run_id", "duplicate_key", "version_sha256", name="uq_dwh_news_item_version"
        ),
        Index("ix_dwh_news_item_published", "published_at"),
        Index("ix_dwh_news_item_source_fetched", "source_id", "fetched_at"),
    )

    producer_run_id: Mapped[int] = mapped_column(ForeignKey("dwh_dim_producer_run.id"), index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("dwh_dim_source.id"), index=True)
    source_key: Mapped[str] = mapped_column(String(128))
    source_name: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(64))
    feed_key: Mapped[str] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    domain: Mapped[str] = mapped_column(String(255))
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime())
    summary: Mapped[str | None] = mapped_column(Text)
    source_language: Mapped[str | None] = mapped_column(String(32))
    source_country: Mapped[str | None] = mapped_column(String(32))
    event_type: Mapped[str | None] = mapped_column(String(64))
    verification_status: Mapped[str] = mapped_column(String(64))
    duplicate_key: Mapped[str] = mapped_column(String(255))
    parsed_path: Mapped[str | None] = mapped_column(Text)


SOURCE_WAREHOUSE_TABLES = (
    CmeOptionFact.__table__,
    FedWatchProbabilityFact.__table__,
    FedWatchFuturesFact.__table__,
    FedFundsSettlementFact.__table__,
    NewsItemFact.__table__,
)
