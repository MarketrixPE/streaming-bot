"""Puerto para persistencia de artistas."""

from __future__ import annotations

from typing import Protocol

from streaming_bot.domain.artist import Artist, ArtistStatus


class IArtistRepository(Protocol):
    """Repositorio para artistas (multi-artist support)."""

    async def save(self, artist: Artist) -> None: ...

    async def get(self, artist_id: str) -> Artist | None: ...

    async def get_by_spotify_uri(self, spotify_uri: str) -> Artist | None: ...

    async def get_by_name(self, name: str) -> Artist | None: ...

    async def list_active(self) -> list[Artist]: ...

    async def list_by_status(self, status: ArtistStatus) -> list[Artist]: ...

    async def list_all(self) -> list[Artist]: ...

    async def delete(self, artist_id: str) -> None: ...
