"""Typed catalog and audit trail for retained raw source files."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from database.models.warehouse import UTCDateTime


class RawSourceBase(DeclarativeBase):
    """Independent metadata: only raw-source tables may reference each other."""


class RawSourceFile(RawSourceBase):
    __tablename__ = "raw_source_file"
    __table_args__ = (
        Index("ix_raw_source_file_retention", "storage_root", "state", "collected_at"),
        Index("ix_raw_source_file_identity", "storage_root", "raw_path", "sha256"),
        CheckConstraint("byte_size >= 0", name="ck_raw_source_file_byte_size"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    storage_root: Mapped[str] = mapped_column(Text, nullable=False)
    raw_path: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    source_key: Mapped[str] = mapped_column(String(128), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    collected_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    # External task id by design: task tables use different SQLAlchemy metadata.
    producer_run_id: Mapped[str | None] = mapped_column(String(255), index=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="registered")
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=lambda: datetime.now(UTC))


class RawSourceLoad(RawSourceBase):
    __tablename__ = "raw_source_load"
    __table_args__ = (
        Index("ix_raw_source_load_file_status", "raw_file_id", "status"),
        CheckConstraint("expected_records >= 0", name="ck_raw_source_load_expected"),
        CheckConstraint("loaded_records >= 0", name="ck_raw_source_load_loaded"),
        CheckConstraint("rejected_records >= 0", name="ck_raw_source_load_rejected"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    raw_file_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("raw_source_file.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    dataset: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_records: Mapped[int] = mapped_column(Integer, nullable=False)
    loaded_records: Mapped[int] = mapped_column(Integer, nullable=False)
    rejected_records: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=lambda: datetime.now(UTC))


class RawSourceLoadBatch(RawSourceBase):
    """Bridge to DWH load batches without a cross-metadata foreign key."""

    __tablename__ = "raw_source_load_batch"
    __table_args__ = (
        UniqueConstraint("load_id", "batch_id", name="uq_raw_source_load_batch"),
        UniqueConstraint("load_id", "ordinal", name="uq_raw_source_load_batch_ordinal"),
    )

    load_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("raw_source_load.id", ondelete="RESTRICT"), primary_key=True
    )
    batch_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)


class RawRetentionEvent(RawSourceBase):
    __tablename__ = "raw_retention_event"
    __table_args__ = (Index("ix_raw_retention_event_status", "status", "intended_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    raw_file_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("raw_source_file.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False, default="delete")
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    # External audit ids by design; no cross-metadata foreign keys.
    task_run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    task_step_id: Mapped[str] = mapped_column(String(36), nullable=False)
    storage_root: Mapped[str] = mapped_column(Text, nullable=False)
    raw_path: Mapped[str] = mapped_column(Text, nullable=False)
    staged_path: Mapped[str | None] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    intended_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    staged_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class RawRetentionScan(RawSourceBase):
    """Durable keyset cursor used only by mutating retention runs.

    Preview deliberately does not update this row.  A nullable cursor means the
    next apply starts at the oldest live catalog row.
    """

    __tablename__ = "raw_retention_scan"

    storage_root: Mapped[str] = mapped_column(Text, primary_key=True)
    last_collected_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_file_id: Mapped[str | None] = mapped_column(String(36))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=lambda: datetime.now(UTC))


def ensure_raw_source_tables(bind) -> None:
    """Explicit test/bootstrap helper; runtime callers must use migrations."""
    from sqlalchemy.orm import Session

    if isinstance(bind, Session):
        bind = bind.connection()
    RawSourceBase.metadata.create_all(bind=bind, checkfirst=True)
