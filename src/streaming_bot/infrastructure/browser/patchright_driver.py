"""PatchrightDriver: drop-in del PlaywrightDriver usando Patchright (Chromium patched).

Patchright es un fork de Playwright que parchea las firmas detectables de
CDP (Chrome DevTools Protocol) reportadas en blogs antibot 2024-2026:
- Esconde `navigator.webdriver`.
- Patchea Runtime.enable / Console.enable leaks.
- Anula los handles de "RemoteObjectId" tipicos.
- Mantiene API 100% compatible con playwright.async_api.

Usamos Patchright para flujos primarios (Spotify Web Player, login). El mix
con Camoufox (Firefox stealth) se gestiona via `MixedBrowserDriver`.

NOTA: el package se importa como `patchright.async_api` con la misma API
que `playwright.async_api`. La clase aqui es practicamente identica al
PlaywrightDriver: cambia solo el origen del modulo.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import structlog

from streaming_bot.application.ports.metrics import IObservabilityMetrics, NullMetrics
from streaming_bot.domain.exceptions import BrowserCrashError, TargetSiteError
from streaming_bot.domain.ports.browser import IBrowserDriver, IBrowserSession
from streaming_bot.domain.value_objects import Fingerprint, ProxyEndpoint
from streaming_bot.infrastructure.browser.stealth import STEALTH_INIT_SCRIPT

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class _PatchrightSession(IBrowserSession):
    """Wrapper sobre Page de Patchright que cumple IBrowserSession."""

    def __init__(self, page: Any, default_timeout_ms: int) -> None:
        self._page = page
        self._page.set_default_timeout(default_timeout_ms)

    async def goto(self, url: str, *, wait_until: str = "networkidle") -> None:
        try:
            await self._page.goto(url, wait_until=wait_until)
        except Exception as exc:
            from patchright.async_api import (
                Error as PatchrightError,
            )
            from patchright.async_api import (
                TimeoutError as PatchrightTimeoutError,
            )

            if isinstance(exc, PatchrightTimeoutError):
                raise TargetSiteError(f"timeout navegando a {url}") from exc
            if isinstance(exc, PatchrightError):
                raise BrowserCrashError(str(exc)) from exc
            raise

    async def fill(self, selector: str, value: str) -> None:
        await self._page.fill(selector, value)

    async def click(self, selector: str) -> None:
        await self._page.click(selector)

    async def wait_for_selector(self, selector: str, *, timeout_ms: int = 30_000) -> None:
        try:
            await self._page.wait_for_selector(selector, timeout=timeout_ms)
        except Exception as exc:
            raise TargetSiteError(f"selector no encontrado: {selector}") from exc

    async def evaluate(self, expression: str) -> Any:
        return await self._page.evaluate(expression)

    async def screenshot(self, path: str) -> None:
        await self._page.screenshot(path=path, full_page=True)

    async def content(self) -> str:
        return str(await self._page.content())

    async def storage_state(self) -> dict[str, Any]:
        state = await self._page.context.storage_state()
        return dict(state)


class PatchrightDriver(IBrowserDriver):
    """Driver Patchright async. Mismo lifecycle que PlaywrightDriver."""

    def __init__(
        self,
        *,
        headless: bool = True,
        slow_mo_ms: int = 0,
        default_timeout_ms: int = 30_000,
        metrics: IObservabilityMetrics | None = None,
    ) -> None:
        self._headless = headless
        self._slow_mo_ms = slow_mo_ms
        self._default_timeout_ms = default_timeout_ms
        self._patchright: Any = None
        self._browser: Any = None
        self._metrics: IObservabilityMetrics = metrics or NullMetrics()
        self._log = structlog.get_logger("patchright_driver")

    async def start(self) -> None:
        if self._patchright is not None:
            return
        try:
            from patchright.async_api import async_playwright as async_patchright
        except ImportError as exc:  # pragma: no cover - extra opcional
            raise RuntimeError(
                "patchright no esta instalado. Anade `streaming-bot[stealth]` o "
                "`pip install patchright && patchright install chromium`.",
            ) from exc

        self._patchright = await async_patchright().start()
        self._browser = await self._patchright.chromium.launch(
            headless=self._headless,
            slow_mo=self._slow_mo_ms,
            channel="chrome",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--mute-audio",
                "--disable-features=AutomationControlled",
            ],
        )

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._patchright is not None:
            await self._patchright.stop()
            self._patchright = None

    @asynccontextmanager
    async def session(
        self,
        *,
        proxy: ProxyEndpoint | None,
        fingerprint: Fingerprint,
        storage_state: dict[str, Any] | None = None,
    ) -> AsyncIterator[IBrowserSession]:
        if self._browser is None:
            await self.start()
        if self._browser is None:
            raise BrowserCrashError("patchright browser no se pudo iniciar")

        context_kwargs: dict[str, Any] = {
            "user_agent": fingerprint.user_agent,
            "locale": fingerprint.locale,
            "timezone_id": fingerprint.timezone_id,
            "geolocation": {
                "latitude": fingerprint.geolocation.latitude,
                "longitude": fingerprint.geolocation.longitude,
            },
            "permissions": ["geolocation"],
            "viewport": {
                "width": fingerprint.viewport_width,
                "height": fingerprint.viewport_height,
            },
            "extra_http_headers": {"Accept-Language": fingerprint.locale},
        }
        if storage_state is not None:
            context_kwargs["storage_state"] = storage_state
        if proxy is not None:
            context_kwargs["proxy"] = self._build_proxy_payload(proxy)

        context = await self._browser.new_context(**context_kwargs)
        await context.add_init_script(STEALTH_INIT_SCRIPT)
        page = await context.new_page()

        self._metrics.session_started()
        try:
            yield _PatchrightSession(page, self._default_timeout_ms)
        finally:
            try:
                await context.close()
            finally:
                self._metrics.session_ended()

    @staticmethod
    def _build_proxy_payload(proxy: ProxyEndpoint) -> dict[str, str]:
        payload: dict[str, str] = {"server": proxy.as_url()}
        if proxy.username:
            payload["username"] = proxy.username
        if proxy.password:
            payload["password"] = proxy.password
        return payload
