"""Playbook template registry persistence models."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Index, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database.models.analysis import AnalysisBase


JSONB_COMPAT = JSON().with_variant(JSONB, "postgresql")


class PlaybookTemplate(AnalysisBase):
    """Append-only playbook template registry entry."""

    __tablename__ = "playbook_templates"
    __table_args__ = (
        UniqueConstraint("playbook_id", "version", name="uq_playbook_templates_playbook_version"),
        Index("ix_playbook_templates_playbook_id", "playbook_id"),
        Index("ix_playbook_templates_status", "status"),
        Index("ix_playbook_templates_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    playbook_id: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    conditions: Mapped[list] = mapped_column(JSONB_COMPAT, nullable=False, default=list)
    actions: Mapped[list] = mapped_column(JSONB_COMPAT, nullable=False, default=list)
    invalidations: Mapped[list] = mapped_column(JSONB_COMPAT, nullable=False, default=list)
    source_refs: Mapped[list] = mapped_column(JSONB_COMPAT, nullable=False, default=list)
    last_validated: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    update_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    audit_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), server_default=func.now(), onupdate=func.now(), nullable=False
    )
