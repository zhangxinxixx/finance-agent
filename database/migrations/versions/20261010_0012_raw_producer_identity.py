"""Preserve named historical producer IDs as well as UUID task IDs."""
from alembic import op
import sqlalchemy as sa

revision = "20261010_0012"
down_revision = "20261010_0011"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("raw_source_file") as batch:
        batch.alter_column("producer_run_id", existing_type=sa.String(36), type_=sa.String(255), existing_nullable=True)


def downgrade():
    too_long = op.get_bind().scalar(sa.text(
        "SELECT COUNT(*) FROM raw_source_file WHERE length(producer_run_id) > 36"
    ))
    if too_long:
        raise RuntimeError("Cannot shrink raw-source producer identities; restore the verified backup")
    with op.batch_alter_table("raw_source_file") as batch:
        batch.alter_column("producer_run_id", existing_type=sa.String(255), type_=sa.String(36), existing_nullable=True)
