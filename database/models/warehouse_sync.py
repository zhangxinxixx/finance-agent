"""Resumable reconciliation of legacy ODS rows with the typed warehouse."""

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.models.warehouse import UTCDateTime, WarehouseBase


class WarehouseSyncCursor(WarehouseBase):
    __tablename__ = "dwh_ingestion_cursor"

    dataset: Mapped[str] = mapped_column(String(32), primary_key=True)
    after_cursor: Mapped[str | None] = mapped_column(String(255))
    cycle_started_at: Mapped[datetime] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())
    cycle_completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_task_run_id: Mapped[str | None] = mapped_column(String(36))


class BatchSourceFile(WarehouseBase):
    """File identity captured while loading the records that reference it.

    One source envelope can contain a manifest and several responses. This is
    explicit lineage to those files, not another fact or a JSON payload store.
    """

    __tablename__ = "dwh_batch_source_file"

    batch_id: Mapped[int] = mapped_column(ForeignKey("dwh_load_batch.id"), primary_key=True)
    raw_path: Mapped[str] = mapped_column(Text, primary_key=True)
    storage_root: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    byte_size: Mapped[int] = mapped_column(Integer)
    source_key: Mapped[str] = mapped_column(String(128))
    source_url: Mapped[str | None] = mapped_column(Text)
    collected_at: Mapped[datetime] = mapped_column(UTCDateTime())
    purpose: Mapped[str] = mapped_column(String(32), default="primary")
    batch_source_path: Mapped[str | None] = mapped_column(Text)
    batch_source_sha256: Mapped[str | None] = mapped_column(String(64))
    batch_source_cursor: Mapped[str] = mapped_column(String(255))
