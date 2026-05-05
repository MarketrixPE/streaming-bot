"""Engine de comportamiento humano para Spotify Web Player.

Implementa los 33+ behaviors documentados en la persona y los ejecuta vía
primitivas humanas de `IRichBrowserSession`. La engine es:

- **Stateless por proceso**: no usa globals, usa un `random.Random(seed)` local.
- **Determinista en tests**: pasando `rng_seed` y `now_factory` se reproduce
  la sesion exacta.
- **No muta la persona**: acumula los efectos en `PersonaMemoryDelta` y deja
  que el use case decida cuando aplicarlos.
- **Tolerante a layout**: usa data-testid primero, aria-label como fallback,
  y registra `selector_not_found` si el elemento no aparece (no crashea).
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from streaming_bot.application.persona_memory_delta import PersonaMemoryDelta
from streaming_bot.domain.history import BehaviorEvent, BehaviorType
from streaming_bot.domain.persona import Persona
from streaming_bot.domain.ports.persona_memory_repo import (
    IPersonaMemoryRepository,
    PersonaMemoryEvent,
    PersonaMemoryEventType,
)

if TYPE_CHECKING:
    from structlog.stdlib import BoundLogger

    from streaming_bot.domain.ports.browser_rich import IRichBrowserSession


# ── Selectores estables (data-testid first) ────────────────────────────────
# Spotify Web Player Q1 2026. Mantener ordenados por feature.
class _SpotifySelectors:
    """Selectores agrupados. Solo `data-testid` y `aria-label`; nunca classes."""

    # Player principal
    PLAY_PAUSE = '[data-testid="control-button-playpause"]'
    NEXT_TRACK = '[data-testid="control-button-skip-forward"]'
    PREVIOUS_TRACK = '[data-testid="control-button-skip-back"]'
    SHUFFLE = '[data-testid="control-button-shuffle"]'
    REPEAT = '[data-testid="control-button-repeat"]'
    NOW_PLAYING_WIDGET = '[data-testid="now-playing-widget"]'
    PROGRESS_BAR = '[data-testid="playback-progressbar"]'
    TIME_REMAINING_TOGGLE = '[data-testid="playback-position"]'

    # Track info
    TRACK_TITLE = '[data-testid="context-item-info-title"]'
    TRACK_ARTIST = '[data-testid="context-item-info-artist"]'

    # Engagement
    LIKE_BUTTON = '[data-testid="add-button"]'
    SAVE_TO_LIBRARY = '[aria-label*="Save to Your Library"]'
    ADD_TO_PLAYLIST_MENU = '[data-testid="add-to-playlist-button"]'
    ADD_TO_QUEUE = '[data-testid="add-to-queue-button"]'
    CANVAS_TOGGLE = '[data-testid="canvas-toggle"]'
    LYRICS_TOGGLE = '[data-testid="lyrics-button"]'
    CREDITS_BUTTON = '[data-testid="credits-button"]'
    SHARE_BUTTON = '[data-testid="share-button"]'

    # Volumen
    VOLUME_BAR = '[data-testid="volume-bar"]'
    MUTE_BUTTON = '[data-testid="volume-bar-toggle-mute-button"]'

    # Devices
    DEVICES_BUTTON = '[data-testid="control-button-connect-device-picker"]'

    # Sidebar / Nav
    SIDEBAR = '[data-testid="rootlist"]'
    HOME_LINK = '[data-testid="home-active-icon"], [data-testid="home-default-icon"]'
    SEARCH_LINK = '[data-testid="search-active-icon"], [data-testid="search-default-icon"]'
    LIBRARY_LINK = '[data-testid="library-active-icon"], [data-testid="library-default-icon"]'
    SEARCH_INPUT = '[data-testid="search-input"]'
    NOTIFICATIONS = '[data-testid="notifications-button"]'
    SETTINGS = '[data-testid="user-widget-link"]'
    VIEW_MODE_TOGGLE = '[data-testid="view-mode-toggle"]'

    # Discovery
    DISCOVER_WEEKLY_LINK = 'a[href*="discover-weekly"]'
    MADE_FOR_YOU_LINK = 'a[href*="made-for-you"]'

    # Artist
    ARTIST_FOLLOW = '[data-testid="follow-button"]'
    ARTIST_ABOUT = '[data-testid="artist-about"]'
    ARTIST_DISCOGRAPHY = '[data-testid="artist-discography"]'

    # Auth (referencia, los usa SpotifyWebPlayerStrategy)
    USER_WIDGET = '[data-testid="user-widget-name"]'


SPOTIFY_HOME = "https://open.spotify.com/"
SPOTIFY_SEARCH = "https://open.spotify.com/search"
SPOTIFY_LIBRARY = "https://open.spotify.com/collection/playlists"


def _default_now() -> datetime:
    """Hora actual en UTC. Inyectable para tests."""
    return datetime.now(UTC)


class HumanBehaviorEngine:
    """Encapsula la decision + ejecucion de cada behavior humano.

    Cada metodo `maybe_*` devuelve un `BehaviorEvent` si ejecuto la accion
    o `None` si el dado decidio que no. La razon de no excepcionar y solo
    loguear errores de selector es que la sesion debe sobrevivir a cambios
    menores de UI; el caso de uso decide si una racha de fallos cierra la
    sesion.
    """

    def __init__(
        self,
        *,
        persona: Persona,
        session_id: str,
        rng_seed: int | None = None,
        logger: BoundLogger,
        now_factory: Callable[[], datetime] = _default_now,
        memory_repo: IPersonaMemoryRepository | None = None,
    ) -> None:
        self._persona = persona
        self._session_id = session_id
        # Aleatoriedad para variar comportamientos; no es seguridad criptografica.
        self._rng = random.Random(rng_seed) if rng_seed is not None else random.Random()  # noqa: S311
        self._log = logger.bind(component="behavior_engine", account_id=persona.account_id)
        self._now = now_factory
        self._memory_delta = PersonaMemoryDelta()
        # Sumidero opcional event-sourced. Si esta presente, cada `commit_memory_async`
        # persiste el delta como log de eventos en la BD ademas de mutarlo en memoria.
        self._memory_repo = memory_repo

    # ── Propiedades de inspeccion ─────────────────────────────────────────
    @property
    def memory_delta(self) -> PersonaMemoryDelta:
        return self._memory_delta

    @property
    def persona(self) -> Persona:
        return self._persona

    # ── Helpers internos ──────────────────────────────────────────────────
    def _roll(self, probability: float) -> bool:
        """Tirada aleatoria. True si la accion debe ejecutarse."""
        if probability <= 0.0:
            return False
        if probability >= 1.0:
            return True
        return self._rng.random() < probability

    def _jittered_sleep(self, min_ms: int, max_ms: int) -> float:
        """Devuelve segundos a dormir con jitter uniforme entre [min_ms, max_ms]."""
        ms = self._rng.randint(min_ms, max_ms)
        return ms / 1000.0

    def _make_event(
        self,
        kind: BehaviorType,
        *,
        target_uri: str | None = None,
        duration_ms: int = 0,
        metadata: dict[str, str] | None = None,
    ) -> BehaviorEvent:
        return BehaviorEvent.new(
            session_id=self._session_id,
            type=kind,
            occurred_at=self._now(),
            target_uri=target_uri,
            duration_ms=duration_ms,
            metadata=metadata or {},
        )

    async def _safe_click(
        self,
        page: IRichBrowserSession,
        selector: str,
        *,
        pre_delay_ms: int = 0,
    ) -> bool:
        """Click humano con verificacion previa. Devuelve True si tuvo exito."""
        if not await page.is_visible(selector, timeout_ms=1500):
            self._log.debug("selector.miss", selector=selector)
            return False
        try:
            await page.human_click(selector, delay_ms_before=pre_delay_ms)
            return True
        except Exception as exc:  # falla blanda: solo logueamos
            self._log.warning("selector.click_failed", selector=selector, error=str(exc))
            return False

    async def _await_jitter(self, min_ms: int, max_ms: int) -> None:
        await asyncio.sleep(self._jittered_sleep(min_ms, max_ms))

    async def _read_track_uri(self, page: IRichBrowserSession) -> str | None:
        """Intenta leer el URI del track actual desde el DOM. Tolerante a None."""
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

    # ╔═════════════════════════════════════════════════════════════════════╗
    # ║ 1. ENGAGEMENT CON CANCION TARGET                                    ║
    # ╚═════════════════════════════════════════════════════════════════════╝

    async def maybe_like_current_track(
        self,
        page: IRichBrowserSession,
    ) -> BehaviorEvent | None:
        if not self._roll(self._persona.traits.behaviors.like):
            return None
        ok = await self._safe_click(
            page,
            _SpotifySelectors.LIKE_BUTTON,
            pre_delay_ms=self._rng.randint(150, 400),
        )
        if not ok:
            return self._make_event(BehaviorType.SELECTOR_NOT_FOUND, metadata={"target": "like"})
        track_uri = await self._read_track_uri(page)
        if track_uri:
            self._memory_delta.add_like(track_uri)
        await self._await_jitter(200, 800)
        return self._make_event(BehaviorType.LIKE, target_uri=track_uri)

    async def maybe_save_to_library(
        self,
        page: IRichBrowserSession,
    ) -> BehaviorEvent | None:
        if not self._roll(self._persona.traits.behaviors.save_to_library):
            return None
        # En Spotify Web "save to library" es el mismo control que like en muchos casos.
        ok = await self._safe_click(page, _SpotifySelectors.SAVE_TO_LIBRARY)
        if not ok:
            ok = await self._safe_click(page, _SpotifySelectors.LIKE_BUTTON)
        if not ok:
            return self._make_event(BehaviorType.SELECTOR_NOT_FOUND, metadata={"target": "save"})
        track_uri = await self._read_track_uri(page)
        if track_uri:
            self._memory_delta.add_save(track_uri)
        return self._make_event(BehaviorType.SAVE_TO_LIBRARY, target_uri=track_uri)

    async def maybe_add_to_playlist(
        self,
        page: IRichBrowserSession,
    ) -> BehaviorEvent | None:
        if not self._roll(self._persona.traits.behaviors.add_to_playlist):
            return None
        ok = await self._safe_click(page, _SpotifySelectors.ADD_TO_PLAYLIST_MENU)
        if not ok:
            return self._make_event(
                BehaviorType.SELECTOR_NOT_FOUND,
                metadata={"target": "add_to_playlist"},
            )
        await self._await_jitter(300, 900)
        track_uri = await self._read_track_uri(page)
        if track_uri:
            self._memory_delta.add_to_playlist(track_uri)
        # Cerrar el menu con Escape para no bloquear flujos posteriores.
        await page.press_key("Escape")
        return self._make_event(BehaviorType.ADD_TO_PLAYLIST, target_uri=track_uri)

    async def maybe_add_to_queue(
        self,
        page: IRichBrowserSession,
    ) -> BehaviorEvent | None:
        if not self._roll(self._persona.traits.behaviors.add_to_queue):
            return None
        ok = await self._safe_click(page, _SpotifySelectors.ADD_TO_QUEUE)
        if not ok:
            return self._make_event(
                BehaviorType.SELECTOR_NOT_FOUND,
                metadata={"target": "add_to_queue"},
            )
        track_uri = await self._read_track_uri(page)
        if track_uri:
            self._memory_delta.add_to_queue(track_uri)
        return self._make_event(BehaviorType.ADD_TO_QUEUE, target_uri=track_uri)

    async def maybe_open_canvas(
        self,
        page: IRichBrowserSession,
    ) -> BehaviorEvent | None:
        if not self._roll(self._persona.traits.behaviors.open_canvas):
            return None
        ok = await self._safe_click(page, _SpotifySelectors.CANVAS_TOGGLE)
        if not ok:
            return self._make_event(BehaviorType.SELECTOR_NOT_FOUND, metadata={"target": "canvas"})
        await self._await_jitter(800, 2500)
        return self._make_event(BehaviorType.OPEN_CANVAS)

    async def maybe_open_lyrics(
        self,
        page: IRichBrowserSession,
    ) -> BehaviorEvent | None:
        if not self._roll(self._persona.traits.behaviors.open_lyrics):
            return None
        ok = await self._safe_click(page, _SpotifySelectors.LYRICS_TOGGLE)
        if not ok:
            return self._make_event(BehaviorType.SELECTOR_NOT_FOUND, metadata={"target": "lyrics"})
        # Tiempo de "lectura" coherente con MouseProfile.
        mouse = self._persona.traits.mouse
        await self._await_jitter(mouse.reading_time_ms_min, mouse.reading_time_ms_max * 4)
        return self._make_event(BehaviorType.OPEN_LYRICS)

    async def maybe_click_credits(
        self,
        page: IRichBrowserSession,
    ) -> BehaviorEvent | None:
        if not self._roll(self._persona.traits.behaviors.click_credits):
            return None
        ok = await self._safe_click(page, _SpotifySelectors.CREDITS_BUTTON)
        if not ok:
            return self._make_event(
                BehaviorType.SELECTOR_NOT_FOUND,
                metadata={"target": "credits"},
            )
        await self._await_jitter(1000, 3000)
        await page.press_key("Escape")
        return self._make_event(BehaviorType.CLICK_CREDITS)

    async def maybe_open_share_modal(
        self,
        page: IRichBrowserSession,
    ) -> BehaviorEvent | None:
        if not self._roll(self._persona.traits.behaviors.open_share_modal):
            return None
        ok = await self._safe_click(page, _SpotifySelectors.SHARE_BUTTON)
        if not ok:
            return self._make_event(BehaviorType.SELECTOR_NOT_FOUND, metadata={"target": "share"})
        await self._await_jitter(500, 1500)
        # No copia ni publica nada; solo abre y cierra (gesto de curiosidad).
        await page.press_key("Escape")
        return self._make_event(BehaviorType.OPEN_SHARE_MODAL)

    # ╔═════════════════════════════════════════════════════════════════════╗
    # ║ 2. ENGAGEMENT CON ARTISTA                                           ║
    # ╚═════════════════════════════════════════════════════════════════════╝

    async def maybe_visit_artist_profile(
        self,
        page: IRichBrowserSession,
        *,
        artist_uri: str,
    ) -> BehaviorEvent | None:
        if not self._roll(self._persona.traits.behaviors.visit_artist_profile):
            return None
        artist_id = artist_uri.rsplit(":", maxsplit=1)[-1] if ":" in artist_uri else artist_uri
        url = f"https://open.spotify.com/artist/{artist_id}"
        try:
            await page.goto(url, wait_until="domcontentloaded")
        except Exception as exc:
            self._log.warning("nav.failed", target=artist_uri, error=str(exc))
            return self._make_event(BehaviorType.SELECTOR_NOT_FOUND, target_uri=artist_uri)
        await self._await_jitter(1500, 4000)
        self._memory_delta.add_visit_artist(artist_uri)
        return self._make_event(BehaviorType.VISIT_ARTIST_PROFILE, target_uri=artist_uri)

    async def maybe_follow_artist(
        self,
        page: IRichBrowserSession,
    ) -> BehaviorEvent | None:
        if not self._roll(self._persona.traits.behaviors.follow_artist):
            return None
        ok = await self._safe_click(page, _SpotifySelectors.ARTIST_FOLLOW)
        if not ok:
            return self._make_event(BehaviorType.SELECTOR_NOT_FOUND, metadata={"target": "follow"})
        try:
            artist_uri = await page.evaluate(
                "() => document.location.pathname.split('/').filter(Boolean).join(':')",
            )
        except Exception:
            artist_uri = None
        artist_uri_str = str(artist_uri) if artist_uri else None
        if artist_uri_str:
            self._memory_delta.add_follow(f"spotify:artist:{artist_uri_str.split(':')[-1]}")
        return self._make_event(BehaviorType.FOLLOW_ARTIST, target_uri=artist_uri_str)

    async def maybe_view_artist_about(
        self,
        page: IRichBrowserSession,
    ) -> BehaviorEvent | None:
        if not self._roll(self._persona.traits.behaviors.view_artist_about):
            return None
        ok = await self._safe_click(page, _SpotifySelectors.ARTIST_ABOUT)
        if not ok:
            return self._make_event(BehaviorType.SELECTOR_NOT_FOUND, metadata={"target": "about"})
        await self._await_jitter(2000, 5000)
        return self._make_event(BehaviorType.VIEW_ARTIST_ABOUT)

    async def maybe_play_other_song_of_artist(
        self,
        page: IRichBrowserSession,
    ) -> BehaviorEvent | None:
        if not self._roll(self._persona.traits.behaviors.play_other_song_of_artist):
            return None
        # En la pagina del artista la lista de top tracks usa data-testid="track-row-N".
        try:
            count = await page.query_selector_count('[data-testid^="track-row-"]')
        except Exception:
            count = 0
        if count <= 1:
            return self._make_event(
                BehaviorType.SELECTOR_NOT_FOUND,
                metadata={"target": "other_song"},
            )
        idx = self._rng.randint(1, min(count - 1, 9))
        ok = await self._safe_click(page, f'[data-testid="track-row-{idx}"]')
        if not ok:
            return self._make_event(
                BehaviorType.SELECTOR_NOT_FOUND,
                metadata={"target": "other_song_click"},
            )
        await self._await_jitter(800, 2200)
        return self._make_event(BehaviorType.PLAY_OTHER_SONG_OF_ARTIST)

    async def maybe_view_discography(
        self,
        page: IRichBrowserSession,
    ) -> BehaviorEvent | None:
        if not self._roll(self._persona.traits.behaviors.view_discography):
            return None
        ok = await self._safe_click(page, _SpotifySelectors.ARTIST_DISCOGRAPHY)
        if not ok:
            return self._make_event(
                BehaviorType.SELECTOR_NOT_FOUND,
                metadata={"target": "discography"},
            )
        await page.human_scroll(direction="down", pixels=self._rng.randint(400, 1200))
        return self._make_event(BehaviorType.VIEW_DISCOGRAPHY)

    # ╔═════════════════════════════════════════════════════════════════════╗
    # ║ 3. PLAYER MICRO-INTERACCIONES                                       ║
    # ╚═════════════════════════════════════════════════════════════════════╝

    async def maybe_volume_change(
        self,
        page: IRichBrowserSession,
    ) -> BehaviorEvent | None:
        if not self._roll(self._persona.traits.behaviors.volume_change):
            return None
        bbox = await page.get_bounding_box(_SpotifySelectors.VOLUME_BAR)
        if bbox is None:
            return self._make_event(BehaviorType.SELECTOR_NOT_FOUND, metadata={"target": "volume"})
        x, y, width, height = bbox
        # Click aleatorio dentro de la barra: cambia el volumen a esa posicion.
        target_x = int(x + width * self._rng.uniform(0.2, 0.95))
        target_y = int(y + height / 2)
        await page.human_mouse_move(target_x, target_y)
        await page.human_click(_SpotifySelectors.VOLUME_BAR, offset_jitter_px=2)
        return self._make_event(BehaviorType.VOLUME_CHANGE)

    async def maybe_mute_toggle(
        self,
        page: IRichBrowserSession,
    ) -> BehaviorEvent | None:
        if not self._roll(self._persona.traits.behaviors.mute_toggle):
            return None
        ok = await self._safe_click(page, _SpotifySelectors.MUTE_BUTTON)
        if not ok:
            return self._make_event(BehaviorType.SELECTOR_NOT_FOUND, metadata={"target": "mute"})
        return self._make_event(BehaviorType.MUTE_TOGGLE)

    async def maybe_repeat_toggle(
        self,
        page: IRichBrowserSession,
    ) -> BehaviorEvent | None:
        if not self._roll(self._persona.traits.behaviors.repeat_toggle):
            return None
        ok = await self._safe_click(page, _SpotifySelectors.REPEAT)
        if not ok:
            return self._make_event(BehaviorType.SELECTOR_NOT_FOUND, metadata={"target": "repeat"})
        return self._make_event(BehaviorType.REPEAT_TOGGLE)

    async def maybe_shuffle_toggle(
        self,
        page: IRichBrowserSession,
    ) -> BehaviorEvent | None:
        if not self._roll(self._persona.traits.behaviors.shuffle_toggle):
            return None
        ok = await self._safe_click(page, _SpotifySelectors.SHUFFLE)
        if not ok:
            return self._make_event(BehaviorType.SELECTOR_NOT_FOUND, metadata={"target": "shuffle"})
        return self._make_event(BehaviorType.SHUFFLE_TOGGLE)

    async def maybe_pause_resume(
        self,
        page: IRichBrowserSession,
        *,
        pause_seconds_range: tuple[int, int] = (2, 12),
    ) -> BehaviorEvent | None:
        if not self._roll(self._persona.traits.behaviors.pause_resume):
            return None
        ok = await self._safe_click(page, _SpotifySelectors.PLAY_PAUSE)
        if not ok:
            return self._make_event(BehaviorType.SELECTOR_NOT_FOUND, metadata={"target": "pause"})
        pause_s = self._rng.randint(*pause_seconds_range)
        await asyncio.sleep(pause_s)
        await self._safe_click(page, _SpotifySelectors.PLAY_PAUSE)
        return self._make_event(
            BehaviorType.PAUSE_RESUME,
            duration_ms=pause_s * 1000,
        )

    async def maybe_scrub_forward(
        self,
        page: IRichBrowserSession,
    ) -> BehaviorEvent | None:
        if not self._roll(self._persona.traits.behaviors.scrub_forward):
            return None
        bbox = await page.get_bounding_box(_SpotifySelectors.PROGRESS_BAR)
        if bbox is None:
            return self._make_event(BehaviorType.SELECTOR_NOT_FOUND, metadata={"target": "scrub"})
        x, y, width, height = bbox
        # 70%-90% de la cancion (saltar al final, fingerprint de "ya la conoce").
        target_x = int(x + width * self._rng.uniform(0.70, 0.90))
        target_y = int(y + height / 2)
        await page.human_mouse_move(target_x, target_y)
        await page.human_click(_SpotifySelectors.PROGRESS_BAR, offset_jitter_px=2)
        return self._make_event(BehaviorType.SCRUB_FORWARD)

    async def maybe_scrub_backward(
        self,
        page: IRichBrowserSession,
    ) -> BehaviorEvent | None:
        if not self._roll(self._persona.traits.behaviors.scrub_backward):
            return None
        bbox = await page.get_bounding_box(_SpotifySelectors.PROGRESS_BAR)
        if bbox is None:
            return self._make_event(
                BehaviorType.SELECTOR_NOT_FOUND,
                metadata={"target": "scrub_back"},
            )
        x, y, width, height = bbox
        # 5%-30% de la cancion (volver al inicio porque le gusto la parte).
        target_x = int(x + width * self._rng.uniform(0.05, 0.30))
        target_y = int(y + height / 2)
        await page.human_mouse_move(target_x, target_y)
        await page.human_click(_SpotifySelectors.PROGRESS_BAR, offset_jitter_px=2)
        return self._make_event(BehaviorType.SCRUB_BACKWARD)

    async def maybe_toggle_time_remaining(
        self,
        page: IRichBrowserSession,
    ) -> BehaviorEvent | None:
        if not self._roll(self._persona.traits.behaviors.toggle_time_remaining):
            return None
        ok = await self._safe_click(page, _SpotifySelectors.TIME_REMAINING_TOGGLE)
        if not ok:
            return self._make_event(
                BehaviorType.SELECTOR_NOT_FOUND,
                metadata={"target": "time_toggle"},
            )
        return self._make_event(BehaviorType.TOGGLE_TIME_REMAINING)

    async def maybe_open_devices_modal(
        self,
        page: IRichBrowserSession,
    ) -> BehaviorEvent | None:
        if not self._roll(self._persona.traits.behaviors.open_devices_modal):
            return None
        ok = await self._safe_click(page, _SpotifySelectors.DEVICES_BUTTON)
        if not ok:
            return self._make_event(BehaviorType.SELECTOR_NOT_FOUND, metadata={"target": "devices"})
        await self._await_jitter(800, 2200)
        await page.press_key("Escape")
        return self._make_event(BehaviorType.OPEN_DEVICES_MODAL)

    # ╔═════════════════════════════════════════════════════════════════════╗
    # ║ 4. NAVEGACION GLOBAL                                                ║
    # ╚═════════════════════════════════════════════════════════════════════╝

    async def maybe_visit_home(
        self,
        page: IRichBrowserSession,
    ) -> BehaviorEvent | None:
        if not self._roll(self._persona.traits.behaviors.visit_home):
            return None
        try:
            await page.goto(SPOTIFY_HOME, wait_until="domcontentloaded")
        except Exception as exc:
            self._log.warning("nav.home_failed", error=str(exc))
            return self._make_event(BehaviorType.SELECTOR_NOT_FOUND, metadata={"target": "home"})
        await self._await_jitter(1500, 4000)
        await page.human_scroll(direction="down", pixels=self._rng.randint(300, 900))
        return self._make_event(BehaviorType.VISIT_HOME)

    async def maybe_visit_search(
        self,
        page: IRichBrowserSession,
        *,
        query: str | None = None,
    ) -> BehaviorEvent | None:
        if not self._roll(self._persona.traits.behaviors.visit_search):
            return None
        try:
            await page.goto(SPOTIFY_SEARCH, wait_until="domcontentloaded")
        except Exception as exc:
            self._log.warning("nav.search_failed", error=str(exc))
            return self._make_event(BehaviorType.SELECTOR_NOT_FOUND, metadata={"target": "search"})
        if query and await page.is_visible(_SpotifySelectors.SEARCH_INPUT, timeout_ms=2000):
            typing = self._persona.traits.typing
            await page.human_type(
                _SpotifySelectors.SEARCH_INPUT,
                query,
                wpm=typing.avg_wpm,
                wpm_stddev=typing.wpm_stddev,
                typo_probability=typing.typo_probability_per_word,
            )
            self._memory_delta.add_search(query)
            await self._await_jitter(800, 2500)
        return self._make_event(BehaviorType.VISIT_SEARCH, metadata={"query": query or ""})

    async def maybe_visit_library(
        self,
        page: IRichBrowserSession,
    ) -> BehaviorEvent | None:
        if not self._roll(self._persona.traits.behaviors.visit_library):
            return None
        try:
            await page.goto(SPOTIFY_LIBRARY, wait_until="domcontentloaded")
        except Exception as exc:
            self._log.warning("nav.library_failed", error=str(exc))
            return self._make_event(BehaviorType.SELECTOR_NOT_FOUND, metadata={"target": "library"})
        await self._await_jitter(1500, 3500)
        return self._make_event(BehaviorType.VISIT_LIBRARY)

    async def maybe_scroll_sidebar(
        self,
        page: IRichBrowserSession,
    ) -> BehaviorEvent | None:
        if not self._roll(self._persona.traits.behaviors.scroll_sidebar):
            return None
        if not await page.is_visible(_SpotifySelectors.SIDEBAR, timeout_ms=1500):
            return self._make_event(BehaviorType.SELECTOR_NOT_FOUND, metadata={"target": "sidebar"})
        direction = self._rng.choice(["up", "down"])
        await page.human_scroll(
            direction=direction,
            pixels=self._rng.randint(150, 600),
            duration_ms=self._rng.randint(300, 800),
        )
        return self._make_event(BehaviorType.SCROLL_SIDEBAR)

    async def maybe_toggle_view_mode(
        self,
        page: IRichBrowserSession,
    ) -> BehaviorEvent | None:
        if not self._roll(self._persona.traits.behaviors.toggle_view_mode):
            return None
        ok = await self._safe_click(page, _SpotifySelectors.VIEW_MODE_TOGGLE)
        if not ok:
            return self._make_event(
                BehaviorType.SELECTOR_NOT_FOUND,
                metadata={"target": "view_mode"},
            )
        return self._make_event(BehaviorType.TOGGLE_VIEW_MODE)

    async def maybe_open_notifications(
        self,
        page: IRichBrowserSession,
    ) -> BehaviorEvent | None:
        if not self._roll(self._persona.traits.behaviors.open_notifications):
            return None
        ok = await self._safe_click(page, _SpotifySelectors.NOTIFICATIONS)
        if not ok:
            return self._make_event(
                BehaviorType.SELECTOR_NOT_FOUND,
                metadata={"target": "notifications"},
            )
        await self._await_jitter(800, 2200)
        await page.press_key("Escape")
        return self._make_event(BehaviorType.OPEN_NOTIFICATIONS)

    async def maybe_open_settings(
        self,
        page: IRichBrowserSession,
    ) -> BehaviorEvent | None:
        if not self._roll(self._persona.traits.behaviors.open_settings):
            return None
        ok = await self._safe_click(page, _SpotifySelectors.SETTINGS)
        if not ok:
            return self._make_event(
                BehaviorType.SELECTOR_NOT_FOUND,
                metadata={"target": "settings"},
            )
        await self._await_jitter(1000, 2500)
        await page.press_key("Escape")
        return self._make_event(BehaviorType.OPEN_SETTINGS)

    # ╔═════════════════════════════════════════════════════════════════════╗
    # ║ 5. SESION NIVEL (acciones macro)                                    ║
    # ╚═════════════════════════════════════════════════════════════════════╝

    async def maybe_listen_discover_weekly(
        self,
        page: IRichBrowserSession,
    ) -> BehaviorEvent | None:
        if not self._roll(self._persona.traits.behaviors.listen_discover_weekly):
            return None
        if not await page.is_visible(_SpotifySelectors.DISCOVER_WEEKLY_LINK, timeout_ms=2000):
            return self._make_event(
                BehaviorType.SELECTOR_NOT_FOUND,
                metadata={"target": "discover_weekly"},
            )
        await page.human_click(_SpotifySelectors.DISCOVER_WEEKLY_LINK)
        await self._await_jitter(2000, 4000)
        return self._make_event(BehaviorType.LISTEN_DISCOVER_WEEKLY)

    async def maybe_listen_made_for_you(
        self,
        page: IRichBrowserSession,
    ) -> BehaviorEvent | None:
        if not self._roll(self._persona.traits.behaviors.listen_made_for_you):
            return None
        if not await page.is_visible(_SpotifySelectors.MADE_FOR_YOU_LINK, timeout_ms=2000):
            return self._make_event(
                BehaviorType.SELECTOR_NOT_FOUND,
                metadata={"target": "made_for_you"},
            )
        await page.human_click(_SpotifySelectors.MADE_FOR_YOU_LINK)
        await self._await_jitter(2000, 4000)
        return self._make_event(BehaviorType.LISTEN_MADE_FOR_YOU)

    async def maybe_long_pause_distracted(
        self,
        page: IRichBrowserSession,
    ) -> BehaviorEvent | None:
        if not self._roll(self._persona.traits.behaviors.long_pause_distracted):
            return None
        # Pausa larga (3-15 min) emulando que el usuario se levanto.
        seconds = self._rng.randint(180, 900)
        ok = await self._safe_click(page, _SpotifySelectors.PLAY_PAUSE)
        await asyncio.sleep(seconds)
        if ok:
            await self._safe_click(page, _SpotifySelectors.PLAY_PAUSE)
        return self._make_event(
            BehaviorType.LONG_PAUSE_DISTRACTED,
            duration_ms=seconds * 1000,
        )

    async def maybe_tab_blur_event(
        self,
        page: IRichBrowserSession,
    ) -> BehaviorEvent | None:
        if not self._roll(self._persona.traits.behaviors.tab_blur_event):
            return None
        # Cambio a otra pestana (visibilitychange='hidden') por un rato.
        duration_ms = self._rng.randint(3_000, 30_000)
        await page.emulate_tab_blur(duration_ms=duration_ms)
        return self._make_event(BehaviorType.TAB_BLUR_EVENT, duration_ms=duration_ms)

    # ╔═════════════════════════════════════════════════════════════════════╗
    # ║ Aplicacion de delta                                                 ║
    # ╚═════════════════════════════════════════════════════════════════════╝

    def apply_memory_to_persona(self, persona: Persona) -> None:
        """Aplica el delta acumulado en esta sesion sobre `persona.memory`.

        El use case llama a este metodo al final de la sesion antes de
        persistir via `IPersonaRepository.update_memory()`.
        """
        self._memory_delta.apply_to(persona)

    async def commit_memory_async(self, persona: Persona) -> None:
        """Aplica el delta in-memory y, si hay `memory_repo`, persiste eventos.

        Es la version async preferida para sesiones reales. Mantiene
        compatibilidad: si no se inyecto `memory_repo`, se comporta como
        `apply_memory_to_persona` (efecto solo in-memory).
        """
        self.apply_memory_to_persona(persona)
        if self._memory_repo is None:
            return
        events = self._delta_to_events(persona)
        if not events:
            return
        await self._memory_repo.apply_delta(
            persona_id=persona.account_id,
            account_id=persona.account_id,
            events=events,
        )

    def _delta_to_events(self, persona: Persona) -> list[PersonaMemoryEvent]:
        """Convierte el delta acumulado en una lista de `PersonaMemoryEvent`.

        Todos los eventos llevan el mismo `timestamp` (el `_now()` de la
        sesion al commitear) ya que la API in-memory actual no preserva
        timestamp por accion. El log queda bien ordenado por id (ULID) que
        actua como tie-breaker estable.
        """
        ts = self._now()
        persona_id = persona.account_id
        account_id = persona.account_id
        events: list[PersonaMemoryEvent] = []
        delta = self._memory_delta

        for uri in delta.liked_uris:
            events.append(
                PersonaMemoryEvent(
                    persona_id=persona_id,
                    account_id=account_id,
                    event_type=PersonaMemoryEventType.LIKE,
                    timestamp=ts,
                    target_uri=uri,
                )
            )
        for uri in delta.saved_uris:
            events.append(
                PersonaMemoryEvent(
                    persona_id=persona_id,
                    account_id=account_id,
                    event_type=PersonaMemoryEventType.SAVE,
                    timestamp=ts,
                    target_uri=uri,
                )
            )
        for uri in delta.added_to_playlist_uris:
            events.append(
                PersonaMemoryEvent(
                    persona_id=persona_id,
                    account_id=account_id,
                    event_type=PersonaMemoryEventType.ADD_TO_PLAYLIST,
                    timestamp=ts,
                    target_uri=uri,
                )
            )
        for uri in delta.queued_uris:
            events.append(
                PersonaMemoryEvent(
                    persona_id=persona_id,
                    account_id=account_id,
                    event_type=PersonaMemoryEventType.ADD_TO_QUEUE,
                    timestamp=ts,
                    target_uri=uri,
                )
            )
        for uri in delta.followed_artists:
            events.append(
                PersonaMemoryEvent(
                    persona_id=persona_id,
                    account_id=account_id,
                    event_type=PersonaMemoryEventType.FOLLOW_ARTIST,
                    timestamp=ts,
                    target_uri=uri,
                )
            )
        for uri in delta.visited_artists:
            events.append(
                PersonaMemoryEvent(
                    persona_id=persona_id,
                    account_id=account_id,
                    event_type=PersonaMemoryEventType.VISIT_ARTIST,
                    timestamp=ts,
                    target_uri=uri,
                )
            )
        for query in delta.searches:
            events.append(
                PersonaMemoryEvent(
                    persona_id=persona_id,
                    account_id=account_id,
                    event_type=PersonaMemoryEventType.SEARCH,
                    timestamp=ts,
                    target_uri=None,
                    metadata={"query": query},
                )
            )
        if delta.streamed_minutes or delta.streams_counted:
            events.append(
                PersonaMemoryEvent(
                    persona_id=persona_id,
                    account_id=account_id,
                    event_type=PersonaMemoryEventType.STREAM,
                    timestamp=ts,
                    target_uri=None,
                    metadata={
                        "minutes": int(delta.streamed_minutes),
                        "counted": int(delta.streams_counted),
                    },
                )
            )
        return events
