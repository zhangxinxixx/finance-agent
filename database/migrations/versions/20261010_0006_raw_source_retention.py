"""Typed raw-source catalog and auditable retention events."""

from alembic import op

from database.models.raw_source import RawSourceBase

revision = "20261010_0006"
down_revision = "20261010_0005"
branch_labels = None
depends_on = None


def upgrade():
    RawSourceBase.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade():
    RawSourceBase.metadata.drop_all(bind=op.get_bind(), checkfirst=True)
