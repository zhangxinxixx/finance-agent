"""Keep source-reported macro comparison values in typed DWD revisions."""
from alembic import op
import sqlalchemy as sa

revision = "20261010_0011"
down_revision = "20261010_0010"
branch_labels = None
depends_on = None


def upgrade():
    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("dwh_fact_macro")}
    for column in (
        sa.Column("previous_value", sa.Numeric(38, 12), nullable=True),
        sa.Column("reference_period", sa.String(64), nullable=True),
        sa.Column("previous_reference_period", sa.String(64), nullable=True),
    ):
        if column.name not in existing:
            op.add_column("dwh_fact_macro", column)


def downgrade():
    for name in ("previous_reference_period", "reference_period", "previous_value"):
        op.drop_column("dwh_fact_macro", name)
