"""SmsGatewayRouter: aplica preferencia farm-first con failover a backups.

Politica:
1. Intenta el primer gateway (FarmSmsHubGateway): si el pais esta cubierto
   y el modem responde, usa la granja propia (coste minimo, OPSEC maximo).
2. Si falla con error tipado o si el pais no esta cubierto, cae al
   siguiente gateway (FiveSimSmsGateway o TwilioSmsGateway).
3. Releases / waits se enrutan al gateway que efectivamente alquilo el
   numero (cada TempPhoneNumber lleva su sid; usamos un mapping interno
   para saber a quien dirigirlo).

Es el implementador de ISmsGateway que el SpotifyAccountCreator inyecta:
asi el use case no necesita saber que hay multiples backends.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import structlog

from streaming_bot.domain.ports.account_creator import (
    ISmsGateway,
    SmsMessage,
    TempPhoneNumber,
)
from streaming_bot.domain.value_objects import Country


class SmsGatewayRouter(ISmsGateway):
    """Router con failover ordenado entre N ISmsGateway."""

    def __init__(
        self,
        *,
        gateways: Sequence[ISmsGateway],
    ) -> None:
        if not gateways:
            raise ValueError("SmsGatewayRouter requiere al menos un gateway")
        self._gateways: list[ISmsGateway] = list(gateways)
        self._sid_to_gateway: dict[str, ISmsGateway] = {}
        self._lock = asyncio.Lock()
        self._log = structlog.get_logger("sms_router")

    async def rent_number(self, *, country: Country) -> TempPhoneNumber:
        """Recorre los gateways en orden hasta que uno responda."""
        last_error: Exception | None = None
        for index, gateway in enumerate(self._gateways):
            try:
                number = await gateway.rent_number(country=country)
            except Exception as exc:
                self._log.warning(
                    "sms_router.gateway_rent_failed",
                    gateway_index=index,
                    gateway=type(gateway).__name__,
                    country=country.value,
                    error=str(exc),
                )
                last_error = exc
                continue
            async with self._lock:
                self._sid_to_gateway[number.sid] = gateway
            return number
        raise RuntimeError(
            f"todos los SMS gateways fallaron para country={country.value}: {last_error}",
        )

    async def release_number(self, sid: str) -> None:
        async with self._lock:
            gateway = self._sid_to_gateway.pop(sid, None)
        if gateway is None:
            self._log.warning("sms_router.release_unknown_sid", sid=sid)
            return
        await gateway.release_number(sid)

    async def wait_for_sms(
        self,
        *,
        number: TempPhoneNumber,
        timeout_seconds: float = 180.0,
        contains: str = "",
    ) -> SmsMessage | None:
        async with self._lock:
            gateway = self._sid_to_gateway.get(number.sid)
        if gateway is None:
            self._log.error("sms_router.wait_unknown_sid", sid=number.sid)
            return None
        return await gateway.wait_for_sms(
            number=number,
            timeout_seconds=timeout_seconds,
            contains=contains,
        )
