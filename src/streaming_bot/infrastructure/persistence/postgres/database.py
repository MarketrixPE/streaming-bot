"""Construcción del engine asíncrono y context manager transaccional.

Justificación de diseño:
- `make_engine` no decide la DSN: la recibe del caller (12-factor).
- `transactional_session` envuelve commit/rollback para forzar atomicidad por
  unit-of-work y evitar fugas de sesiones colgadas en handlers de errores.
- `expire_on_commit=False` permite que las entidades sigan accesibles tras
  commit sin gatillar lazy-load fuera de la sesión.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def make_engine(dsn: str, *, echo: bool = False) -> AsyncEngine:
    """Crea un AsyncEngine con pooling y pre-ping habilitado.

    `pool_pre_ping` evita usar conexiones zombie tras failover de Postgres,
    pero se desactiva para SQLite porque su pool es trivial (NullPool).
    """
    is_sqlite = dsn.startswith("sqlite")
    return create_async_engine(
        dsn,
        echo=echo,
        future=True,
        pool_pre_ping=not is_sqlite,
    )


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Devuelve una `async_sessionmaker` lista para inyectar en repositorios.

    `expire_on_commit=False` para que los DTO mapeados sigan utilizables
    después del commit (los repos hacen `to_domain` y devuelven entidades
    desconectadas de la sesión).
    """
    return async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )


@asynccontextmanager
async def transactional_session(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Context manager unit-of-work.

    Hace commit si el bloque termina sin excepción; rollback automático
    en caso contrario. Usar siempre en use-cases para garantizar atomicidad.
    """
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
