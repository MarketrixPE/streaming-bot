"""FarmSmsHubGateway: ISmsGateway que consume el SMS hub propio (HTTP).

El "SMS hub" es un servicio HTTP que vive junto a la granja de modems
(Lithuania/Bulgaria/Vietnam). Expone:

    POST /numbers/rent          -> alquila un numero E.164 de un modem libre
    DELETE /numbers/{sid}       -> libera el numero (vuelve al pool)
    GET /numbers/{sid}/sms      -> long-poll esperando un SMS entrante

Internamente el daemon de cada modem suscribe URC AT (+CMTI / +CMT) y
empuja el SMS recibido a un Redis stream o Postgres `sms_inbox`. El hub
HTTP expone estado al gateway que vive en el control plane.

Esta clase es solo el adapter cliente (httpx). El servidor SMS hub vive
en `infra/sms_hub/` (codigo + Dockerfile separado).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

from streaming_bot.domain.ports.account_creator import (
    ISmsGateway,
    SmsMessage,
    TempPhoneNumber,
)
from streaming_bot.domain.value_objects import Country


@dataclass(frozen=True, slots=True)
class FarmSmsHubConfig:
    base_url: str  # ej "http://10.10.0.30:8090"
    api_token: str
    request_timeout_seconds: float = 30.0
    poll_interval_seconds: float = 3.0


class FarmSmsHubGateway(ISmsGateway):
    """Cliente del SMS hub propio (granja Lithuania/Bulgaria/Vietnam)."""

    def __init__(self, config: FarmSmsHubConfig) -> None:
        self._config = config
        self._headers = {"Authorization": f"Bearer {config.api_token}"}
        self._log = structlog.get_logger("farm_sms_hub")

    async def rent_number(self, *, country: Country) -> TempPhoneNumber:
        """Alquila un numero E.164 de un modem libre del pais solicitado."""
        async with httpx.AsyncClient(
            timeout=self._config.request_timeout_seconds,
        ) as client:
            response = await client.post(
                f"{self._config.base_url}/numbers/rent",
                headers=self._headers,
                json={"country": country.value},
            )
            response.raise_for_status()
            payload: dict[str, Any] = response.json()

        return TempPhoneNumber(
            e164=payload["e164"],
            country=Country(payload["country"]),
            rented_at=datetime.now(UTC),
            sid=payload["sid"],
        )

    async def release_number(self, sid: str) -> None:
        """Libera el numero (vuelve al pool del modem)."""
        async with httpx.AsyncClient(
            timeout=self._config.request_timeout_seconds,
        ) as client:
            try:
                response = await client.delete(
                    f"{self._config.base_url}/numbers/{sid}",
                    headers=self._headers,
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                # Best-effort release. Si falla, el hub auto-expira en 30 min.
                self._log.warning(
                    "farm_sms.release_failed",
                    sid=sid,
                    error=str(exc),
                )

    async def wait_for_sms(
        self,
        *,
        number: TempPhoneNumber,
        timeout_seconds: float = 180.0,
        contains: str = "",
    ) -> SmsMessage | None:
        """Long-poll al hub esperando un SMS al numero alquilado."""
        deadline = asyncio.get_event_loop().time() + timeout_seconds
        async with httpx.AsyncClient(
            timeout=self._config.request_timeout_seconds,
        ) as client:
            while True:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    return None

                # Pasamos `wait_seconds` al hub para que haga long-poll
                # interno hasta `min(remaining, request_timeout - 1)`.
                wait = min(remaining, self._config.request_timeout_seconds - 1.0)
                try:
                    response = await client.get(
                        f"{self._config.base_url}/numbers/{number.sid}/sms",
                        headers=self._headers,
                        params={"wait_seconds": wait, "contains": contains},
                    )
                except httpx.RequestError as exc:
                    self._log.warning(
                        "farm_sms.poll_request_failed",
                        sid=number.sid,
                        error=str(exc),
                    )
                    await asyncio.sleep(self._config.poll_interval_seconds)
                    continue

                if response.status_code == 204:
                    # Sin SMS aun, reintentar.
                    continue

                if response.status_code >= 400:
                    self._log.warning(
                        "farm_sms.poll_status_error",
                        sid=number.sid,
                        status=response.status_code,
                        body=response.text[:200],
                    )
                    await asyncio.sleep(self._config.poll_interval_seconds)
                    continue

                payload: dict[str, Any] = response.json()
                return SmsMessage(
                    from_number=payload["from"],
                    body=payload["body"],
                    received_at=datetime.fromisoformat(payload["received_at"]),
                )
