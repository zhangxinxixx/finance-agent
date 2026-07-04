"""Alembic environment for the finance-agent runtime schema."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from database.models.analysis import AnalysisBase
from database.models.execution import ExecutionBase
from database.models.report import ReportBase
from database.models.task import Base

# Import model modules that register tables on shared metadata.
from database.models import cme as _cme_models  # noqa: F401
from database.models import playbook as _playbook_models  # noqa: F401

# this is the Alembic Config object
config = getattr(context, "config", None)

# Interpret the config file for Python logging
if config is not None and config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override sqlalchemy.url from environment variable if available
DATABASE_URL = __import__("os").environ.get("DATABASE_URL")
if config is not None and DATABASE_URL:
    config.set_main_option("sqlalchemy.url", DATABASE_URL)

target_metadata = [
    AnalysisBase.metadata,
    Base.metadata,
    ExecutionBase.metadata,
    ReportBase.metadata,
]


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generate SQL without connecting)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if config is not None:
    if context.is_offline_mode():
        run_migrations_offline()
    else:
        run_migrations_online()
