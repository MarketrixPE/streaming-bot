"""Adaptador ModemPool -> IProxyProvider.

El resto del sistema (orquestador, browser driver) consume `IProxyProvider`. Este
adapter lo conecta al pool de modems sin que el caller sepa que detras hay AT
commands, semaforos y rotaciones de IP.

Mapeo de la interfaz:
- `acquire(country)`         -> `pool.acquire(country=...)` y devuelve ProxyEndpoint local.
- `report_success(endpoint)` -> resuelve modem por endpoint, llama `pool.release(rotate_ip=True)`.
- `report_failure(endpoint)` -> resuelve modem por endpoint, llama `pool.report_failure`.

Mantenemos un mapeo en memoria endpoint -> modem para resolver el modem desde el
ProxyEndpoint que el caller nos devuelve (es la forma natural de la interfaz).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from streaming_bot.domain.modem import Modem
from streaming_bot.domain.ports.proxy_provider import IProxyProvider
from streaming_bot.domain.value_objects import Country, ProxyEndpoint

if TYPE_CHECKING:
    from structlog.stdlib import BoundLogger

    from streaming_bot.infrastructure.modems.modem_pool import ModemPool


@dataclass(slots=True)
class _AcquiredHandle:
    """Mantiene el binding endpoint <-> modem hasta que se libere."""

    modem: Modem
    endpoint: ProxyEndpoint


class ModemPoolProxyProvider(IProxyProvider):
    """Adapter que expone el ModemPool como IProxyProvider."""

    def __init__(
        self,
        *,
        pool: ModemPool,
        logger: BoundLogger,
    ) -> None:
        self._pool = pool
        self._logger = logger
        self._handles: dict[ProxyEndpoint, _AcquiredHandle] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, *, country: Country | None = None) -> ProxyEndpoint | None:
        if country is None:
            # IProxyProvider permite country=None; el pool requiere uno explicito.
            self._logger.debug("modem_proxy_provider_country_none")
            return None
        modem = await self._pool.acquire(country=country)
        if modem is None:
            return None
        endpoint = await self._pool.to_proxy_endpoint(modem)
        async with self._lock:
            self._handles[endpoint] = _AcquiredHandle(modem=modem, endpoint=endpoint)
        return endpoint

    async def report_success(self, proxy: ProxyEndpoint) -> None:
        handle = await self._pop_handle(proxy)
        if handle is None:
            self._logger.warning(
                "modem_proxy_report_success_unknown_endpoint",
                endpoint=proxy.as_url(),
            )
            return
        await self._pool.release(handle.modem, rotate_ip=True)

    async def report_failure(self, proxy: ProxyEndpoint, reason: str) -> None:
        handle = await self._pop_handle(proxy)
        if handle is None:
            self._logger.warning(
                "modem_proxy_report_failure_unknown_endpoint",
                endpoint=proxy.as_url(),
                reason=reason,
            )
            return
        await self._pool.report_failure(handle.modem, reason)

    async def _pop_handle(self, endpoint: ProxyEndpoint) -> _AcquiredHandle | None:
        async with self._lock:
            return self._handles.pop(endpoint, None)
