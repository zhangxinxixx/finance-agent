"""Add typed DWD news context and child tables.

Revision ID: 20261010_0010
Revises: 20261010_0009
"""

from alembic import op

from database.models.warehouse_news import NEWS_CONTEXT_TABLES

revision = "20261010_0010"
down_revision = "20261010_0009"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    for table in NEWS_CONTEXT_TABLES:
        table.create(bind=bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    for table in reversed(NEWS_CONTEXT_TABLES):
        table.drop(bind=bind, checkfirst=True)
