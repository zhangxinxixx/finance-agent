"""Preserve named FedWatch context and official target evidence for DWS."""

from alembic import op

from database.models.warehouse_fedwatch import FedWatchContextFact, FedWatchSourceEvidence

revision = "20261010_0009"
down_revision = "20261010_0008"
branch_labels = None
depends_on = None


def upgrade():
    for model in (FedWatchContextFact, FedWatchSourceEvidence):
        model.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    for model in (FedWatchSourceEvidence, FedWatchContextFact):
        model.__table__.drop(op.get_bind(), checkfirst=True)
