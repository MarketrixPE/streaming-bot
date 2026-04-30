"""Pool de camuflaje en memoria para tests.

Implementación del puerto `ICamouflagePool` sin dependencias de base de datos.
Útil para tests unitarios del composer y servicios de aplicación.
"""

from __future__ import annotations

import random

from streaming_bot.domain.playlist import PlaylistTrack
from streaming_bot.domain.song import Song, SongRole
from streaming_bot.domain.value_objects import Country


class InMemoryCamouflagePool:
    """Pool de canciones de camuflaje en memoria."""

    def __init__(self) -> None:
        self._songs: dict[str, Song] = {}

    def add_song(self, song: Song) -> None:
        """Agrega una canción al pool (helper para tests)."""
        if song.role != SongRole.CAMOUFLAGE:
            raise ValueError(f"Solo se permiten songs con role=CAMOUFLAGE, got {song.role}")
        self._songs[song.spotify_uri] = song

    async def fetch_top_by_genre(
        self,
        *,
        genre: str,
        market: Country,
        limit: int = 50,
    ) -> list[PlaylistTrack]:
        """Filtra por género y mercado."""
        candidates = [
            s
            for s in self._songs.values()
            if genre.lower() in [g.lower() for g in s.metadata.genres]
            and s.top_country_distribution.get(market, 0.0) > 0.0
        ]
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
        """Muestra aleatoria de canciones del mercado, excluyendo URIs."""
        excluding = excluding_uris or set()
        candidates = [
            s
            for s in self._songs.values()
            if s.spotify_uri not in excluding and s.top_country_distribution.get(market, 0.0) > 0.0
        ]
        sampled = random.sample(candidates, min(size, len(candidates)))
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

    async def refresh_pool(self, *, markets: list[Country]) -> int:  # noqa: ARG002
        """No-op para in-memory pool. Devuelve 0."""
        return 0
