"""Execution observability models.

P0 Run Observability Core:
- TaskRun remains the canonical run object.
- TaskStep remains the canonical task/step object.
- ExecutionEvent adds append-only execution timeline events.
- RunArtifact adds a normalized artifact registry for run/task outputs.

This module is intentionally independent from database.models.task.Base so it can be
created additively without changing the existing task metadata/state machine.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, func, inspect, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class ExecutionBase(DeclarativeBase):
    """Portable base for execution observability tables."""

    pass


class ExecutionEvent(ExecutionBase):
    """Append-only event stream for a TaskRun / TaskStep execution.

    Note:
        `run_id` maps to TaskRun.id.
        `task_id` maps to TaskStep.id when the event is step-scoped.
    """

    __tablename__ = "execution_events"
    __table_args__ = (
        Index("ix_execution_events_run_created", "run_id", "created_at"),
        Index("ix_execution_events_task_created", "task_id", "created_at"),
        Index("ix_execution_events_type", "event_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True, doc="JSON-encoded event payload")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class RunArtifact(ExecutionBase):
    """Normalized artifact registry for run/task outputs.

    Existing TaskStep.output_ref / output_refs / artifact_refs remain supported.
    This table is the forward-looking registry for timeline and lineage views.
    """

    __tablename__ = "run_artifacts"
    __table_args__ = (
        Index("ix_run_artifacts_run_created", "run_id", "created_at"),
        Index("ix_run_artifacts_task_created", "task_id", "created_at"),
        Index("ix_run_artifacts_type", "artifact_type"),
        Index("ix_run_artifacts_path", "file_path"),
    )

    artifact_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    storage_backend: Mapped[str] = mapped_column(String(32), nullable=False, server_default="local_fs")
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_refs: Mapped[str | None] = mapped_column(Text, nullable=True, doc="JSON-encoded source refs")
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True, doc="JSON-encoded artifact metadata")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def ensure_execution_tables(bind_or_session) -> None:
    """Create execution observability tables and additive columns if missing."""
    from sqlalchemy.orm import Session as _Session

    bind = bind_or_session
    if isinstance(bind, _Session):
        bind = bind.get_bind()
    ExecutionBase.metadata.create_all(bind=bind, checkfirst=True)
    _ensure_execution_columns(bind)


def _ensure_execution_columns(bind: Engine | Connection) -> None:
    """Add backward-compatible columns that create_all cannot add to existing tables."""
    inspector = inspect(bind)
    existing = {
        table: {column["name"] for column in inspector.get_columns(table)}
        for table in ("execution_events", "run_artifacts")
        if inspector.has_table(table)
    }
    ddl: list[str] = []

    if "execution_events" in existing:
        columns = existing["execution_events"]
        if "payload" not in columns:
            ddl.append("ALTER TABLE execution_events ADD COLUMN payload TEXT")
        if "created_at" not in columns:
            ddl.append("ALTER TABLE execution_events ADD COLUMN created_at TIMESTAMP")

    if "run_artifacts" in existing:
        columns = existing["run_artifacts"]
        if "storage_backend" not in columns:
            ddl.append("ALTER TABLE run_artifacts ADD COLUMN storage_backend VARCHAR(32) DEFAULT 'local_fs'")
        if "sha256" not in columns:
            ddl.append("ALTER TABLE run_artifacts ADD COLUMN sha256 VARCHAR(64)")
        if "source_refs" not in columns:
            ddl.append("ALTER TABLE run_artifacts ADD COLUMN source_refs TEXT")
        if "metadata_json" not in columns:
            ddl.append("ALTER TABLE run_artifacts ADD COLUMN metadata_json TEXT")
        if "created_at" not in columns:
            ddl.append("ALTER TABLE run_artifacts ADD COLUMN created_at TIMESTAMP")

    if not ddl:
        return

    if isinstance(bind, Engine):
        with bind.begin() as conn:
            for statement in ddl:
                conn.execute(text(statement))
        return

    for statement in ddl:
        bind.execute(text(statement))
