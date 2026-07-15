"""Portable persistent analysis-state models.

``AnalysisState`` and ``AnalysisTransition`` are append-only. Only
``AnalysisStateHead`` is mutable, and it points exclusively at the current
canonical state for one asset. ``task_run_id`` is a logical reference because
TaskRun and analysis models intentionally use separate SQLAlchemy metadata.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, event, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.analysis import AnalysisBase, JSONB_COMPAT


class AnalysisState(AnalysisBase):
    """Immutable candidate or accepted analysis-state snapshot."""

    __tablename__ = "analysis_states"
    __table_args__ = (
        Index("ix_analysis_states_asset_as_of", "asset", "as_of"),
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
        UniqueConstraint("asset", name="uq_analysis_state_heads_asset"),
        UniqueConstraint("canonical_state_id", name="uq_analysis_state_heads_state"),
        Index("ix_analysis_state_heads_asset_version", "asset", "version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    asset: Mapped[str] = mapped_column(String(32), nullable=False)
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
        UniqueConstraint("to_state_id", name="uq_analysis_transitions_to_state"),
        Index("ix_analysis_transitions_asset_created", "asset", "created_at"),
        Index("ix_analysis_transitions_from_state_id", "from_state_id"),
        Index("ix_analysis_transitions_task_run_id", "task_run_id"),
        Index("ix_analysis_transitions_content_hash", "content_hash"),
        Index("ix_analysis_transitions_actions_gin", "actions", postgresql_using="gin"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    asset: Mapped[str] = mapped_column(String(32), nullable=False)
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
