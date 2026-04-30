"""Puerto para repositorio de cuentas (interfaz segregada por uso)."""

from __future__ import annotations

from typing import Protocol

from streaming_bot.domain.entities import Account


class IAccountRepository(Protocol):
    """Lectura/escritura de cuentas. Las implementaciones deben cifrar en disco."""

    async def all(self) -> list[Account]: ...

    async def get(self, account_id: str) -> Account: ...

    async def update(self, account: Account) -> None: ...
