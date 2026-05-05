"""Estrategia para Amazon Music Web Player.

Amazon Music es el DSP del trio con menor presion antifraud y el peor payout
(~$0.004/stream tier 3). El login es el flujo estandar de Amazon (`ap/signin`)
con email + password en pasos separados; ocasionalmente Amazon inserta un
captcha de imagen distorsionada que delegamos al `ICaptchaSolver` con hint
"amazon captcha letters".

Implementa IRichSiteStrategy: login + perform_action + helpers de player +
helpers de engagement (like, follow_artist, add_to_playlist).

Selectores: ver `amazon_music_selectors.py` (Q1 2026).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from streaming_bot.application.ports.site_strategy import IRichSiteStrategy
from streaming_bot.domain.exceptions import AuthenticationError, TargetSiteError
from streaming_bot.presentation.strategies import amazon_music_selectors as sel

if TYPE_CHECKING:
    from streaming_bot.domain.entities import Account
    from streaming_bot.domain.ports.browser import IBrowserSession
    from streaming_bot.domain.ports.browser_rich import IRichBrowserSession
    from streaming_bot.domain.ports.captcha_solver import ICaptchaSolver


_LOGIN_TOTAL_WAIT_S: float = 25.0
_LOGIN_POLL_S: float = 0.5
# Hint en lenguaje natural para el provider de captcha (CapSolver/2Captcha/GPT-4V).
_AMAZON_CAPTCHA_HINT: str = "amazon captcha letters"


class AmazonMusicStrategy(IRichSiteStrategy):
    """Estrategia para Amazon Music Web Player.

    El captcha solver es opcional: si no se inyecta y aparece un captcha de
    imagen durante el login, lanzamos AuthenticationError ("captcha sin solver").
    """

    def __init__(self, *, captcha_solver: ICaptchaSolver | None = None) -> None:
        self._captcha_solver = captcha_solver

    # ── ISiteStrategy ────────────────────────────────────────────────────
    async def is_logged_in(self, page: IBrowserSession) -> bool:
        """Detecta sesion activa por avatar de cuenta o link a la biblioteca."""
        for selector in (sel.USER_AVATAR, sel.LIBRARY_LINK):
            try:
                await page.wait_for_selector(selector, timeout_ms=2500)
            except Exception:  # noqa: S112 selector miss esperado, no es bug
                continue
            return True
        return False

    async def login(self, page: IBrowserSession, account: Account) -> None:
        """Login Amazon AP. Soporta captcha de imagen via solver inyectado."""
        await page.goto(sel.HOME_URL, wait_until="domcontentloaded")

        # Click en "Sign In" para llegar al endpoint estandar ap/signin.
        # Algunos paises/locales redirigen directo a signin sin link visible;
        # en ese caso pasamos por alto y seguimos al wait del email field.
        try:
            await page.wait_for_selector(sel.SIGN_IN_LINK, timeout_ms=8000)
            await page.click(sel.SIGN_IN_LINK)
        except Exception:  # noqa: S110 redirect directo es flujo valido
            pass

        try:
            await page.wait_for_selector(sel.LOGIN_EMAIL, timeout_ms=12_000)
        except Exception as exc:
            raise TargetSiteError(f"login form (email) no aparecio: {exc}") from exc

        await page.fill(sel.LOGIN_EMAIL, account.username)
        # Amazon a veces hace email-only step (continue) y luego password.
        if await self._selector_appeared(page, sel.LOGIN_CONTINUE, timeout_ms=1500):
            await page.click(sel.LOGIN_CONTINUE)

        try:
            await page.wait_for_selector(sel.LOGIN_PASSWORD, timeout_ms=10_000)
        except Exception as exc:
            raise TargetSiteError(f"password step no cargo: {exc}") from exc

        await page.fill(sel.LOGIN_PASSWORD, account.password)
        await page.click(sel.LOGIN_SUBMIT)

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

        # Amazon Music exige >=30s para contar el stream (Amazon for Artists docs).
        await asyncio.sleep(max(listen_seconds, 35))

    # ── IRichSiteStrategy: helpers de player ──────────────────────────────
    async def wait_for_player_ready(self, page: IRichBrowserSession) -> None:
        """Espera al widget de now-playing y al titulo del track."""
        try:
            await page.wait_for_selector(sel.NOW_PLAYING_WIDGET, timeout_ms=15_000)
            await page.wait_for_selector(sel.NOW_PLAYING_TITLE, timeout_ms=10_000)
        except Exception as exc:
            raise TargetSiteError(f"player no llego a estado ready: {exc}") from exc

    async def get_current_track_uri(self, page: IRichBrowserSession) -> str | None:
        """Lee `data-asin` (id Amazon) del widget now-playing.

        Construye URI sintetico `amazon:track:<asin>`. Devuelve None si el
        DOM aun no expone el atributo (transicion entre tracks).
        """
        try:
            asin = await page.evaluate(
                "() => {"
                "  const el = document.querySelector('[data-id=\"now-playing\"]');"
                "  return el && el.getAttribute('data-asin');"
                "}",
            )
            if not asin:
                return None
            return f"amazon:track:{asin}"
        except Exception:
            return None

    async def get_current_artist_uri(self, page: IRichBrowserSession) -> str | None:
        """Extrae el id de artista del href del link en now-playing."""
        try:
            href = await page.evaluate(
                "() => {"
                "  const sel = '[data-id=\"now-playing\"] a[href*=\"/artists/\"]';"
                "  const el = document.querySelector(sel);"
                "  return el && el.getAttribute('href');"
                "}",
            )
            if not href:
                return None
            artist_id = str(href).rstrip("/").split("/")[-1]
            return f"amazon:artist:{artist_id}"
        except Exception:
            return None

    # ── Helpers especificos del DSP ───────────────────────────────────────
    async def like_current_track(self, page: IRichBrowserSession) -> bool:
        """Thumbs-up sobre el track actual. True si tuvo exito."""
        return await self._safe_click(page, sel.LIKE_BUTTON)

    async def add_to_playlist(self, page: IRichBrowserSession) -> bool:
        """Abre el picker de "Add to playlist". El caller cierra el modal."""
        return await self._safe_click(page, sel.ADD_TO_PLAYLIST)

    async def follow_current_artist(self, page: IRichBrowserSession) -> bool:
        """Sigue al artista (estando en su pagina)."""
        return await self._safe_click(page, sel.ARTIST_FOLLOW)

    # ── Helpers internos ──────────────────────────────────────────────────
    async def _await_login_completion(self, page: IBrowserSession) -> None:
        """Polling de salida del login: avatar, captcha (resolver), 2FA, error."""
        deadline_iters = int(_LOGIN_TOTAL_WAIT_S / _LOGIN_POLL_S)
        for _ in range(deadline_iters):
            await asyncio.sleep(_LOGIN_POLL_S)
            if await self._selector_appeared(page, sel.USER_AVATAR):
                return
            if await self._selector_appeared(page, sel.IMAGE_CAPTCHA, timeout_ms=300):
                if self._captcha_solver is None:
                    raise AuthenticationError("Amazon captcha y no hay solver inyectado")
                await self._solve_amazon_image_captcha(page)
                # Tras inyectar la respuesta, Amazon re-submit. Continuamos polling.
                continue
            if await self._selector_appeared(page, sel.TWO_FACTOR_OTP, timeout_ms=300):
                # Cuenta requiere OTP; sin acceso al canal SMS/TOTP, fallamos limpio.
                raise AuthenticationError(
                    "Amazon 2FA OTP requerido: cuenta no warmed o sin numero confiable",
                )
            if await self._selector_appeared(page, sel.LOGIN_ERROR, timeout_ms=300):
                raise AuthenticationError("Amazon login rechazado (credenciales o bloqueo)")

        raise AuthenticationError("login no se completo en el tiempo esperado")

    async def _solve_amazon_image_captcha(self, page: IBrowserSession) -> None:
        """Lee el src del captcha como base64, lo resuelve y rellena el input.

        El src del captcha de Amazon es una URL HTTPS, pero el contrato del
        ICaptchaSolver pide un base64. Aqui descargamos via `fetch()` en el
        contexto de la pagina (mismo origen, mismas cookies) y convertimos a
        b64. Es la unica via fiable; los providers de captcha aceptan tanto
        URL como b64, pero la firma del puerto exige b64.
        """
        if self._captcha_solver is None:
            raise AuthenticationError("Amazon captcha y no hay solver inyectado")
        try:
            image_b64 = await page.evaluate(
                "() => {"
                "  const img = document.querySelector('[id=\"auth-captcha-image\"]');"
                "  if (!img) return null;"
                "  return fetch(img.src).then(r => r.blob()).then(b => new Promise((res) => {"
                "    const fr = new FileReader();"
                "    fr.onload = () => res(String(fr.result).split(',')[1] || '');"
                "    fr.readAsDataURL(b);"
                "  }));"
                "}",
            )
        except Exception as exc:
            raise AuthenticationError(f"no pude leer la imagen del captcha: {exc}") from exc

        if not image_b64:
            raise AuthenticationError("captcha image no accesible")

        text = await self._captcha_solver.solve_image_text(
            image_b64=str(image_b64),
            hint=_AMAZON_CAPTCHA_HINT,
        )
        try:
            await page.fill(sel.IMAGE_CAPTCHA_INPUT, text)
            await page.click(sel.LOGIN_SUBMIT)
        except Exception as exc:
            raise AuthenticationError(f"no pude reenviar el form con captcha: {exc}") from exc

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
