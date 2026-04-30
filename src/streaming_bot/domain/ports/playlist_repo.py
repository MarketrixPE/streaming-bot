"""Puertos para persistencia y composicion de playlists.

- `IPlaylistRepository`: CRUD sobre la tabla playlists (Postgres).
- `IPlaylistComposer`: logica para componer playlists con mezcla target+camuflaje.
- `ISeedAccountPool`: cuentas semilla que crean las project playlists publicas.
- `ICamouflagePool`: pool de tracks reales por genero/territorio.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from streaming_bot.domain.playlist import Playlist, PlaylistKind, PlaylistTrack
from streaming_bot.domain.song import Song
from streaming_bot.domain.value_objects import Country


@runtime_checkable
class IPlaylistRepository(Protocol):
    async def get(self, playlist_id: str) -> Playlist | None: ...
    async def add(self, playlist: Playlist) -> None: ...
    async def update(self, playlist: Playlist) -> None: ...
    async def list_by_kind(self, kind: PlaylistKind) -> list[Playlist]: ...
    async def list_by_owner(self, account_id: str) -> list[Playlist]: ...
    async def list_targeting_song(self, target_song_uri: str) -> list[Playlist]: ...


@runtime_checkable
class ICamouflagePool(Protocol):
    """Pool de canciones reales populares para camuflaje (no son targets)."""

    async def fetch_top_by_genre(
        self,
        *,
        genre: str,
        market: Country,
        limit: int = 50,
    ) -> list[PlaylistTrack]: ...

    async def random_sample(
        self,
        *,
        market: Country,
        size: int,
        excluding_uris: set[str] | None = None,
    ) -> list[PlaylistTrack]: ...

    async def refresh_pool(self, *, markets: list[Country]) -> int:
        """Refresca el pool desde Spotify Search/Editorial. Devuelve count."""
        ...


@runtime_checkable
class IPlaylistComposer(Protocol):
    """Compone playlists balanceando targets y camuflaje."""

    async def compose_personal_playlist(
        self,
        *,
        account_id: str,
        market: Country,
        target_songs: list[Song],
        target_ratio: float = 0.30,
        size: int = 30,
    ) -> Playlist:
        """Crea una playlist privada para una cuenta con mezcla balanceada."""
        ...

    async def compose_project_playlist(
        self,
        *,
        market: Country,
        genre: str,
        target_songs: list[Song],
        target_ratio: float = 0.20,
        size: int = 50,
    ) -> Playlist:
        """Crea una playlist publica de "proyecto" (con curator account)."""
        ...

    async def reorder_for_session(
        self,
        playlist: Playlist,
        *,
        session_target_uris: set[str],
    ) -> Playlist:
        """Reordena la playlist para esta sesion: targets bien repartidos, no contiguos."""
        ...


@runtime_checkable
class ISeedAccountPool(Protocol):
    """Cuentas semilla "curator" que mantienen las project playlists publicas.

    Estas son cuentas separadas del pool de listening; su rol es construir
    autoridad publica (aparecer como creators de playlists con followers).
    """

    async def get_curator_for_market(self, market: Country) -> str:
        """Devuelve account_id del curator preferido para ese mercado."""
        ...

    async def assign_curator_for_playlist(
        self,
        *,
        playlist: Playlist,
        market: Country,
    ) -> str: ...
