"""Add typed TradingView research-market DWD tables."""

from alembic import op

from database.models.warehouse_research_market import RESEARCH_MARKET_TABLES

revision = "20261010_0013"
down_revision = "20261010_0012"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    for table in RESEARCH_MARKET_TABLES:
        table.create(bind=bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    for table in reversed(RESEARCH_MARKET_TABLES):
        table.drop(bind=bind, checkfirst=True)
