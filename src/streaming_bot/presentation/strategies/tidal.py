"""Estrategia para Tidal Web Player.

Tidal tiene presion antifraud moderada y selectores `data-test=*` muy
estables (SPA React). El payout depende del tier de la cuenta:
- Premium estandar: ~$0.0125/stream
- HiFi: ~$0.012-0.014/stream
- HiFi Plus: tier mas alto, paga aprox 2x via "Direct Artist Payouts"

Por eso la estrategia expone `verify_hifi_tier()` para que el orchestrator
pueda descartar (o re-routear a otro pool) cuentas que perdieron el tier
HiFi (downgrade a Free, que ya no genera payout).

Captcha: rarisimo en login, mas comun en signup. Aceptamos solver opcional.

Implementa IRichSiteStrategy.

Selectores: ver `tidal_selectors.py` (Q1 2026).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from streaming_bot.application.ports.site_strategy import IRichSiteStrategy
from streaming_bot.domain.exceptions import AuthenticationError, TargetSiteError
from streaming_bot.presentation.strategies import tidal_selectors as sel

if TYPE_CHECKING:
    from streaming_bot.domain.entities import Account
    from streaming_bot.domain.ports.browser import IBrowserSession
    from streaming_bot.domain.ports.browser_rich import IRichBrowserSession
    from streaming_bot.domain.ports.captcha_solver import ICaptchaSolver


_LOGIN_TOTAL_WAIT_S: float = 25.0
_LOGIN_POLL_S: float = 0.5
# Subcadenas que indican tier valido para payout. Las matcheamos contra el
# texto del badge en `account/subscription` (case-insensitive).
_HIFI_TIER_KEYWORDS: tuple[str, ...] = ("hifi", "hi-fi", "hifi plus", "hifi+", "hi-fi plus")


class TidalStrategy(IRichSiteStrategy):
    """Estrategia para Tidal Web Player.

    El captcha solver es opcional: solo se activa si Tidal sirve un
    Turnstile/hCaptcha en login (rarisimo en cuentas existentes).
    """

    def __init__(self, *, captcha_solver: ICaptchaSolver | None = None) -> None:
        self._captcha_solver = captcha_solver

    # ── ISiteStrategy ────────────────────────────────────────────────────
    async def is_logged_in(self, page: IBrowserSession) -> bool:
        """Detecta sesion activa por avatar de usuario en la sidebar."""
        try:
            await page.wait_for_selector(sel.USER_AVATAR, timeout_ms=3000)
        except Exception:
            return False
        return True

    async def login(self, page: IBrowserSession, account: Account) -> None:
        """Login Tidal. Form de un solo paso (email + password + submit)."""
        await page.goto(sel.LOGIN_URL, wait_until="domcontentloaded")

        try:
            await page.wait_for_selector(sel.LOGIN_EMAIL, timeout_ms=10_000)
        except Exception as exc:
            raise TargetSiteError(f"login form no aparecio: {exc}") from exc

        await page.fill(sel.LOGIN_EMAIL, account.username)
        await page.fill(sel.LOGIN_PASSWORD, account.password)
        await page.click(sel.LOGIN_BUTTON)

        await self._await_login_completion(page)

    async def perform_action(
        self,
        page: IBrowserSession,
        target_url: str,
        listen_seconds: int,
    ) -> None:
        """Reproduccion simple de un track o album (modo legacy)."""
        await page.goto(target_url, wait_until="domcontentloaded")
        try:
            await page.wait_for_selector(sel.PLAY_BUTTON, timeout_ms=12_000)
            await page.click(sel.PLAY_BUTTON)
        except Exception:
            try:
                await page.wait_for_selector(sel.PLAY_PAUSE, timeout_ms=5_000)
                await page.click(sel.PLAY_PAUSE)
            except Exception as exc:
                raise TargetSiteError(f"no se pudo iniciar reproduccion: {exc}") from exc

        # Tidal cuenta el stream tras 30s de reproduccion continua.
        await asyncio.sleep(max(listen_seconds, 35))

    # ── IRichSiteStrategy: helpers de player ──────────────────────────────
    async def wait_for_player_ready(self, page: IRichBrowserSession) -> None:
        """Espera al footer-player y al titulo del track."""
        try:
            await page.wait_for_selector(sel.NOW_PLAYING_WIDGET, timeout_ms=15_000)
            await page.wait_for_selector(sel.NOW_PLAYING_TITLE, timeout_ms=10_000)
        except Exception as exc:
            raise TargetSiteError(f"player no llego a estado ready: {exc}") from exc

    async def get_current_track_uri(self, page: IRichBrowserSession) -> str | None:
        """Lee `data-test-track-id` del footer-player.

        Construye URI sintetico `tidal:track:<id>`.
        """
        try:
            track_id = await page.evaluate(
                "() => {"
                "  const el = document.querySelector('[data-test=\"footer-player\"]');"
                "  return el && el.getAttribute('data-test-track-id');"
                "}",
            )
            if not track_id:
                return None
            return f"tidal:track:{track_id}"
        except Exception:
            return None

    async def get_current_artist_uri(self, page: IRichBrowserSession) -> str | None:
        """Extrae el id del artista del href en footer-player."""
        try:
            href = await page.evaluate(
                "() => {"
                "  const sel = '[data-test=\"footer-player\"] a[href*=\"/artist/\"]';"
                "  const el = document.querySelector(sel);"
                "  return el && el.getAttribute('href');"
                "}",
            )
            if not href:
                return None
            artist_id = str(href).rstrip("/").split("/")[-1]
            return f"tidal:artist:{artist_id}"
        except Exception:
            return None

    # ── Helpers especificos del DSP ───────────────────────────────────────
    async def like_current_track(self, page: IRichBrowserSession) -> bool:
        """Favoritea el track actual. True si tuvo exito."""
        return await self._safe_click(page, sel.LIKE_BUTTON)

    async def add_to_playlist(self, page: IRichBrowserSession) -> bool:
        """Abre el menu "Add to playlist" sobre el track actual."""
        return await self._safe_click(page, sel.ADD_TO_PLAYLIST)

    async def follow_current_artist(self, page: IRichBrowserSession) -> bool:
        """Sigue al artista (estando en su pagina)."""
        return await self._safe_click(page, sel.ARTIST_FOLLOW)

    async def verify_hifi_tier(self, page: IBrowserSession) -> bool:
        """Verifica que la cuenta loggeada tiene tier HiFi/HiFi+ activo.

        Navega a `account/subscription` y matchea el texto del badge contra
        las keywords HiFi conocidas. Devuelve False si la cuenta cayo a tier
        Free/trial (deja de generar payout) o si la pagina no carga.
        Nunca lanza: el orchestrator decide que hacer con el bool.
        """
        try:
            await page.goto(sel.SUBSCRIPTION_URL, wait_until="domcontentloaded")
            await page.wait_for_selector(sel.SUBSCRIPTION_BADGE, timeout_ms=8000)
        except Exception:
            return False
        try:
            tier_text = await page.evaluate(
                "() => {"
                "  const el = document.querySelector('[data-test=\"subscription-tier\"]');"
                "  return el ? el.textContent : '';"
                "}",
            )
        except Exception:
            return False
        normalized = str(tier_text or "").lower()
        return any(keyword in normalized for keyword in _HIFI_TIER_KEYWORDS)

    # ── Helpers internos ──────────────────────────────────────────────────
    async def _await_login_completion(self, page: IBrowserSession) -> None:
        """Polling de salida del login: avatar o error."""
        deadline_iters = int(_LOGIN_TOTAL_WAIT_S / _LOGIN_POLL_S)
        for _ in range(deadline_iters):
            await asyncio.sleep(_LOGIN_POLL_S)
            if await self._selector_appeared(page, sel.USER_AVATAR):
                return
            if await self._selector_appeared(page, sel.LOGIN_ERROR, timeout_ms=300):
                raise AuthenticationError("Tidal login rechazado (credenciales o bloqueo)")
            # Captcha: solo si el solver esta disponible. De otro modo
            # dejamos que el polling caiga en timeout y re-intentamos
            # con el orchestrator de retries.
            if self._captcha_solver is not None and await self._selector_appeared(
                page,
                'iframe[src*="hcaptcha.com"], iframe[src*="turnstile"]',
                timeout_ms=300,
            ):
                # Tidal no documenta su site_key publicamente; en la practica
                # es Turnstile. Si llegamos aqui, marcamos como warming-required.
                raise AuthenticationError(
                    "Tidal sirvio captcha en login: requiere warming manual de la cuenta",
                )

        raise AuthenticationError("login no se completo en el tiempo esperado")

    @staticmethod
    async def _selector_appeared(
        page: IBrowserSession,
        selector: str,
        *,
        timeout_ms: int = 500,
    ) -> bool:
        """True si el selector aparece dentro del timeout."""
        try:
            await page.wait_for_selector(selector, timeout_ms=timeout_ms)
        except Exception:
            return False
        return True

    @staticmethod
    async def _safe_click(page: IRichBrowserSession, selector: str) -> bool:
        """Click defensivo: chequea visibilidad antes y traga errores."""
        try:
            visible = await page.is_visible(selector, timeout_ms=2000)
        except Exception:
            return False
        if not visible:
            return False
        try:
            await page.human_click(selector)
        except Exception:
            return False
        return True
