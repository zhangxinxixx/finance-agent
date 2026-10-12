"""Verify published database history survives the current warehouse release."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from database.migrations.runtime import build_alembic_config


@pytest.fixture
def isolated_postgres():
    value = os.getenv("ANALYSIS_MEMORY_POSTGRES_URL")
    if not value:
        pytest.skip("ANALYSIS_MEMORY_POSTGRES_URL is required for PostgreSQL migration checks")
    url = make_url(value)
    assert url.get_backend_name() == "postgresql"
    schema = f"public_upgrade_ci_{uuid4().hex}"
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    target = url.update_query_dict({"options": f"-csearch_path={schema}"}, append=False)
    engine = create_engine(target)
    try:
        yield engine, build_alembic_config(target.render_as_string(hide_password=False))
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()


def test_fresh_postgres_has_single_head_and_current_warehouse(isolated_postgres):
    engine, config = isolated_postgres
    command.upgrade(config, "head")
    assert {
        "analysis_snapshots", "analysis_states", "analysis_state_heads", "canary_approvals",
        "canary_attempts", "task_runs", "dwh_fact_macro", "dwh_fact_candle",
    } <= set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all() == [
            "20261012_0014"
        ]
    command.upgrade(config, "head")


@pytest.mark.parametrize("previous_revision", ["20260728_0005", "20261010_0013"])
def test_public_and_warehouse_heads_upgrade_without_losing_records(isolated_postgres, previous_revision):
    engine, config = isolated_postgres
    command.upgrade(config, previous_revision)
    historical_state = previous_revision == "20260728_0005"
    if historical_state:
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO analysis_states "
                "(id, schema_version, asset, state_scope, as_of, task_run_id, quality_gate_action, "
                "publish_allowed, accepted_output_source, input_snapshot_ids, source_refs, "
                "evidence_cursors, payload, content_hash) VALUES "
                "('historical-state', '1.1', 'XAUUSD', 'daily_close', '2026-07-28 00:00:00+00', "
                "'historical-run', 'manual_review', false, 'none', '{}'::jsonb, '[]'::jsonb, "
                "'{}'::jsonb, '{\"asset\":\"XAUUSD\"}'::jsonb, :content_hash)"
            ), {"content_hash": "a" * 64})
            connection.execute(text(
                "INSERT INTO analysis_state_heads "
                "(id, asset, state_scope, canonical_state_id, version) VALUES "
                "('historical-head', 'XAUUSD', 'daily_close', 'historical-state', 7)"
            ))
        with engine.connect() as connection:
            before = connection.execute(text(
                "SELECT id, payload::text, content_hash FROM analysis_states WHERE id='historical-state'"
            )).one()
    else:
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO dwh_dim_source (source_key) VALUES ('historical-fred')"))
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20261012_0014"
        if historical_state:
            after = connection.execute(text(
                "SELECT id, payload::text, content_hash FROM analysis_states WHERE id='historical-state'"
            )).one()
            assert after == before
            assert connection.scalar(text(
                "SELECT version FROM analysis_state_heads WHERE id='historical-head'"
            )) == 7
        else:
            assert connection.scalar(text(
                "SELECT source_key FROM dwh_dim_source WHERE source_key='historical-fred'"
            )) == "historical-fred"
