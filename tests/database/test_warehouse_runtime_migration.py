from __future__ import annotations

from alembic import command
from sqlalchemy import create_engine, inspect, text

from database.migrations.runtime import build_alembic_config


def test_0008_is_additive_preserves_unknown_history_and_downgrades(tmp_path):
    url = f"sqlite:///{tmp_path / 'warehouse-runtime.sqlite'}"
    config = build_alembic_config(url)
    command.upgrade(config, "20261010_0007")
    engine = create_engine(url)

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO dwh_dim_date "
                "(date_key, date, year, month, day, weekday) "
                "VALUES (20261009, '2026-10-09', 2026, 10, 9, 4)"
            )
        )
        connection.execute(text("INSERT INTO dwh_dim_source (source_key) VALUES ('fred')"))
        connection.execute(text("INSERT INTO dwh_dim_asset (code) VALUES ('XAUUSD')"))
        source_id = connection.scalar(text("SELECT id FROM dwh_dim_source WHERE source_key='fred'"))
        asset_id = connection.scalar(text("SELECT id FROM dwh_dim_asset WHERE code='XAUUSD'"))
        connection.execute(
            text(
                "INSERT INTO dwh_dim_metric (source_id, symbol, unit, frequency) "
                "VALUES (:source_id, 'DGS10', 'percent', 'daily')"
            ),
            {"source_id": source_id},
        )
        metric_id = connection.scalar(text("SELECT id FROM dwh_dim_metric WHERE symbol='DGS10'"))
        for dataset, cursor in (("macro", "m1"), ("candles", "c1")):
            connection.execute(
                text(
                    "INSERT INTO dwh_load_batch "
                    "(dataset, source_cursor, load_time, transform_version, processed, inserted, skipped, rejected, "
                    "status, audit_task_run_id, audit_task_step_id) "
                    "VALUES (:dataset, :cursor, '2026-10-10 00:00:00', 'test', 1, 1, 0, 0, "
                    "'loaded', :run_id, :step_id)"
                ),
                {"dataset": dataset, "cursor": cursor, "run_id": f"run-{dataset}", "step_id": f"step-{dataset}"},
            )
        macro_batch = connection.scalar(text("SELECT id FROM dwh_load_batch WHERE dataset='macro'"))
        candle_batch = connection.scalar(text("SELECT id FROM dwh_load_batch WHERE dataset='candles'"))
        connection.execute(
            text(
                "INSERT INTO dwh_fact_macro "
                "(batch_id, version_sha256, source_record_id, metric_id, date_key, value, unit, retrieved_at) "
                "VALUES (:batch, :version, 'macro-old', :metric, 20261009, 4.2, 'percent', NULL)"
            ),
            {"batch": macro_batch, "version": "a" * 64, "metric": metric_id},
        )
        connection.execute(
            text(
                "INSERT INTO dwh_fact_candle "
                "(batch_id, version_sha256, source_record_id, asset_id, source_id, date_key, timeframe, "
                "open_time, open, high, low, close, volume) "
                "VALUES (:batch, :version, 'candle-old', :asset, :source, 20261009, '5m', "
                "'2026-10-09 01:00:00', 3998, 4003, 3997, 4001, NULL)"
            ),
            {
                "batch": candle_batch,
                "version": "b" * 64,
                "asset": asset_id,
                "source": source_id,
            },
        )

    command.upgrade(config, "20261010_0008")
    inspector = inspect(engine)
    macro_columns = {column["name"] for column in inspector.get_columns("dwh_fact_macro")}
    candle_columns = {column["name"] for column in inspector.get_columns("dwh_fact_candle")}
    assert "source_url" in macro_columns
    assert {
        "retrieved_at",
        "created_at",
        "updated_at",
        "provider_symbol",
        "instrument_type",
        "source_role",
        "source_reference",
    } <= candle_columns
    assert {index["name"] for index in inspector.get_indexes("dwh_fact_macro")} >= {
        "ix_dwh_macro_source_record",
        "ix_dwh_macro_pit",
    }
    assert {index["name"] for index in inspector.get_indexes("dwh_fact_candle")} >= {
        "ix_dwh_candle_source_record",
        "ix_dwh_candle_pit",
    }
    with engine.connect() as connection:
        macro = connection.execute(text("SELECT source_record_id, source_url FROM dwh_fact_macro")).one()
        candle = connection.execute(
            text("SELECT source_record_id, retrieved_at, provider_symbol FROM dwh_fact_candle")
        ).one()
    assert macro == ("macro-old", None)
    assert candle == ("candle-old", None, None)

    command.downgrade(config, "20261010_0007")
    inspector = inspect(engine)
    assert "source_url" not in {column["name"] for column in inspector.get_columns("dwh_fact_macro")}
    assert "provider_symbol" not in {column["name"] for column in inspector.get_columns("dwh_fact_candle")}
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT source_record_id FROM dwh_fact_macro")) == "macro-old"
        assert connection.scalar(text("SELECT source_record_id FROM dwh_fact_candle")) == "candle-old"

    command.upgrade(config, "20261010_0008")
    engine.dispose()
