"""Alembic environment.

Async-aware: we read the connection URL from `app.core.config.settings` (which
also handles Railway's `DATABASE_URL` injection and the `postgresql+asyncpg`
driver normalization). All model modules are imported eagerly so their tables
register on `Base.metadata` for autogenerate / `--sql` offline mode.
"""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import settings
from app.core.db import Base

# Import all model modules so they register on Base.metadata.
import app.modules.auth.models  # noqa: F401
import app.modules.auth.session_model  # noqa: F401
import app.modules.chat.models  # noqa: F401
import app.modules.users_prefs.models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject the live URL. alembic.ini leaves `sqlalchemy.url` empty on purpose.
config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


def _include_name(name: str, type_: str, parent_names: dict) -> bool:
    """Limit autogenerate to objects in the `ai` schema only.

    The database may host tables from other tools / projects (e.g.
    `library_coderag.*`); we don't want our migrations to drop or alter
    those.
    """
    if type_ == "schema":
        return name == "ai"
    parent_schema = parent_names.get("schema_name")
    if parent_schema and parent_schema != "ai":
        return False
    return True


def run_migrations_offline() -> None:
    """Render SQL to stdout without connecting (useful for review)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_name=_include_name,
        version_table_schema="ai",
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=_include_name,
        version_table_schema="ai",
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        # Pre-create the schema that will hold alembic_version. Without this,
        # the very first `alembic upgrade head` on a brand-new (empty)
        # database fails with `InvalidSchemaNameError: schema "ai" does not
        # exist` when alembic tries to create `ai.alembic_version` before
        # running the migration body. CREATE SCHEMA IF NOT EXISTS is a
        # no-op on subsequent runs.
        await connection.execute(text("CREATE SCHEMA IF NOT EXISTS ai"))
        await connection.commit()

        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()