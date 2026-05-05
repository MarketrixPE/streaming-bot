"""Tests del `PostgresPersonaMemoryRepository`.

Estrategia:
- Usamos SQLite in-memory (aiosqlite) con `StaticPool` para evitar dependencia
  de un Postgres real, manteniendo el contrato semantico (insert + indices +
  ORDER BY DESC). Equivale a "mockear asyncpg" en el sentido de no requerir
  servicio externo, pero ejerciendo SQL real para detectar bugs de mapeo.
- Verificamos:
  * `apply_delta` persiste cada evento con sus campos correctos.
  * `apply_delta` con lote vacio es no-op (no abre transaccion innecesaria).
  * `get_state` reconstruye el agregado deduplicando sets y sumando counters.
  * `list_recent_actions` ordena DESC y respeta el `limit`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from streaming_bot.domain.persona import (
    BehaviorProbabilities,
    DeviceType,
    EngagementLevel,
    MouseProfile,
    Persona,
    PersonaMemory,
    PersonaTraits,
    PlatformProfile,
    SessionPattern,
    TypingProfile,
)
from streaming_bot.domain.ports.persona_memory_repo import (
    PersonaMemoryEvent,
    PersonaMemoryEventType,
)
from streaming_bot.domain.value_objects import Country
from streaming_bot.infrastructure.persistence.postgres.models import Base
from streaming_bot.infrastructure.persistence.postgres.repos.persona_memory_repository import (
    PostgresPersonaMemoryRepository,
)
from streaming_bot.infrastructure.persistence.postgres.repos.persona_repository import (
    PostgresPersonaRepository,
)


@pytest_asyncio.fixture()
async def session() -> AsyncIterator[AsyncSession]:
    """Sesion async fresh por test contra SQLite in-memory."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as s:
        yield s

    await engine.dispose()


def _persona(account_id: str = "acc-mem-1") -> Persona:
    """Construye una persona valida para satisfacer la FK persona_id."""
    traits = PersonaTraits(
        engagement_level=EngagementLevel.ENGAGED,
        preferred_genres=("reggaeton",),
        preferred_session_hour_local=(18, 23),
        device=DeviceType.DESKTOP_CHROME,
        platform=PlatformProfile.WINDOWS_DESKTOP,
        ui_language="es-PE",
        timezone="America/Lima",
        country=Country.PE,
        behaviors=BehaviorProbabilities.for_engagement_level(EngagementLevel.ENGAGED),
        typing=TypingProfile(),
        mouse=MouseProfile(),
        session=SessionPattern(),
    )
    return Persona(
        account_id=account_id,
        traits=traits,
        memory=PersonaMemory(),
        created_at_iso="2026-01-01T00:00:00+00:00",
    )


async def _seed_persona(session: AsyncSession, account_id: str = "acc-mem-1") -> str:
    """Inserta la fila padre en `personas` (necesaria por la FK)."""
    repo = PostgresPersonaRepository(session)
    await repo.add(_persona(account_id))
    return account_id


def _event(
    *,
    persona_id: str,
    event_type: PersonaMemoryEventType,
    target_uri: str | None = None,
    when: datetime,
    metadata: dict[str, str | int] | None = None,
) -> PersonaMemoryEvent:
    """Helper para construir eventos de dominio en los tests."""
    return PersonaMemoryEvent(
        persona_id=persona_id,
        account_id=persona_id,
        event_type=event_type,
        timestamp=when,
        target_uri=target_uri,
        metadata=dict(metadata or {}),
    )


class TestApplyDelta:
    async def test_persists_each_event(self, session: AsyncSession) -> None:
        persona_id = await _seed_persona(session)
        repo = PostgresPersonaMemoryRepository(session)
        now = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)
        events = [
            _event(
                persona_id=persona_id,
                event_type=PersonaMemoryEventType.LIKE,
                target_uri="spotify:track:a",
                when=now,
            ),
            _event(
                persona_id=persona_id,
                event_type=PersonaMemoryEventType.SAVE,
                target_uri="spotify:track:b",
                when=now + timedelta(seconds=1),
            ),
        ]
        await repo.apply_delta(persona_id=persona_id, account_id=persona_id, events=events)

        recent = await repo.list_recent_actions(persona_id, limit=10)
        assert len(recent) == 2
        kinds = {e.event_type for e in recent}
        assert kinds == {PersonaMemoryEventType.LIKE, PersonaMemoryEventType.SAVE}

    async def test_empty_delta_is_noop(self, session: AsyncSession) -> None:
        persona_id = await _seed_persona(session)
        repo = PostgresPersonaMemoryRepository(session)
        await repo.apply_delta(persona_id=persona_id, account_id=persona_id, events=[])
        assert await repo.list_recent_actions(persona_id) == []


class TestGetState:
    async def test_aggregates_log_correctly(self, session: AsyncSession) -> None:
        persona_id = await _seed_persona(session)
        repo = PostgresPersonaMemoryRepository(session)
        base = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)
        events = [
            _event(
                persona_id=persona_id,
                event_type=PersonaMemoryEventType.LIKE,
                target_uri="spotify:track:a",
                when=base,
            ),
            _event(
                persona_id=persona_id,
                event_type=PersonaMemoryEventType.LIKE,
                target_uri="spotify:track:a",  # duplicado: deduplicarse
                when=base + timedelta(seconds=1),
            ),
            _event(
                persona_id=persona_id,
                event_type=PersonaMemoryEventType.SAVE,
                target_uri="spotify:track:b",
                when=base + timedelta(seconds=2),
            ),
            _event(
                persona_id=persona_id,
                event_type=PersonaMemoryEventType.FOLLOW_ARTIST,
                target_uri="spotify:artist:x",
                when=base + timedelta(seconds=3),
            ),
            _event(
                persona_id=persona_id,
                event_type=PersonaMemoryEventType.SEARCH,
                when=base + timedelta(seconds=4),
                metadata={"query": "perreo"},
            ),
            _event(
                persona_id=persona_id,
                event_type=PersonaMemoryEventType.STREAM,
                when=base + timedelta(seconds=5),
                metadata={"minutes": 12, "counted": 1},
            ),
        ]
        await repo.apply_delta(persona_id=persona_id, account_id=persona_id, events=events)

        agg = await repo.get_state(persona_id)
        assert agg.persona_id == persona_id
        assert set(agg.liked_uris) == {"spotify:track:a"}
        assert set(agg.saved_uris) == {"spotify:track:b"}
        assert set(agg.followed_artists) == {"spotify:artist:x"}
        assert "perreo" in agg.searches
        assert agg.streamed_minutes == 12
        assert agg.streams_counted == 1
        assert agg.total_events == len(events)
        assert agg.last_event_at is not None

    async def test_empty_persona_returns_empty_aggregate(
        self,
        session: AsyncSession,
    ) -> None:
        persona_id = await _seed_persona(session)
        repo = PostgresPersonaMemoryRepository(session)
        agg = await repo.get_state(persona_id)
        assert agg.persona_id == persona_id
        assert agg.total_events == 0
        assert agg.last_event_at is None
        assert agg.liked_uris == ()


class TestListRecentActions:
    async def test_orders_desc_by_timestamp(self, session: AsyncSession) -> None:
        persona_id = await _seed_persona(session)
        repo = PostgresPersonaMemoryRepository(session)
        base = datetime(2026, 5, 4, 10, 0, tzinfo=UTC)
        events = [
            _event(
                persona_id=persona_id,
                event_type=PersonaMemoryEventType.LIKE,
                target_uri=f"spotify:track:{i}",
                when=base + timedelta(seconds=i),
            )
            for i in range(5)
        ]
        await repo.apply_delta(persona_id=persona_id, account_id=persona_id, events=events)

        recent = await repo.list_recent_actions(persona_id, limit=10)
        timestamps = [e.timestamp for e in recent]
        assert timestamps == sorted(timestamps, reverse=True)
        assert recent[0].target_uri == "spotify:track:4"

    async def test_respects_limit(self, session: AsyncSession) -> None:
        persona_id = await _seed_persona(session)
        repo = PostgresPersonaMemoryRepository(session)
        base = datetime(2026, 5, 4, 10, 0, tzinfo=UTC)
        events = [
            _event(
                persona_id=persona_id,
                event_type=PersonaMemoryEventType.LIKE,
                target_uri=f"spotify:track:{i}",
                when=base + timedelta(seconds=i),
            )
            for i in range(8)
        ]
        await repo.apply_delta(persona_id=persona_id, account_id=persona_id, events=events)
        recent = await repo.list_recent_actions(persona_id, limit=3)
        assert len(recent) == 3

    async def test_zero_limit_returns_empty(self, session: AsyncSession) -> None:
        persona_id = await _seed_persona(session)
        repo = PostgresPersonaMemoryRepository(session)
        await repo.apply_delta(
            persona_id=persona_id,
            account_id=persona_id,
            events=[
                _event(
                    persona_id=persona_id,
                    event_type=PersonaMemoryEventType.LIKE,
                    target_uri="spotify:track:a",
                    when=datetime(2026, 5, 4, 12, 0, tzinfo=UTC),
                ),
            ],
        )
        assert await repo.list_recent_actions(persona_id, limit=0) == []
