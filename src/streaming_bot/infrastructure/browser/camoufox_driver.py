"""Driver Camoufox: Firefox-fork con anti-detección nativa + Browserforge fingerprints.

Sustituye al `PlaywrightDriver` para los flujos sensibles (Spotify, registros).
Coexiste con el driver legacy: ambos viven en `infrastructure/browser/__init__.py`.

Decisiones clave:
- Una instancia de Playwright/Browser por DRIVER (no por sesión) para amortizar
  el coste de spawn de Firefox. Cada `session()` abre un BrowserContext aislado.
- `humanize=False` en Camoufox: la humanización del cursor la hace el
  `CamoufoxSession` con curvas Bezier explícitas (necesario para overshoot,
  hover times y métricas determinísticas en tests).
- `geoip=True` cuando hay proxy: Camoufox calcula timezone/locale a partir de
  la IP saliente para coherencia. Si NO hay proxy, lo desactivamos.
- `stealth_v2.inject_stealth` se añade encima del stealth nativo de Camoufox
  como red de seguridad (level configurable).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from camoufox.async_api import AsyncCamoufox
from playwright.async_api import Browser, BrowserContext
from structlog.stdlib import BoundLogger

from streaming_bot.config import BrowserSettings
from streaming_bot.domain.exceptions import BrowserCrashError
from streaming_bot.domain.persona import MouseProfile, TypingProfile
from streaming_bot.domain.ports.browser_rich import IRichBrowserDriver, IRichBrowserSession
from streaming_bot.domain.value_objects import Fingerprint, ProxyEndpoint
from streaming_bot.infrastructure.browser.camoufox_session import CamoufoxSession
from streaming_bot.infrastructure.browser.stealth_v2 import StealthLevel, inject_stealth

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from random import Random


class CamoufoxDriver(IRichBrowserDriver):
    """Driver moderno con Camoufox + Browserforge.

    Cada llamada a `session()` instancia un AsyncCamoufox dedicado: garantiza
    que el geoip se calcule por proxy y simplifica el cleanup. El coste de
    spawn (~1.5s) es aceptable para flujos de larga duración tipo streaming.
    """

    def __init__(
        self,
        *,
        settings: BrowserSettings,
        logger: BoundLogger,
        mouse_profile: MouseProfile | None = None,
        typing_profile: TypingProfile | None = None,
        stealth_level: StealthLevel = "balanced",
    ) -> None:
        self._settings = settings
        self._log = logger.bind(component="CamoufoxDriver")
        self._mouse_profile = mouse_profile if mouse_profile is not None else MouseProfile()
        self._typing_profile = typing_profile if typing_profile is not None else TypingProfile()
        self._stealth_level = stealth_level

    async def close(self) -> None:
        """No-op: cada `session()` abre/cierra su propio AsyncCamoufox."""

    @asynccontextmanager
    async def session(
        self,
        *,
        proxy: ProxyEndpoint | None,
        fingerprint: Fingerprint,
        storage_state: dict[str, Any] | None = None,
        rng: Random | None = None,
    ) -> AsyncIterator[IRichBrowserSession]:
        proxy_dict = self._build_proxy_payload(proxy) if proxy is not None else None

        # Camoufox toma el control del lanzamiento de Playwright/Firefox.
        launch_kwargs: dict[str, Any] = {
            "headless": self._settings.headless,
            "humanize": False,
            "locale": fingerprint.locale,
            "window": (fingerprint.viewport_width, fingerprint.viewport_height),
        }
        if proxy_dict is not None:
            launch_kwargs["proxy"] = proxy_dict
            launch_kwargs["geoip"] = True
        else:
            launch_kwargs["geoip"] = False

        async with AsyncCamoufox(**launch_kwargs) as browser_or_context:  # type: ignore[no-untyped-call]
            context = await self._ensure_context(
                browser_or_context,
                fingerprint=fingerprint,
                storage_state=storage_state,
            )
            try:
                await inject_stealth(
                    context,
                    fingerprint=fingerprint,
                    level=self._stealth_level,
                )
                page = await context.new_page()
                session_obj = CamoufoxSession(
                    page,
                    context,
                    default_timeout_ms=self._settings.default_timeout_ms,
                    mouse_profile=self._mouse_profile,
                    typing_profile=self._typing_profile,
                    logger=self._log,
                    rng=rng,
                )
                yield session_obj
            except Exception as exc:
                self._log.error("camoufox_session_error", error=str(exc))
                raise BrowserCrashError(str(exc)) from exc
            finally:
                # Sólo cerramos el context que abrimos nosotros; si Camoufox
                # nos entregó un BrowserContext directamente lo cierra el
                # __aexit__ del AsyncCamoufox.
                if isinstance(browser_or_context, Browser):
                    await context.close()

    async def _ensure_context(
        self,
        browser_or_context: Browser | BrowserContext,
        *,
        fingerprint: Fingerprint,
        storage_state: dict[str, Any] | None,
    ) -> BrowserContext:
        """Devuelve un BrowserContext listo, abriéndolo si recibimos un Browser."""
        context_kwargs: dict[str, Any] = {
            "viewport": {
                "width": fingerprint.viewport_width,
                "height": fingerprint.viewport_height,
            },
            "timezone_id": fingerprint.timezone_id,
            "locale": fingerprint.locale,
            "geolocation": {
                "latitude": fingerprint.geolocation.latitude,
                "longitude": fingerprint.geolocation.longitude,
            },
            "permissions": ["geolocation"],
            "extra_http_headers": {"Accept-Language": fingerprint.locale},
        }
        if storage_state is not None:
            context_kwargs["storage_state"] = storage_state

        if isinstance(browser_or_context, Browser):
            return await browser_or_context.new_context(**context_kwargs)
        # Si Camoufox entregó un context (modo persistente), no podemos
        # reconfigurar tz/locale, pero sí storage_state y headers vía page.
        return browser_or_context

    @staticmethod
    def _build_proxy_payload(proxy: ProxyEndpoint) -> dict[str, str]:
        payload: dict[str, str] = {"server": proxy.as_url()}
        if proxy.username:
            payload["username"] = proxy.username
        if proxy.password:
            payload["password"] = proxy.password
        return payload
