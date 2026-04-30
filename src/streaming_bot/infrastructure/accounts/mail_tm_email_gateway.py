"""Gateway de email temporal usando el servicio mail.tm (API REST pública)."""

from __future__ import annotations

import asyncio
import secrets
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

from streaming_bot.domain.ports.account_creator import EmailMessage, TempEmailAddress
from streaming_bot.infrastructure.accounts.errors import EmailGatewayError

logger = structlog.get_logger("streaming_bot.email.mailtm")


class MailTmEmailGateway:
    """Implementación de IEmailGateway usando mail.tm (https://api.mail.tm).

    Flow:
    1. create_inbox(): GET /domains, POST /accounts, POST /token
    2. wait_for_email(): polling GET /messages con filtros
    3. delete_inbox(): DELETE /accounts/{id}
    """

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        base_url: str = "https://api.mail.tm",
        timeout_seconds: float = 15.0,
    ) -> None:
        self._http = http_client
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._tokens: dict[str, str] = {}  # inbox_id -> JWT token

    async def create_inbox(self) -> TempEmailAddress:
        """Crea una dirección de email temporal y obtiene JWT auth token."""
        log = logger.bind(action="create_inbox")
        try:
            # 1. GET /domains para obtener un dominio activo
            domains_resp = await self._http.get(
                f"{self._base_url}/domains",
                timeout=self._timeout,
            )
            domains_resp.raise_for_status()
            domains_data = domains_resp.json()
            if not domains_data.get("hydra:member"):
                msg = "No hay dominios disponibles en mail.tm"
                raise EmailGatewayError(msg)

            domain = domains_data["hydra:member"][0]["domain"]
            log.debug("domain_obtenido", domain=domain)

            # 2. Generar credenciales
            local_part = secrets.token_urlsafe(10).replace("_", "").replace("-", "").lower()[:12]
            address = f"{local_part}@{domain}"
            password = secrets.token_urlsafe(16)

            # 3. POST /accounts para crear la cuenta
            account_resp = await self._http.post(
                f"{self._base_url}/accounts",
                json={"address": address, "password": password},
                timeout=self._timeout,
            )
            account_resp.raise_for_status()
            account_data = account_resp.json()
            account_id = account_data["id"]
            log.info("inbox_creada", address=address, account_id=account_id)

            # 4. POST /token para autenticarse
            token_resp = await self._http.post(
                f"{self._base_url}/token",
                json={"address": address, "password": password},
                timeout=self._timeout,
            )
            token_resp.raise_for_status()
            token_data = token_resp.json()
            token = token_data["token"]
            self._tokens[account_id] = token

            return TempEmailAddress(
                address=address,
                inbox_id=account_id,
                password=password,
                created_at=datetime.now(UTC),
            )

        except httpx.HTTPStatusError as e:
            msg = f"mail.tm API error: {e.response.status_code}"
            log.error("http_error", status=e.response.status_code, text=e.response.text)
            raise EmailGatewayError(msg) from e
        except Exception as e:
            log.error("create_inbox_failed", error=str(e))
            raise EmailGatewayError(f"Failed to create inbox: {e}") from e

    async def wait_for_email(
        self,
        *,
        inbox: TempEmailAddress,
        timeout_seconds: float = 120.0,
        from_contains: str = "",
        subject_contains: str = "",
    ) -> EmailMessage | None:
        """Espera hasta que llegue un email que cumpla los filtros.

        Polling cada 3s hasta timeout_seconds. Devuelve el primer match o None.
        """
        log = logger.bind(
            action="wait_for_email",
            inbox=inbox.address,
            from_contains=from_contains,
            subject_contains=subject_contains,
        )
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        poll_interval = 3.0

        while asyncio.get_running_loop().time() < deadline:
            try:
                messages = await self._list_messages(inbox)
                for msg_data in messages:
                    from_addr = msg_data.get("from", {}).get("address", "")
                    subject = msg_data.get("subject", "")

                    if (
                        from_contains.lower() in from_addr.lower()
                        and subject_contains.lower() in subject.lower()
                    ):
                        # Obtener el mensaje completo (con body)
                        msg_id = msg_data["id"]
                        full_msg = await self._get_message(inbox, msg_id)
                        log.info("email_recibido", msg_id=msg_id, subject=subject)
                        return full_msg

                # No hay match, esperar antes del siguiente poll
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break
                await asyncio.sleep(min(poll_interval, remaining))

            except EmailGatewayError:
                # Re-raise errors de autenticación
                raise
            except Exception as e:
                log.warning("polling_error", error=str(e))
                await asyncio.sleep(poll_interval)

        log.warning("email_timeout", timeout_seconds=timeout_seconds)
        return None

    async def list_inbox(self, inbox: TempEmailAddress) -> list[EmailMessage]:
        """Lista todos los emails en el inbox."""
        log = logger.bind(action="list_inbox", inbox=inbox.address)
        try:
            messages_data = await self._list_messages(inbox)
            result = []
            for msg_data in messages_data:
                msg_id = msg_data["id"]
                full_msg = await self._get_message(inbox, msg_id)
                result.append(full_msg)
            log.debug("inbox_listada", count=len(result))
            return result
        except Exception as e:
            log.error("list_inbox_failed", error=str(e))
            raise EmailGatewayError(f"Failed to list inbox: {e}") from e

    async def delete_inbox(self, inbox: TempEmailAddress) -> None:
        """Elimina la cuenta de mail.tm. Idempotente (404 OK)."""
        log = logger.bind(action="delete_inbox", inbox=inbox.address)
        try:
            token = await self._ensure_token(inbox)
            resp = await self._http.delete(
                f"{self._base_url}/accounts/{inbox.inbox_id}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=self._timeout,
            )
            if resp.status_code == 404:
                log.debug("inbox_ya_eliminada")
                return
            resp.raise_for_status()
            log.info("inbox_eliminada")
            self._tokens.pop(inbox.inbox_id, None)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                log.debug("inbox_ya_eliminada_404")
                return
            msg = f"mail.tm delete error: {e.response.status_code}"
            log.error("delete_error", status=e.response.status_code)
            raise EmailGatewayError(msg) from e
        except Exception as e:
            log.error("delete_inbox_failed", error=str(e))
            raise EmailGatewayError(f"Failed to delete inbox: {e}") from e

    # --- Private helpers ---

    async def _list_messages(self, inbox: TempEmailAddress) -> list[dict[str, Any]]:
        """GET /messages?page=1 con autenticación."""
        token = await self._ensure_token(inbox)
        resp = await self._http.get(
            f"{self._base_url}/messages",
            params={"page": 1},
            headers={"Authorization": f"Bearer {token}"},
            timeout=self._timeout,
        )
        if resp.status_code == 401:
            # Re-autenticar y reintentar
            await self._reauth(inbox)
            token = self._tokens[inbox.inbox_id]
            resp = await self._http.get(
                f"{self._base_url}/messages",
                params={"page": 1},
                headers={"Authorization": f"Bearer {token}"},
                timeout=self._timeout,
            )
        resp.raise_for_status()
        data = resp.json()
        result: list[dict[str, Any]] = data.get("hydra:member", [])
        return result

    async def _get_message(self, inbox: TempEmailAddress, msg_id: str) -> EmailMessage:
        """GET /messages/{id} para obtener el cuerpo completo."""
        token = await self._ensure_token(inbox)
        resp = await self._http.get(
            f"{self._base_url}/messages/{msg_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=self._timeout,
        )
        if resp.status_code == 401:
            await self._reauth(inbox)
            token = self._tokens[inbox.inbox_id]
            resp = await self._http.get(
                f"{self._base_url}/messages/{msg_id}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=self._timeout,
            )
        resp.raise_for_status()
        msg_data = resp.json()

        return EmailMessage(
            from_address=msg_data.get("from", {}).get("address", ""),
            subject=msg_data.get("subject", ""),
            body_text=msg_data.get("text", ""),
            body_html=msg_data.get("html", [""]),
            received_at=datetime.fromisoformat(
                msg_data.get("createdAt", datetime.now(UTC).isoformat())
            ),
        )

    async def _ensure_token(self, inbox: TempEmailAddress) -> str:
        """Devuelve el token JWT, reautenticando si es necesario."""
        if inbox.inbox_id in self._tokens:
            return self._tokens[inbox.inbox_id]
        await self._reauth(inbox)
        return self._tokens[inbox.inbox_id]

    async def _reauth(self, inbox: TempEmailAddress) -> None:
        """Re-autentica con POST /token usando password."""
        resp = await self._http.post(
            f"{self._base_url}/token",
            json={"address": inbox.address, "password": inbox.password},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        token_data = resp.json()
        self._tokens[inbox.inbox_id] = token_data["token"]
