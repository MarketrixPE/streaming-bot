"""Entorno Alembic async-aware.

Soporta tanto Postgres (`postgresql+asyncpg://...`) como SQLite
(`sqlite+aiosqlite:///...`). La DSN se lee de la variable de entorno
`DATABASE_URL` para no hardcodear credenciales en el repo.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from streaming_bot.infrastructure.persistence.postgres.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inyecta la DSN dinámica antes de instanciar el engine.
_dsn = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./alembic_default.db")
config.set_main_option("sqlalchemy.url", _dsn)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Modo offline: emite SQL sin abrir conexión real (para CI/scripts)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Hook sincrónico que Alembic ejecuta dentro del run_sync del engine."""
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Crea engine async y delega la migración al hook sync."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Modo online: detecta drivers async y orquesta la corrutina."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
