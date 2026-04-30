"""Estrategia para Spotify Web Player.

Implementa `ISiteStrategy` (interfaz heredada) pero su `perform_action` se
limita a delegar al `PlaylistSessionUseCase` cuando este esta disponible.
Para ejecuciones legacy de "stream-cancion", `perform_action` simula la
reproduccion de un track simple usando los selectores de Q1 2026.

Selectores: data-testid first, aria-label como fallback. Nunca CSS classes
de Spotify (cambian semanalmente).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from streaming_bot.application.stream_song import ISiteStrategy
from streaming_bot.domain.entities import Account
from streaming_bot.domain.exceptions import AuthenticationError, TargetSiteError

if TYPE_CHECKING:
    from streaming_bot.domain.ports.browser import IBrowserSession


# ── Selectores Spotify Web Player (Q1 2026) ────────────────────────────────
LOGIN_USERNAME = '[data-testid="login-username"]'
LOGIN_PASSWORD = '[data-testid="login-password"]'  # noqa: S105  selector, no secret
LOGIN_BUTTON = '[data-testid="login-button"]'
USER_WIDGET_NAME = '[data-testid="user-widget-name"]'

PLAYLIST_PLAY_BUTTON = '[data-testid="play-button"]'
PLAYER_CONTROLS = '[data-testid="player-controls__buttons"]'
PLAY_PAUSE = '[data-testid="control-button-playpause"]'
NOW_PLAYING_WIDGET = '[data-testid="now-playing-widget"]'
TRACK_TITLE = '[data-testid="context-item-info-title"]'
TRACK_ARTIST = '[data-testid="context-item-info-artist"]'

CAPTCHA_HINT = '[data-testid="captcha"]'
LOGIN_FAILED_HINT = '[data-testid="login-error"]'

LOGIN_URL = "https://accounts.spotify.com/login"


class SpotifyWebPlayerStrategy(ISiteStrategy):
    """Estrategia de site para Spotify Web Player.

    Esta clase es delgada: delega los flujos complejos (playlist + 33 behaviors)
    al `PlaylistSessionUseCase`. Aqui solo viven login, deteccion de logueado,
    y un `perform_action` minimo para compatibilidad con `StreamSongUseCase`.
    """

    async def is_logged_in(self, page: IBrowserSession) -> bool:
        """Detecta sesion activa por presencia del widget de usuario.

        No reintenta. Si el selector no aparece en 3s asumimos que no esta
        logueado (cookie expirada, primer login, etc.).
        """
        try:
            await page.wait_for_selector(USER_WIDGET_NAME, timeout_ms=3000)
            return True
        except Exception:
            return False

    async def login(self, page: IBrowserSession, account: Account) -> None:
        """Login estandar con detección defensiva de captcha y errores."""
        await page.goto(LOGIN_URL, wait_until="domcontentloaded")

        try:
            await page.wait_for_selector(LOGIN_USERNAME, timeout_ms=10_000)
        except Exception as exc:
            raise TargetSiteError(f"login form no aparecio: {exc}") from exc

        await page.fill(LOGIN_USERNAME, account.username)
        await page.fill(LOGIN_PASSWORD, account.password)
        await page.click(LOGIN_BUTTON)

        # Esperamos: o el widget de usuario (success) o un hint de error.
        for _ in range(40):  # ~20s con sleeps de 0.5s
            await asyncio.sleep(0.5)
            if await self._selector_appeared(page, USER_WIDGET_NAME):
                return
            if await self._selector_appeared(page, CAPTCHA_HINT, timeout_ms=300):
                raise AuthenticationError("captcha durante login")
            if await self._selector_appeared(page, LOGIN_FAILED_HINT, timeout_ms=300):
                raise AuthenticationError("credenciales rechazadas")

        raise AuthenticationError("login no se completo en el tiempo esperado")

    @staticmethod
    async def _selector_appeared(
        page: IBrowserSession,
        selector: str,
        *,
        timeout_ms: int = 500,
    ) -> bool:
        """Helper: True si el selector aparece dentro del timeout."""
        try:
            await page.wait_for_selector(selector, timeout_ms=timeout_ms)
        except Exception:
            return False
        return True

    async def perform_action(
        self,
        page: IBrowserSession,
        target_url: str,
        listen_seconds: int,
    ) -> None:
        """Reproduccion simple de un track o playlist (modo legacy).

        Para el flujo rico (playlist + behaviors) se invoca `PlaylistSessionUseCase`,
        no este metodo. Mantenemos este simple por compatibilidad con `StreamSongUseCase`.
        """
        await page.goto(target_url, wait_until="domcontentloaded")
        try:
            await page.wait_for_selector(PLAYLIST_PLAY_BUTTON, timeout_ms=10_000)
            await page.click(PLAYLIST_PLAY_BUTTON)
        except Exception:
            try:
                await page.wait_for_selector(PLAY_PAUSE, timeout_ms=5_000)
                await page.click(PLAY_PAUSE)
            except Exception as exc:
                raise TargetSiteError(f"no se pudo iniciar reproduccion: {exc}") from exc

        await asyncio.sleep(max(listen_seconds, 35))

    # ── Helpers privados (uso desde PlaylistSessionUseCase) ───────────────
    async def wait_for_player_ready(self, page: IBrowserSession) -> None:
        """Espera a que el now-playing widget tenga track cargado."""
        try:
            await page.wait_for_selector(NOW_PLAYING_WIDGET, timeout_ms=15_000)
            await page.wait_for_selector(TRACK_TITLE, timeout_ms=10_000)
        except Exception as exc:
            raise TargetSiteError(f"player no llego a estado ready: {exc}") from exc

    async def get_current_track_uri(self, page: IBrowserSession) -> str | None:
        """Lee el URI del track actual desde el data attribute del widget."""
        try:
            uri = await page.evaluate(
                "() => {"
                "  const el = document.querySelector('[data-testid=\"now-playing-widget\"]');"
                "  return el && el.getAttribute('data-track-uri');"
                "}",
            )
            return str(uri) if uri else None
        except Exception:
            return None

    async def get_current_artist_uri(self, page: IBrowserSession) -> str | None:
        """Lee el URI del artista actual desde el link del player."""
        try:
            href = await page.evaluate(
                "() => {"
                "  const el = document.querySelector('[data-testid=\"context-item-info-artist\"]');"
                "  return el && el.getAttribute('href');"
                "}",
            )
            if not href:
                return None
            artist_id = str(href).rstrip("/").split("/")[-1]
            return f"spotify:artist:{artist_id}"
        except Exception:
            return None
