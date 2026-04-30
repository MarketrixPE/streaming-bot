"""Tests para las extensiones de repos_adapter (playlists, camouflage)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from streaming_bot.domain.playlist import Playlist, PlaylistKind, PlaylistVisibility
from streaming_bot.domain.value_objects import Country
from streaming_bot.infrastructure.persistence.postgres.database import (
    make_session_factory,
)
from streaming_bot.infrastructure.persistence.postgres.models import Base
from streaming_bot.presentation.dashboard.repos_adapter import (
    AsyncRunner,
    SyncReposAdapter,
)


@pytest.fixture
def engine() -> AsyncEngine:
    """Engine SQLite en memoria para testing."""
    return create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)


@pytest.fixture
async def adapter(engine: AsyncEngine) -> AsyncRunner:
    """Adapter sincrono con AsyncRunner."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = make_session_factory(engine)
    runner = AsyncRunner()
    adapter = SyncReposAdapter(session_factory=factory, runner=runner)

    yield adapter  # type: ignore[misc]

    runner.shutdown()
    await engine.dispose()


def test_list_playlists_by_kind_empty(adapter: SyncReposAdapter) -> None:
    """Verifica que list_playlists_by_kind retorne vacio si no hay datos."""
    playlists = adapter.list_playlists_by_kind(PlaylistKind.PROJECT_PUBLIC)
    assert playlists == []


def test_count_camouflage_tracks_zero(adapter: SyncReposAdapter) -> None:
    """Verifica que count_camouflage_tracks retorne 0 si no hay datos."""
    count = adapter.count_camouflage_tracks()
    assert count == 0


def test_list_camouflage_genres_empty(adapter: SyncReposAdapter) -> None:
    """Verifica que list_camouflage_genres retorne vacio si no hay datos."""
    genres = adapter.list_camouflage_genres()
    assert genres == []


def test_add_playlist(adapter: SyncReposAdapter) -> None:
    """Verifica que add_playlist persista correctamente."""
    playlist = Playlist.new(
        name="Test Playlist",
        kind=PlaylistKind.PROJECT_PUBLIC,
        visibility=PlaylistVisibility.PUBLIC,
        territory=Country.PE,
        genre="reggaeton",
    )

    adapter.add_playlist(playlist)

    retrieved = adapter.list_playlists_by_kind(PlaylistKind.PROJECT_PUBLIC)
    assert len(retrieved) == 1
    assert retrieved[0].name == "Test Playlist"
    assert retrieved[0].kind == PlaylistKind.PROJECT_PUBLIC
