"""Gateway de SMS real usando Twilio Programmable SMS API."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

from streaming_bot.domain.ports.account_creator import SmsMessage, TempPhoneNumber
from streaming_bot.domain.value_objects import Country
from streaming_bot.infrastructure.accounts.errors import SmsGatewayError

logger = structlog.get_logger("streaming_bot.sms.twilio")


class TwilioSmsGateway:
    """Implementación de ISmsGateway usando Twilio Programmable SMS.

    Requiere credenciales de Twilio. Si no están configuradas, lazy-fail
    en el primer método invocado (NO en __init__).
    """

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        account_sid: str,
        auth_token: str,
    ) -> None:
        self._http = http_client
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._base_url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}"

    def _check_credentials(self) -> None:
        """Verifica que las credenciales estén configuradas."""
        if not self._account_sid or not self._auth_token:
            msg = "twilio_credentials_missing: account_sid o auth_token vacío"
            raise SmsGatewayError(msg)

    def _auth(self) -> httpx.Auth:
        """Devuelve HTTP Basic Auth para Twilio."""
        return httpx.BasicAuth(self._account_sid, self._auth_token)

    async def rent_number(self, *, country: Country) -> TempPhoneNumber:
        """Busca y compra un número disponible en el país especificado."""
        self._check_credentials()
        log = logger.bind(action="rent_number", country=country.value)

        try:
            # 1. Buscar números disponibles (Mobile type)
            iso2 = country.value
            search_url = f"{self._base_url}/AvailablePhoneNumbers/{iso2}/Mobile.json"
            search_resp = await self._http.get(search_url, auth=self._auth())
            search_resp.raise_for_status()
            available = search_resp.json().get("available_phone_numbers", [])

            if not available:
                msg = f"No hay números disponibles para {country.value}"
                log.error("no_numbers_available")
                raise SmsGatewayError(msg)

            # 2. Comprar el primer número disponible
            number_to_buy = available[0]["phone_number"]
            log.debug("comprando_numero", number=number_to_buy)

            buy_url = f"{self._base_url}/IncomingPhoneNumbers.json"
            buy_resp = await self._http.post(
                buy_url,
                data={"PhoneNumber": number_to_buy},
                auth=self._auth(),
            )
            buy_resp.raise_for_status()
            buy_data = buy_resp.json()
            phone_sid = buy_data["sid"]

            log.info("numero_comprado", number=number_to_buy, sid=phone_sid)
            return TempPhoneNumber(
                e164=number_to_buy,
                country=country,
                rented_at=datetime.now(UTC),
                sid=phone_sid,
            )

        except httpx.HTTPStatusError as e:
            msg = f"Twilio API error: {e.response.status_code}"
            log.error("http_error", status=e.response.status_code, text=e.response.text)
            raise SmsGatewayError(msg) from e
        except Exception as e:
            log.error("rent_number_failed", error=str(e))
            raise SmsGatewayError(f"Failed to rent number: {e}") from e

    async def release_number(self, sid: str) -> None:
        """Libera (elimina) un número de Twilio."""
        self._check_credentials()
        log = logger.bind(action="release_number", sid=sid)

        try:
            url = f"{self._base_url}/IncomingPhoneNumbers/{sid}.json"
            resp = await self._http.delete(url, auth=self._auth())
            resp.raise_for_status()
            log.info("numero_liberado")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                log.debug("numero_ya_liberado_404")
                return
            msg = f"Twilio release error: {e.response.status_code}"
            log.error("release_error", status=e.response.status_code)
            raise SmsGatewayError(msg) from e
        except Exception as e:
            log.error("release_number_failed", error=str(e))
            raise SmsGatewayError(f"Failed to release number: {e}") from e

    async def wait_for_sms(
        self,
        *,
        number: TempPhoneNumber,
        timeout_seconds: float = 180.0,
        contains: str = "",
    ) -> SmsMessage | None:
        """Espera hasta que llegue un SMS al número que contenga el texto especificado.

        Polling cada 5s hasta timeout_seconds.
        """
        self._check_credentials()
        log = logger.bind(
            action="wait_for_sms",
            number=number.e164,
            contains=contains,
        )
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        poll_interval = 5.0

        while asyncio.get_running_loop().time() < deadline:
            try:
                url = f"{self._base_url}/Messages.json"
                resp = await self._http.get(
                    url,
                    params={"To": number.e164, "PageSize": 20},
                    auth=self._auth(),
                )
                resp.raise_for_status()
                messages: list[dict[str, Any]] = resp.json().get("messages", [])

                for msg_data in messages:
                    body = msg_data.get("body", "")
                    if contains.lower() in body.lower():
                        log.info("sms_recibido", from_number=msg_data["from"])
                        return SmsMessage(
                            from_number=msg_data["from"],
                            body=body,
                            received_at=datetime.fromisoformat(msg_data["date_created"]),
                        )

                # No hay match, esperar
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break
                await asyncio.sleep(min(poll_interval, remaining))

            except Exception as e:
                log.warning("polling_error", error=str(e))
                await asyncio.sleep(poll_interval)

        log.warning("sms_timeout", timeout_seconds=timeout_seconds)
        return None
