"""Four-domain typed financial warehouse."""

from alembic import op
from database.models.warehouse import WarehouseBase

revision = "20261005_0004"
down_revision = "20261005_0003"
branch_labels = None
depends_on = None

# Keep this historical revision fixed when later modules join WarehouseBase.
TABLE_NAMES = (
    "dwh_dim_date", "dwh_dim_source", "dwh_dim_asset", "dwh_dim_metric", "dwh_dim_producer_run",
    "dwh_load_batch", "dwh_fact_macro", "dwh_fact_candle", "dwh_fact_news_event", "dwh_fact_news_trigger",
    "dwh_bridge_event_asset", "dwh_bridge_trigger_asset", "dwh_event_source_ref", "dwh_trigger_source_ref",
    "dwh_trigger_action", "dwh_trigger_reason", "dwh_trigger_topic",
)


def upgrade():
    WarehouseBase.metadata.create_all(bind=op.get_bind(), tables=[WarehouseBase.metadata.tables[name] for name in TABLE_NAMES], checkfirst=True)


def downgrade():
    WarehouseBase.metadata.drop_all(bind=op.get_bind(), tables=[WarehouseBase.metadata.tables[name] for name in TABLE_NAMES], checkfirst=True)
