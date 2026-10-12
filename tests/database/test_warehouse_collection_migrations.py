from alembic import command
from sqlalchemy import create_engine, inspect, text

from database.migrations.runtime import build_alembic_config


def test_warehouse_migrations_preserve_old_revision_boundary_and_data(tmp_path):
    url = f"sqlite:///{tmp_path / 'migration.sqlite'}"
    config = build_alembic_config(url)
    # Public databases retain their independent historical analysis branch.
    command.upgrade(config, "20260728_0005")
    command.upgrade(config, "20261005_0004")
    engine = create_engine(url)
    old_names = set(inspect(engine).get_table_names())
    assert "dwh_fact_macro" in old_names
    assert "dwh_fact_cme_option" not in old_names
    assert "dwh_ingestion_cursor" not in old_names
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO dwh_dim_asset (code) VALUES ('GC')"))
    command.upgrade(config, "head")
    names = set(inspect(engine).get_table_names())
    assert {"raw_source_file", "raw_source_load", "raw_source_load_batch", "raw_retention_event",
            "dwh_fact_cme_option", "dwh_fact_fedwatch_probability", "dwh_fact_fedwatch_futures",
            "dwh_fact_fed_funds_settlement", "dwh_fact_news_item", "dwh_ingestion_cursor"} <= names
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT code FROM dwh_dim_asset")) == "GC"
    command.downgrade(config, "20261005_0004")
    assert set(inspect(engine).get_table_names()) == old_names
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT code FROM dwh_dim_asset")) == "GC"
    command.upgrade(config, "head")
    engine.dispose()
