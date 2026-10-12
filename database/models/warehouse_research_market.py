"""Typed DWD facts for TradingView research-market observations.

The tables intentionally contain named provider fields only.  Raw/parsed
artifact bodies remain in immutable storage and are referenced by path.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.models.warehouse import UTCDateTime, WarehouseBase


class ResearchMarketBatch(WarehouseBase):
    __tablename__ = "dwh_research_market_batch"
    __table_args__ = (
        UniqueConstraint("run_id", "kind", "content_sha256", name="uq_dwh_research_market_version"),
        CheckConstraint("kind IN ('cross_asset','adaptive','execution')", name="ck_dwh_research_market_kind"),
        Index("ix_dwh_research_market_run_kind", "run_id", "kind"),
        Index("ix_dwh_research_market_retrieved", "retrieved_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(16))
    content_sha256: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[str | None] = mapped_column(String(128))
    retrieved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    parsed_path: Mapped[str | None] = mapped_column(Text)
    chart_parsed_path: Mapped[str | None] = mapped_column(Text)
    scanner_error: Mapped[str | None] = mapped_column(String(128))
    has_schema_version: Mapped[bool] = mapped_column(Boolean)
    has_retrieved_at: Mapped[bool] = mapped_column(Boolean)
    has_parsed_path: Mapped[bool] = mapped_column(Boolean)
    has_chart_parsed_path: Mapped[bool] = mapped_column(Boolean)
    has_scanner_error: Mapped[bool] = mapped_column(Boolean)
    has_observations: Mapped[bool] = mapped_column(Boolean)
    has_chart_series: Mapped[bool] = mapped_column(Boolean)
    has_execution_chart_series: Mapped[bool] = mapped_column(Boolean)
    has_series: Mapped[bool] = mapped_column(Boolean)
    has_source_refs: Mapped[bool] = mapped_column(Boolean)
    has_limitations: Mapped[bool] = mapped_column(Boolean)
    audit_task_run_id: Mapped[str] = mapped_column(String(36), index=True)
    audit_task_step_id: Mapped[str] = mapped_column(String(36))


class ResearchMarketScannerQuote(WarehouseBase):
    __tablename__ = "dwh_research_market_scanner_quote"
    __table_args__ = (
        UniqueConstraint("batch_id", "ordinal", name="uq_dwh_research_scanner_ordinal"),
        UniqueConstraint("batch_id", "ticker", name="uq_dwh_research_scanner_ticker"),
        CheckConstraint("status IN ('available','missing','invalid')", name="ck_dwh_research_scanner_status"),
        CheckConstraint("status = 'available' OR value IS NULL", name="ck_dwh_research_scanner_unavailable_value"),
        CheckConstraint("delay_seconds IS NULL OR delay_seconds >= 0", name="ck_dwh_research_scanner_delay"),
        Index("ix_dwh_research_scanner_ticker_time", "ticker", "retrieved_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("dwh_research_market_batch.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    ticker: Mapped[str] = mapped_column(String(128))
    symbol: Mapped[str] = mapped_column(String(128))
    instrument_type: Mapped[str] = mapped_column(String(64))
    unit: Mapped[str] = mapped_column(String(64))
    retrieved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str | None] = mapped_column(String(128))
    value: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    quote_time: Mapped[datetime | None] = mapped_column(UTCDateTime())
    quote_time_verified: Mapped[bool | None] = mapped_column(Boolean)
    value_kind: Mapped[str] = mapped_column(String(64))
    delay_seconds: Mapped[int | None] = mapped_column(Integer)
    provider_bar_time: Mapped[datetime | None] = mapped_column(UTCDateTime())
    minute_bar_time: Mapped[datetime | None] = mapped_column(UTCDateTime())
    continuous_contract: Mapped[bool | None] = mapped_column(Boolean)
    scanner_close: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    update_mode: Mapped[str | None] = mapped_column(String(64))
    current_session: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)
    provider_change_pct: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    provider_change_abs: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    change_basis: Mapped[str | None] = mapped_column(String(128))


class ResearchMarketChartSeries(WarehouseBase):
    __tablename__ = "dwh_research_market_chart_series"
    __table_args__ = (
        UniqueConstraint("batch_id", "collection_key", "ordinal", name="uq_dwh_research_series_ordinal"),
        UniqueConstraint(
            "batch_id", "collection_key", "ticker", "resolution_seconds", name="uq_dwh_research_series_grain"
        ),
        CheckConstraint(
            "collection_key IN ('chart_series','execution_chart_series','series')",
            name="ck_dwh_research_series_collection",
        ),
        CheckConstraint("status IN ('available','unavailable')", name="ck_dwh_research_series_status"),
        CheckConstraint("resolution_seconds IN (60,900,3600,14400)", name="ck_dwh_research_series_resolution"),
        CheckConstraint("delay_seconds IS NULL OR delay_seconds >= 0", name="ck_dwh_research_series_delay"),
        Index("ix_dwh_research_series_ticker_time", "ticker", "resolution_seconds", "retrieved_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("dwh_research_market_batch.id", ondelete="CASCADE"), index=True)
    collection_key: Mapped[str] = mapped_column(String(32))
    ordinal: Mapped[int] = mapped_column(Integer)
    ticker: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32))
    resolution_seconds: Mapped[int] = mapped_column(Integer)
    delay_seconds: Mapped[int | None] = mapped_column(Integer)
    retrieved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    front_contract: Mapped[str | None] = mapped_column(String(64))
    continuous_contract: Mapped[bool | None] = mapped_column(Boolean)
    error: Mapped[str | None] = mapped_column(String(128))
    exchange: Mapped[str | None] = mapped_column(String(64))
    instrument_type: Mapped[str | None] = mapped_column(String(64))
    currency: Mapped[str | None] = mapped_column(String(32))
    update_mode: Mapped[str | None] = mapped_column(String(64))
    provider_delay_seconds: Mapped[int | None] = mapped_column(Integer)
    series_completed: Mapped[bool | None] = mapped_column(Boolean)
    provider_timezone: Mapped[str | None] = mapped_column(String(128))
    provider_session: Mapped[str | None] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text)
    has_metadata: Mapped[bool] = mapped_column(Boolean)


class ResearchMarketBar(WarehouseBase):
    __tablename__ = "dwh_research_market_bar"
    __table_args__ = (
        UniqueConstraint("series_id", "bar_time", name="uq_dwh_research_bar_time"),
        UniqueConstraint("series_id", "ordinal", name="uq_dwh_research_bar_ordinal"),
        CheckConstraint(
            "high >= open AND high >= close AND low <= open AND low <= close", name="ck_dwh_research_bar_ohlc"
        ),
        CheckConstraint("volume IS NULL OR volume >= 0", name="ck_dwh_research_bar_volume"),
        Index("ix_dwh_research_bar_series_time", "series_id", "bar_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    series_id: Mapped[int] = mapped_column(
        ForeignKey("dwh_research_market_chart_series.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    bar_time: Mapped[datetime] = mapped_column(UTCDateTime())
    open: Mapped[Decimal] = mapped_column(Numeric(38, 12))
    high: Mapped[Decimal] = mapped_column(Numeric(38, 12))
    low: Mapped[Decimal] = mapped_column(Numeric(38, 12))
    close: Mapped[Decimal] = mapped_column(Numeric(38, 12))
    volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    front_contract: Mapped[str | None] = mapped_column(String(64))


class _ResearchMarketSourceRef:
    ordinal: Mapped[int] = mapped_column(Integer)
    source: Mapped[str | None] = mapped_column(String(128))
    source_url: Mapped[str | None] = mapped_column(Text)
    ticker: Mapped[str | None] = mapped_column(String(128))
    symbol: Mapped[str | None] = mapped_column(String(128))
    raw_path: Mapped[str | None] = mapped_column(Text)
    parsed_path: Mapped[str | None] = mapped_column(Text)
    retrieved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    source_tier: Mapped[str | None] = mapped_column(String(64))
    evidence_scope: Mapped[str | None] = mapped_column(String(128))
    reference: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str | None] = mapped_column(String(64))
    source_type: Mapped[str | None] = mapped_column(String(64))
    source_name: Mapped[str | None] = mapped_column(String(255))
    content_scope: Mapped[str | None] = mapped_column(String(128))


class ResearchMarketBatchSourceRef(_ResearchMarketSourceRef, WarehouseBase):
    __tablename__ = "dwh_research_market_batch_source_ref"
    __table_args__ = (UniqueConstraint("batch_id", "ordinal", name="uq_dwh_research_batch_ref"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("dwh_research_market_batch.id", ondelete="CASCADE"), index=True)


class ResearchMarketScannerSourceRef(_ResearchMarketSourceRef, WarehouseBase):
    __tablename__ = "dwh_research_market_scanner_source_ref"
    __table_args__ = (UniqueConstraint("quote_id", "ordinal", name="uq_dwh_research_scanner_ref"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quote_id: Mapped[int] = mapped_column(
        ForeignKey("dwh_research_market_scanner_quote.id", ondelete="CASCADE"), index=True
    )


class ResearchMarketSeriesSourceRef(_ResearchMarketSourceRef, WarehouseBase):
    __tablename__ = "dwh_research_market_series_source_ref"
    __table_args__ = (UniqueConstraint("series_id", "ordinal", name="uq_dwh_research_series_ref"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    series_id: Mapped[int] = mapped_column(
        ForeignKey("dwh_research_market_chart_series.id", ondelete="CASCADE"), index=True
    )


class ResearchMarketLimitation(WarehouseBase):
    __tablename__ = "dwh_research_market_limitation"
    __table_args__ = (UniqueConstraint("batch_id", "ordinal", name="uq_dwh_research_limitation"),)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("dwh_research_market_batch.id", ondelete="CASCADE"), primary_key=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    limitation: Mapped[str] = mapped_column(Text)


RESEARCH_MARKET_TABLES = (
    ResearchMarketBatch.__table__,
    ResearchMarketScannerQuote.__table__,
    ResearchMarketChartSeries.__table__,
    ResearchMarketBar.__table__,
    ResearchMarketBatchSourceRef.__table__,
    ResearchMarketScannerSourceRef.__table__,
    ResearchMarketSeriesSourceRef.__table__,
    ResearchMarketLimitation.__table__,
)
