"""Fixtures del dashboard: engine SQLite in-memory + session_factory + runner.

Comparte la estrategia del resto de la suite: ``StaticPool`` para mantener
la misma conexion entre threads (Streamlit usa el ``AsyncRunner`` que vive
en un hilo distinto al del test).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from streaming_bot.infrastructure.persistence.postgres.models import Base
from streaming_bot.presentation.dashboard.repos_adapter import (
    AsyncRunner,
    SyncReposAdapter,
)


@pytest.fixture()
def runner() -> Iterator[AsyncRunner]:
    """Runner real con loop dedicado en thread daemon."""
    rnr = AsyncRunner()
    yield rnr
    rnr.shutdown()


@pytest.fixture()
def session_factory(
    runner: AsyncRunner,
) -> Iterator[async_sessionmaker[AsyncSession]]:
    """Engine SQLite in-memory con tablas creadas dentro del loop del runner."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )

    async def _create() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    runner.run(_create())

    factory = async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    yield factory

    async def _dispose() -> None:
        await engine.dispose()

    runner.run(_dispose())


@pytest.fixture()
def repos(
    session_factory: async_sessionmaker[AsyncSession],
    runner: AsyncRunner,
) -> SyncReposAdapter:
    return SyncReposAdapter(session_factory=session_factory, runner=runner)
