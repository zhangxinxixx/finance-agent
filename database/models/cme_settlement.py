"""Append-only collection events and contract observations on task Base."""

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from database.models.analysis import JSONB_COMPAT
from database.models.task import Base


class CmeSettlementSnapshot(Base):
    __tablename__ = "cme_settlement_snapshot"
    __table_args__ = (
        Index("ix_cme_settlement_trade_observed", "trade_date", "observed_at"),
        CheckConstraint(
            "settlement_status IS NULL OR settlement_status IN ('FINAL','PRELIMINARY')", name="ck_cme_settlement_phase"
        ),
    )
    snapshot_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    settlement_status: Mapped[str | None] = mapped_column(String(16))
    data_status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB_COMPAT, nullable=False)


class CmeSettlementContract(Base):
    __tablename__ = "cme_settlement_contract"
    __table_args__ = (
        CheckConstraint("volume IS NULL OR volume >= 0", name="ck_cme_settlement_volume"),
        CheckConstraint("open_interest IS NULL OR open_interest >= 0", name="ck_cme_settlement_oi"),
        Index("ix_cme_settlement_contract_month", "contract_month"),
    )
    snapshot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cme_settlement_snapshot.snapshot_id"), primary_key=True
    )
    contract: Mapped[str] = mapped_column(String(16), primary_key=True)
    contract_month: Mapped[date] = mapped_column(Date, nullable=False)
    settle: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[int | None] = mapped_column(Integer)
    open_interest: Mapped[int | None] = mapped_column(Integer)


def ensure_cme_settlement_tables(bind_or_session):
    bind = bind_or_session.get_bind() if hasattr(bind_or_session, "get_bind") else bind_or_session
    Base.metadata.create_all(bind, tables=[CmeSettlementSnapshot.__table__, CmeSettlementContract.__table__])
