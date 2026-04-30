"""Tests del wiring async (engine, session factory, transactional context)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from streaming_bot.infrastructure.persistence.postgres.database import (
    make_engine,
    make_session_factory,
    transactional_session,
)


async def test_make_engine_and_session_factory_smoke() -> None:
    """Crea engine SQLite, hace SELECT 1 y dispone."""
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    factory = make_session_factory(engine)
    async with factory() as session:
        result = await session.execute(text("SELECT 1"))
        assert result.scalar_one() == 1
    await engine.dispose()


async def test_transactional_session_commits_on_success() -> None:
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    factory = make_session_factory(engine)
    async with transactional_session(factory) as session:
        result = await session.execute(text("SELECT 1"))
        assert result.scalar_one() == 1
    await engine.dispose()


async def test_transactional_session_rolls_back_on_error() -> None:
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    factory = make_session_factory(engine)

    with pytest.raises(RuntimeError):
        async with transactional_session(factory) as session:
            await session.execute(text("SELECT 1"))
            raise RuntimeError("forced")

    await engine.dispose()
