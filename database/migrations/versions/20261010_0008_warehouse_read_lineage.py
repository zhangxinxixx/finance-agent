"""Add immutable macro/candle lineage required by typed DWD readers."""

from alembic import op
import sqlalchemy as sa


revision = "20261010_0008"
down_revision = "20261010_0007"
branch_labels = None
depends_on = None


_CANDLE_COLUMNS = (
    sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("provider", sa.String(length=128), nullable=True),
    sa.Column("provider_symbol", sa.String(length=128), nullable=True),
    sa.Column("provider_timeframe", sa.String(length=64), nullable=True),
    sa.Column("instrument_type", sa.String(length=64), nullable=True),
    sa.Column("source_role", sa.String(length=64), nullable=True),
    sa.Column("source_url", sa.Text(), nullable=True),
    sa.Column("source_reference", sa.Text(), nullable=True),
    sa.Column("reference_status", sa.String(length=64), nullable=True),
    sa.Column("evidence_scope", sa.String(length=64), nullable=True),
    sa.Column("source_tier", sa.String(length=64), nullable=True),
    sa.Column("identity_guard", sa.String(length=64), nullable=True),
)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    macro_columns = {column["name"] for column in inspector.get_columns("dwh_fact_macro")}
    candle_columns = {column["name"] for column in inspector.get_columns("dwh_fact_candle")}
    macro_indexes = {index["name"] for index in inspector.get_indexes("dwh_fact_macro")}
    candle_indexes = {index["name"] for index in inspector.get_indexes("dwh_fact_candle")}

    if "source_url" not in macro_columns:
        op.add_column("dwh_fact_macro", sa.Column("source_url", sa.Text(), nullable=True))
    for column in _CANDLE_COLUMNS:
        if column.name not in candle_columns:
            op.add_column("dwh_fact_candle", column)

    if "ix_dwh_macro_source_record" not in macro_indexes:
        op.create_index("ix_dwh_macro_source_record", "dwh_fact_macro", ["source_record_id"])
    if "ix_dwh_macro_pit" not in macro_indexes:
        op.create_index(
            "ix_dwh_macro_pit",
            "dwh_fact_macro",
            ["metric_id", "date_key", "retrieved_at", "id"],
        )
    if "ix_dwh_candle_source_record" not in candle_indexes:
        op.create_index("ix_dwh_candle_source_record", "dwh_fact_candle", ["source_record_id"])
    if "ix_dwh_candle_pit" not in candle_indexes:
        op.create_index(
            "ix_dwh_candle_pit",
            "dwh_fact_candle",
            [
                "asset_id",
                "source_id",
                "timeframe",
                "open_time",
                "retrieved_at",
                "updated_at",
                "created_at",
                "id",
            ],
        )


def downgrade():
    op.drop_index("ix_dwh_candle_pit", table_name="dwh_fact_candle")
    op.drop_index("ix_dwh_candle_source_record", table_name="dwh_fact_candle")
    op.drop_index("ix_dwh_macro_pit", table_name="dwh_fact_macro")
    op.drop_index("ix_dwh_macro_source_record", table_name="dwh_fact_macro")
    for column in reversed(_CANDLE_COLUMNS):
        op.drop_column("dwh_fact_candle", column.name)
    op.drop_column("dwh_fact_macro", "source_url")
