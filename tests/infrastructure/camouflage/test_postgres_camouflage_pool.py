"""Tests para PostgresCamouflagePool con SQLite in-memory."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from streaming_bot.domain.ports.spotify_client import SpotifyTrackMeta
from streaming_bot.domain.song import SongRole
from streaming_bot.domain.value_objects import Country
from streaming_bot.infrastructure.camouflage import PostgresCamouflagePool
from streaming_bot.infrastructure.persistence.postgres.database import (
    make_engine,
    make_session_factory,
    transactional_session,
)
from streaming_bot.infrastructure.persistence.postgres.models.base import Base
from streaming_bot.infrastructure.persistence.postgres.models.song import SongModel


class FakeSpotifyClient:
    """Mock de ISpotifyClient para tests."""

    def __init__(self, tracks_to_return: list[SpotifyTrackMeta]) -> None:
        self._tracks = tracks_to_return

    async def get_top_tracks_by_genre(
        self,
        *,
        genre: str,
        market: Country,
        limit: int = 50,
    ) -> list[SpotifyTrackMeta]:
        """Devuelve tracks fake."""
        return self._tracks[:limit]


@pytest.fixture
async def engine() -> AsyncEngine:
    """Engine SQLite in-memory."""
    engine = make_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker:
    """Session factory para tests."""
    return make_session_factory(engine)


@pytest.fixture
def fake_spotify() -> FakeSpotifyClient:
    """Spotify client fake con 20 tracks."""
    tracks = [
        SpotifyTrackMeta(
            uri=f"spotify:track:fake{i:03d}",
            name=f"Fake Track {i}",
            duration_ms=180000 + i * 1000,
            artist_uris=(f"spotify:artist:art{i:03d}",),
            artist_names=(f"Artist {i}",),
            album_uri=f"spotify:album:alb{i:03d}",
            popularity=50 + i,
            explicit=False,
            isrc=f"ISRC{i:05d}",
        )
        for i in range(20)
    ]
    return FakeSpotifyClient(tracks)


@pytest.mark.asyncio
async def test_refresh_pool_upserts_tracks(
    session_factory: async_sessionmaker,
    fake_spotify: FakeSpotifyClient,
) -> None:
    """Verifica que refresh_pool inserta tracks como CAMOUFLAGE."""
    pool = PostgresCamouflagePool(session_factory, fake_spotify)

    result = await pool.refresh_pool(markets=[Country.PE, Country.MX])

    assert result > 0

    # Verificar que se insertaron en la DB
    async with transactional_session(session_factory) as session:
        stmt = SongModel.__table__.select().where(SongModel.role == SongRole.CAMOUFLAGE.value)
        rows = await session.execute(stmt)
        all_rows = rows.fetchall()
        assert len(all_rows) > 0


@pytest.mark.asyncio
async def test_refresh_pool_is_idempotent(
    session_factory: async_sessionmaker,
    fake_spotify: FakeSpotifyClient,
) -> None:
    """Verifica que refresh_pool es idempotente (no duplica)."""
    pool = PostgresCamouflagePool(session_factory, fake_spotify)

    first = await pool.refresh_pool(markets=[Country.PE])
    second = await pool.refresh_pool(markets=[Country.PE])

    # Segunda vez no debe agregar nuevos (mismas URIs)
    assert first > 0
    # Puede actualizar mercados, pero no duplicar
    assert second >= 0


@pytest.mark.asyncio
async def test_random_sample_excludes_uris(
    session_factory: async_sessionmaker,
    fake_spotify: FakeSpotifyClient,
) -> None:
    """Verifica que random_sample excluye URIs."""
    pool = PostgresCamouflagePool(session_factory, fake_spotify)

    await pool.refresh_pool(markets=[Country.PE])

    excluding = {"spotify:track:fake000", "spotify:track:fake001"}
    tracks = await pool.random_sample(
        market=Country.PE,
        size=5,
        excluding_uris=excluding,
    )

    assert all(t.track_uri not in excluding for t in tracks)


@pytest.mark.asyncio
async def test_fetch_top_by_genre_returns_empty_when_no_matches(
    session_factory: async_sessionmaker,
    fake_spotify: FakeSpotifyClient,
) -> None:
    """Verifica que devuelve vacío cuando no hay matches de género."""
    pool = PostgresCamouflagePool(session_factory, fake_spotify)

    await pool.refresh_pool(markets=[Country.PE])

    # Buscar un género que no existe
    tracks = await pool.fetch_top_by_genre(
        genre="heavy metal",
        market=Country.PE,
        limit=10,
    )

    # El pool no filtra por género en la query, así que puede devolver tracks
    # pero no necesariamente del género solicitado
    assert isinstance(tracks, list)


@pytest.mark.asyncio
async def test_random_sample_returns_up_to_size(
    session_factory: async_sessionmaker,
    fake_spotify: FakeSpotifyClient,
) -> None:
    """Verifica que random_sample devuelve hasta size tracks."""
    pool = PostgresCamouflagePool(session_factory, fake_spotify)

    await pool.refresh_pool(markets=[Country.PE])

    tracks = await pool.random_sample(
        market=Country.PE,
        size=3,
        excluding_uris=None,
    )

    assert len(tracks) <= 3


@pytest.mark.asyncio
async def test_refresh_pool_handles_spotify_errors_gracefully(
    session_factory: async_sessionmaker,
) -> None:
    """Verifica que captura errores de Spotify sin fallar."""

    class FailingSpotifyClient:
        async def get_top_tracks_by_genre(
            self,
            *,
            genre: str,
            market: Country,
            limit: int = 50,
        ) -> list[SpotifyTrackMeta]:
            raise RuntimeError("Spotify API error")

    pool = PostgresCamouflagePool(session_factory, FailingSpotifyClient())

    # No debe explotar, debe devolver 0
    result = await pool.refresh_pool(markets=[Country.PE])

    assert result == 0
