"""CME daily bulletin storage models."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.task import Base


class CmeRawFile(Base):
    __tablename__ = "cme_raw_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    section: Mapped[str] = mapped_column(String(128), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    raw_path: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    report_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    option_rows: Mapped[list["CmeOptionRow"]] = relationship(
        back_populates="raw_file",
        cascade="all, delete-orphan",
    )
    parse_run: Mapped["CmeParseRun | None"] = relationship(
        back_populates="raw_file",
        cascade="all, delete-orphan",
        uselist=False,
    )


class CmeOptionRow(Base):
    __tablename__ = "cme_option_rows"
    __table_args__ = (
        UniqueConstraint("report_date", "product_code", "expiry", "strike", "option_type", "version_type", name="uq_cme_option_row"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    raw_file_id: Mapped[str] = mapped_column(String(36), ForeignKey("cme_raw_files.id"), nullable=False, index=True)
    trade_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    report_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    version_type: Mapped[str] = mapped_column(String(16), nullable=False, default="PRELIMINARY", index=True)
    product_code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    underlying: Mapped[str | None] = mapped_column(String(16), nullable=True, default="GC")
    expiry: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    strike: Mapped[int] = mapped_column(Integer, nullable=False)
    option_type: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    settlement: Mapped[float | None] = mapped_column(Float, nullable=True)
    delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    open_interest: Mapped[int | None] = mapped_column(Integer, nullable=True)
    oi_change: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    block_volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pnt_volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    globex_volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcry_volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exercises: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pt_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    raw_file: Mapped["CmeRawFile"] = relationship(back_populates="option_rows")


class CmeParseRun(Base):
    __tablename__ = "cme_parse_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    raw_file_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("cme_raw_files.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    detail_rows_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary_rows_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warnings_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    notes_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    raw_file: Mapped["CmeRawFile"] = relationship(back_populates="parse_run")
