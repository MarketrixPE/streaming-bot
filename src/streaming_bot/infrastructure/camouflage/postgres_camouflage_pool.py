"""Pool de camuflaje respaldado por Postgres.

Implementación que persiste canciones de camuflaje en la tabla `songs` con
`role=CAMOUFLAGE`. Refresca el pool desde Spotify Search/Editorial via `ISpotifyClient`.
"""

from __future__ import annotations

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from streaming_bot.domain.playlist import PlaylistTrack
from streaming_bot.domain.ports.spotify_client import ISpotifyClient
from streaming_bot.domain.song import Song, SongMetadata, SongRole
from streaming_bot.domain.value_objects import Country
from streaming_bot.infrastructure.persistence.postgres.database import (
    transactional_session,
)
from streaming_bot.infrastructure.persistence.postgres.models.song import SongModel
from streaming_bot.infrastructure.persistence.postgres.repos.mappers import (
    apply_song_to_model,
    from_domain_song,
    to_domain_song,
)

_LATAM_GENRES: tuple[str, ...] = (
    "reggaeton",
    "trap latino",
    "perreo",
    "latin pop",
    "urbano latino",
    "dembow",
)


class PostgresCamouflagePool:
    """Pool de camuflaje con backend Postgres."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        spotify: ISpotifyClient,
        logger: structlog.BoundLogger | None = None,
    ) -> None:
        self._factory = session_factory
        self._spotify = spotify
        self._logger = logger or structlog.get_logger()

    async def fetch_top_by_genre(
        self,
        *,
        genre: str,
        market: Country,
        limit: int = 50,
    ) -> list[PlaylistTrack]:
        """Devuelve top tracks de camuflaje por género y mercado."""
        async with transactional_session(self._factory) as session:
            stmt = select(SongModel).where(SongModel.role == SongRole.CAMOUFLAGE.value).limit(limit)
            result = await session.execute(stmt)
            models = result.scalars().all()

            candidates = []
            for model in models:
                song = to_domain_song(model)
                # Filtrar por género y mercado en Python (compatibilidad sqlite/postgres)
                if (
                    any(g.lower() == genre.lower() for g in song.metadata.genres)
                    and song.top_country_distribution.get(market, 0.0) > 0.0
                ):
                    candidates.append(song)

            candidates_sorted = sorted(
                candidates,
                key=lambda s: s.top_country_distribution.get(market, 0.0),
                reverse=True,
            )

            return [
                PlaylistTrack(
                    track_uri=s.spotify_uri,
                    position=0,
                    is_target=False,
                    duration_ms=s.metadata.duration_seconds * 1000,
                    artist_uri=s.artist_uri,
                    title=s.title,
                )
                for s in candidates_sorted[:limit]
            ]

    async def random_sample(
        self,
        *,
        market: Country,
        size: int,
        excluding_uris: set[str] | None = None,
    ) -> list[PlaylistTrack]:
        """Muestra aleatoria de canciones de camuflaje del mercado."""
        excluding = excluding_uris or set()
        async with transactional_session(self._factory) as session:
            stmt = select(SongModel).where(SongModel.role == SongRole.CAMOUFLAGE.value)
            if excluding:
                stmt = stmt.where(SongModel.spotify_uri.not_in(excluding))
            # Orden aleatorio (cross-DB compatible)
            stmt = stmt.order_by(func.random()).limit(size)

            result = await session.execute(stmt)
            models = result.scalars().all()

            candidates = []
            for model in models:
                song = to_domain_song(model)
                # Filtrar por mercado en Python
                if song.top_country_distribution.get(market, 0.0) > 0.0:
                    candidates.append(song)

            # Si no hay suficientes, tomar lo que hay
            sampled = candidates[:size]

            return [
                PlaylistTrack(
                    track_uri=s.spotify_uri,
                    position=0,
                    is_target=False,
                    duration_ms=s.metadata.duration_seconds * 1000,
                    artist_uri=s.artist_uri,
                    title=s.title,
                )
                for s in sampled
            ]

    async def refresh_pool(self, *, markets: list[Country]) -> int:
        """Refresca el pool desde Spotify Search/Editorial."""
        total_upserted = 0

        async with transactional_session(self._factory) as session:
            for market in markets:
                for genre in _LATAM_GENRES:
                    try:
                        tracks = await self._spotify.get_top_tracks_by_genre(
                            genre=genre,
                            market=market,
                            limit=50,
                        )

                        for track_meta in tracks:
                            # Buscar por URI (idempotente)
                            stmt = select(SongModel).where(SongModel.spotify_uri == track_meta.uri)
                            result = await session.execute(stmt)
                            existing = result.scalar_one_or_none()

                            if existing is None:
                                # Insert nuevo
                                song = Song(
                                    spotify_uri=track_meta.uri,
                                    title=track_meta.name,
                                    artist_name=track_meta.artist_names[0]
                                    if track_meta.artist_names
                                    else "Unknown",
                                    artist_uri=track_meta.artist_uris[0]
                                    if track_meta.artist_uris
                                    else "",
                                    role=SongRole.CAMOUFLAGE,
                                    metadata=SongMetadata(
                                        duration_seconds=track_meta.duration_ms // 1000,
                                        isrc=track_meta.isrc,
                                        genres=(genre,),
                                    ),
                                    top_country_distribution={market: 1.0},
                                )
                                session.add(from_domain_song(song))
                                total_upserted += 1
                            else:
                                # Update (agregar mercado a distribución si falta)
                                song = to_domain_song(existing)
                                if market not in song.top_country_distribution:
                                    updated_dist = dict(song.top_country_distribution)
                                    updated_dist[market] = 1.0
                                    updated_song = Song(
                                        spotify_uri=song.spotify_uri,
                                        title=song.title,
                                        artist_name=song.artist_name,
                                        artist_uri=song.artist_uri,
                                        role=song.role,
                                        metadata=song.metadata,
                                        top_country_distribution=updated_dist,
                                    )
                                    apply_song_to_model(updated_song, existing)
                                    total_upserted += 1

                        await session.flush()

                    except Exception as exc:
                        self._logger.warning(
                            "refresh_pool_error",
                            market=market.value,
                            genre=genre,
                            error=str(exc),
                        )
                        continue

        return total_upserted
