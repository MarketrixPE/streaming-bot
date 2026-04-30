"""Repositorio de modems (estado persistido para reanudar tras reinicio)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from streaming_bot.domain.modem import Modem
from streaming_bot.domain.value_objects import Country


@runtime_checkable
class IModemRepository(Protocol):
    async def get(self, modem_id: str) -> Modem | None: ...
    async def add(self, modem: Modem) -> None: ...
    async def update(self, modem: Modem) -> None: ...
    async def list_all(self) -> list[Modem]: ...
    async def list_by_country(self, country: Country) -> list[Modem]: ...
