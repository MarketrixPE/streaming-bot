"""Estrategia NetEase Cloud Music (China) implementando IRichSiteStrategy.

NetEase es el DSP de mayor dificultad operativa del router asiatico:
- Solo accesible desde IPs CN -> el orquestador DEBE pedir un proxy con
  `country=Country.CN` antes de invocar esta strategy. La strategy NO
  valida la geo del proxy: esa es responsabilidad del use case (el
  fingerprint v1 derivara timezone Asia/Shanghai + locale zh-CN
  automaticamente).
- Login solo via telefono +86 + SMS code: la cuenta debe traer
  `username` = numero +86 (con prefijo o sin el) y `password` = codigo
  SMS recien recibido del provider (5SIM, etc.). El orquestador es
  quien hace la danza SMS hub -> cuenta antes de pasarnos el codigo.
- Player y engagement viven dentro de un iframe (`contentFrame`); el
  driver Camoufox/Patchright debe haber drilling de frames antes de
  pasarnos `IBrowserSession`. Si el host pasa el documento principal,
  los selectores siguen funcionando en muchas paginas (NetEase migro
  parte de la UI a SPA), pero los helpers `evaluate` consultan el
  document raiz que ya el caller selecciono.

Esta strategy mantiene el contrato thin del paquete y delega el ritmo
humano al engine de behaviors.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from streaming_bot.application.ports.site_strategy import IRichSiteStrategy
from streaming_bot.domain.exceptions import AuthenticationError, TargetSiteError
from streaming_bot.presentation.strategies import netease_selectors as sel

if TYPE_CHECKING:
    from streaming_bot.domain.entities import Account
    from streaming_bot.domain.ports.browser import IBrowserSession
    from streaming_bot.domain.ports.browser_rich import IRichBrowserSession


class NetEaseStrategy(IRichSiteStrategy):
    """Strategy thin para NetEase Cloud Music.

    Importante: requiere proxy CN para no rebotar contra el muro
    geografico del DSP. Sin IP china, los assets ni siquiera cargan
    (timeouts en goto). El orquestador es responsable de garantizar la
    geo correcta antes de invocar la strategy.
    """

    async def is_logged_in(self, page: IBrowserSession) -> bool:
        try:
            await page.wait_for_selector(sel.USER_AVATAR, timeout_ms=3000)
        except Exception:
            return False
        return True

    async def login(self, page: IBrowserSession, account: Account) -> None:
        """Login via telefono +86 + SMS code.

        Convencion: `account.username` = numero CN (`+86138...`) y
        `account.password` = codigo SMS de 4-6 digitos provisto por el
        SMS hub justo antes de la ejecucion. La strategy NO consulta el
        hub: el caller es quien orquesta la peticion + write del codigo
        en el campo `password`.
        """
        await page.goto(sel.LOGIN_URL, wait_until="domcontentloaded")

        try:
            await page.wait_for_selector(sel.PHONE_INPUT, timeout_ms=10_000)
        except Exception as exc:
            raise TargetSiteError(f"login form de NetEase no aparecio: {exc}") from exc

        await page.fill(sel.PHONE_INPUT, account.username)
        await page.fill(sel.SMS_CODE_INPUT, account.password)
        await page.click(sel.LOGIN_SUBMIT)

        for _ in range(40):  # ~20s con sleeps de 0.5s
            await asyncio.sleep(0.5)
            if await self._selector_appeared(page, sel.USER_AVATAR):
                return
            if await self._selector_appeared(page, sel.LOGIN_ERROR, timeout_ms=300):
                raise AuthenticationError("SMS/telefono rechazado por NetEase")

        raise AuthenticationError("login NetEase no se completo en el tiempo esperado")

    async def perform_action(
        self,
        page: IBrowserSession,
        target_url: str,
        listen_seconds: int,
    ) -> None:
        """Navega al target_url y arranca la reproduccion via `.ply`."""
        await page.goto(target_url, wait_until="domcontentloaded")
        try:
            await page.wait_for_selector(sel.PLAY_BUTTON, timeout_ms=10_000)
            await page.click(sel.PLAY_BUTTON)
        except Exception as exc:
            raise TargetSiteError(f"no se pudo iniciar reproduccion NetEase: {exc}") from exc

        await asyncio.sleep(max(listen_seconds, 35))

    # ── Helpers de player ────────────────────────────────────────────────
    async def wait_for_player_ready(self, page: IRichBrowserSession) -> None:
        """Espera al player-bar y al titulo del track actual."""
        try:
            await page.wait_for_selector(sel.NOW_PLAYING_WIDGET, timeout_ms=15_000)
            await page.wait_for_selector(sel.NOW_PLAYING_TITLE, timeout_ms=10_000)
        except Exception as exc:
            raise TargetSiteError(f"player NetEase no llego a ready: {exc}") from exc

    async def get_current_track_uri(self, page: IRichBrowserSession) -> str | None:
        """Lee el id del track desde el player-bar.

        NetEase mantiene un `data-track-id` en `.m-playbar` para sincronizar
        el bar con el track activo. Devolvemos `netease:song:<id>` como
        URI canonica.
        """
        try:
            track_id = await page.evaluate(
                "() => {"
                "  const el = document.querySelector('.m-playbar, .player');"
                "  return el && (el.getAttribute('data-track-id') "
                "|| el.getAttribute('data-song-id'));"
                "}",
            )
        except Exception:
            return None
        if not track_id:
            return None
        return f"netease:song:{track_id}"

    async def get_current_artist_uri(self, page: IRichBrowserSession) -> str | None:
        """Lee el href del artista del track actual.

        NetEase enlaza al artista con paths del tipo `/#/artist?id=<id>`;
        intentamos extraer el query param `id` y, como fallback, el ultimo
        segmento del pathname.
        """
        try:
            href = await page.evaluate(
                "() => {"
                "  const a = document.querySelector("
                "'.words .by a, .play-by a');"
                "  return a && a.getAttribute('href');"
                "}",
            )
        except Exception:
            return None
        if not href:
            return None
        href_str = str(href)
        artist_id = self._extract_artist_id(href_str)
        if not artist_id:
            return None
        return f"netease:artist:{artist_id}"

    @staticmethod
    def _extract_artist_id(href: str) -> str | None:
        """Extrae el id de artista de URLs estilo NetEase.

        Formatos vistos: `/#/artist?id=12345`, `/artist/12345`,
        `https://music.163.com/#/artist?id=12345`. Estrategia: buscar
        `id=` y, si no esta, caer al ultimo segmento del path.
        """
        marker = "id="
        if marker in href:
            tail = href.split(marker, 1)[1]
            artist_id = tail.split("&", 1)[0].strip()
            if artist_id:
                return artist_id
        last = href.rstrip("/").split("/")[-1].strip()
        return last or None

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
