"""Caso de uso: ejecutar un stream contra un sitio objetivo.

Diseno:
- Recibe puertos por constructor (Inversion de Dependencias).
- No conoce Playwright, Spotify, Selenium, requests, etc.
- Las particularidades del sitio (selectores, flujo de login) se inyectan
  via un objeto de estrategia que el caso de uso recibe.
- IObservabilityMetrics es opcional: en tests usamos NullMetrics.
- TransientError se RE-LANZA (no se captura): la politica de retry vive
  en StreamOrchestrator (Tenacity AsyncRetrying).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from streaming_bot.application.ports.metrics import IObservabilityMetrics, NullMetrics
from streaming_bot.application.ports.site_strategy import ISiteStrategy
from streaming_bot.domain.exceptions import (
    AuthenticationError,
    PermanentError,
    TransientError,
)
from streaming_bot.domain.ports import (
    IAccountRepository,
    IBrowserDriver,
    IFingerprintGenerator,
    IProxyProvider,
    ISessionStore,
)
from streaming_bot.domain.value_objects import StreamResult

if TYPE_CHECKING:
    from structlog.stdlib import BoundLogger

# Re-export ISiteStrategy para retrocompatibilidad con callers que ya hacen
# `from streaming_bot.application.stream_song import ISiteStrategy`. La
# definicion canonica vive ahora en application/ports/site_strategy.py.
__all__ = ["ISiteStrategy", "StreamSongRequest", "StreamSongUseCase"]


@dataclass(frozen=True, slots=True)
class StreamSongRequest:
    """DTO de entrada al caso de uso."""

    account_id: str
    target_url: str


class StreamSongUseCase:
    """Orquesta un unico stream para una cuenta.

    Flujo:
    1. Adquirir proxy coherente con la cuenta.
    2. Generar fingerprint coherente.
    3. Cargar storage_state si existe.
    4. Abrir sesion browser.
    5. Si no logueado: login, guardar state.
    6. Ejecutar accion del sitio.
    7. Reportar metricas y retornar Result.
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
        metrics: IObservabilityMetrics | None = None,
    ) -> None:
        self._browser = browser
        self._accounts = accounts
        self._proxies = proxies
        self._fingerprints = fingerprints
        self._sessions = sessions
        self._strategy = strategy
        self._log = logger
        self._metrics: IObservabilityMetrics = metrics or NullMetrics()

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
        country_label = fingerprint.country.value

        log = log.bind(
            proxy=proxy.as_url() if proxy else "direct",
            tz=fingerprint.timezone_id,
            locale=fingerprint.locale,
            cached_session=storage_state is not None,
            country=country_label,
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

            duration_seconds = time.monotonic() - started_at
            duration_ms = int(duration_seconds * 1000)
            log.info("stream.completed", duration_ms=duration_ms)
            self._metrics.record_stream(
                country=country_label,
                success=True,
                duration_seconds=duration_seconds,
            )
            return StreamResult.ok(account_id=account.id, duration_ms=duration_ms)

        except AuthenticationError as exc:
            account.deactivate(reason=str(exc))
            await self._accounts.update(account)
            await self._sessions.delete(account.id)
            duration_seconds = time.monotonic() - started_at
            duration_ms = int(duration_seconds * 1000)
            log.exception("auth.failed", error=str(exc))
            self._metrics.record_stream(
                country=country_label,
                success=False,
                duration_seconds=duration_seconds,
            )
            self._metrics.increment_account_blocked()
            return StreamResult.failed(
                account_id=account.id,
                duration_ms=duration_ms,
                error=str(exc),
            )

        except PermanentError as exc:
            duration_seconds = time.monotonic() - started_at
            duration_ms = int(duration_seconds * 1000)
            log.exception("stream.permanent_failure", error=str(exc))
            self._metrics.record_stream(
                country=country_label,
                success=False,
                duration_seconds=duration_seconds,
            )
            return StreamResult.failed(
                account_id=account.id,
                duration_ms=duration_ms,
                error=str(exc),
            )

        except TransientError as exc:
            # Reportamos al pool y re-lanzamos: la POLITICA de retry es del
            # StreamOrchestrator (Tenacity AsyncRetrying con backoff exponencial),
            # no del use case. Si capturasemos aqui, el retry nunca dispararia
            # (auditoria seccion 1: retry roto).
            if proxy is not None:
                await self._proxies.report_failure(proxy, reason=str(exc))
                self._metrics.increment_proxy_failure()
            duration_seconds = time.monotonic() - started_at
            duration_ms = int(duration_seconds * 1000)
            log.exception("stream.transient_failure", error=str(exc), duration_ms=duration_ms)
            self._metrics.record_stream(
                country=country_label,
                success=False,
                duration_seconds=duration_seconds,
            )
            raise
