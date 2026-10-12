"""Read-only readiness checks, independent of process liveness and Redis."""
from __future__ import annotations

from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool


def _probe_database() -> None:
    from database.models.engine import engine
    from database.models.analysis import AnalysisSnapshot
    from database.models.report import ReportItem
    from database.models.task import TaskRun, TaskStep

    # A dedicated short-lived connection bounds PostgreSQL startup probes and
    # never changes the transaction/pool of an in-flight application request.
    options = {"connect_timeout": 3, "options": "-c statement_timeout=3000"} if engine.dialect.name == "postgresql" else {}
    probe = create_engine(engine.url, poolclass=NullPool, connect_args=options)
    try:
        with probe.connect() as connection:
            connection.execute(text("SELECT 1"))
            for model in (TaskRun, TaskStep, AnalysisSnapshot, ReportItem):
                connection.execute(select(model).limit(0))
    finally:
        probe.dispose()


def get_readiness() -> dict:
    try:
        _probe_database()
    except (SQLAlchemyError, OSError):
        # Connection strings and backend exception text must not reach clients.
        return {"status": "not_ready", "checks": {"database": "unavailable_or_schema_missing"}}
    return {"status": "ready", "checks": {"database": "ready"}}
