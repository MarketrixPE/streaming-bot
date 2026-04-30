"""Repositorio Postgres de canciones."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from streaming_bot.domain.song import Song, SongRole
from streaming_bot.domain.value_objects import Country
from streaming_bot.infrastructure.persistence.postgres.models.song import SongModel
from streaming_bot.infrastructure.persistence.postgres.repos.mappers import (
    apply_song_to_model,
    from_domain_song,
    to_domain_song,
)

# Tier "mid" superior: por encima de 500 streams/día consideramos "high"
# (no eligible para piloto post-Oct'25 por riesgo de huella mediática).
_PILOT_BASELINE_CEILING: float = 500.0


class PostgresSongRepository:
    """Implementación de `ISongRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, song_id: str) -> Song | None:
        """Búsqueda por ULID interno."""
        model = await self._session.get(SongModel, song_id)
        return to_domain_song(model) if model is not None else None

    async def get_by_uri(self, uri: str) -> Song | None:
        """Búsqueda por la URI canónica de Spotify."""
        stmt = select(SongModel).where(SongModel.spotify_uri == uri)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return to_domain_song(model) if model is not None else None

    async def get_by_isrc(self, isrc: str) -> Song | None:
        """Búsqueda por ISRC; útil para deduplicar entre distribuidores."""
        stmt = select(SongModel).where(SongModel.isrc == isrc)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return to_domain_song(model) if model is not None else None

    async def add(self, song: Song) -> None:
        """INSERT. La PK ULID se genera en cliente vía default."""
        self._session.add(from_domain_song(song))
        await self._session.flush()

    async def update(self, song: Song) -> None:
        """UPDATE in-place vía spotify_uri (id interno se preserva)."""
        stmt = select(SongModel).where(SongModel.spotify_uri == song.spotify_uri)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            self._session.add(from_domain_song(song))
        else:
            apply_song_to_model(song, model)
        await self._session.flush()

    async def list_by_role(self, role: SongRole) -> list[Song]:
        """Lista canciones por rol (target/camouflage/discovery)."""
        stmt = select(SongModel).where(SongModel.role == role.value)
        result = await self._session.execute(stmt)
        return [to_domain_song(m) for m in result.scalars().all()]

    async def list_targets_by_market(self, market: Country) -> list[Song]:
        """Targets cuyo top-country incluye `market` con peso > 0.

        Se hace en Python por compatibilidad sqlite/postgres: filtrar JSONB
        por contains-key requeriría operadores específicos de Postgres.
        """
        stmt = select(SongModel).where(SongModel.role == SongRole.TARGET.value)
        result = await self._session.execute(stmt)
        models = result.scalars().all()
        market_code = market.value
        return [
            to_domain_song(m)
            for m in models
            if (m.top_country_distribution or {}).get(market_code, 0.0) > 0.0
        ]

    async def list_pilot_eligible(self, *, max_songs: int = 60) -> list[Song]:
        """Devuelve targets aptos para piloto: zombies+low+mid sin spike Oct'25.

        Tier por baseline_streams_per_day:
        - zombie: < 10
        - low:    < 100
        - mid:    < 500   (límite del piloto)
        - high:   >= 500  (excluido)
        """
        stmt = (
            select(SongModel)
            .where(
                SongModel.role == SongRole.TARGET.value,
                SongModel.spike_oct2025_flag.is_(False),
                SongModel.baseline_streams_per_day < _PILOT_BASELINE_CEILING,
                SongModel.is_active.is_(True),
            )
            .order_by(SongModel.baseline_streams_per_day.asc())
            .limit(max_songs)
        )
        result = await self._session.execute(stmt)
        return [to_domain_song(m) for m in result.scalars().all()]

    async def count_active_targets(self) -> int:
        """Conteo barato vía SELECT COUNT(*); usa el índice (role, is_active)."""
        stmt = (
            select(func.count())
            .select_from(SongModel)
            .where(
                SongModel.role == SongRole.TARGET.value,
                SongModel.is_active.is_(True),
            )
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def mark_spike_oct2025(self, *, spotify_uri: str) -> None:
        """Marca una canción como excluida del piloto (huella Oct'25)."""
        stmt = select(SongModel).where(SongModel.spotify_uri == spotify_uri)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is not None:
            model.spike_oct2025_flag = True
            await self._session.flush()
