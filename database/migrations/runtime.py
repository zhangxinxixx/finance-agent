"""Runtime entrypoints for applying Alembic migrations."""

from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config


_MIGRATIONS_DIR = Path(__file__).resolve().parent
_ALEMBIC_INI = _MIGRATIONS_DIR / "alembic.ini"


def build_alembic_config(database_url: str | None = None) -> Config:
    """Build an Alembic config pinned to this repo's migrations directory."""
    config = Config(str(_ALEMBIC_INI))
    config.set_main_option("script_location", str(_MIGRATIONS_DIR))
    resolved_url = database_url or os.getenv("DATABASE_URL")
    if resolved_url:
        config.set_main_option("sqlalchemy.url", resolved_url)
    config.attributes["database_url_explicit"] = database_url is not None
    return config


def run_database_migrations(database_url: str | None = None) -> None:
    """Upgrade the configured database to the latest Alembic revision."""
    command.upgrade(build_alembic_config(database_url), "head")
