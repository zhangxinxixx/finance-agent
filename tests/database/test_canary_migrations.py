"""Focused lifecycle and fail-closed checks for Canary migrations 0004/0005."""

from __future__ import annotations

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text

from database.migrations.runtime import build_alembic_config
from database.models.analysis_state import CanaryApproval, CanaryAttempt


REVISION_0003 = "20260722_0003"
REVISION_0004 = "20260728_0004"
REVISION_0005 = "20260728_0005"


def _database(tmp_path, name: str):
    database_url = f"sqlite:///{tmp_path / name}"
    return build_alembic_config(database_url), create_engine(database_url)


def _version(engine) -> str:
    with engine.connect() as connection:
        return connection.scalar(text("SELECT version_num FROM alembic_version"))


def test_fresh_incremental_and_repeat_upgrade_reach_0005(tmp_path) -> None:
    fresh_config, fresh_engine = _database(tmp_path, "fresh.sqlite")
    command.upgrade(fresh_config, REVISION_0005)
    assert {"canary_approvals", "canary_attempts"} <= set(inspect(fresh_engine).get_table_names())
    assert _version(fresh_engine) == REVISION_0005
    command.upgrade(fresh_config, REVISION_0005)
    assert _version(fresh_engine) == REVISION_0005

    incremental_config, incremental_engine = _database(tmp_path, "incremental.sqlite")
    command.upgrade(incremental_config, REVISION_0003)
    assert {"canary_approvals", "canary_attempts"}.isdisjoint(
        inspect(incremental_engine).get_table_names()
    )
    command.upgrade(incremental_config, REVISION_0005)
    assert {"canary_approvals", "canary_attempts"} <= set(
        inspect(incremental_engine).get_table_names()
    )
    assert _version(incremental_engine) == REVISION_0005


def test_existing_complete_tables_are_explicitly_compatible(tmp_path) -> None:
    config, engine = _database(tmp_path, "compatible.sqlite")
    command.upgrade(config, REVISION_0003)
    assert {CanaryApproval.__tablename__, CanaryAttempt.__tablename__}.isdisjoint(
        inspect(engine).get_table_names()
    )
    CanaryApproval.__table__.create(engine)
    command.upgrade(config, REVISION_0004)
    assert _version(engine) == REVISION_0004

    CanaryAttempt.__table__.create(engine)
    command.upgrade(config, REVISION_0005)
    assert _version(engine) == REVISION_0005


@pytest.mark.parametrize(
    ("target_revision", "table_name"),
    ((REVISION_0004, "canary_approvals"), (REVISION_0005, "canary_attempts")),
)
def test_existing_incomplete_table_fails_closed(tmp_path, target_revision: str, table_name: str) -> None:
    config, engine = _database(tmp_path, f"incomplete-{table_name}.sqlite")
    predecessor = REVISION_0003 if target_revision == REVISION_0004 else REVISION_0004
    command.upgrade(config, predecessor)
    identity = "approval_id" if table_name == "canary_approvals" else "attempt_id"
    with engine.begin() as connection:
        connection.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
        connection.execute(text(f"CREATE TABLE {table_name} ({identity} VARCHAR(64) PRIMARY KEY)"))

    with pytest.raises(RuntimeError, match=rf"existing {table_name} table is incompatible: columns"):
        command.upgrade(config, target_revision)
    assert _version(engine) == predecessor
