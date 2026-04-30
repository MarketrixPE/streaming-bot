"""Puerto para Spotify Web API: catalog, playlists, search, editorial.

La implementacion usara el endpoint oficial OAuth (cuenta legitima de
distribuidor) para evitar scraping del web player. Esto es legal y seguro
para tareas de READ (catalog metadata, popularity, top tracks por pais).

Para acciones de WRITE (crear playlist, agregar tracks) tambien se usa
OAuth pero con cuentas separadas del pool.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from streaming_bot.domain.value_objects import Country


@dataclass(frozen=True, slots=True)
class SpotifyTrackMeta:
    """Metadata canonica de una pista."""

    uri: str  # spotify:track:abc123
    name: str
    duration_ms: int
    artist_uris: tuple[str, ...]
    artist_names: tuple[str, ...]
    album_uri: str
    popularity: int  # 0-100
    explicit: bool = False
    isrc: str | None = None


@dataclass(frozen=True, slots=True)
class SpotifyArtistMeta:
    uri: str
    name: str
    genres: tuple[str, ...]
    popularity: int
    follower_count: int


@dataclass(frozen=True, slots=True)
class SpotifyPlaylistMeta:
    uri: str
    spotify_id: str
    name: str
    description: str
    owner_id: str
    is_public: bool
    follower_count: int
    track_count: int


@runtime_checkable
class ISpotifyClient(Protocol):
    """Cliente Spotify Web API (OAuth user/client credentials)."""

    async def get_track(self, uri: str) -> SpotifyTrackMeta | None: ...

    async def get_tracks_batch(self, uris: list[str]) -> list[SpotifyTrackMeta]: ...

    async def get_artist(self, uri: str) -> SpotifyArtistMeta | None: ...

    async def search_tracks(
        self,
        *,
        query: str,
        market: Country | None = None,
        limit: int = 20,
    ) -> list[SpotifyTrackMeta]: ...

    async def get_top_tracks_by_genre(
        self,
        *,
        genre: str,
        market: Country,
        limit: int = 50,
    ) -> list[SpotifyTrackMeta]:
        """Top tracks de un genero en un mercado (camuflaje pool)."""
        ...

    async def get_artist_top_tracks(
        self,
        *,
        artist_uri: str,
        market: Country,
    ) -> list[SpotifyTrackMeta]: ...

    async def get_playlist(self, playlist_id: str) -> SpotifyPlaylistMeta | None: ...

    async def get_playlist_tracks(self, playlist_id: str) -> list[SpotifyTrackMeta]: ...

    async def create_playlist(
        self,
        *,
        owner_user_id: str,
        name: str,
        description: str = "",
        public: bool = False,
    ) -> SpotifyPlaylistMeta: ...

    async def add_tracks_to_playlist(
        self,
        *,
        playlist_id: str,
        track_uris: list[str],
    ) -> None: ...

    async def reorder_playlist_tracks(
        self,
        *,
        playlist_id: str,
        range_start: int,
        insert_before: int,
    ) -> None: ...
