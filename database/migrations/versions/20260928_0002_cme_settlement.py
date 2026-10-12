"""Add independent append-only CME Fed Funds settlement observations.

Revision ID: 20260928_0002
Revises: 20260704_0001
"""

from alembic import op

from database.models.cme_settlement import (
    CmeSettlementContract,
    CmeSettlementSnapshot,
    ensure_cme_settlement_tables,
)

revision = "20260928_0002"
down_revision = "20260704_0001"
branch_labels = None
depends_on = None


def upgrade():
    ensure_cme_settlement_tables(op.get_bind())


def downgrade():
    CmeSettlementContract.__table__.drop(op.get_bind(), checkfirst=True)
    CmeSettlementSnapshot.__table__.drop(op.get_bind(), checkfirst=True)
