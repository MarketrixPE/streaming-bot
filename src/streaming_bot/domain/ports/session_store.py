"""Puerto para persistencia de storage_state (cookies/localStorage)."""

from __future__ import annotations

from typing import Any, Protocol


class ISessionStore(Protocol):
    """Persiste el storage_state cifrado por cuenta."""

    async def load(self, account_id: str) -> dict[str, Any] | None: ...

    async def save(self, account_id: str, state: dict[str, Any]) -> None: ...

    async def delete(self, account_id: str) -> None: ...
