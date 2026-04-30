"""Repositorios Postgres para historial de streams y sesiones."""

from __future__ import annotations

from datetime import UTC, date, datetime, time

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from streaming_bot.domain.exceptions import DomainError
from streaming_bot.domain.history import SessionRecord, StreamHistory
from streaming_bot.infrastructure.persistence.postgres.models.history import (
    SessionRecordModel,
    StreamHistoryModel,
)
from streaming_bot.infrastructure.persistence.postgres.models.song import SongModel
from streaming_bot.infrastructure.persistence.postgres.repos.mappers import (
    from_domain_session_record,
    from_domain_stream_history,
    to_domain_session_record,
    to_domain_stream_history,
)


class PostgresStreamHistoryRepository:
    """Implementación de `IStreamHistoryRepository` con resolución de song_id."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, history: StreamHistory) -> None:
        """Persiste un intento de stream.

        Resuelve `song_id` interno desde `history.song_uri` para mantener la
        FK fuerte. Si la canción no existe lanzamos en lugar de auto-crear:
        un stream sin canción registrada es siempre un bug del scheduler.
        """
        song_id = await self._resolve_song_id(history.song_uri)
        model = from_domain_stream_history(history, song_id=song_id)
        self._session.add(model)
        await self._session.flush()

    async def list_for_song(
        self,
        song_id: str,
        *,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[StreamHistory]:
        """Stream history por canción.

        `song_id` aquí refiere al ID interno (ULID) de `songs.id`. Para
        analítica externa por URI, usar `list_for_song_uri` (helper extra).
        """
        return await self._list_for_song_internal(
            song_id_or_uri=song_id,
            by_uri=False,
            from_date=from_date,
            to_date=to_date,
        )

    async def list_for_song_uri(
        self,
        song_uri: str,
        *,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[StreamHistory]:
        """Atajo para resolver historial por URI sin exponer el id interno."""
        return await self._list_for_song_internal(
            song_id_or_uri=song_uri,
            by_uri=True,
            from_date=from_date,
            to_date=to_date,
        )

    async def count_for_song_today(self, song_id: str) -> int:
        """Conteo de hoy para un song_id (UTC)."""
        start, end = _today_range_utc()
        stmt = (
            select(func.count())
            .select_from(StreamHistoryModel)
            .where(
                StreamHistoryModel.song_id == song_id,
                StreamHistoryModel.started_at >= start,
                StreamHistoryModel.started_at < end,
            )
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def count_for_account_today(self, account_id: str) -> int:
        """Conteo de hoy para una cuenta (UTC). Crítico para rate limit."""
        start, end = _today_range_utc()
        stmt = (
            select(func.count())
            .select_from(StreamHistoryModel)
            .where(
                StreamHistoryModel.account_id == account_id,
                StreamHistoryModel.started_at >= start,
                StreamHistoryModel.started_at < end,
            )
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    # -- internos -------------------------------------------------------- #

    async def _resolve_song_id(self, song_uri: str) -> str:
        stmt = select(SongModel.id).where(SongModel.spotify_uri == song_uri)
        result = await self._session.execute(stmt)
        song_id = result.scalar_one_or_none()
        if song_id is None:
            raise DomainError(
                f"no existe Song para uri={song_uri}; añade la canción antes de registrar history",
            )
        return song_id

    async def _list_for_song_internal(
        self,
        *,
        song_id_or_uri: str,
        by_uri: bool,
        from_date: date | None,
        to_date: date | None,
    ) -> list[StreamHistory]:
        stmt = select(StreamHistoryModel, SongModel).join(
            SongModel,
            SongModel.id == StreamHistoryModel.song_id,
        )
        if by_uri:
            stmt = stmt.where(SongModel.spotify_uri == song_id_or_uri)
        else:
            stmt = stmt.where(StreamHistoryModel.song_id == song_id_or_uri)
        if from_date is not None:
            stmt = stmt.where(
                StreamHistoryModel.started_at >= datetime.combine(from_date, time.min, UTC),
            )
        if to_date is not None:
            stmt = stmt.where(
                StreamHistoryModel.started_at <= datetime.combine(to_date, time.max, UTC),
            )
        result = await self._session.execute(stmt.order_by(StreamHistoryModel.started_at.asc()))
        rows = result.all()
        return [
            to_domain_stream_history(
                history_model,
                song_uri=song_model.spotify_uri,
                artist_uri=song_model.artist_uri,
            )
            for history_model, song_model in rows
        ]


class PostgresSessionRecordRepository:
    """Implementación de `ISessionRecordRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, record: SessionRecord) -> None:
        """INSERT del record completo (eventos quedan en JSON inline)."""
        self._session.add(from_domain_session_record(record))
        await self._session.flush()

    async def get(self, session_id: str) -> SessionRecord | None:
        """Lookup por PK del session_id (UUID4 del dominio)."""
        model = await self._session.get(SessionRecordModel, session_id)
        return to_domain_session_record(model) if model is not None else None

    async def list_for_account(
        self,
        account_id: str,
        *,
        limit: int = 50,
    ) -> list[SessionRecord]:
        """Últimas N sesiones de la cuenta (orden DESC por started_at)."""
        stmt = (
            select(SessionRecordModel)
            .where(SessionRecordModel.account_id == account_id)
            .order_by(SessionRecordModel.started_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [to_domain_session_record(m) for m in result.scalars().all()]


def _today_range_utc() -> tuple[datetime, datetime]:
    """Devuelve (00:00, 24:00) del día actual en UTC."""
    now = datetime.now(UTC)
    start = datetime.combine(now.date(), time.min, UTC)
    end = datetime.combine(now.date(), time.max, UTC)
    return start, end
