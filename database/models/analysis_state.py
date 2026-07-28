"""Portable persistent analysis-state models.

``AnalysisState`` and ``AnalysisTransition`` are append-only. Only
``AnalysisStateHead`` is mutable, and it points exclusively at the current
canonical state for one asset. ``task_run_id`` is a logical reference because
TaskRun and analysis models intentionally use separate SQLAlchemy metadata.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.analysis import AnalysisBase, JSONB_COMPAT


class CanaryApproval(AnalysisBase):
    """Mutable, server-issued authority for one scoped canary materialization."""

    __tablename__ = "canary_approvals"
    __table_args__ = (
        CheckConstraint(
            "state_scope IN ('intraday', 'daily_close', 'weekly_fundamental')",
            name="ck_canary_approvals_state_scope",
        ),
        CheckConstraint(
            "status IN ('active', 'consumed', 'revoked')",
            name="ck_canary_approvals_status",
        ),
        CheckConstraint(
            "trade_date IS NOT NULL OR run_id IS NOT NULL",
            name="ck_canary_approvals_binding",
        ),
        CheckConstraint(
            "expires_at > approved_at",
            name="ck_canary_approvals_valid_window",
        ),
        Index("ix_canary_approvals_status_expires", "status", "expires_at"),
        Index("ix_canary_approvals_asset_scope_date", "asset", "state_scope", "trade_date"),
        Index("ix_canary_approvals_run_id", "run_id"),
        Index("ix_canary_approvals_consumed_by_run_id", "consumed_by_run_id"),
    )

    approval_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, doc="Server-issued immutable approval identity"
    )
    asset: Mapped[str] = mapped_column(String(32), nullable=False, doc="Approved asset")
    state_scope: Mapped[str] = mapped_column(String(32), nullable=False, doc="Approved state scope")
    trade_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, doc="Optional exact approved trade date"
    )
    run_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, doc="Optional exact approved TaskRun identity"
    )
    approved_by: Mapped[str] = mapped_column(String(128), nullable=False, doc="Approver identity")
    approved_role: Mapped[str] = mapped_column(String(64), nullable=False, doc="Approver authorization role")
    approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, doc="Approval issue time in UTC"
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, doc="Exclusive approval expiry time in UTC"
    )
    approval_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, doc="SHA256 over immutable grant content"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", doc="active, consumed, or revoked"
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, doc="UTC time of successful canonical consumption"
    )
    consumed_by_run_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, doc="TaskRun that atomically consumed this approval"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CanaryAttempt(AnalysisBase):
    """Durable lifecycle record for one logical canary sidecar attempt."""

    __tablename__ = "canary_attempts"
    __table_args__ = (
        CheckConstraint("attempt_no IN (0, 1)", name="ck_canary_attempts_attempt_no"),
        CheckConstraint(
            "status IN ('started', 'audit_persisted', 'recompute_authorized', 'terminal', 'failed')",
            name="ck_canary_attempts_status",
        ),
        UniqueConstraint("run_id", "attempt_no", name="uq_canary_attempts_run_attempt"),
        Index("ix_canary_attempts_run_status", "run_id", "status"),
        Index("ix_canary_attempts_approval_id", "approval_id"),
        Index("ix_canary_attempts_updated_at", "updated_at"),
    )

    attempt_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()), doc="Stable logical attempt identity"
    )
    run_id: Mapped[str] = mapped_column(String(255), nullable=False, doc="TaskRun identity")
    approval_id: Mapped[str] = mapped_column(String(64), nullable=False, doc="Persistent approval identity")
    approval_hash: Mapped[str] = mapped_column(String(64), nullable=False, doc="Immutable approval grant hash")
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, doc="0 initially; 1 is the sole CAS recompute")
    asset: Mapped[str] = mapped_column(String(32), nullable=False, doc="Canary asset")
    state_scope: Mapped[str] = mapped_column(String(32), nullable=False, doc="Scoped state machine")
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, doc="Canary trade date")
    requested_canonical_state_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, doc="Canonical predecessor bound when the attempt started"
    )
    expected_head_version: Mapped[int | None] = mapped_column(
        Integer, nullable=True, doc="Expected scoped head version bound when the attempt started"
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="started", doc="Durable lifecycle state")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, doc="UTC start time")
    context_bundle_id: Mapped[str | None] = mapped_column(String(255), nullable=True, doc="Audited Bundle identity")
    context_bundle_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, doc="Audited Bundle SHA256")
    authority_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, doc="Audited authority SHA256")
    audit_artifact_path: Mapped[str | None] = mapped_column(Text, nullable=True, doc="Content-addressed attempt audit path")
    audit_artifact_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, doc="Attempt audit SHA256")
    terminal_artifact_path: Mapped[str | None] = mapped_column(Text, nullable=True, doc="Committed terminal artifact path")
    terminal_artifact_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, doc="Committed terminal SHA256")
    terminal_status: Mapped[str | None] = mapped_column(String(32), nullable=True, doc="CanaryMaterializationResult status")
    failure_code: Mapped[str | None] = mapped_column(String(128), nullable=True, doc="Stable fail-closed code")
    failure_detail: Mapped[str | None] = mapped_column(Text, nullable=True, doc="Bounded diagnostic detail")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AnalysisState(AnalysisBase):
    """Immutable candidate or accepted analysis-state snapshot."""

    __tablename__ = "analysis_states"
    __table_args__ = (
        CheckConstraint(
            "state_scope IN ('intraday', 'daily_close', 'weekly_fundamental')",
            name="ck_analysis_states_state_scope",
        ),
        Index("ix_analysis_states_asset_scope_as_of", "asset", "state_scope", "as_of"),
        Index("ix_analysis_states_previous_state_id", "previous_state_id"),
        Index("ix_analysis_states_task_run_id", "task_run_id"),
        Index("ix_analysis_states_quality", "quality_gate_action", "publish_allowed"),
        Index("ix_analysis_states_content_hash", "content_hash"),
        Index("ix_analysis_states_payload_gin", "payload", postgresql_using="gin"),
        Index("ix_analysis_states_source_refs_gin", "source_refs", postgresql_using="gin"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False, doc="Stable state contract version")
    asset: Mapped[str] = mapped_column(String(32), nullable=False)
    state_scope: Mapped[str] = mapped_column(String(32), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    previous_state_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("analysis_states.id", ondelete="RESTRICT"), nullable=True
    )
    task_run_id: Mapped[str] = mapped_column(String(255), nullable=False, doc="Logical TaskRun identifier")
    analysis_snapshot_db_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("analysis_snapshots.id", ondelete="RESTRICT"), nullable=True
    )
    final_analysis_result_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("final_analysis_results.id", ondelete="RESTRICT"), nullable=True
    )
    quality_gate_action: Mapped[str] = mapped_column(String(32), nullable=False)
    publish_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    accepted_output_source: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    accepted_output_agent_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    accepted_output_snapshot_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    input_snapshot_ids: Mapped[dict] = mapped_column(JSONB_COMPAT, nullable=False, default=dict)
    source_refs: Mapped[list] = mapped_column(JSONB_COMPAT, nullable=False, default=list)
    evidence_cursors: Mapped[dict] = mapped_column(JSONB_COMPAT, nullable=False, default=dict)
    payload: Mapped[dict] = mapped_column(JSONB_COMPAT, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    previous_state: Mapped["AnalysisState | None"] = relationship(
        "AnalysisState", remote_side="AnalysisState.id", foreign_keys=[previous_state_id]
    )


class AnalysisStateHead(AnalysisBase):
    """Mutable compare-and-swap pointer to one asset's canonical state."""

    __tablename__ = "analysis_state_heads"
    __table_args__ = (
        CheckConstraint(
            "state_scope IN ('intraday', 'daily_close', 'weekly_fundamental')",
            name="ck_analysis_state_heads_state_scope",
        ),
        UniqueConstraint("asset", "state_scope", name="uq_analysis_state_heads_asset_scope"),
        UniqueConstraint("canonical_state_id", name="uq_analysis_state_heads_state"),
        Index("ix_analysis_state_heads_asset_scope_version", "asset", "state_scope", "version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    asset: Mapped[str] = mapped_column(String(32), nullable=False)
    state_scope: Mapped[str] = mapped_column(String(32), nullable=False)
    canonical_state_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_states.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    canonical_state: Mapped[AnalysisState] = relationship("AnalysisState", foreign_keys=[canonical_state_id])


class AnalysisTransition(AnalysisBase):
    """Immutable explanation connecting a state to its predecessor."""

    __tablename__ = "analysis_transitions"
    __table_args__ = (
        CheckConstraint(
            "state_scope IN ('intraday', 'daily_close', 'weekly_fundamental')",
            name="ck_analysis_transitions_state_scope",
        ),
        UniqueConstraint("to_state_id", name="uq_analysis_transitions_to_state"),
        Index(
            "ix_analysis_transitions_asset_scope_created",
            "asset",
            "state_scope",
            "created_at",
        ),
        Index("ix_analysis_transitions_from_state_id", "from_state_id"),
        Index("ix_analysis_transitions_task_run_id", "task_run_id"),
        Index("ix_analysis_transitions_content_hash", "content_hash"),
        Index("ix_analysis_transitions_actions_gin", "actions", postgresql_using="gin"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    asset: Mapped[str] = mapped_column(String(32), nullable=False)
    state_scope: Mapped[str] = mapped_column(String(32), nullable=False)
    from_state_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("analysis_states.id", ondelete="RESTRICT"), nullable=True
    )
    to_state_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_states.id", ondelete="RESTRICT"), nullable=False
    )
    task_run_id: Mapped[str] = mapped_column(String(255), nullable=False, doc="Logical TaskRun identifier")
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    actions: Mapped[list] = mapped_column(JSONB_COMPAT, nullable=False)
    evidence_refs: Mapped[list] = mapped_column(JSONB_COMPAT, nullable=False, default=list)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _reject_immutable_write(_mapper, _connection, target) -> None:
    raise RuntimeError(f"{type(target).__name__} is append-only")


for _immutable_model in (AnalysisState, AnalysisTransition):
    event.listen(_immutable_model, "before_update", _reject_immutable_write)
    event.listen(_immutable_model, "before_delete", _reject_immutable_write)
