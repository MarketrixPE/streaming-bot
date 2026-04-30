"""Repositorio de personas (traits + memoria) por cuenta."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from streaming_bot.domain.persona import Persona


@runtime_checkable
class IPersonaRepository(Protocol):
    async def get(self, account_id: str) -> Persona | None: ...
    async def add(self, persona: Persona) -> None: ...
    async def update_memory(self, persona: Persona) -> None:
        """Solo actualiza la memoria evolutiva (likes/follows/etc), traits inmutables."""
        ...

    async def list_all(self) -> list[Persona]: ...
