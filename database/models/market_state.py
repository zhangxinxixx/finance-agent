"""Append-only S1–SX research state ledger; never a Gold trading authority."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.models.analysis import AnalysisBase, JSONB_COMPAT


class MarketStateSnapshot(AnalysisBase):
    __tablename__ = "market_state_snapshot"
    __table_args__ = (
        UniqueConstraint("namespace", "proposal_key", name="uq_market_state_proposal"),
        UniqueConstraint("namespace", "accepted_proposal_id", name="uq_market_state_acceptance"),
        Index("ix_market_state_asset_time", "asset", "as_of"),
    )

    state_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    namespace: Mapped[str] = mapped_column(String(64), nullable=False)
    asset: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    proposal_key: Mapped[str | None] = mapped_column(String(255))
    accepted_proposal_id: Mapped[str | None] = mapped_column(String(100), ForeignKey("market_state_snapshot.state_id"))
    predecessor_id: Mapped[str | None] = mapped_column(String(100), ForeignKey("market_state_snapshot.state_id"))
    source_snapshot_id: Mapped[str] = mapped_column(String(255), ForeignKey("analysis_snapshots.snapshot_id"), nullable=False)
    run_id: Mapped[str] = mapped_column(String(255), nullable=False)
    accepted_state: Mapped[str | None] = mapped_column(String(8))
    candidate_state: Mapped[str | None] = mapped_column(String(8))
    previous_state: Mapped[str | None] = mapped_column(String(8))
    transition_status: Mapped[str] = mapped_column(String(32), nullable=False)
    calculation_version: Mapped[str] = mapped_column(String(64), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict] = mapped_column(JSONB_COMPAT, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class MarketStateHead(AnalysisBase):
    __tablename__ = "market_state_heads"
    namespace: Mapped[str] = mapped_column(String(64), primary_key=True)
    asset: Mapped[str] = mapped_column(String(32), primary_key=True)
    state_id: Mapped[str | None] = mapped_column(String(100), ForeignKey("market_state_snapshot.state_id"))
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


def ensure_research_state_tables(bind):
    """Add only these two tables; do not alter existing schema or revision history."""
    MarketStateSnapshot.__table__.create(bind=bind, checkfirst=True)
    MarketStateHead.__table__.create(bind=bind, checkfirst=True)
