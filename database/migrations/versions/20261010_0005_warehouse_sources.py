"""Typed facts for collected CME, FedWatch, settlement, and news sources."""

from alembic import op

from database.models.warehouse_sources import SOURCE_WAREHOUSE_TABLES

revision = "20261010_0005"
down_revision = "20261005_0004"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    for table in SOURCE_WAREHOUSE_TABLES:
        table.create(bind=bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    for table in reversed(SOURCE_WAREHOUSE_TABLES):
        table.drop(bind=bind, checkfirst=True)
