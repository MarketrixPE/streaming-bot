"""Caso de uso: ejecutar un stream contra un sitio objetivo.

Diseño:
- Recibe puertos por constructor (Inversión de Dependencias).
- No conoce Playwright, Spotify, Selenium, requests, etc.
- Las particularidades del sitio (selectores, flujo de login) se inyectan
  vía un objeto de estrategia que el caso de uso recibe.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from streaming_bot.domain.entities import Account
from streaming_bot.domain.exceptions import (
    AuthenticationError,
    PermanentError,
    TransientError,
)
from streaming_bot.domain.ports import (
    IAccountRepository,
    IBrowserDriver,
    IBrowserSession,
    IFingerprintGenerator,
    IProxyProvider,
    ISessionStore,
)
from streaming_bot.domain.value_objects import StreamResult

if TYPE_CHECKING:
    from structlog.stdlib import BoundLogger


class ISiteStrategy(Protocol):
    """Estrategia específica del sitio objetivo. Cumple OCP: nuevos sitios
    se añaden creando una nueva estrategia, sin modificar el caso de uso.
    """

    async def is_logged_in(self, page: IBrowserSession) -> bool: ...

    async def login(self, page: IBrowserSession, account: Account) -> None: ...

    async def perform_action(
        self,
        page: IBrowserSession,
        target_url: str,
        listen_seconds: int,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class StreamSongRequest:
    """DTO de entrada al caso de uso."""

    account_id: str
    target_url: str


class StreamSongUseCase:
    """Orquesta un único stream para una cuenta.

    Flujo:
    1. Adquirir proxy coherente con la cuenta.
    2. Generar fingerprint coherente.
    3. Cargar storage_state si existe.
    4. Abrir sesión browser.
    5. Si no logueado → login → guardar state.
    6. Ejecutar acción del sitio.
    7. Reportar métricas + retornar Result.
    """

    def __init__(
        self,
        *,
        browser: IBrowserDriver,
        accounts: IAccountRepository,
        proxies: IProxyProvider,
        fingerprints: IFingerprintGenerator,
        sessions: ISessionStore,
        strategy: ISiteStrategy,
        logger: BoundLogger,
    ) -> None:
        self._browser = browser
        self._accounts = accounts
        self._proxies = proxies
        self._fingerprints = fingerprints
        self._sessions = sessions
        self._strategy = strategy
        self._log = logger

    async def execute(self, request: StreamSongRequest) -> StreamResult:
        started_at = time.monotonic()
        account = await self._accounts.get(request.account_id)
        log = self._log.bind(account_id=account.id, target_url=request.target_url)

        if not account.status.is_usable:
            log.warning("account.skipped", state=account.status.state)
            return StreamResult.failed(
                account_id=account.id,
                duration_ms=0,
                error=f"account_not_usable:{account.status.state}",
            )

        proxy = await self._proxies.acquire(country=account.country)
        fingerprint = self._fingerprints.coherent_for(proxy, fallback_country=account.country)
        storage_state = await self._sessions.load(account.id)

        log = log.bind(
            proxy=proxy.as_url() if proxy else "direct",
            tz=fingerprint.timezone_id,
            locale=fingerprint.locale,
            cached_session=storage_state is not None,
        )

        try:
            async with self._browser.session(
                proxy=proxy,
                fingerprint=fingerprint,
                storage_state=storage_state,
            ) as page:
                if not await self._strategy.is_logged_in(page):
                    log.info("auth.login.start")
                    await self._strategy.login(page, account)
                    await self._sessions.save(account.id, await page.storage_state())
                    log.info("auth.login.success")

                await self._strategy.perform_action(
                    page,
                    request.target_url,
                    fingerprint.realistic_listen_seconds(),
                )

            account.mark_used()
            await self._accounts.update(account)
            if proxy is not None:
                await self._proxies.report_success(proxy)

            duration_ms = int((time.monotonic() - started_at) * 1000)
            log.info("stream.completed", duration_ms=duration_ms)
            return StreamResult.ok(account_id=account.id, duration_ms=duration_ms)

        except AuthenticationError as exc:
            account.deactivate(reason=str(exc))
            await self._accounts.update(account)
            await self._sessions.delete(account.id)
            duration_ms = int((time.monotonic() - started_at) * 1000)
            log.exception("auth.failed", error=str(exc))
            return StreamResult.failed(
                account_id=account.id,
                duration_ms=duration_ms,
                error=str(exc),
            )

        except PermanentError as exc:
            duration_ms = int((time.monotonic() - started_at) * 1000)
            log.exception("stream.permanent_failure", error=str(exc))
            return StreamResult.failed(
                account_id=account.id,
                duration_ms=duration_ms,
                error=str(exc),
            )

        except TransientError as exc:
            if proxy is not None:
                await self._proxies.report_failure(proxy, reason=str(exc))
            duration_ms = int((time.monotonic() - started_at) * 1000)
            log.exception("stream.transient_failure", error=str(exc))
            return StreamResult.failed(
                account_id=account.id,
                duration_ms=duration_ms,
                error=str(exc),
            )
