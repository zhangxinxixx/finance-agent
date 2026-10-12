"""Portable report artifact models for Phase 4 report detail APIs."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from database.models.analysis import JSONB_COMPAT


class ReportBase(DeclarativeBase):
    """Portable base for report tables."""

    pass


class ReportItem(ReportBase):
    __tablename__ = "report_items"
    __table_args__ = (
        UniqueConstraint("report_id", name="uq_report_items_report_id"),
        Index("ix_report_items_family_trade_date", "family", "trade_date"),
        Index("ix_report_items_run_id", "run_id"),
        Index("ix_report_items_snapshot_id", "snapshot_id"),
        Index("ix_report_items_status", "data_status", "lifecycle_status"),
        Index("ix_report_items_source_refs_gin", "source_refs", postgresql_using="gin"),
        Index("ix_report_items_metadata_gin", "metadata", postgresql_using="gin"),
    )

    report_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    family: Mapped[str] = mapped_column(String(64), nullable=False)
    report_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    asset: Mapped[str | None] = mapped_column(String(32), nullable=True)
    trade_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    snapshot_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    data_status: Mapped[str] = mapped_column(String(32), nullable=False, default="live")
    lifecycle_status: Mapped[str] = mapped_column(String(32), nullable=False, default="generated")
    source_refs: Mapped[list] = mapped_column(JSONB_COMPAT, nullable=False, default=list)
    report_metadata: Mapped[dict] = mapped_column("metadata", JSONB_COMPAT, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    artifacts: Mapped[list["ReportArtifact"]] = relationship(
        back_populates="report_item",
        cascade="all, delete-orphan",
        order_by="ReportArtifact.generated_at.desc()",
    )


class ReportArtifact(ReportBase):
    __tablename__ = "report_artifacts"
    __table_args__ = (
        UniqueConstraint("artifact_id", name="uq_report_artifacts_artifact_id"),
        UniqueConstraint("report_id", "artifact_type", "file_path", name="uq_report_artifacts_report_type_path"),
        Index("ix_report_artifacts_report_id", "report_id"),
        Index("ix_report_artifacts_type", "artifact_type"),
        Index("ix_report_artifacts_primary", "report_id", "is_primary"),
        Index("ix_report_artifacts_source_refs_gin", "source_refs", postgresql_using="gin"),
        Index("ix_report_artifacts_metadata_gin", "metadata", postgresql_using="gin"),
    )

    artifact_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    report_id: Mapped[str] = mapped_column(ForeignKey("report_items.report_id"), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(32), nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    storage_backend: Mapped[str] = mapped_column(String(32), nullable=False, default="local_fs")
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    template_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="generated")
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_refs: Mapped[list] = mapped_column(JSONB_COMPAT, nullable=False, default=list)
    artifact_metadata: Mapped[dict] = mapped_column("metadata", JSONB_COMPAT, nullable=False, default=dict)
    metadata_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    report_item: Mapped[ReportItem] = relationship(back_populates="artifacts")


def ensure_report_tables(bind_or_session):
    """Create report tables if they do not already exist."""
    from sqlalchemy.orm import Session as _Session

    bind = bind_or_session
    if isinstance(bind, _Session):
        bind = bind.get_bind()
    ReportBase.metadata.create_all(bind=bind, checkfirst=True)
    _ensure_report_columns(bind)


def _ensure_report_columns(bind: Engine | Connection) -> None:
    """Add backward-compatible report artifact columns that create_all cannot add."""
    inspector = inspect(bind)
    if not inspector.has_table("report_artifacts"):
        return

    json_type = "JSONB" if bind.dialect.name == "postgresql" else "JSON"
    columns = {column["name"] for column in inspector.get_columns("report_artifacts")}
    ddl: list[str] = []
    if "storage_backend" not in columns:
        ddl.append("ALTER TABLE report_artifacts ADD COLUMN storage_backend VARCHAR(32) DEFAULT 'local_fs'")
    if "byte_size" not in columns:
        ddl.append("ALTER TABLE report_artifacts ADD COLUMN byte_size INTEGER")
    if "source_refs" not in columns:
        ddl.append(f"ALTER TABLE report_artifacts ADD COLUMN source_refs {json_type}")
    if "metadata" not in columns:
        ddl.append(f"ALTER TABLE report_artifacts ADD COLUMN metadata {json_type}")

    if not ddl:
        return

    if isinstance(bind, Engine):
        with bind.begin() as conn:
            for statement in ddl:
                conn.execute(text(statement))
        return

    for statement in ddl:
        bind.execute(text(statement))
