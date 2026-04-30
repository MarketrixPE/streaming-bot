"""Tests del PostgresPersonaRepository (traits inmutables + memory snapshots)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from streaming_bot.domain.exceptions import DomainError
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
from streaming_bot.domain.value_objects import Country
from streaming_bot.infrastructure.persistence.postgres.repos.persona_repository import (
    PostgresPersonaRepository,
)


def _make_traits() -> PersonaTraits:
    return PersonaTraits(
        engagement_level=EngagementLevel.ENGAGED,
        preferred_genres=("reggaeton", "trap_latino"),
        preferred_session_hour_local=(18, 23),
        device=DeviceType.DESKTOP_CHROME,
        platform=PlatformProfile.MACOS_DESKTOP,
        ui_language="es-PE",
        timezone="America/Lima",
        country=Country.PE,
        behaviors=BehaviorProbabilities.for_engagement_level(EngagementLevel.ENGAGED),
        typing=TypingProfile(),
        mouse=MouseProfile(),
        session=SessionPattern(),
    )


def _make_persona(account_id: str = "acc-1") -> Persona:
    return Persona(
        account_id=account_id,
        traits=_make_traits(),
        memory=PersonaMemory(
            liked_songs={"spotify:track:1"},
            saved_songs={"spotify:track:2"},
            followed_artists={"spotify:artist:1"},
            recent_searches=["tony jaxx", "perreo 2026"],
        ),
        created_at_iso="2026-04-27T07:00:00+00:00",
    )


async def test_add_then_get_round_trip(session: AsyncSession) -> None:
    repo = PostgresPersonaRepository(session)
    persona = _make_persona()

    await repo.add(persona)
    fetched = await repo.get(persona.account_id)

    assert fetched is not None
    assert fetched.account_id == persona.account_id
    assert fetched.traits.engagement_level == EngagementLevel.ENGAGED
    assert fetched.traits.preferred_genres == ("reggaeton", "trap_latino")
    assert fetched.memory.liked_songs == {"spotify:track:1"}
    assert "tony jaxx" in fetched.memory.recent_searches


async def test_get_unknown_returns_none(session: AsyncSession) -> None:
    repo = PostgresPersonaRepository(session)

    assert await repo.get("does-not-exist") is None


async def test_update_memory_appends_snapshot_and_keeps_traits(
    session: AsyncSession,
) -> None:
    repo = PostgresPersonaRepository(session)
    persona = _make_persona()
    await repo.add(persona)

    persona.memory.liked_songs.add("spotify:track:NEW")
    persona.memory.total_streams = 42
    await repo.update_memory(persona)

    refreshed = await repo.get(persona.account_id)
    assert refreshed is not None
    assert "spotify:track:NEW" in refreshed.memory.liked_songs
    assert refreshed.memory.total_streams == 42
    # Traits permanecen iguales (inmutables): mismo engagement_level/género.
    assert refreshed.traits.engagement_level == EngagementLevel.ENGAGED


async def test_update_memory_unknown_raises(session: AsyncSession) -> None:
    repo = PostgresPersonaRepository(session)
    ghost = _make_persona(account_id="ghost")

    with pytest.raises(DomainError):
        await repo.update_memory(ghost)


async def test_list_all_returns_each_persona(session: AsyncSession) -> None:
    repo = PostgresPersonaRepository(session)
    await repo.add(_make_persona(account_id="a1"))
    await repo.add(_make_persona(account_id="a2"))

    personas = await repo.list_all()

    assert {p.account_id for p in personas} == {"a1", "a2"}
