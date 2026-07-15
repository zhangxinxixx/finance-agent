from __future__ import annotations

from sqlalchemy import text

from database.models.engine import DEFAULT_DATABASE_URL
from dagster_finance.resources.db import DbSessionResource


def test_db_session_resource_uses_explicit_runtime_database_url() -> None:
    resource = DbSessionResource(database_url="sqlite://")
    session = resource.get_session()
    try:
        assert str(session.get_bind().url) == "sqlite://"
        assert session.execute(text("select 1")).scalar_one() == 1
    finally:
        session.close()


def test_default_database_url_matches_managed_local_stack() -> None:
    assert DEFAULT_DATABASE_URL.endswith("@127.0.0.1:55432/finance_agent")
