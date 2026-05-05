"""Estrategia JioSaavn (India) implementando IRichSiteStrategy.

JioSaavn es un DSP de altisimo volumen y bajo payout (~$0.0005/stream):
ideal para AI music masiva (lo-fi, sleep, study). Antifraude bajo en
relacion con Spotify; basta con login estandar email/password y un
player web mobile-first. La complejidad real esta en mantener el feed
diversificado (parecer un usuario IN normal) mas que en tecnicas
anti-bot avanzadas.

Diseno:
- Igual que `SpotifyWebPlayerStrategy`: selectores externalizados a
  `jiosaavn_selectors.py` para que un cambio de DOM solo toque un archivo.
- `perform_action` modo simple: navega al target_url, dispara el play y
  espera `listen_seconds`. Los behaviors humanos (likes, follows,
  navegaciones laterales) son responsabilidad del `PlaylistSessionUseCase`
  via los helpers `wait_for_player_ready` / `get_current_*_uri`.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from streaming_bot.application.ports.site_strategy import IRichSiteStrategy
from streaming_bot.domain.exceptions import AuthenticationError, TargetSiteError
from streaming_bot.presentation.strategies import jiosaavn_selectors as sel

if TYPE_CHECKING:
    from streaming_bot.domain.entities import Account
    from streaming_bot.domain.ports.browser import IBrowserSession
    from streaming_bot.domain.ports.browser_rich import IRichBrowserSession


class JioSaavnStrategy(IRichSiteStrategy):
    """Estrategia thin para JioSaavn (login + reproduccion + helpers de player).

    Cumple el contrato `IRichSiteStrategy` (login, is_logged_in,
    perform_action, wait_for_player_ready, get_current_track_uri,
    get_current_artist_uri). Los flujos humanos completos (likes
    probabilisticos, scrolls, follows) se delegan al engine de
    behaviors aguas arriba.
    """

    async def is_logged_in(self, page: IBrowserSession) -> bool:
        """Detecta sesion activa por presencia del avatar de cuenta.

        No reintenta: si el selector no aparece en 3s asumimos cuenta
        deslogueada (cookie expirada, primer login, etc.).
        """
        try:
            await page.wait_for_selector(sel.USER_AVATAR, timeout_ms=3000)
        except Exception:
            return False
        return True

    async def login(self, page: IBrowserSession, account: Account) -> None:
        """Login estandar email + password con deteccion defensiva de errores.

        JioSaavn ofrece login con telefono +91 o email; aqui usamos email
        que es el flujo soportado por las cuentas farm. Si aparece el
        captcha (signup-only normalmente) lanzamos AuthenticationError
        para que el orquestador lo enrute al solver dedicado.
        """
        await page.goto(sel.LOGIN_URL, wait_until="domcontentloaded")

        try:
            await page.wait_for_selector(sel.LOGIN_EMAIL, timeout_ms=10_000)
        except Exception as exc:
            raise TargetSiteError(f"login form de JioSaavn no aparecio: {exc}") from exc

        await page.fill(sel.LOGIN_EMAIL, account.username)
        await page.fill(sel.LOGIN_PASSWORD, account.password)
        await page.click(sel.LOGIN_SUBMIT)

        # Loop defensivo: o avatar (success), o captcha, o error visible.
        for _ in range(40):  # ~20s con sleeps de 0.5s
            await asyncio.sleep(0.5)
            if await self._selector_appeared(page, sel.USER_AVATAR):
                return
            if await self._selector_appeared(page, sel.CAPTCHA_HINT, timeout_ms=300):
                raise AuthenticationError("captcha durante login JioSaavn")
            if await self._selector_appeared(page, sel.LOGIN_ERROR, timeout_ms=300):
                raise AuthenticationError("credenciales rechazadas por JioSaavn")

        raise AuthenticationError("login JioSaavn no se completo en el tiempo esperado")

    async def perform_action(
        self,
        page: IBrowserSession,
        target_url: str,
        listen_seconds: int,
    ) -> None:
        """Navega al target_url y arranca la reproduccion.

        El minimo para contar como stream pagado en JioSaavn es ~30s;
        usamos 35s como floor por compatibilidad con Spotify (no penaliza
        a nadie alargar un poco).
        """
        await page.goto(target_url, wait_until="domcontentloaded")
        try:
            await page.wait_for_selector(sel.PLAY_ICON, timeout_ms=10_000)
            await page.click(sel.PLAY_ICON)
        except Exception as exc:
            raise TargetSiteError(f"no se pudo iniciar reproduccion JioSaavn: {exc}") from exc

        await asyncio.sleep(max(listen_seconds, 35))

    # ── Helpers de player (consumidos por PlaylistSessionUseCase) ─────────
    async def wait_for_player_ready(self, page: IRichBrowserSession) -> None:
        """Espera a que el player-bar tenga track cargado (titulo visible)."""
        try:
            await page.wait_for_selector(sel.NOW_PLAYING_WIDGET, timeout_ms=15_000)
            await page.wait_for_selector(sel.NOW_PLAYING_TITLE, timeout_ms=10_000)
        except Exception as exc:
            raise TargetSiteError(f"player JioSaavn no llego a ready: {exc}") from exc

    async def get_current_track_uri(self, page: IRichBrowserSession) -> str | None:
        """Lee el data-id del track desde el widget del player.

        JioSaavn embebe `data-id` en el player-bar para el tracking
        interno; lo emitimos como `jiosaavn:song:<id>` para mantener un
        URI canonico estable independiente del sitio.
        """
        try:
            song_id = await page.evaluate(
                "() => {"
                "  const el = document.querySelector('.player-controls, "
                "[data-testid=\"player-bar\"]');"
                "  return el && (el.getAttribute('data-id') "
                "|| el.getAttribute('data-track-id'));"
                "}",
            )
        except Exception:
            return None
        if not song_id:
            return None
        return f"jiosaavn:song:{song_id}"

    async def get_current_artist_uri(self, page: IRichBrowserSession) -> str | None:
        """Lee el href del link de artista del track actual.

        JioSaavn enlaza al artista con paths del tipo `/artist/<slug>/<id>`;
        extraemos el ultimo segmento como id. Si no hay link visible
        (por ejemplo en transiciones) devolvemos None: el caller decide.
        """
        try:
            href = await page.evaluate(
                "() => {"
                "  const a = document.querySelector('.artist-name a, "
                "[data-testid=\"player-track-artist\"] a');"
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
        return f"jiosaavn:artist:{artist_id}"

    @staticmethod
    async def _selector_appeared(
        page: IBrowserSession,
        selector: str,
        *,
        timeout_ms: int = 500,
    ) -> bool:
        """True si el selector aparece dentro del timeout. Nunca propaga."""
        try:
            await page.wait_for_selector(selector, timeout_ms=timeout_ms)
        except Exception:
            return False
        return True
