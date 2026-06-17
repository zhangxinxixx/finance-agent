"""任务日志模型：task_runs 和 task_steps。

P4-03: 扩展步骤级 input/output/error payload 和状态语义
(blocked/cancelled/stale)，保持向后兼容。
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text, func, inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TaskStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"
    partial_success = "partial_success"
    degraded = "degraded"
    # P4-03: richer lifecycle states (additive, backward-compatible)
    blocked = "blocked"
    cancelled = "cancelled"
    stale = "stale"


class StepStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"
    skipped = "skipped"
    # P4-03: step-level blocked (when upstream failure blocks a step)
    blocked = "blocked"


class TaskRun(Base):
    __tablename__ = "task_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    task_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.pending, nullable=False)
    current_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    progress: Mapped[float | None] = mapped_column(Float, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    token_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    snapshot_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    final_result_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    trade_date: Mapped[str | None] = mapped_column(
        String(32), nullable=True, doc="Trade date for dedup (e.g. 2026-05-24)"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    steps: Mapped[list["TaskStep"]] = relationship(back_populates="task_run", cascade="all, delete-orphan")


class TaskStep(Base):
    __tablename__ = "task_steps"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("task_runs.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    task_kind: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[StepStatus] = mapped_column(Enum(StepStatus), default=StepStatus.pending, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    input_refs: Mapped[str | None] = mapped_column(Text, nullable=True, doc="Structured input artifact refs (JSON)")
    output_refs: Mapped[str | None] = mapped_column(Text, nullable=True, doc="Structured output artifact refs (JSON)")
    artifact_refs: Mapped[str | None] = mapped_column(
        Text, nullable=True, doc="Additional artifact refs emitted by this step (JSON)"
    )
    source_refs: Mapped[str | None] = mapped_column(Text, nullable=True, doc="Structured source refs (JSON)")
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── P4-03: step observability fields (all nullable, backward-compatible) ──
    step_order: Mapped[int | None] = mapped_column(Integer, nullable=True, doc="Canonical execution order index")
    input_json: Mapped[str | None] = mapped_column(Text, nullable=True, doc="Step input snapshot (JSON)")
    output_json: Mapped[str | None] = mapped_column(Text, nullable=True, doc="Step output / summary (JSON)")
    error_json: Mapped[str | None] = mapped_column(Text, nullable=True, doc="Structured error details (JSON)")
    retryable: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, doc="Whether this step can be retried"
    )
    blocked_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True, doc="Why this step is blocked (e.g. upstream failure)"
    )

    # ── State machine enhancement fields ──
    input_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, doc="SHA256 of input_json for idempotency check"
    )
    output_ref: Mapped[str | None] = mapped_column(Text, nullable=True, doc="Primary output artifact path")
    error_type: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        doc="Structured error class: network_timeout/parse_failure/data_unavailable/config_error",
    )
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, doc="Number of retries attempted")

    task_run: Mapped["TaskRun"] = relationship(back_populates="steps")


# ── Table creation helper ──


def ensure_task_tables(bind_or_session):
    """Create task tables and additive MVP columns if missing.

    Usage:
        ensure_task_tables(engine)        # from Engine
        ensure_task_tables(session)       # from Session (auto-resolves bind)
    """
    from sqlalchemy.orm import Session as _Session

    bind = bind_or_session
    if isinstance(bind, _Session):
        bind = bind.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)
    _ensure_task_columns(bind)


def _ensure_task_columns(bind: Engine | Connection) -> None:
    """Add backward-compatible columns that create_all cannot add to existing tables."""
    inspector = inspect(bind)
    existing = {
        table: {column["name"] for column in inspector.get_columns(table)}
        for table in ("task_runs", "task_steps")
        if inspector.has_table(table)
    }
    ddl: list[str] = []

    if "task_runs" in existing and "trade_date" not in existing["task_runs"]:
        ddl.append("ALTER TABLE task_runs ADD COLUMN trade_date VARCHAR(32)")
    if "task_runs" in existing:
        task_run_columns = existing["task_runs"]
        if "task_type" not in task_run_columns:
            ddl.append("ALTER TABLE task_runs ADD COLUMN task_type VARCHAR(128)")
        if "workspace_id" not in task_run_columns:
            ddl.append("ALTER TABLE task_runs ADD COLUMN workspace_id VARCHAR(128)")
        if "current_stage" not in task_run_columns:
            ddl.append("ALTER TABLE task_runs ADD COLUMN current_stage VARCHAR(64)")
        if "progress" not in task_run_columns:
            ddl.append("ALTER TABLE task_runs ADD COLUMN progress FLOAT")
        if "started_at" not in task_run_columns:
            ddl.append("ALTER TABLE task_runs ADD COLUMN started_at TIMESTAMP")
        if "ended_at" not in task_run_columns:
            ddl.append("ALTER TABLE task_runs ADD COLUMN ended_at TIMESTAMP")
        if "total_cost_usd" not in task_run_columns:
            ddl.append("ALTER TABLE task_runs ADD COLUMN total_cost_usd FLOAT")
        if "token_in" not in task_run_columns:
            ddl.append("ALTER TABLE task_runs ADD COLUMN token_in INTEGER")
        if "token_out" not in task_run_columns:
            ddl.append("ALTER TABLE task_runs ADD COLUMN token_out INTEGER")
        if "snapshot_id" not in task_run_columns:
            ddl.append("ALTER TABLE task_runs ADD COLUMN snapshot_id VARCHAR(128)")
        if "final_result_id" not in task_run_columns:
            ddl.append("ALTER TABLE task_runs ADD COLUMN final_result_id VARCHAR(128)")
        if "error_summary" not in task_run_columns:
            ddl.append("ALTER TABLE task_runs ADD COLUMN error_summary TEXT")

    if "task_steps" in existing:
        task_step_columns = existing["task_steps"]
        if "stage" not in task_step_columns:
            ddl.append("ALTER TABLE task_steps ADD COLUMN stage VARCHAR(64)")
        if "task_kind" not in task_step_columns:
            ddl.append("ALTER TABLE task_steps ADD COLUMN task_kind VARCHAR(64)")
        if "input_refs" not in task_step_columns:
            ddl.append("ALTER TABLE task_steps ADD COLUMN input_refs TEXT")
        if "output_refs" not in task_step_columns:
            ddl.append("ALTER TABLE task_steps ADD COLUMN output_refs TEXT")
        if "artifact_refs" not in task_step_columns:
            ddl.append("ALTER TABLE task_steps ADD COLUMN artifact_refs TEXT")
        if "source_refs" not in task_step_columns:
            ddl.append("ALTER TABLE task_steps ADD COLUMN source_refs TEXT")
        if "duration_ms" not in task_step_columns:
            ddl.append("ALTER TABLE task_steps ADD COLUMN duration_ms INTEGER")
        if "input_hash" not in task_step_columns:
            ddl.append("ALTER TABLE task_steps ADD COLUMN input_hash VARCHAR(64)")
        if "output_ref" not in task_step_columns:
            ddl.append("ALTER TABLE task_steps ADD COLUMN output_ref TEXT")
        if "error_type" not in task_step_columns:
            ddl.append("ALTER TABLE task_steps ADD COLUMN error_type VARCHAR(64)")
        if "retry_count" not in task_step_columns:
            ddl.append("ALTER TABLE task_steps ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0")

    if isinstance(bind, Engine):
        with bind.begin() as conn:
            enum_ddl = _postgres_enum_value_ddl(conn)
            if not ddl and not enum_ddl:
                return
            for statement in enum_ddl:
                conn.execute(text(statement))
            for statement in ddl:
                conn.execute(text(statement))
        return

    enum_ddl = _postgres_enum_value_ddl(bind)
    if not ddl and not enum_ddl:
        return

    for statement in enum_ddl:
        bind.execute(text(statement))
    for statement in ddl:
        bind.execute(text(statement))


def _postgres_enum_value_ddl(bind: Engine | Connection) -> list[str]:
    """Return additive enum DDL for existing PostgreSQL task status types."""
    if bind.dialect.name != "postgresql":
        return []
    enum_types = {
        row[0]
        for row in bind.execute(
            text("SELECT typname FROM pg_type WHERE typname IN ('taskstatus', 'stepstatus')")
        )
    }
    return _build_postgres_enum_value_ddl(enum_types)


def _build_postgres_enum_value_ddl(enum_types: set[str]) -> list[str]:
    ddl: list[str] = []
    if "taskstatus" in enum_types:
        ddl.extend(
            [
                "ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'blocked'",
                "ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'cancelled'",
                "ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'stale'",
                "ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'degraded'",
            ]
        )
    if "stepstatus" in enum_types:
        ddl.append("ALTER TYPE stepstatus ADD VALUE IF NOT EXISTS 'blocked'")
    return ddl
