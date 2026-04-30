"""Tests para StubSmsGateway (mock sin red)."""

from __future__ import annotations

import asyncio

import pytest

from streaming_bot.domain.value_objects import Country
from streaming_bot.infrastructure.accounts.stub_sms_gateway import StubSmsGateway


class TestStubSmsGateway:
    """Tests de StubSmsGateway sin hacer red."""

    @pytest.mark.asyncio
    async def test_rent_number_returns_fake(self) -> None:
        """Verifica que rent_number devuelve números falsos incrementales."""
        gateway = StubSmsGateway()

        phone1 = await gateway.rent_number(country=Country.PE)
        phone2 = await gateway.rent_number(country=Country.MX)

        assert phone1.e164 == "+00000000001"
        assert phone1.country == Country.PE
        assert phone1.sid == "stub-1"

        assert phone2.e164 == "+00000000002"
        assert phone2.country == Country.MX
        assert phone2.sid == "stub-2"

    @pytest.mark.asyncio
    async def test_release_number_is_noop(self) -> None:
        """Verifica que release_number no lanza error (no-op)."""
        gateway = StubSmsGateway()
        phone = await gateway.rent_number(country=Country.PE)

        await gateway.release_number(phone.sid)

    @pytest.mark.asyncio
    async def test_inject_and_wait_for_sms(self) -> None:
        """Verifica que inject_sms alimenta la queue y wait_for_sms la consume."""
        gateway = StubSmsGateway()
        phone = await gateway.rent_number(country=Country.PE)

        # Inyectar mensaje en background
        async def inject_later() -> None:
            await asyncio.sleep(0.1)
            gateway.inject_sms(
                number=phone.e164,
                body="Your Spotify verification code is 999888",
            )

        task = asyncio.create_task(inject_later())
        del task  # Just to start the background task

        # Esperar el SMS
        sms = await gateway.wait_for_sms(
            number=phone,
            timeout_seconds=2.0,
            contains="Spotify",
        )

        assert sms is not None
        assert "Spotify" in sms.body
        assert "999888" in sms.body
        assert sms.from_number == "+15555550000"

    @pytest.mark.asyncio
    async def test_wait_for_sms_timeout_returns_none(self) -> None:
        """Verifica que si no hay mensajes, wait_for_sms retorna None tras timeout."""
        gateway = StubSmsGateway()
        phone = await gateway.rent_number(country=Country.PE)

        sms = await gateway.wait_for_sms(
            number=phone,
            timeout_seconds=0.5,
            contains="Spotify",
        )

        assert sms is None

    @pytest.mark.asyncio
    async def test_inject_filters_by_number(self) -> None:
        """Verifica que wait_for_sms solo recibe mensajes para su número."""
        gateway = StubSmsGateway()
        phone1 = await gateway.rent_number(country=Country.PE)
        phone2 = await gateway.rent_number(country=Country.MX)

        # Inyectar para phone2
        gateway.inject_sms(phone2.e164, "Message for phone2")

        # phone1 no debe recibirlo
        sms = await gateway.wait_for_sms(
            number=phone1,
            timeout_seconds=0.5,
            contains="Message",
        )

        assert sms is None
