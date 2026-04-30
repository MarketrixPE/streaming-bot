"""Tests para InMemoryCamouflagePool."""

from __future__ import annotations

import pytest

from streaming_bot.domain.song import Song, SongMetadata, SongRole
from streaming_bot.domain.value_objects import Country
from streaming_bot.infrastructure.camouflage import InMemoryCamouflagePool


@pytest.fixture
def pool_with_data() -> InMemoryCamouflagePool:
    """Pool con 50 canciones sintéticas."""
    pool = InMemoryCamouflagePool()

    for i in range(50):
        genre = "reggaeton" if i < 20 else "trap latino" if i < 40 else "latin pop"
        market = Country.PE if i < 15 else Country.MX if i < 30 else Country.US

        song = Song(
            spotify_uri=f"spotify:track:cam{i:03d}",
            title=f"Camuflaje Track {i}",
            artist_name=f"Artist {i}",
            artist_uri=f"spotify:artist:art{i:03d}",
            role=SongRole.CAMOUFLAGE,
            metadata=SongMetadata(
                duration_seconds=180 + i * 5,
                genres=(genre,),
            ),
            top_country_distribution={market: 1.0},
        )
        pool.add_song(song)

    return pool


@pytest.mark.asyncio
async def test_fetch_top_by_genre_filters_correctly(
    pool_with_data: InMemoryCamouflagePool,
) -> None:
    """Verifica que fetch_top_by_genre filtra por género y mercado."""
    tracks = await pool_with_data.fetch_top_by_genre(
        genre="reggaeton",
        market=Country.PE,
        limit=50,
    )

    assert len(tracks) == 15  # 15 canciones con reggaeton + PE
    assert all(not t.is_target for t in tracks)
    assert all(t.position == 0 for t in tracks)  # position se asigna después


@pytest.mark.asyncio
async def test_fetch_top_by_genre_respects_limit(
    pool_with_data: InMemoryCamouflagePool,
) -> None:
    """Verifica que respeta el límite solicitado."""
    tracks = await pool_with_data.fetch_top_by_genre(
        genre="reggaeton",
        market=Country.PE,
        limit=5,
    )

    assert len(tracks) == 5


@pytest.mark.asyncio
async def test_random_sample_excludes_uris(
    pool_with_data: InMemoryCamouflagePool,
) -> None:
    """Verifica que random_sample excluye URIs."""
    excluding = {
        "spotify:track:cam000",
        "spotify:track:cam001",
        "spotify:track:cam002",
    }

    tracks = await pool_with_data.random_sample(
        market=Country.PE,
        size=10,
        excluding_uris=excluding,
    )

    assert len(tracks) <= 10
    assert all(t.track_uri not in excluding for t in tracks)
    assert all(not t.is_target for t in tracks)


@pytest.mark.asyncio
async def test_random_sample_filters_by_market(
    pool_with_data: InMemoryCamouflagePool,
) -> None:
    """Verifica que random_sample filtra por mercado."""
    tracks = await pool_with_data.random_sample(
        market=Country.PE,
        size=20,
        excluding_uris=None,
    )

    # Solo 15 canciones tienen PE en su distribución
    assert len(tracks) <= 15


@pytest.mark.asyncio
async def test_refresh_pool_is_noop(
    pool_with_data: InMemoryCamouflagePool,
) -> None:
    """Verifica que refresh_pool es no-op para in-memory."""
    result = await pool_with_data.refresh_pool(markets=[Country.PE, Country.MX])
    assert result == 0


@pytest.mark.asyncio
async def test_add_song_rejects_non_camouflage() -> None:
    """Verifica que solo acepta songs con role=CAMOUFLAGE."""
    pool = InMemoryCamouflagePool()

    target_song = Song(
        spotify_uri="spotify:track:target001",
        title="Target Song",
        artist_name="Artist",
        artist_uri="spotify:artist:art001",
        role=SongRole.TARGET,
        metadata=SongMetadata(duration_seconds=200),
    )

    with pytest.raises(ValueError, match="role=CAMOUFLAGE"):
        pool.add_song(target_song)


@pytest.mark.asyncio
async def test_random_sample_returns_empty_when_no_matches(
    pool_with_data: InMemoryCamouflagePool,
) -> None:
    """Verifica que devuelve vacío cuando no hay matches."""
    # Bolivia no está en el pool
    tracks = await pool_with_data.random_sample(
        market=Country.BO,
        size=10,
        excluding_uris=None,
    )

    assert len(tracks) == 0
