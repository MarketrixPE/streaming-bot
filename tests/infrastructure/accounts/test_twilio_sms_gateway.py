"""Tests para TwilioSmsGateway usando httpx.MockTransport."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from streaming_bot.domain.value_objects import Country
from streaming_bot.infrastructure.accounts.errors import SmsGatewayError
from streaming_bot.infrastructure.accounts.twilio_sms_gateway import (
    TwilioSmsGateway,
)


class TestTwilioSmsGateway:
    """Tests de TwilioSmsGateway con mock de HTTP."""

    @pytest.fixture
    def mock_transport(self) -> httpx.MockTransport:
        """Mock transport que simula las respuestas de Twilio API."""

        def handler(request: httpx.Request) -> httpx.Response:
            # GET /AvailablePhoneNumbers/{ISO2}/Mobile.json  # noqa: ERA001
            if "AvailablePhoneNumbers" in request.url.path and request.method == "GET":
                return httpx.Response(
                    200,
                    json={
                        "available_phone_numbers": [
                            {"phone_number": "+51987654321", "friendly_name": "Lima"},
                            {"phone_number": "+51987654322", "friendly_name": "Lima"},
                        ]
                    },
                )

            # POST /IncomingPhoneNumbers.json (comprar número)
            if "IncomingPhoneNumbers" in request.url.path and request.method == "POST":
                return httpx.Response(
                    201,
                    json={
                        "sid": "PN123abc456def",
                        "phone_number": "+51987654321",
                        "date_created": datetime.now(UTC).isoformat(),
                    },
                )

            # DELETE /IncomingPhoneNumbers/{sid}.json  # noqa: ERA001
            if request.url.path.startswith("/2010-04-01/Accounts/") and request.method == "DELETE":
                return httpx.Response(204)

            # GET /Messages.json (listar mensajes)
            if "Messages.json" in request.url.path and request.method == "GET":
                return httpx.Response(
                    200,
                    json={
                        "messages": [
                            {
                                "sid": "SM123",
                                "from": "+15555550000",
                                "to": "+51987654321",
                                "body": "Your Spotify verification code is 123456",
                                "date_created": datetime.now(UTC).isoformat(),
                            }
                        ]
                    },
                )

            return httpx.Response(404, json={"error": "Not found"})

        return httpx.MockTransport(handler)

    @pytest.fixture
    async def gateway(self, mock_transport: httpx.MockTransport) -> TwilioSmsGateway:
        """Gateway con mock transport."""
        client = httpx.AsyncClient(
            transport=mock_transport,
            base_url="https://api.twilio.com",
        )
        return TwilioSmsGateway(
            http_client=client,
            account_sid="AC123testaccount",
            auth_token="test_auth_token",
        )

    @pytest.mark.asyncio
    async def test_rent_number_success(self, gateway: TwilioSmsGateway) -> None:
        """Verifica que rent_number busca disponibles y compra el primero."""
        phone = await gateway.rent_number(country=Country.PE)

        assert phone.e164 == "+51987654321"
        assert phone.country == Country.PE
        assert phone.sid == "PN123abc456def"
        assert phone.rented_at

    @pytest.mark.asyncio
    async def test_release_number_success(self, gateway: TwilioSmsGateway) -> None:
        """Verifica que release_number elimina el número."""
        await gateway.release_number(sid="PN123abc456def")

    @pytest.mark.asyncio
    async def test_wait_for_sms_finds_match(self, gateway: TwilioSmsGateway) -> None:
        """Verifica que wait_for_sms encuentra un mensaje que contiene el texto."""
        phone = await gateway.rent_number(country=Country.PE)

        sms = await gateway.wait_for_sms(
            number=phone,
            timeout_seconds=5.0,
            contains="Spotify",
        )

        assert sms is not None
        assert "Spotify" in sms.body
        assert sms.from_number == "+15555550000"
        assert sms.received_at

    @pytest.mark.asyncio
    async def test_missing_credentials_raises_on_first_use(self) -> None:
        """Verifica que lazy-fail: error solo cuando se invoca el primer método."""
        client = httpx.AsyncClient()
        gateway = TwilioSmsGateway(
            http_client=client,
            account_sid="",  # vacío
            auth_token="",
        )

        # No debe fallar en construcción
        assert gateway is not None

        # Debe fallar en el primer método invocado
        with pytest.raises(SmsGatewayError, match="twilio_credentials_missing"):
            await gateway.rent_number(country=Country.PE)

    @pytest.mark.asyncio
    async def test_no_numbers_available_raises(self) -> None:
        """Verifica que si no hay números disponibles, se lanza SmsGatewayError."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "AvailablePhoneNumbers" in request.url.path:
                return httpx.Response(200, json={"available_phone_numbers": []})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport, base_url="https://api.twilio.com")
        gateway = TwilioSmsGateway(
            http_client=client,
            account_sid="AC123",
            auth_token="token",
        )

        with pytest.raises(SmsGatewayError, match="No hay números disponibles"):
            await gateway.rent_number(country=Country.PE)
