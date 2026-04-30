"""Tests para MailTmEmailGateway usando httpx.MockTransport."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from streaming_bot.infrastructure.accounts.errors import EmailGatewayError
from streaming_bot.infrastructure.accounts.mail_tm_email_gateway import (
    MailTmEmailGateway,
)


class TestMailTmEmailGateway:
    """Tests de MailTmEmailGateway con mock de HTTP."""

    @pytest.fixture
    def mock_transport(self) -> httpx.MockTransport:
        """Mock transport que simula las respuestas de mail.tm API."""

        def handler(request: httpx.Request) -> httpx.Response:  # noqa: PLR0911
            # GET /domains
            if request.url.path == "/domains":
                return httpx.Response(
                    200,
                    json={
                        "hydra:member": [{"id": "1", "domain": "example.mail.tm", "isActive": True}]
                    },
                )

            # POST /accounts
            if request.url.path == "/accounts" and request.method == "POST":
                return httpx.Response(
                    201,
                    json={
                        "id": "acc123",
                        "address": "test@example.mail.tm",
                        "createdAt": datetime.now(UTC).isoformat(),
                    },
                )

            # POST /token
            if request.url.path == "/token" and request.method == "POST":
                return httpx.Response(
                    200,
                    json={"token": "jwt_token_abc123"},
                )

            # GET /messages
            if request.url.path == "/messages" and request.method == "GET":
                # Primera vez: sin mensajes; segunda vez: con mensaje
                # (simplificado para el test)
                return httpx.Response(
                    200,
                    json={
                        "hydra:member": [
                            {
                                "id": "msg1",
                                "from": {"address": "no-reply@spotify.com"},
                                "subject": "Confirm your email",
                                "createdAt": datetime.now(UTC).isoformat(),
                            }
                        ]
                    },
                )

            # GET /messages/{id}  # noqa: ERA001
            if request.url.path.startswith("/messages/") and request.method == "GET":
                return httpx.Response(
                    200,
                    json={
                        "id": "msg1",
                        "from": {"address": "no-reply@spotify.com"},
                        "subject": "Confirm your email",
                        "text": "Click here to confirm: https://example.com/confirm",
                        "html": ["<p>Click here to confirm</p>"],
                        "createdAt": datetime.now(UTC).isoformat(),
                    },
                )

            # DELETE /accounts/{id}  # noqa: ERA001
            if request.url.path.startswith("/accounts/") and request.method == "DELETE":
                return httpx.Response(204)

            return httpx.Response(404, json={"error": "Not found"})

        return httpx.MockTransport(handler)

    @pytest.fixture
    async def gateway(self, mock_transport: httpx.MockTransport) -> MailTmEmailGateway:
        """Gateway con mock transport."""
        client = httpx.AsyncClient(transport=mock_transport, base_url="https://api.mail.tm")
        return MailTmEmailGateway(
            http_client=client,
            base_url="https://api.mail.tm",
            timeout_seconds=15.0,
        )

    @pytest.mark.asyncio
    async def test_create_inbox_success(self, gateway: MailTmEmailGateway) -> None:
        """Verifica que create_inbox devuelve un TempEmailAddress válido."""
        inbox = await gateway.create_inbox()

        assert inbox.address.endswith("@example.mail.tm")
        assert inbox.inbox_id == "acc123"
        assert inbox.password
        assert inbox.created_at

    @pytest.mark.asyncio
    async def test_wait_for_email_finds_match(self, gateway: MailTmEmailGateway) -> None:
        """Verifica que wait_for_email encuentra un mensaje que cumple filtros."""
        inbox = await gateway.create_inbox()

        email = await gateway.wait_for_email(
            inbox=inbox,
            timeout_seconds=5.0,
            from_contains="spotify.com",
            subject_contains="Confirm",
        )

        assert email is not None
        assert "spotify.com" in email.from_address
        assert "Confirm" in email.subject
        assert email.body_text
        assert email.received_at

    @pytest.mark.asyncio
    async def test_list_inbox(self, gateway: MailTmEmailGateway) -> None:
        """Verifica que list_inbox devuelve lista de EmailMessage."""
        inbox = await gateway.create_inbox()

        messages = await gateway.list_inbox(inbox)

        assert len(messages) >= 1
        assert messages[0].from_address == "no-reply@spotify.com"

    @pytest.mark.asyncio
    async def test_delete_inbox_idempotent(self, gateway: MailTmEmailGateway) -> None:
        """Verifica que delete_inbox es idempotente (404 OK)."""
        inbox = await gateway.create_inbox()

        await gateway.delete_inbox(inbox)
        # Segunda vez debería ser OK también (idempotente)
        await gateway.delete_inbox(inbox)

    @pytest.mark.asyncio
    async def test_no_domains_available_raises(self) -> None:
        """Verifica que si no hay dominios, se lanza EmailGatewayError."""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/domains":
                return httpx.Response(200, json={"hydra:member": []})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport, base_url="https://api.mail.tm")
        gateway = MailTmEmailGateway(
            http_client=client,
            base_url="https://api.mail.tm",
        )

        with pytest.raises(EmailGatewayError, match="No hay dominios disponibles"):
            await gateway.create_inbox()
