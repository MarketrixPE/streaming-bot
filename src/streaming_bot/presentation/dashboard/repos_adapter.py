"""Adapter sincrono para los repositorios async del dominio.

Streamlit ejecuta scripts top-down en hilos sin event loop activo. Para
acceder a los repositorios async (SQLAlchemy asyncpg/aiosqlite) sin
bloquear ni romper el binding de loop del engine, mantenemos un loop
dedicado en un thread daemon: ``AsyncRunner``.

Patron:
1. ``AsyncRunner`` se crea una vez via ``st.cache_resource``.
2. ``SyncReposAdapter`` recibe la session_factory + runner y expone
   metodos sincronos que abren una sesion transactional, llaman al repo
   y devuelven los resultados materializados.

Ventajas sobre ``asyncio.run`` por llamada:
- El engine asyncio se crea una sola vez en el mismo loop, evitando los
  ``RuntimeError: attached to a different loop`` recurrentes.
- El thread es daemon: muere con el proceso de Streamlit limpio.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from streaming_bot.domain.artist import Artist
from streaming_bot.domain.entities import Account
from streaming_bot.domain.history import SessionRecord
from streaming_bot.domain.label import Label
from streaming_bot.domain.modem import Modem
from streaming_bot.domain.song import Song, SongRole
from streaming_bot.infrastructure.persistence.postgres.database import (
    transactional_session,
)
from streaming_bot.infrastructure.persistence.postgres.models.history import (
    SessionRecordModel,
)
from streaming_bot.infrastructure.persistence.postgres.repos.account_repository import (
    PostgresAccountRepository,
)
from streaming_bot.infrastructure.persistence.postgres.repos.artist_repository import (
    PostgresArtistRepository,
)
from streaming_bot.infrastructure.persistence.postgres.repos.history_repository import (
    PostgresSessionRecordRepository,
)
from streaming_bot.infrastructure.persistence.postgres.repos.label_repository import (
    PostgresLabelRepository,
)
from streaming_bot.infrastructure.persistence.postgres.repos.mappers import (
    to_domain_session_record,
)
from streaming_bot.infrastructure.persistence.postgres.repos.modem_repository import (
    PostgresModemRepository,
)
from streaming_bot.infrastructure.persistence.postgres.repos.song_repository import (
    PostgresSongRepository,
)

T = TypeVar("T")


class AsyncRunner:
    """Loop asyncio dedicado a un thread daemon para uso desde sync code.

    Razon de no usar ``asyncio.run`` por llamada: cada ``run`` crea un
    nuevo loop, y los engines de SQLAlchemy async se ligan al primer loop
    que los usa. Resultado: ``RuntimeError`` en la 2da llamada. Un loop
    estable evita esto y reduce setup overhead.
    """

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever,
            name="streamlit-async-runner",
            daemon=True,
        )
        self._thread.start()

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return self._loop

    def run(self, coro: Coroutine[Any, Any, T]) -> T:
        """Ejecuta una corutina en el loop dedicado y bloquea hasta result."""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    def shutdown(self) -> None:
        """Detiene el loop de forma ordenada (uso en tests)."""
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5.0)
        if not self._loop.is_closed():
            self._loop.close()


@dataclass(slots=True)
class SyncReposAdapter:
    """Wrapper sincrono sobre los repos async.

    Cada metodo abre una `transactional_session` corta (read-only en su
    mayoria). Los repos siguen siendo los mismos del Postgres backend.
    """

    session_factory: async_sessionmaker[AsyncSession]
    runner: AsyncRunner

    # Songs
    def list_songs_by_role(self, role: SongRole) -> list[Song]:
        """Lista canciones por rol (target/camouflage/discovery)."""
        return self.runner.run(self._list_songs_by_role(role))

    def list_target_songs(self) -> list[Song]:
        """Atajo: lista todas las TARGET (las que ve el operador en catalogo)."""
        return self.list_songs_by_role(SongRole.TARGET)

    def list_pilot_eligible(self, *, max_songs: int = 60) -> list[Song]:
        """Canciones aptas para el piloto (zombie/low/mid no flagged)."""
        return self.runner.run(self._list_pilot_eligible(max_songs))

    def count_active_targets(self) -> int:
        return self.runner.run(self._count_active_targets())

    def update_song(self, song: Song) -> None:
        """Persiste cambios in-place (toggle is_active, tier, etc.)."""
        self.runner.run(self._update_song(song))

    # Accounts
    def list_accounts(self) -> list[Account]:
        return self.runner.run(self._list_accounts())

    # Modems
    def list_modems(self) -> list[Modem]:
        return self.runner.run(self._list_modems())

    # Artists
    def list_artists(self) -> list[Artist]:
        """Lista todos los artistas registrados."""
        return self.runner.run(self._list_artists())

    # Labels
    def list_labels(self) -> list[Label]:
        """Lista todos los labels/distribuidores registrados."""
        return self.runner.run(self._list_labels())

    # Sessions
    def list_recent_sessions(self, *, limit: int = 100) -> list[SessionRecord]:
        return self.runner.run(self._list_recent_sessions(limit))

    def get_session(self, session_id: str) -> SessionRecord | None:
        return self.runner.run(self._get_session(session_id))

    # Playlists
    def list_playlists_by_kind(self, kind: Any) -> list[Any]:
        """Lista playlists por kind (project_public, personal_private, etc)."""
        return self.runner.run(self._list_playlists_by_kind(kind))

    def add_playlist(self, playlist: Any) -> None:
        """Persiste una nueva playlist."""
        self.runner.run(self._add_playlist(playlist))

    # Camouflage
    def count_camouflage_tracks(self) -> int:
        """Cuenta total de tracks en el pool de camuflaje."""
        return self.runner.run(self._count_camouflage_tracks())

    def list_camouflage_genres(self) -> list[tuple[str, int]]:
        """Lista generos con count (genre, count) del pool de camuflaje."""
        return self.runner.run(self._list_camouflage_genres())

    # Async internals
    async def _list_songs_by_role(self, role: SongRole) -> list[Song]:
        async with transactional_session(self.session_factory) as session:
            repo = PostgresSongRepository(session)
            return await repo.list_by_role(role)

    async def _list_pilot_eligible(self, max_songs: int) -> list[Song]:
        async with transactional_session(self.session_factory) as session:
            repo = PostgresSongRepository(session)
            return await repo.list_pilot_eligible(max_songs=max_songs)

    async def _count_active_targets(self) -> int:
        async with transactional_session(self.session_factory) as session:
            repo = PostgresSongRepository(session)
            return await repo.count_active_targets()

    async def _update_song(self, song: Song) -> None:
        async with transactional_session(self.session_factory) as session:
            repo = PostgresSongRepository(session)
            await repo.update(song)

    async def _list_accounts(self) -> list[Account]:
        async with transactional_session(self.session_factory) as session:
            repo = PostgresAccountRepository(session)
            return await repo.all()

    async def _list_modems(self) -> list[Modem]:
        async with transactional_session(self.session_factory) as session:
            repo = PostgresModemRepository(session)
            return await repo.list_all()

    async def _list_artists(self) -> list[Artist]:
        async with transactional_session(self.session_factory) as session:
            repo = PostgresArtistRepository(session)
            return await repo.list_all()

    async def _list_labels(self) -> list[Label]:
        async with transactional_session(self.session_factory) as session:
            repo = PostgresLabelRepository(session)
            return await repo.list_all()

    async def _list_recent_sessions(self, limit: int) -> list[SessionRecord]:
        async with transactional_session(self.session_factory) as session:
            stmt = (
                select(SessionRecordModel)
                .order_by(SessionRecordModel.started_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            return [to_domain_session_record(m) for m in result.scalars().all()]

    async def _get_session(self, session_id: str) -> SessionRecord | None:
        async with transactional_session(self.session_factory) as session:
            repo = PostgresSessionRecordRepository(session)
            return await repo.get(session_id)

    async def _list_playlists_by_kind(self, kind: Any) -> list[Any]:
        from streaming_bot.infrastructure.persistence.postgres.repos import (  # noqa: PLC0415
            PostgresPlaylistRepository,
        )

        async with transactional_session(self.session_factory) as session:
            repo = PostgresPlaylistRepository(session)
            return await repo.list_by_kind(kind)

    async def _add_playlist(self, playlist: Any) -> None:
        from streaming_bot.infrastructure.persistence.postgres.repos import (  # noqa: PLC0415
            PostgresPlaylistRepository,
        )

        async with transactional_session(self.session_factory) as session:
            repo = PostgresPlaylistRepository(session)
            await repo.add(playlist)

    async def _count_camouflage_tracks(self) -> int:
        from streaming_bot.infrastructure.persistence.postgres.models import (  # noqa: PLC0415
            SongModel,
        )

        async with transactional_session(self.session_factory) as session:
            from sqlalchemy import func  # noqa: PLC0415

            stmt = select(func.count()).where(SongModel.role == "camouflage")
            result = await session.execute(stmt)
            return result.scalar() or 0

    async def _list_camouflage_genres(self) -> list[tuple[str, int]]:
        """Agrupa canciones role=CAMOUFLAGE por genero en memoria.

        SongModel no expone genre como columna; vive dentro del DTO de dominio
        bajo `metadata.genre`. Para mantener clean architecture, leemos las
        canciones via repo (mappers ya hidratan SongMetadata) y agrupamos en
        Python. El pool de camuflaje suele ser pequeno (<5K rows) asi que
        no es problema de performance.
        """
        from streaming_bot.domain.song import SongRole  # noqa: PLC0415
        from streaming_bot.infrastructure.persistence.postgres.repos import (  # noqa: PLC0415
            PostgresSongRepository,
        )

        async with transactional_session(self.session_factory) as session:
            repo = PostgresSongRepository(session)
            songs = await repo.list_by_role(SongRole.CAMOUFLAGE)

        counts: dict[str, int] = {}
        for song in songs:
            if not song.metadata.genres:
                counts["unknown"] = counts.get("unknown", 0) + 1
                continue
            for raw_genre in song.metadata.genres:
                genre = raw_genre.strip().lower() or "unknown"
                counts[genre] = counts.get(genre, 0) + 1
        return sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
