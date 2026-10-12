"""Track bounded warehouse reconciliation without relying on UUID chronology."""

from alembic import op
from database.models.warehouse_sync import BatchSourceFile, WarehouseSyncCursor

revision = "20261010_0007"
down_revision = "20261010_0006"
branch_labels = None
depends_on = None


def upgrade():
    WarehouseSyncCursor.__table__.create(op.get_bind(), checkfirst=True)
    BatchSourceFile.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    BatchSourceFile.__table__.drop(op.get_bind(), checkfirst=True)
    WarehouseSyncCursor.__table__.drop(op.get_bind(), checkfirst=True)
