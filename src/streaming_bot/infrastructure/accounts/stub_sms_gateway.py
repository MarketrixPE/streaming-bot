"""Gateway de SMS stub (mock) para desarrollo sin credenciales de Twilio."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from streaming_bot.domain.ports.account_creator import SmsMessage, TempPhoneNumber
from streaming_bot.domain.value_objects import Country


class StubSmsGateway:
    """Implementación stub de ISmsGateway. No hace red. Útil para dev/testing.

    Permite inyectar mensajes manualmente con inject_sms() para simular
    llegada de SMS sin usar Twilio.
    """

    def __init__(self) -> None:
        self._counter = 0
        self._queue: asyncio.Queue[tuple[str, SmsMessage]] = asyncio.Queue()

    async def rent_number(self, *, country: Country) -> TempPhoneNumber:
        """Devuelve un número falso determinístico."""
        self._counter += 1
        return TempPhoneNumber(
            e164=f"+0000000{self._counter:04d}",
            country=country,
            rented_at=datetime.now(UTC),
            sid=f"stub-{self._counter}",
        )

    async def release_number(self, sid: str) -> None:
        """No-op en stub."""

    async def wait_for_sms(
        self,
        *,
        number: TempPhoneNumber,
        timeout_seconds: float = 180.0,
        contains: str = "",
    ) -> SmsMessage | None:
        """Espera hasta que inject_sms() inyecte un mensaje para este número.

        Si la queue está vacía y nadie la alimenta, espera hasta timeout.
        """
        deadline = asyncio.get_running_loop().time() + timeout_seconds

        while asyncio.get_running_loop().time() < deadline:
            try:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break

                # Intentar obtener mensaje de la queue con timeout
                target_number, msg = await asyncio.wait_for(
                    self._queue.get(), timeout=min(1.0, remaining)
                )

                if target_number == number.e164:
                    # Es para este número, verificar si cumple el filtro
                    if contains.lower() in msg.body.lower():
                        return msg
                    # No cumple, volver a meter en queue
                    self._queue.put_nowait((target_number, msg))

            except TimeoutError:
                continue

        return None

    def inject_sms(
        self,
        number: str,
        body: str,
        from_number: str = "+15555550000",
    ) -> None:
        """Inyecta un SMS en la queue para simular llegada.

        Args:
            number: e164 del número destino (TempPhoneNumber.e164)
            body: contenido del mensaje
            from_number: número emisor (default fake)
        """
        msg = SmsMessage(
            from_number=from_number,
            body=body,
            received_at=datetime.now(UTC),
        )
        self._queue.put_nowait((number, msg))
