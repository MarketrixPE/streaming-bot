"""Puerto para proveedor de proxies con health-check."""

from __future__ import annotations

from typing import Protocol

from streaming_bot.domain.value_objects import Country, ProxyEndpoint


class IProxyProvider(Protocol):
    """Provee proxies sanos, idealmente respetando el país de la cuenta."""

    async def acquire(self, *, country: Country | None = None) -> ProxyEndpoint | None:
        """Retorna un proxy sano o None si no hay (modo direct)."""
        ...

    async def report_failure(self, proxy: ProxyEndpoint, reason: str) -> None:
        """Marca un proxy como muerto y lo saca de rotación temporalmente."""
        ...

    async def report_success(self, proxy: ProxyEndpoint) -> None:
        """Reporta uso exitoso (para scoring)."""
        ...
