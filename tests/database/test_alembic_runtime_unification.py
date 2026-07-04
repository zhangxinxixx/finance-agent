from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect


def _metadata_table_names(target_metadata) -> set[str]:
    metadatas = target_metadata if isinstance(target_metadata, (list, tuple)) else [target_metadata]
    return {table.name for metadata in metadatas for table in metadata.tables.values()}


def test_alembic_env_targets_all_runtime_metadata() -> None:
    from database.migrations.env import target_metadata

    table_names = _metadata_table_names(target_metadata)

    assert "analysis_snapshots" in table_names
    assert "task_runs" in table_names
    assert "execution_events" in table_names
    assert "report_items" in table_names
    assert "cme_option_rows" in table_names


def test_runtime_alembic_upgrade_creates_current_schema(tmp_path) -> None:
    from database.migrations.runtime import run_database_migrations

    db_path = tmp_path / "finance-agent.sqlite"
    database_url = f"sqlite:///{db_path}"

    run_database_migrations(database_url)

    inspector = inspect(create_engine(database_url))
    table_names = set(inspector.get_table_names())

    assert "analysis_snapshots" in table_names
    assert "task_runs" in table_names
    assert "execution_events" in table_names
    assert "report_items" in table_names
    assert "cme_option_rows" in table_names


@pytest.mark.anyio
async def test_api_startup_runs_alembic_upgrade_instead_of_runtime_table_patch(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api import main as api_main

    calls: list[str] = []

    monkeypatch.setattr(api_main, "_database_reachable", lambda: True)
    monkeypatch.setattr(api_main, "_should_skip_background_jobs", lambda: True)
    monkeypatch.setattr(api_main, "run_database_migrations", lambda *_args, **_kwargs: calls.append("alembic"), raising=False)

    def fail_runtime_patch(_db):
        raise AssertionError("startup must use Alembic, not runtime ensure_* DDL")

    monkeypatch.setattr(api_main, "ensure_task_tables", fail_runtime_patch, raising=False)
    monkeypatch.setattr(api_main, "ensure_execution_tables", fail_runtime_patch, raising=False)
    monkeypatch.setattr(api_main, "ensure_analysis_tables", fail_runtime_patch, raising=False)
    monkeypatch.setattr(api_main, "ensure_report_tables", fail_runtime_patch, raising=False)

    async with api_main.lifespan(api_main.app):
        pass

    assert calls == ["alembic"]
