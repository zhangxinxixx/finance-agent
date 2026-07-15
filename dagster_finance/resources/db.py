"""SQLAlchemy session resource for Dagster ops."""

from contextlib import contextmanager

from dagster import ConfigurableResource
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


class DbSessionResource(ConfigurableResource):
    """Provides a SQLAlchemy session to ops via context manager.

    Usage in ops: context.resources.db_session
    """

    database_url: str = ""

    def get_session(self) -> Session:
        if self.database_url:
            return Session(bind=create_engine(self.database_url, echo=False, pool_pre_ping=True))
        from database.models.engine import SessionLocal

        return SessionLocal()

    @contextmanager
    def yield_for_execution(self, context):
        session = self.get_session()
        try:
            yield session
        finally:
            session.close()
