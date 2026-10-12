"""Named collection context needed to reproduce FedWatch DWS from DWD."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.models.warehouse import UTCDateTime, WarehouseBase


class FedWatchContextFact(WarehouseBase):
    __tablename__ = "dwh_fedwatch_context"
    __table_args__ = (UniqueConstraint("source_snapshot_id", "version_sha256", name="uq_dwh_fw_context_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_snapshot_id: Mapped[str] = mapped_column(String(36), index=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("dwh_load_batch.id"))
    version_sha256: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(128))
    source_url: Mapped[str] = mapped_column(Text)
    collected_at: Mapped[datetime] = mapped_column(UTCDateTime())
    source_as_of: Mapped[datetime | None] = mapped_column(UTCDateTime())
    collector_version: Mapped[str] = mapped_column(String(128))
    http_status: Mapped[int | None] = mapped_column(Integer)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    raw_artifact_ref: Mapped[str | None] = mapped_column(Text)
    parse_status: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str | None] = mapped_column(Text)
    transport: Mapped[str | None] = mapped_column(String(64))
    source_window_start: Mapped[datetime | None] = mapped_column(UTCDateTime())
    source_window_end: Mapped[datetime | None] = mapped_column(UTCDateTime())
    available_tab_count: Mapped[int | None] = mapped_column(Integer)
    captured_tab_count: Mapped[int | None] = mapped_column(Integer)
    all_future_meetings: Mapped[bool | None] = mapped_column(Boolean)
    target_present: Mapped[bool] = mapped_column(Boolean)
    target_lower: Mapped[Decimal | None] = mapped_column(Numeric(18, 12))
    target_upper: Mapped[Decimal | None] = mapped_column(Numeric(18, 12))
    target_rate_unit: Mapped[str | None] = mapped_column(String(32))
    target_effective_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    target_published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    target_timestamp_precision: Mapped[str | None] = mapped_column(String(32))
    target_availability_convention: Mapped[str | None] = mapped_column(Text)


class FedWatchSourceEvidence(WarehouseBase):
    __tablename__ = "dwh_fedwatch_source_evidence"
    __table_args__ = (
        UniqueConstraint("context_id", "scope", "ordinal", name="uq_dwh_fw_evidence_ordinal"),
        CheckConstraint("scope IN ('market', 'target')", name="ck_dwh_fw_evidence_scope"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    context_id: Mapped[int] = mapped_column(ForeignKey("dwh_fedwatch_context.id"), index=True)
    scope: Mapped[str] = mapped_column(String(16))
    ordinal: Mapped[int] = mapped_column(Integer)
    source: Mapped[str | None] = mapped_column(String(128))
    source_url: Mapped[str | None] = mapped_column(Text)
    retrieved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    raw_artifact_ref: Mapped[str | None] = mapped_column(Text)
    raw_path: Mapped[str | None] = mapped_column(Text)
    sha256: Mapped[str | None] = mapped_column(String(64))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    source_tier: Mapped[str | None] = mapped_column(String(64))
    capture_kind: Mapped[str | None] = mapped_column(String(64))
    hash_verified_at_ingestion: Mapped[bool | None] = mapped_column(Boolean)
