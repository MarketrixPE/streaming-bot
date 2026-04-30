"""Fixtures de la capa de persistencia.

Se monta SQLite in-memory por test para garantizar aislamiento total.
`StaticPool` es necesario porque cada conexión SQLite in-memory abre su
propia base; el pool estático fuerza compartir una sola conexión y el
schema entre la sesión async y los `flush`/`commit` que dispare el repo.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from streaming_bot.infrastructure.persistence.postgres.models import Base


@pytest_asyncio.fixture()
async def session() -> AsyncIterator[AsyncSession]:
    """Sesión async fresh por test contra SQLite in-memory."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as s:
        yield s

    await engine.dispose()
