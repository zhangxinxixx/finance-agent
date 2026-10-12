from sqlalchemy import JSON, LargeBinary, create_engine, inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from database.models.warehouse import WarehouseBase
from database.models.warehouse_sources import SOURCE_WAREHOUSE_TABLES


ORIGINAL_TABLES = {
    "dwh_dim_date",
    "dwh_dim_source",
    "dwh_dim_asset",
    "dwh_dim_metric",
    "dwh_dim_producer_run",
    "dwh_load_batch",
    "dwh_fact_macro",
    "dwh_fact_candle",
    "dwh_fact_news_event",
    "dwh_fact_news_trigger",
    "dwh_bridge_event_asset",
    "dwh_bridge_trigger_asset",
    "dwh_event_source_ref",
    "dwh_trigger_source_ref",
    "dwh_trigger_action",
    "dwh_trigger_reason",
    "dwh_trigger_topic",
}


def test_source_schema_extends_exact_original_contract_with_typed_tables():
    assert set(WarehouseBase.metadata.tables) == ORIGINAL_TABLES | {table.name for table in SOURCE_WAREHOUSE_TABLES} | {
        "dwh_ingestion_cursor", "dwh_batch_source_file",
        "dwh_fedwatch_context", "dwh_fedwatch_source_evidence",
        "dwh_news_item_context", "dwh_news_article_paragraph", "dwh_news_relevance_asset_tag",
        "dwh_news_relevance_topic_tag", "dwh_news_item_source_ref",
        "dwh_research_market_batch", "dwh_research_market_scanner_quote", "dwh_research_market_chart_series",
        "dwh_research_market_bar", "dwh_research_market_batch_source_ref",
        "dwh_research_market_scanner_source_ref", "dwh_research_market_series_source_ref",
        "dwh_research_market_limitation",
    }
    assert len(ORIGINAL_TABLES) == 17
    assert {table.name for table in SOURCE_WAREHOUSE_TABLES} == {
        "dwh_fact_cme_option",
        "dwh_fact_fedwatch_probability",
        "dwh_fact_fedwatch_futures",
        "dwh_fact_fed_funds_settlement",
        "dwh_fact_news_item",
    }
    for table in SOURCE_WAREHOUSE_TABLES:
        assert str(CreateTable(table).compile(dialect=postgresql.dialect()))
        assert not any(
            isinstance(column.type, (JSON, LargeBinary))
            or column.name in {"payload", "raw_payload", "metadata", "value_json"}
            for column in table.columns
        )
        assert {fk.column.table.metadata for fk in table.foreign_keys} == {WarehouseBase.metadata}


def test_0005_table_scope_can_upgrade_and_downgrade_without_old_table_loss():
    engine = create_engine("sqlite:///:memory:")
    old_tables = [WarehouseBase.metadata.tables[name] for name in ORIGINAL_TABLES]
    WarehouseBase.metadata.create_all(engine, tables=old_tables)
    for table in SOURCE_WAREHOUSE_TABLES:
        table.create(engine)
    assert set(inspect(engine).get_table_names()) == ORIGINAL_TABLES | {table.name for table in SOURCE_WAREHOUSE_TABLES}
    for table in reversed(SOURCE_WAREHOUSE_TABLES):
        table.drop(engine)
    assert set(inspect(engine).get_table_names()) == ORIGINAL_TABLES
    engine.dispose()
