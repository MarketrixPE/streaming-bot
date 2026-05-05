"""Estrategia KKBox (Taiwan + HK + SE Asia) implementando IRichSiteStrategy.

KKBox tiene antifraude moderado (en el midpoint entre JioSaavn y Spotify);
payout decente (~$0.002/stream) y sirve para los mercados taiwanes,
honkonese y como fallback aceptable para Korea. El login es estandar
email/password; el captcha solo aparece en signup (hCaptcha).

Diseno espejo a las otras strategies del paquete: selectores externos,
flujo defensivo en login, helpers `wait_for_player_ready` /
`get_current_*_uri` para el `PlaylistSessionUseCase`.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from streaming_bot.application.ports.site_strategy import IRichSiteStrategy
from streaming_bot.domain.exceptions import AuthenticationError, TargetSiteError
from streaming_bot.presentation.strategies import kkbox_selectors as sel

if TYPE_CHECKING:
    from streaming_bot.domain.entities import Account
    from streaming_bot.domain.ports.browser import IBrowserSession
    from streaming_bot.domain.ports.browser_rich import IRichBrowserSession


class KKBoxStrategy(IRichSiteStrategy):
    """Strategy thin para KKBox: login + reproduccion + helpers de player.

    El captcha hCaptcha es defensivo aqui (no deberia disparar en login,
    si lo hace lanzamos AuthenticationError para que el orquestador
    enrute al ICaptchaSolver con la site_key del frame).
    """

    async def is_logged_in(self, page: IBrowserSession) -> bool:
        try:
            await page.wait_for_selector(sel.USER_AVATAR, timeout_ms=3000)
        except Exception:
            return False
        return True

    async def login(self, page: IBrowserSession, account: Account) -> None:
        """Login email + password. Detecta hCaptcha y errores visibles.

        El hCaptcha de KKBox aparece principalmente en signup; si en login
        emerge (por reputacion baja del IP o de la cuenta) lanzamos
        AuthenticationError para forzar reentry con la pipeline de
        captcha solver del use case superior.
        """
        await page.goto(sel.LOGIN_URL, wait_until="domcontentloaded")

        try:
            await page.wait_for_selector(sel.LOGIN_EMAIL, timeout_ms=10_000)
        except Exception as exc:
            raise TargetSiteError(f"login form de KKBox no aparecio: {exc}") from exc

        await page.fill(sel.LOGIN_EMAIL, account.username)
        await page.fill(sel.LOGIN_PASSWORD, account.password)
        await page.click(sel.LOGIN_SUBMIT)

        for _ in range(40):  # ~20s con sleeps de 0.5s
            await asyncio.sleep(0.5)
            if await self._selector_appeared(page, sel.USER_AVATAR):
                return
            if await self._selector_appeared(page, sel.HCAPTCHA_FRAME, timeout_ms=300):
                raise AuthenticationError("hCaptcha durante login KKBox")
            if await self._selector_appeared(page, sel.LOGIN_ERROR, timeout_ms=300):
                raise AuthenticationError("credenciales rechazadas por KKBox")

        raise AuthenticationError("login KKBox no se completo en el tiempo esperado")

    async def perform_action(
        self,
        page: IBrowserSession,
        target_url: str,
        listen_seconds: int,
    ) -> None:
        """Navega al target_url y arranca la reproduccion via play-pause."""
        await page.goto(target_url, wait_until="domcontentloaded")
        try:
            await page.wait_for_selector(sel.PLAY_PAUSE, timeout_ms=10_000)
            await page.click(sel.PLAY_PAUSE)
        except Exception as exc:
            raise TargetSiteError(f"no se pudo iniciar reproduccion KKBox: {exc}") from exc

        await asyncio.sleep(max(listen_seconds, 35))

    # ── Helpers de player ────────────────────────────────────────────────
    async def wait_for_player_ready(self, page: IRichBrowserSession) -> None:
        """Espera al player-bar y al titulo del track actual."""
        try:
            await page.wait_for_selector(sel.NOW_PLAYING_WIDGET, timeout_ms=15_000)
            await page.wait_for_selector(sel.NOW_PLAYING_TITLE, timeout_ms=10_000)
        except Exception as exc:
            raise TargetSiteError(f"player KKBox no llego a ready: {exc}") from exc

    async def get_current_track_uri(self, page: IRichBrowserSession) -> str | None:
        """Lee el atributo `data-track-id` del widget de player.

        KKBox expone el id del track via data-attributes en el player-bar
        (mismo patron que Spotify). Devolvemos `kkbox:song:<id>` para
        mantener una URI canonica estable.
        """
        try:
            track_id = await page.evaluate(
                "() => {"
                "  const el = document.querySelector('[data-testid=\"player-bar\"], "
                "[data-testid=\"now-playing\"]');"
                "  return el && (el.getAttribute('data-track-id') "
                "|| el.getAttribute('data-song-id'));"
                "}",
            )
        except Exception:
            return None
        if not track_id:
            return None
        return f"kkbox:song:{track_id}"

    async def get_current_artist_uri(self, page: IRichBrowserSession) -> str | None:
        """Lee el href del artista del track actual y extrae el id."""
        try:
            href = await page.evaluate(
                "() => {"
                "  const a = document.querySelector("
                "'[data-testid=\"now-playing-artist\"] a');"
                "  return a && a.getAttribute('href');"
                "}",
            )
        except Exception:
            return None
        if not href:
            return None
        artist_id = str(href).rstrip("/").split("/")[-1]
        if not artist_id:
            return None
        return f"kkbox:artist:{artist_id}"

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
