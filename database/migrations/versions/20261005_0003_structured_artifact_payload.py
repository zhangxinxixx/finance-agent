"""Add validated structured bodies to the existing artifact registry.

Revision ID: 20261005_0003
Revises: 20260928_0002
"""

from alembic import op

from database.models.execution import ensure_execution_tables

revision = "20261005_0003"
down_revision = "20260928_0002"
branch_labels = None
depends_on = None


def upgrade():
    ensure_execution_tables(op.get_bind())


def downgrade():
    # Dropping persisted business bodies needs an explicit data-retention plan.
    raise RuntimeError("structured_artifact_downgrade_requires_data_retention_plan")
