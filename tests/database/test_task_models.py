from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

from database.models.task import _build_postgres_enum_value_ddl, ensure_task_tables


def test_ensure_task_tables_adds_state_machine_columns_to_existing_tables():
    engine = create_engine("sqlite:///:memory:")

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE task_runs (
                    id CHAR(32) PRIMARY KEY,
                    name VARCHAR(128) NOT NULL,
                    status VARCHAR(32) NOT NULL,
                    error TEXT,
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE task_steps (
                    id CHAR(32) PRIMARY KEY,
                    task_run_id CHAR(32) NOT NULL,
                    name VARCHAR(128) NOT NULL,
                    status VARCHAR(32) NOT NULL,
                    error TEXT,
                    started_at DATETIME,
                    finished_at DATETIME,
                    created_at DATETIME,
                    step_order INTEGER,
                    input_json TEXT,
                    output_json TEXT,
                    error_json TEXT,
                    retryable BOOLEAN NOT NULL DEFAULT 1,
                    blocked_reason TEXT
                )
                """
            )
        )

    ensure_task_tables(engine)

    columns = {
        table: {column["name"] for column in inspect(engine).get_columns(table)}
        for table in ("task_runs", "task_steps")
    }
    assert "trade_date" in columns["task_runs"]
    assert {"input_hash", "output_ref", "error_type", "retry_count"} <= columns["task_steps"]


def test_postgres_enum_migration_adds_new_task_status_values():
    assert _build_postgres_enum_value_ddl({"taskstatus", "stepstatus"}) == [
        "ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'blocked'",
        "ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'cancelled'",
        "ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'stale'",
        "ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'degraded'",
        "ALTER TYPE stepstatus ADD VALUE IF NOT EXISTS 'blocked'",
    ]
