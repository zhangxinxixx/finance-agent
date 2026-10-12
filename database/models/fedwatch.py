"""Portable normalized persistence models for free CME FedWatch snapshots."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.analysis import JSONB_COMPAT
from database.models.task import Base


class FedWatchRawSnapshot(Base):
    """One immutable collection event, including failed collection events."""

    __tablename__ = "fedwatch_raw_snapshot"
    __table_args__ = (
        CheckConstraint(
            "parse_status IN ('ok', 'parse_failed', 'missing')",
            name="ck_fedwatch_raw_snapshot_parse_status",
        ),
        Index("ix_fedwatch_raw_snapshot_source_as_of", "source", "as_of"),
        Index("ix_fedwatch_raw_snapshot_collected_at", "collected_at"),
        Index("ix_fedwatch_raw_snapshot_parse_status", "parse_status"),
        Index("ix_fedwatch_raw_snapshot_content_hash", "content_hash"),
    )

    snapshot_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    collector_version: Mapped[str] = mapped_column(String(128), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_artifact_ref: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    parse_status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_refs: Mapped[list] = mapped_column(JSONB_COMPAT, nullable=False, default=list)
    snapshot_metadata: Mapped[dict] = mapped_column(JSONB_COMPAT, nullable=False, default=dict)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    meetings: Mapped[list["FedWatchMeetingSnapshot"]] = relationship(
        back_populates="snapshot",
        cascade="all, delete-orphan",
        order_by="FedWatchMeetingSnapshot.row_index",
    )
    futures: Mapped[list["FedWatchFutures"]] = relationship(
        back_populates="snapshot",
        cascade="all, delete-orphan",
        order_by="FedWatchFutures.row_index",
    )
    factor: Mapped["FedWatchFactor | None"] = relationship(
        back_populates="snapshot",
        cascade="all, delete-orphan",
        uselist=False,
    )


class FedWatchMeetingSnapshot(Base):
    """A meeting/window distribution observed at one actual source time."""

    __tablename__ = "fedwatch_meeting_snapshot"
    __table_args__ = (
        CheckConstraint(
            "comparison_window IN ('current', '1d', '1w', '1m')",
            name="ck_fedwatch_meeting_snapshot_window",
        ),
        UniqueConstraint(
            "snapshot_id",
            "meeting_date",
            "comparison_window",
            name="uq_fedwatch_meeting_snapshot_window",
        ),
        UniqueConstraint(
            "snapshot_id", "row_index", name="uq_fedwatch_meeting_snapshot_row_index"
        ),
        Index(
            "ix_fedwatch_meeting_snapshot_meeting_window_as_of",
            "meeting_date",
            "comparison_window",
            "as_of",
        ),
        Index("ix_fedwatch_meeting_snapshot_snapshot_id", "snapshot_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    snapshot_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("fedwatch_raw_snapshot.snapshot_id", ondelete="CASCADE"),
        nullable=False,
    )
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    meeting_date: Mapped[date] = mapped_column(Date, nullable=False)
    contract_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    comparison_window: Mapped[str] = mapped_column(String(16), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    snapshot: Mapped["FedWatchRawSnapshot"] = relationship(back_populates="meetings")
    probabilities: Mapped[list["FedWatchProbability"]] = relationship(
        back_populates="meeting_snapshot",
        cascade="all, delete-orphan",
        order_by="FedWatchProbability.row_index",
    )


class FedWatchProbability(Base):
    """One queryable target-range probability in a meeting distribution."""

    __tablename__ = "fedwatch_probability"
    __table_args__ = (
        CheckConstraint("target_low >= 0 AND target_low <= 100", name="ck_fedwatch_probability_low"),
        CheckConstraint("target_high >= 0 AND target_high <= 100", name="ck_fedwatch_probability_high"),
        CheckConstraint("target_low <= target_high", name="ck_fedwatch_probability_range"),
        CheckConstraint("probability >= 0 AND probability <= 1", name="ck_fedwatch_probability_value"),
        UniqueConstraint(
            "meeting_snapshot_id",
            "target_low",
            "target_high",
            name="uq_fedwatch_probability_target_range",
        ),
        UniqueConstraint(
            "meeting_snapshot_id", "row_index", name="uq_fedwatch_probability_row_index"
        ),
        Index("ix_fedwatch_probability_meeting_snapshot_id", "meeting_snapshot_id"),
        Index("ix_fedwatch_probability_target_range", "target_low", "target_high"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    meeting_snapshot_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("fedwatch_meeting_snapshot.id", ondelete="CASCADE"),
        nullable=False,
    )
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    target_low: Mapped[float] = mapped_column(Float, nullable=False)
    target_high: Mapped[float] = mapped_column(Float, nullable=False)
    probability: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    meeting_snapshot: Mapped["FedWatchMeetingSnapshot"] = relationship(
        back_populates="probabilities"
    )


class FedWatchFutures(Base):
    """Optional normalized futures observations retained with a snapshot."""

    __tablename__ = "fedwatch_futures"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "row_index", name="uq_fedwatch_futures_row_index"),
        Index("ix_fedwatch_futures_snapshot_id", "snapshot_id"),
        Index("ix_fedwatch_futures_contract_as_of", "contract_ref", "as_of"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    snapshot_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("fedwatch_raw_snapshot.snapshot_id", ondelete="CASCADE"),
        nullable=False,
    )
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    contract_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB_COMPAT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    snapshot: Mapped["FedWatchRawSnapshot"] = relationship(back_populates="futures")


class FedWatchFactor(Base):
    """Versioned deterministic factor payload derived from one snapshot."""

    __tablename__ = "fedwatch_factor"
    __table_args__ = (
        Index("ix_fedwatch_factor_as_of", "as_of"),
        Index("ix_fedwatch_factor_version_as_of", "factor_version", "as_of"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    snapshot_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("fedwatch_raw_snapshot.snapshot_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    factor_version: Mapped[str] = mapped_column(String(128), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_refs: Mapped[list] = mapped_column(JSONB_COMPAT, nullable=False, default=list)
    payload: Mapped[dict] = mapped_column(JSONB_COMPAT, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    snapshot: Mapped["FedWatchRawSnapshot"] = relationship(back_populates="factor")


# Compatibility aliases for callers that spell the product name as one word.
FedwatchRawSnapshot = FedWatchRawSnapshot
FedwatchMeetingSnapshot = FedWatchMeetingSnapshot
FedwatchProbability = FedWatchProbability
FedwatchFutures = FedWatchFutures
FedwatchFactor = FedWatchFactor


def ensure_fedwatch_tables(bind_or_session) -> None:
    """Create only FedWatch tables on the supplied Engine, Connection, or Session."""

    from sqlalchemy.orm import Session as _Session

    bind = bind_or_session.get_bind() if isinstance(bind_or_session, _Session) else bind_or_session
    Base.metadata.create_all(
        bind=bind,
        tables=[
            FedWatchRawSnapshot.__table__,
            FedWatchMeetingSnapshot.__table__,
            FedWatchProbability.__table__,
            FedWatchFutures.__table__,
            FedWatchFactor.__table__,
        ],
        checkfirst=True,
    )
