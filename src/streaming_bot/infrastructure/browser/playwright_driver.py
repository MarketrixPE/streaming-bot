"""Adaptador Playwright async que implementa IBrowserDriver.

Diseño:
- Una única instancia de Playwright + Browser compartida.
- Por cada sesión: un BrowserContext aislado (cookies/cache propios).
- Stealth aplicado en cada contexto via add_init_script.
- Locale/TZ/Geo/UA configurados desde el Fingerprint coherente.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)
from playwright.async_api import (
    Error as PlaywrightError,
)
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from streaming_bot.domain.exceptions import BrowserCrashError, TargetSiteError
from streaming_bot.domain.ports.browser import IBrowserDriver, IBrowserSession
from streaming_bot.domain.value_objects import Fingerprint, ProxyEndpoint

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from streaming_bot.infrastructure.browser.stealth import STEALTH_INIT_SCRIPT


class _PlaywrightSession(IBrowserSession):
    """Wrapper sobre `Page` que cumple el puerto IBrowserSession."""

    def __init__(self, page: Page, default_timeout_ms: int) -> None:
        self._page = page
        self._page.set_default_timeout(default_timeout_ms)

    async def goto(self, url: str, *, wait_until: str = "networkidle") -> None:
        try:
            await self._page.goto(url, wait_until=wait_until)  # type: ignore[arg-type]
        except PlaywrightTimeoutError as exc:
            raise TargetSiteError(f"timeout navegando a {url}") from exc
        except PlaywrightError as exc:
            raise BrowserCrashError(str(exc)) from exc

    async def fill(self, selector: str, value: str) -> None:
        await self._page.fill(selector, value)

    async def click(self, selector: str) -> None:
        await self._page.click(selector)

    async def wait_for_selector(self, selector: str, *, timeout_ms: int = 30_000) -> None:
        try:
            await self._page.wait_for_selector(selector, timeout=timeout_ms)
        except PlaywrightTimeoutError as exc:
            raise TargetSiteError(f"selector no encontrado: {selector}") from exc

    async def evaluate(self, expression: str) -> Any:
        return await self._page.evaluate(expression)

    async def screenshot(self, path: str) -> None:
        await self._page.screenshot(path=path, full_page=True)

    async def content(self) -> str:
        return await self._page.content()

    async def storage_state(self) -> dict[str, Any]:
        state = await self._page.context.storage_state()
        return dict(state)


class PlaywrightDriver(IBrowserDriver):
    """Driver Playwright async. Lifecycle: start() → session() ... → close()."""

    def __init__(
        self,
        *,
        headless: bool = True,
        slow_mo_ms: int = 0,
        default_timeout_ms: int = 30_000,
    ) -> None:
        self._headless = headless
        self._slow_mo_ms = slow_mo_ms
        self._default_timeout_ms = default_timeout_ms
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    async def start(self) -> None:
        """Inicia Playwright y lanza un Chromium compartido."""
        if self._playwright is not None:
            return
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self._headless,
            slow_mo=self._slow_mo_ms,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--mute-audio",
            ],
        )

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

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
            raise BrowserCrashError("browser no se pudo iniciar")

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
        }
        if storage_state is not None:
            context_kwargs["storage_state"] = storage_state
        if proxy is not None:
            context_kwargs["proxy"] = self._build_proxy_payload(proxy)

        context: BrowserContext = await self._browser.new_context(**context_kwargs)
        await context.add_init_script(STEALTH_INIT_SCRIPT)
        page = await context.new_page()

        try:
            yield _PlaywrightSession(page, self._default_timeout_ms)
        finally:
            await context.close()

    @staticmethod
    def _build_proxy_payload(proxy: ProxyEndpoint) -> dict[str, str]:
        payload: dict[str, str] = {"server": proxy.as_url()}
        if proxy.username:
            payload["username"] = proxy.username
        if proxy.password:
            payload["password"] = proxy.password
        return payload
