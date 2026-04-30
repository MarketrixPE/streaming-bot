"""Repositorio Postgres de playlists."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from streaming_bot.domain.playlist import Playlist, PlaylistKind
from streaming_bot.infrastructure.persistence.postgres.models.playlist import (
    PlaylistModel,
    PlaylistTrackModel,
)
from streaming_bot.infrastructure.persistence.postgres.repos.mappers import (
    from_domain_playlist,
    from_domain_playlist_track,
    to_domain_playlist,
)


class PostgresPlaylistRepository:
    """Implementación de `IPlaylistRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, playlist_id: str) -> Playlist | None:
        """Tracks se hidratan por relationship con `lazy='selectin'`."""
        model = await self._session.get(PlaylistModel, playlist_id)
        return to_domain_playlist(model) if model is not None else None

    async def add(self, playlist: Playlist) -> None:
        """INSERT atómico playlist + tracks (cascade configurada)."""
        self._session.add(from_domain_playlist(playlist))
        await self._session.flush()

    async def update(self, playlist: Playlist) -> None:
        """UPDATE: replace de tracks (delete-orphan + reinsert).

        Se evita un diff tracks por position: para playlists de 30-50 items
        el coste de DELETE+INSERT es despreciable y simplifica la semántica.
        Se asigna la lista a `model.tracks` (en lugar de session.add con FK)
        para gatillar el cascade delete-orphan correctamente.
        """
        model = await self._session.get(PlaylistModel, playlist.id)
        if model is None:
            await self.add(playlist)
            return
        model.spotify_id = playlist.spotify_id
        model.name = playlist.name
        model.kind = playlist.kind.value
        model.visibility = playlist.visibility.value
        model.owner_account_id = playlist.owner_account_id
        model.territory = playlist.territory.value if playlist.territory else None
        model.genre = playlist.genre
        model.description = playlist.description
        model.cover_image_path = playlist.cover_image_path
        model.follower_count = playlist.follower_count
        model.last_synced_at = playlist.last_synced_at
        model.tracks = [from_domain_playlist_track(t) for t in playlist.tracks]
        await self._session.flush()

    async def list_by_kind(self, kind: PlaylistKind) -> list[Playlist]:
        """Filtro por tipo (project_public, personal_private, etc.)."""
        stmt = select(PlaylistModel).where(PlaylistModel.kind == kind.value)
        result = await self._session.execute(stmt)
        return [to_domain_playlist(m) for m in result.scalars().unique().all()]

    async def list_by_owner(self, account_id: str) -> list[Playlist]:
        """Playlists creadas/owned por una cuenta."""
        stmt = select(PlaylistModel).where(
            PlaylistModel.owner_account_id == account_id,
        )
        result = await self._session.execute(stmt)
        return [to_domain_playlist(m) for m in result.scalars().unique().all()]

    async def list_targeting_song(self, target_song_uri: str) -> list[Playlist]:
        """Playlists con la canción objetivo marcada como `is_target=True`.

        Usa el índice compuesto `(track_uri, is_target)` para resolver el
        join sin escanear `playlist_tracks`. `unique()` necesario para
        deduplicar por la cardinalidad del JOIN.
        """
        stmt = (
            select(PlaylistModel)
            .join(PlaylistTrackModel, PlaylistModel.id == PlaylistTrackModel.playlist_id)
            .where(
                PlaylistTrackModel.track_uri == target_song_uri,
                PlaylistTrackModel.is_target.is_(True),
            )
        )
        result = await self._session.execute(stmt)
        return [to_domain_playlist(m) for m in result.scalars().unique().all()]
