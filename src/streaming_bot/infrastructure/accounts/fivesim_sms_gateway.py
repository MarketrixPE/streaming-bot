"""FiveSimSmsGateway: ISmsGateway adapter para 5SIM (5sim.net).

5SIM es un broker de SMS comercial que cubre 100+ paises con cuentas
verificables (Spotify, Instagram, Twitter, Telegram, etc.). Lo usamos
como BACKUP cuando la granja propia (FarmSmsHubGateway) no tiene capacidad
en una geo o esta degradada.

API: https://docs.5sim.net/
- POST /v1/user/buy/activation/<country>/<operator>/<product>
- GET  /v1/user/check/<order_id>
- GET  /v1/user/finish/<order_id>
- GET  /v1/user/cancel/<order_id>

Productos relevantes: spotify, instagram, soundcloud, deezer, facebook.

Coste real (2025-2026, snapshots informe): spotify x PE ~0.06 USD,
spotify x US ~0.40 USD, spotify x DE ~0.30 USD. El budget guard del
SpotifyAccountCreator decide si compensa el SMS o si rota a otro pais.
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
class FiveSimConfig:
    api_token: str
    product: str = "spotify"
    operator: str = "any"
    base_url: str = "https://5sim.net"
    request_timeout_seconds: float = 30.0
    poll_interval_seconds: float = 5.0


class FiveSimGatewayError(Exception):
    """Error tipado para fallas del API de 5SIM."""


# Mapeo Country (ISO 3166-1 alpha-2) -> codigo 5SIM (mayoritariamente
# coincide con alpha-2 lowercase pero hay excepciones).
_COUNTRY_TO_5SIM: dict[Country, str] = {
    Country.PE: "peru",
    Country.MX: "mexico",
    Country.US: "usa",
    Country.CL: "chile",
    Country.AR: "argentina",
    Country.CO: "colombia",
    Country.EC: "ecuador",
    Country.BO: "bolivia",
    Country.DO: "dominican",
    Country.PR: "puertorico",
    Country.VE: "venezuela",
    Country.UY: "uruguay",
    Country.PY: "paraguay",
    Country.PA: "panama",
    Country.GT: "guatemala",
    Country.HN: "honduras",
    Country.SV: "elsalvador",
    Country.NI: "nicaragua",
    Country.CR: "costarica",
    Country.BR: "brazil",
    Country.ES: "spain",
    Country.GB: "england",
    Country.CH: "switzerland",
    Country.DE: "germany",
    Country.FR: "france",
    Country.IT: "italy",
    Country.PT: "portugal",
    Country.NL: "netherlands",
    Country.SE: "sweden",
    Country.NO: "norway",
    Country.DK: "denmark",
    Country.FI: "finland",
    Country.IE: "ireland",
    Country.AT: "austria",
    Country.BE: "belgium",
    Country.JP: "japan",
    Country.AU: "australia",
    Country.NZ: "newzealand",
    Country.CA: "canada",
    Country.TH: "thailand",
}


class FiveSimSmsGateway(ISmsGateway):
    """Adapter HTTP del API publico de 5SIM."""

    def __init__(self, config: FiveSimConfig) -> None:
        self._config = config
        self._headers = {
            "Authorization": f"Bearer {config.api_token}",
            "Accept": "application/json",
        }
        self._log = structlog.get_logger("fivesim_gateway")

    async def rent_number(self, *, country: Country) -> TempPhoneNumber:
        country_code = _COUNTRY_TO_5SIM.get(country)
        if country_code is None:
            raise FiveSimGatewayError(f"5sim no cubre el pais {country.value}")

        url = (
            f"{self._config.base_url}/v1/user/buy/activation/"
            f"{country_code}/{self._config.operator}/{self._config.product}"
        )
        async with httpx.AsyncClient(
            timeout=self._config.request_timeout_seconds,
        ) as client:
            response = await client.get(url, headers=self._headers)
            if response.status_code >= 400:
                raise FiveSimGatewayError(
                    f"5sim rent_number failed: {response.status_code} {response.text[:200]}",
                )
            payload: dict[str, Any] = response.json()

        return TempPhoneNumber(
            e164=payload["phone"],
            country=country,
            rented_at=datetime.now(UTC),
            sid=str(payload["id"]),
        )

    async def release_number(self, sid: str) -> None:
        """Cancela la activacion. 5SIM reembolsa si no recibimos SMS."""
        url = f"{self._config.base_url}/v1/user/cancel/{sid}"
        async with httpx.AsyncClient(
            timeout=self._config.request_timeout_seconds,
        ) as client:
            try:
                response = await client.get(url, headers=self._headers)
                if response.status_code not in (200, 400):
                    self._log.warning(
                        "fivesim.cancel_unexpected_status",
                        sid=sid,
                        status=response.status_code,
                    )
            except httpx.HTTPError as exc:
                self._log.warning("fivesim.cancel_request_failed", sid=sid, error=str(exc))

    async def wait_for_sms(
        self,
        *,
        number: TempPhoneNumber,
        timeout_seconds: float = 180.0,
        contains: str = "",
    ) -> SmsMessage | None:
        """Polling al endpoint /check/{order_id} hasta que llegue un SMS."""
        deadline = asyncio.get_event_loop().time() + timeout_seconds
        url = f"{self._config.base_url}/v1/user/check/{number.sid}"

        async with httpx.AsyncClient(
            timeout=self._config.request_timeout_seconds,
        ) as client:
            while asyncio.get_event_loop().time() < deadline:
                try:
                    response = await client.get(url, headers=self._headers)
                except httpx.RequestError as exc:
                    self._log.warning("fivesim.poll_failed", sid=number.sid, error=str(exc))
                    await asyncio.sleep(self._config.poll_interval_seconds)
                    continue

                if response.status_code != 200:
                    self._log.warning(
                        "fivesim.poll_status_error",
                        sid=number.sid,
                        status=response.status_code,
                    )
                    await asyncio.sleep(self._config.poll_interval_seconds)
                    continue

                payload: dict[str, Any] = response.json()
                sms_list: list[dict[str, Any]] = payload.get("sms") or []
                for sms in sms_list:
                    body = sms.get("text") or ""
                    if contains and contains not in body:
                        continue
                    return SmsMessage(
                        from_number=sms.get("sender") or "unknown",
                        body=body,
                        received_at=_parse_iso(sms.get("date")),
                    )

                if payload.get("status") in {"FINISHED", "BANNED", "TIMEOUT"}:
                    return None

                await asyncio.sleep(self._config.poll_interval_seconds)
        return None


def _parse_iso(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(UTC)
