"""Repositorio Postgres de artistas (multi-artist support)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from streaming_bot.domain.artist import Artist, ArtistStatus
from streaming_bot.infrastructure.persistence.postgres.models.artist import ArtistModel
from streaming_bot.infrastructure.persistence.postgres.repos.mappers import (
    apply_artist_to_model,
    from_domain_artist,
    to_domain_artist,
)


class PostgresArtistRepository:
    """Implementación de `IArtistRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, artist: Artist) -> None:
        """Upsert por id. Si existe, hace UPDATE in-place."""
        existing = await self._session.get(ArtistModel, artist.id)
        if existing is None:
            self._session.add(from_domain_artist(artist))
        else:
            apply_artist_to_model(artist, existing)
        await self._session.flush()

    async def get(self, artist_id: str) -> Artist | None:
        model = await self._session.get(ArtistModel, artist_id)
        return to_domain_artist(model) if model is not None else None

    async def get_by_spotify_uri(self, spotify_uri: str) -> Artist | None:
        stmt = select(ArtistModel).where(ArtistModel.spotify_uri == spotify_uri)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return to_domain_artist(model) if model is not None else None

    async def get_by_name(self, name: str) -> Artist | None:
        stmt = select(ArtistModel).where(ArtistModel.name == name)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return to_domain_artist(model) if model is not None else None

    async def list_active(self) -> list[Artist]:
        stmt = select(ArtistModel).where(ArtistModel.status == ArtistStatus.ACTIVE.value)
        result = await self._session.execute(stmt)
        return [to_domain_artist(m) for m in result.scalars().all()]

    async def list_by_status(self, status: ArtistStatus) -> list[Artist]:
        stmt = select(ArtistModel).where(ArtistModel.status == status.value)
        result = await self._session.execute(stmt)
        return [to_domain_artist(m) for m in result.scalars().all()]

    async def list_all(self) -> list[Artist]:
        stmt = select(ArtistModel).order_by(ArtistModel.name)
        result = await self._session.execute(stmt)
        return [to_domain_artist(m) for m in result.scalars().all()]

    async def delete(self, artist_id: str) -> None:
        model = await self._session.get(ArtistModel, artist_id)
        if model is not None:
            await self._session.delete(model)
            await self._session.flush()
