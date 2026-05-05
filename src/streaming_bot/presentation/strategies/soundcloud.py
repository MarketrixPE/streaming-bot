"""Estrategia rica para SoundCloud Web (Patchright + soundcloud-v2 hibrido).

Implementa `IRichSiteStrategy`: login + perform_action + helpers de player.
Las acciones de boost (like, repost, follow, comment) se exponen como
metodos publicos para que `PremierBoostStrategy` las orqueste.

Antifraude:
- DataDome challenge: detectamos `iframe[src*="datadome"]` o
  `[data-cf-data-dome]` y delegamos a `ICaptchaSolver` (variantes
  `solve_image_text` o `solve_cloudflare_turnstile`).
- Comportamiento humano: cada accion respeta un delay del
  `DecisionDelayPolicy` antes de ejecutar (jitter log-normal).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from streaming_bot.application.behavior.decision_delay import (
    DecisionType,
    DelayContext,
    LogNormalDelayPolicy,
)
from streaming_bot.application.ports.site_strategy import IRichSiteStrategy
from streaming_bot.domain.exceptions import AuthenticationError, TargetSiteError
from streaming_bot.presentation.strategies.soundcloud_selectors import (
    COMMENT_INPUT,
    COMMENT_SUBMIT,
    DATADOME_ATTRIBUTE,
    DATADOME_GLOBAL_SELECTOR,
    DATADOME_IFRAME,
    EMAIL_INPUT,
    FOLLOW_BUTTON,
    FOLLOW_FALLBACK,
    HEADER_USER_NAV,
    LIKE_BUTTON,
    LIKE_FALLBACK,
    PASSWORD_INPUT,
    PLAY_BUTTON,
    PLAY_FALLBACK,
    REPOST_BUTTON,
    REPOST_FALLBACK,
    SIGNIN_BUTTON,
    SIGNIN_FORM,
    SIGNIN_URL,
)

if TYPE_CHECKING:
    from streaming_bot.application.behavior.decision_delay import DecisionDelayPolicy
    from streaming_bot.domain.entities import Account
    from streaming_bot.domain.ports.browser import IBrowserSession
    from streaming_bot.domain.ports.browser_rich import IRichBrowserSession
    from streaming_bot.domain.ports.captcha_solver import ICaptchaSolver


# Constantes de timing (segundos / ms). Capturadas aqui para que un solo
# ajuste afecte a todo el flujo si SoundCloud cambia tiempos de respuesta.
_LOGIN_FORM_TIMEOUT_MS = 12_000
_USER_NAV_TIMEOUT_MS = 15_000
_USER_NAV_POLL_RETRIES = 30
_USER_NAV_POLL_INTERVAL_S = 0.5
_DATADOME_CHECK_TIMEOUT_MS = 800
_PLAY_BUTTON_TIMEOUT_MS = 10_000
_DATADOME_REVALIDATION_TIMEOUT_MS = 20_000


class SoundcloudStrategy(IRichSiteStrategy):
    """Strategy SoundCloud: login + plays + like/repost/follow/comment."""

    def __init__(
        self,
        *,
        captcha_solver: ICaptchaSolver | None = None,
        delay_policy: DecisionDelayPolicy | None = None,
        engagement_level: str | None = None,
    ) -> None:
        self._captcha_solver = captcha_solver
        self._delay_policy: DecisionDelayPolicy = delay_policy or LogNormalDelayPolicy()
        self._engagement_level = engagement_level

    # ── ISiteStrategy ──────────────────────────────────────────────────────

    async def is_logged_in(self, page: IBrowserSession) -> bool:
        """Detecta sesion activa por presencia del nav del header."""
        try:
            await page.wait_for_selector(HEADER_USER_NAV, timeout_ms=3_000)
        except Exception:
            return False
        return True

    async def login(self, page: IBrowserSession, account: Account) -> None:
        """Login con manejo defensivo de DataDome challenges.

        Si en cualquier punto detectamos un iframe DataDome o el atributo
        `data-cf-data-dome` invocamos `_handle_datadome` que delega al
        `ICaptchaSolver`. Si el solver no fue inyectado o falla,
        relanzamos `AuthenticationError` para que el orchestrator marque
        la cuenta como rate-limited y la rote.
        """
        await page.goto(SIGNIN_URL, wait_until="domcontentloaded")

        if await self._datadome_present(page):
            await self._handle_datadome(page)

        try:
            await page.wait_for_selector(SIGNIN_FORM, timeout_ms=_LOGIN_FORM_TIMEOUT_MS)
        except Exception as exc:
            raise TargetSiteError(f"signin form no aparecio: {exc}") from exc

        await self._delay(DecisionType.TYPE)
        await page.fill(EMAIL_INPUT, account.username)
        await self._delay(DecisionType.TYPE)
        await page.fill(PASSWORD_INPUT, account.password)
        await self._delay(DecisionType.CLICK)
        await page.click(SIGNIN_BUTTON)

        for _ in range(_USER_NAV_POLL_RETRIES):
            await asyncio.sleep(_USER_NAV_POLL_INTERVAL_S)
            if await self._selector_appeared(page, HEADER_USER_NAV):
                return
            if await self._datadome_present(page):
                await self._handle_datadome(page)
                # Tras resolver el reto reintentamos esperar nav.
                if await self._selector_appeared(
                    page,
                    HEADER_USER_NAV,
                    timeout_ms=_DATADOME_REVALIDATION_TIMEOUT_MS,
                ):
                    return
                raise AuthenticationError("datadome resuelto pero login no completo")

        raise AuthenticationError("login no se completo en el tiempo esperado")

    async def perform_action(
        self,
        page: IBrowserSession,
        target_url: str,
        listen_seconds: int,
    ) -> None:
        """Reproduce un track: navega + click play + sleep humano."""
        await page.goto(target_url, wait_until="domcontentloaded")

        if await self._datadome_present(page):
            await self._handle_datadome(page)

        try:
            await page.wait_for_selector(PLAY_BUTTON, timeout_ms=_PLAY_BUTTON_TIMEOUT_MS)
            await self._delay(DecisionType.CLICK)
            await page.click(PLAY_BUTTON)
        except Exception:
            try:
                await page.wait_for_selector(PLAY_FALLBACK, timeout_ms=5_000)
                await self._delay(DecisionType.CLICK)
                await page.click(PLAY_FALLBACK)
            except Exception as exc:
                raise TargetSiteError(
                    f"no se pudo iniciar reproduccion soundcloud: {exc}",
                ) from exc

        await asyncio.sleep(max(listen_seconds, 30))

    # ── Helpers IRichSiteStrategy ──────────────────────────────────────────

    async def wait_for_player_ready(self, page: IRichBrowserSession) -> None:
        try:
            await page.wait_for_selector(PLAY_BUTTON, timeout_ms=_PLAY_BUTTON_TIMEOUT_MS)
        except Exception as exc:
            raise TargetSiteError(f"player soundcloud no listo: {exc}") from exc

    async def get_current_track_uri(self, page: IRichBrowserSession) -> str | None:
        """Lee la URL canonica del track desde `<link rel="canonical">`."""
        try:
            url = await page.evaluate(
                "() => document.querySelector('link[rel=\"canonical\"]')?.href || null",
            )
            return str(url) if url else None
        except Exception:
            return None

    async def get_current_artist_uri(self, page: IRichBrowserSession) -> str | None:
        """Lee la URL del artista desde el meta `og:soundcloud:user`."""
        try:
            url = await page.evaluate(
                "() => document.querySelector("
                "'meta[property=\"og:soundcloud:user\"]'"
                ")?.content || null",
            )
            return str(url) if url else None
        except Exception:
            return None

    # ── Boost actions (publicas, llamadas por PremierBoostStrategy) ────────

    async def like_current_track(self, page: IBrowserSession) -> None:
        """Click en el boton like (data-testid + fallback aria-label)."""
        await self._click_with_fallback(page, LIKE_BUTTON, LIKE_FALLBACK)

    async def repost_current_track(self, page: IBrowserSession) -> None:
        await self._click_with_fallback(page, REPOST_BUTTON, REPOST_FALLBACK)

    async def follow_current_artist(self, page: IBrowserSession) -> None:
        await self._click_with_fallback(page, FOLLOW_BUTTON, FOLLOW_FALLBACK)

    async def comment_current_track(self, page: IBrowserSession, text: str) -> None:
        if not text.strip():
            raise ValueError("comment text vacio")
        await self._delay(DecisionType.TYPE)
        await page.fill(COMMENT_INPUT, text)
        await self._delay(DecisionType.CLICK)
        await page.click(COMMENT_SUBMIT)

    # ── Internos ───────────────────────────────────────────────────────────

    async def _click_with_fallback(
        self,
        page: IBrowserSession,
        primary: str,
        fallback: str,
    ) -> None:
        await self._delay(DecisionType.CLICK)
        try:
            await page.wait_for_selector(primary, timeout_ms=4_000)
            await page.click(primary)
        except Exception:
            try:
                await page.wait_for_selector(fallback, timeout_ms=4_000)
                await page.click(fallback)
            except Exception as exc:
                raise TargetSiteError(
                    f"no se pudo clicar selector primario ni fallback: {exc}",
                ) from exc

    @staticmethod
    async def _selector_appeared(
        page: IBrowserSession,
        selector: str,
        *,
        timeout_ms: int = _USER_NAV_TIMEOUT_MS,
    ) -> bool:
        try:
            await page.wait_for_selector(selector, timeout_ms=timeout_ms)
        except Exception:
            return False
        return True

    async def _datadome_present(self, page: IBrowserSession) -> bool:
        """True si la pagina muestra un challenge DataDome."""
        for hint in (DATADOME_IFRAME, DATADOME_ATTRIBUTE, DATADOME_GLOBAL_SELECTOR):
            if await self._selector_appeared(
                page,
                hint,
                timeout_ms=_DATADOME_CHECK_TIMEOUT_MS,
            ):
                return True
        return False

    async def _handle_datadome(self, page: IBrowserSession) -> None:
        """Delega el reto DataDome al ICaptchaSolver inyectado.

        SoundCloud usa dos variantes:
        - Image-based (selecciona casillas con vehiculos/etc): usamos
          `solve_image_text` con un screenshot codificado en base64.
        - Cloudflare Turnstile (token): usamos
          `solve_cloudflare_turnstile` con site_key extraido del iframe.

        Sin solver inyectado o si la variante es desconocida levantamos
        `AuthenticationError` para que el orchestrator rote la cuenta.
        """
        if self._captcha_solver is None:
            raise AuthenticationError("datadome detectado y no hay captcha solver inyectado")

        try:
            site_key = await page.evaluate(
                "() => {"
                "  const f = document.querySelector('iframe[src*=\"datadome\"]');"
                "  if (!f) return null;"
                "  const url = new URL(f.src);"
                "  return url.searchParams.get('k') || url.searchParams.get('siteKey');"
                "}",
            )
        except Exception:
            site_key = None

        page_url = await self._best_effort_url(page)
        try:
            if site_key:
                await self._captcha_solver.solve_cloudflare_turnstile(
                    site_key=str(site_key),
                    page_url=page_url,
                )
            else:
                screenshot_b64 = ""  # placeholder defensivo (sin path real)
                await self._captcha_solver.solve_image_text(
                    image_b64=screenshot_b64,
                    hint="datadome challenge",
                )
        except Exception as exc:
            raise AuthenticationError(f"datadome no pudo resolverse: {exc}") from exc

    @staticmethod
    async def _best_effort_url(page: IBrowserSession) -> str:
        """Devuelve la URL actual usando current_url() si existe (rich) o ''."""
        getter = getattr(page, "current_url", None)
        if getter is None:
            return ""
        try:
            return str(await getter())
        except Exception:
            return ""

    async def _delay(self, decision: DecisionType) -> None:
        """Aplica el delay humano del policy antes de la accion."""
        ms = await self._delay_policy.decide(
            DelayContext(
                decision=decision,
                engagement_level=self._engagement_level,
            ),
        )
        if ms > 0:
            await asyncio.sleep(ms / 1000.0)
