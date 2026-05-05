"""Estrategia ACPS-aware para Deezer Web Player.

Cumple `IRichSiteStrategy`:
- `is_logged_in`: detecta sesion via presencia del menu de usuario.
- `login`: rellena formulario, resuelve hCaptcha via `ICaptchaSolver` si
  aparece, y espera al menu del usuario.
- `perform_action`: ejecuta una sesion super-fan minima (target + replay)
  para mantener compatibilidad con `StreamSongUseCase`.
- `play_planned_session`: reproduce una `PlannedSession` previamente
  generada por `SuperFanEmulationEngine`. Es el flujo recomendado para
  Deezer; incluye jitter humano y respeta el orden del plan.
- `wait_for_player_ready`, `get_current_track_uri`, `get_current_artist_uri`:
  helpers que `PlaylistSessionUseCase` u otros orquestadores pueden usar.

Esta clase NO toca httpx ni `IDeezerClient` directamente. La fuente de
datos del plan se inyecta como `PlannedSession` ya construido. Asi mantenemos
limpia la frontera presentation -> application -> infrastructure.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import TYPE_CHECKING

from streaming_bot.application.ports.site_strategy import IRichSiteStrategy
from streaming_bot.domain.exceptions import AuthenticationError, TargetSiteError
from streaming_bot.presentation.strategies import deezer_selectors as sel

if TYPE_CHECKING:
    from streaming_bot.application.deezer.super_fan_emulation_engine import PlannedSession
    from streaming_bot.domain.entities import Account
    from streaming_bot.domain.ports.browser import IBrowserSession
    from streaming_bot.domain.ports.browser_rich import IRichBrowserSession
    from streaming_bot.domain.ports.captcha_solver import ICaptchaSolver


_LOGIN_POLL_ITERATIONS = 40
_LOGIN_POLL_INTERVAL_SECONDS = 0.5
_HCAPTCHA_DETECT_TIMEOUT_MS = 1500


class DeezerStrategy(IRichSiteStrategy):
    """Estrategia Deezer ACPS-aware.

    Args:
        captcha_solver: opcional. Si Deezer presenta hCaptcha y no se inyecta,
            el login lanza `AuthenticationError`. En produccion siempre debe
            inyectarse uno.
    """

    def __init__(self, *, captcha_solver: ICaptchaSolver | None = None) -> None:
        self._captcha = captcha_solver

    # ── ISiteStrategy ─────────────────────────────────────────────────────
    async def is_logged_in(self, page: IBrowserSession) -> bool:
        """True si vemos el menu de usuario en <3s."""
        try:
            await page.wait_for_selector(sel.USER_MENU, timeout_ms=3000)
            return True
        except Exception:
            return False

    async def login(self, page: IBrowserSession, account: Account) -> None:
        """Login estandar con manejo defensivo de hCaptcha y errores."""
        await page.goto(sel.LOGIN_URL, wait_until="domcontentloaded")

        try:
            await page.wait_for_selector(sel.LOGIN_EMAIL, timeout_ms=10_000)
        except Exception as exc:
            raise TargetSiteError(f"login form no aparecio: {exc}") from exc

        await page.fill(sel.LOGIN_EMAIL, account.username)
        await page.fill(sel.LOGIN_PASSWORD, account.password)

        # Resolver hCaptcha si aparece ANTES del submit.
        await self._maybe_solve_hcaptcha(page)

        await page.click(sel.LOGIN_SUBMIT)

        for _ in range(_LOGIN_POLL_ITERATIONS):
            await asyncio.sleep(_LOGIN_POLL_INTERVAL_SECONDS)
            if await self._selector_appeared(page, sel.USER_MENU):
                return
            if await self._selector_appeared(page, sel.LOGIN_ERROR, timeout_ms=300):
                raise AuthenticationError("credenciales rechazadas por Deezer")
            if await self._selector_appeared(page, sel.HCAPTCHA_CONTAINER, timeout_ms=300):
                # Si re-aparece tras submit es probable rerolling: intentamos
                # resolverlo una vez mas y seguimos polling.
                await self._maybe_solve_hcaptcha(page)

        raise AuthenticationError("login Deezer no se completo en el tiempo esperado")

    async def perform_action(
        self,
        page: IBrowserSession,
        target_url: str,
        listen_seconds: int,
    ) -> None:
        """Reproduccion simple de un track + 1 replay (modo legacy ACPS-aware).

        Para sesiones super-fan completas (>= 45min con relleno) usar
        `play_planned_session(page, plan)`; este metodo es el minimo viable
        para compatibilidad con `StreamSongUseCase`.
        """
        await page.goto(target_url, wait_until="domcontentloaded")
        try:
            await page.wait_for_selector(sel.PLAY_PAUSE, timeout_ms=10_000)
        except Exception as exc:
            raise TargetSiteError(f"player Deezer no aparecio: {exc}") from exc

        await page.click(sel.PLAY_PAUSE)
        # Garantizamos al menos 35s (umbral minimo de stream contado) y
        # respetamos el `listen_seconds` solicitado por el caller.
        await asyncio.sleep(max(listen_seconds, 35))
        # Replay: aprieta de nuevo play (en Deezer pause + play reinicia).
        await page.click(sel.PLAY_PAUSE)
        await asyncio.sleep(max(listen_seconds, 35))

    # ── IRichSiteStrategy ────────────────────────────────────────────────
    async def wait_for_player_ready(self, page: IRichBrowserSession) -> None:
        try:
            await page.wait_for_selector(sel.NOW_PLAYING_WIDGET, timeout_ms=15_000)
            await page.wait_for_selector(sel.NOW_PLAYING_TITLE, timeout_ms=10_000)
        except Exception as exc:
            raise TargetSiteError(f"player no llego a estado ready: {exc}") from exc

    async def get_current_track_uri(self, page: IRichBrowserSession) -> str | None:
        """Lee el URI canonico del track actual desde un data-attribute.

        Deezer expone `data-track-id` en el widget de now-playing; lo
        envolvemos en el formato `deezer:track:{id}` por simetria con Spotify.
        """
        try:
            track_id = await page.evaluate(
                "() => {"
                "  const el = document.querySelector('[data-testid=\"now-playing\"]');"
                "  return el && el.getAttribute('data-track-id');"
                "}",
            )
            return f"deezer:track:{track_id}" if track_id else None
        except Exception:
            return None

    async def get_current_artist_uri(self, page: IRichBrowserSession) -> str | None:
        try:
            artist_id = await page.evaluate(
                "() => {"
                "  const el = document.querySelector('[data-testid=\"now-playing\"]');"
                "  return el && el.getAttribute('data-artist-id');"
                "}",
            )
            return f"deezer:artist:{artist_id}" if artist_id else None
        except Exception:
            return None

    # ── Sesion super-fan ─────────────────────────────────────────────────
    async def play_planned_session(
        self,
        page: IRichBrowserSession,
        plan: PlannedSession,
    ) -> None:
        """Reproduce todos los tracks de `plan` en orden, con jitter humano.

        Cada `PlannedTrackPlay` se ejecuta como:
        1. `pre_jitter_seconds` de espera (3-15s segun el plan).
        2. Navegacion al URL del track (`https://www.deezer.com/track/{id}`).
        3. Click en play.
        4. Espera de `listen_seconds`.

        Si una navegacion falla puntualmente, se loguea (via excepcion) y
        seguimos con el siguiente play; el plan completo es lo importante.
        """
        for play in plan.plays:
            if play.pre_jitter_seconds > 0:
                await asyncio.sleep(play.pre_jitter_seconds)
            track_url = self._track_url(play.track_uri)
            played = await self._safe_play(page, track_url)
            if played:
                await asyncio.sleep(max(play.listen_seconds, 35))

    # ── Helpers privados ─────────────────────────────────────────────────
    @staticmethod
    async def _safe_play(page: IRichBrowserSession, track_url: str) -> bool:
        """Navega y arranca el play. Devuelve True solo si todo tuvo exito.

        Falla blanda: una excepcion deja el play sin contar y deja al caller
        seguir con el siguiente. El logging detallado vive en el adapter del
        browser; aqui evitamos `try/except/continue` porque ruff (S112)
        recomienda separar la decision en una funcion explicita.
        """
        try:
            await page.goto(track_url, wait_until="domcontentloaded")
            await page.wait_for_selector(sel.PLAY_PAUSE, timeout_ms=10_000)
            await page.click(sel.PLAY_PAUSE)
        except Exception:
            return False
        return True

    @staticmethod
    def _track_url(track_uri: str) -> str:
        """Convierte `deezer:track:1234` -> `https://www.deezer.com/track/1234`."""
        if track_uri.startswith("deezer:track:"):
            track_id = track_uri.rsplit(":", maxsplit=1)[-1]
            return f"https://www.deezer.com/track/{track_id}"
        return track_uri

    async def _maybe_solve_hcaptcha(self, page: IBrowserSession) -> None:
        """Detecta hCaptcha y delega la resolucion al `ICaptchaSolver`.

        Si no hay solver inyectado y el captcha esta presente, lanzamos
        `AuthenticationError` para detener el login limpiamente.
        """
        appeared = await self._selector_appeared(
            page,
            sel.HCAPTCHA_CONTAINER,
            timeout_ms=_HCAPTCHA_DETECT_TIMEOUT_MS,
        )
        if not appeared:
            return
        if self._captcha is None:
            raise AuthenticationError("hCaptcha presente pero no hay ICaptchaSolver inyectado")

        site_key = await self._read_hcaptcha_sitekey(page)
        if not site_key:
            raise AuthenticationError("no se pudo leer site_key del hCaptcha de Deezer")

        page_url = await self._current_page_url(page)
        token = await self._captcha.solve_hcaptcha(site_key=site_key, page_url=page_url)
        # Inyectamos el token en el textarea oculto que Deezer lee al submit.
        # Escapamos las comillas via json.dumps para evitar inyeccion JS.
        token_literal = json.dumps(token)
        with contextlib.suppress(Exception):
            await page.evaluate(
                "() => {"
                f"  const token = {token_literal};"
                "  const el = document.querySelector('textarea[name=\"h-captcha-response\"]');"
                "  if (el) { el.value = token; }"
                "}",
            )

    @staticmethod
    async def _read_hcaptcha_sitekey(page: IBrowserSession) -> str | None:
        try:
            value = await page.evaluate(
                "() => {"
                "  const el = document.querySelector('[data-sitekey]');"
                "  return el && el.getAttribute('data-sitekey');"
                "}",
            )
            return str(value) if value else None
        except Exception:
            return None

    @staticmethod
    async def _current_page_url(page: IBrowserSession) -> str:
        """Devuelve la URL actual del browser. Cae a LOGIN_URL si el driver
        no expone `current_url` (caso `IBrowserSession` basico)."""
        try:
            url = await page.evaluate("() => document.location.href")
            return str(url) if url else sel.LOGIN_URL
        except Exception:
            return sel.LOGIN_URL

    @staticmethod
    async def _selector_appeared(
        page: IBrowserSession,
        selector: str,
        *,
        timeout_ms: int = 500,
    ) -> bool:
        try:
            await page.wait_for_selector(selector, timeout_ms=timeout_ms)
        except Exception:
            return False
        return True
