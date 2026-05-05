"""Estrategia para Apple Music Web Player.

Apple Music es el DSP mas hostil del trio Apple/Amazon/Tidal:
- Anti-bot agresivo (Akamai Bot Manager + huellas Webkit Apple-only).
- AppleID con metodo de pago verificado obligatorio.
- 2FA device-binding (no SMS): la cuenta solo se loguea limpio si ya
  tiene un dispositivo de confianza marcado. Por eso el adapter NO
  intenta resolver el 2FA: si lo encuentra, falla con AuthenticationError
  para que el orchestrator marque la cuenta como "needs_warming".
- Captcha hCaptcha aparece en signup; en login normal es raro pero
  posible. Si aparece y hay ICaptchaSolver inyectado, lo resolvemos.

Implementa IRichSiteStrategy: login + perform_action + helpers de player
+ helpers de engagement (like, follow_artist, add_to_library) para que
el behavior_engine v2 pueda componer 33+ acciones humanas.

Selectores: ver `apple_music_selectors.py` (Q1 2026).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from streaming_bot.application.ports.site_strategy import IRichSiteStrategy
from streaming_bot.domain.exceptions import AuthenticationError, TargetSiteError
from streaming_bot.presentation.strategies import apple_music_selectors as sel

if TYPE_CHECKING:
    from streaming_bot.domain.entities import Account
    from streaming_bot.domain.ports.browser import IBrowserSession
    from streaming_bot.domain.ports.browser_rich import IRichBrowserSession
    from streaming_bot.domain.ports.captcha_solver import ICaptchaSolver


# Limite max de espera para que aparezca el avatar tras submit de password.
_LOGIN_TOTAL_WAIT_S: float = 25.0
_LOGIN_POLL_S: float = 0.5


class AppleMusicStrategy(IRichSiteStrategy):
    """Estrategia para Apple Music Web Player.

    Se inyecta el captcha solver opcionalmente: si no se provee y aparece
    un hCaptcha durante el login, lanzamos AuthenticationError ("captcha
    sin solver").
    """

    def __init__(self, *, captcha_solver: ICaptchaSolver | None = None) -> None:
        # Solver opcional. La estrategia delega tipo y site_key concretos al
        # adapter de captcha; aqui solo decidimos si invocarlo o fallar.
        self._captcha_solver = captcha_solver

    # ── ISiteStrategy ────────────────────────────────────────────────────
    async def is_logged_in(self, page: IBrowserSession) -> bool:
        """Detecta sesion activa por presencia del avatar de cuenta.

        No reintenta. 3s es suficiente: si el avatar no aparece es que
        no hay sesion (cookie expirada o primer login).
        """
        try:
            await page.wait_for_selector(sel.USER_AVATAR, timeout_ms=3000)
        except Exception:
            return False
        return True

    async def login(self, page: IBrowserSession, account: Account) -> None:
        """Login AppleID. Maneja captcha hCaptcha y detecta 2FA fatal."""
        await page.goto(sel.LOGIN_URL, wait_until="domcontentloaded")

        try:
            await page.wait_for_selector(sel.LOGIN_USERNAME, timeout_ms=10_000)
        except Exception as exc:
            raise TargetSiteError(f"login form no aparecio: {exc}") from exc

        await page.fill(sel.LOGIN_USERNAME, account.username)
        # Apple separa email y password en dos pasos: submit, espera, password.
        await page.click(sel.LOGIN_USERNAME_SUBMIT)

        try:
            await page.wait_for_selector(sel.LOGIN_PASSWORD, timeout_ms=10_000)
        except Exception as exc:
            raise TargetSiteError(f"password step no cargo: {exc}") from exc

        await page.fill(sel.LOGIN_PASSWORD, account.password)
        await page.click(sel.LOGIN_PASSWORD_SUBMIT)

        await self._await_login_completion(page)

    async def perform_action(
        self,
        page: IBrowserSession,
        target_url: str,
        listen_seconds: int,
    ) -> None:
        """Reproduccion simple de un track o album (modo legacy).

        Para flujos ricos (playlist + behaviors + engagement) el caller
        delega al PlaylistSessionUseCase con HumanBehaviorEngine.
        """
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

        # Apple Music exige >30s para contar el stream (ver Apple for Artists).
        await asyncio.sleep(max(listen_seconds, 35))

    # ── IRichSiteStrategy: helpers de player ──────────────────────────────
    async def wait_for_player_ready(self, page: IRichBrowserSession) -> None:
        """Espera a que el chrome del player y el titulo del track esten montados."""
        try:
            await page.wait_for_selector(sel.NOW_PLAYING_WIDGET, timeout_ms=15_000)
            await page.wait_for_selector(sel.NOW_PLAYING_TITLE, timeout_ms=10_000)
        except Exception as exc:
            raise TargetSiteError(f"player no llego a estado ready: {exc}") from exc

    async def get_current_track_uri(self, page: IRichBrowserSession) -> str | None:
        """Lee el id del track desde el atributo `data-track-id` del header.

        Apple no expone URIs canonicos en el DOM tan limpiamente como Spotify;
        construimos un URI sintetico `apple:track:<id>` desde el data attr.
        Devuelve None si no hay nada que leer.
        """
        try:
            track_id = await page.evaluate(
                "() => {"
                "  const el = document.querySelector('[data-testid=\"chrome-player\"]');"
                "  return el && el.getAttribute('data-track-id');"
                "}",
            )
            if not track_id:
                return None
            return f"apple:track:{track_id}"
        except Exception:
            return None

    async def get_current_artist_uri(self, page: IRichBrowserSession) -> str | None:
        """Lee el href del link al artista del track actual y extrae el id."""
        try:
            href = await page.evaluate(
                "() => {"
                "  const el = document.querySelector('[data-testid=\"now-playing-artist\"] a');"
                "  return el && el.getAttribute('href');"
                "}",
            )
            if not href:
                return None
            artist_id = str(href).rstrip("/").split("/")[-1]
            return f"apple:artist:{artist_id}"
        except Exception:
            return None

    # ── Helpers especificos del DSP (engagement) ──────────────────────────
    async def like_current_track(self, page: IRichBrowserSession) -> bool:
        """Like sobre el track actualmente en reproduccion. True si tuvo exito."""
        return await self._safe_click(page, sel.LIKE_BUTTON)

    async def add_to_library(self, page: IRichBrowserSession) -> bool:
        """Agrega la cancion actual a la biblioteca personal. True si tuvo exito."""
        return await self._safe_click(page, sel.ADD_TO_LIBRARY)

    async def follow_current_artist(self, page: IRichBrowserSession) -> bool:
        """Sigue al artista (estando en su pagina). True si tuvo exito."""
        return await self._safe_click(page, sel.ARTIST_FOLLOW)

    # ── Helpers internos ──────────────────────────────────────────────────
    async def _await_login_completion(self, page: IBrowserSession) -> None:
        """Polling de salida del login: o avatar, o 2FA, o captcha, o error.

        2FA = AuthenticationError (cuenta no warmed; Apple device binding).
        Captcha sin solver = AuthenticationError. Con solver, lo intenta
        resolver y vuelve a hacer polling.
        """
        deadline_iters = int(_LOGIN_TOTAL_WAIT_S / _LOGIN_POLL_S)
        for _ in range(deadline_iters):
            await asyncio.sleep(_LOGIN_POLL_S)
            if await self._selector_appeared(page, sel.USER_AVATAR):
                return
            if await self._selector_appeared(page, sel.TWO_FACTOR_HINT, timeout_ms=300):
                raise AuthenticationError(
                    "Apple 2FA activado: cuenta requiere device-binding previo (warming)",
                )
            if await self._selector_appeared(page, sel.HCAPTCHA_FRAME, timeout_ms=300):
                if self._captcha_solver is None:
                    raise AuthenticationError("hCaptcha durante login y no hay solver inyectado")
                await self._solve_hcaptcha_during_login(page)
                continue
            if await self._selector_appeared(page, sel.LOGIN_ERROR, timeout_ms=300):
                raise AuthenticationError("AppleID rechazado o cuenta bloqueada")

        raise AuthenticationError("login no se completo en el tiempo esperado")

    async def _solve_hcaptcha_during_login(self, page: IBrowserSession) -> None:
        """Resuelve un hCaptcha intra-login y lo inyecta en el form.

        Esta es una implementacion conservadora: leemos el data-sitekey,
        pedimos token al solver y lo pegamos en el textarea hidden estandar
        de hCaptcha (`h-captcha-response`). El submit final lo dispara
        Apple cuando detecta el token via callback.
        """
        if self._captcha_solver is None:
            raise AuthenticationError("hCaptcha durante login y no hay solver inyectado")
        try:
            site_key = await page.evaluate(
                "() => {"
                "  const el = document.querySelector('[data-sitekey]');"
                "  return el && el.getAttribute('data-sitekey');"
                "}",
            )
            page_url = await page.evaluate("() => document.location.href")
        except Exception as exc:
            raise AuthenticationError(f"no pude leer el hCaptcha: {exc}") from exc

        if not site_key or not page_url:
            raise AuthenticationError("hCaptcha sin site_key o url accesible")

        token = await self._captcha_solver.solve_hcaptcha(
            site_key=str(site_key),
            page_url=str(page_url),
        )
        # hCaptcha estandar inyecta el token en un textarea hidden compartido
        # entre el iframe y la pagina padre; sobreescribimos ambos por seguridad.
        injection_js = (
            "() => {"
            f"  const token = {token!r};"
            "  const tas = document.querySelectorAll("
            "    'textarea[name=\"h-captcha-response\"], textarea[name=\"g-recaptcha-response\"]'"
            "  );"
            "  tas.forEach((t) => { t.value = token; });"
            "}"
        )
        try:
            await page.evaluate(injection_js)
        except Exception as exc:
            raise AuthenticationError(f"no pude inyectar token hCaptcha: {exc}") from exc
        # Apple-side: dejamos que el callback de hCaptcha dispare el submit
        # (configurado en su widget) o que el siguiente poll detecte el avatar.

    @staticmethod
    async def _selector_appeared(
        page: IBrowserSession,
        selector: str,
        *,
        timeout_ms: int = 500,
    ) -> bool:
        """True si el selector aparece dentro del timeout, False si no."""
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
