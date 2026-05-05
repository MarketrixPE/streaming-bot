"""Selectores Spotify Web Player Q1 2026 con fallbacks por estabilidad.

Spotify rota classes hashed cada release menor. La unica capa estable es
`data-testid` (ingenieria interna las usa para QA), seguida de `aria-label`
(accesibilidad, contractualmente estable porque rompe lectores de pantalla
si cambia). Nunca confiamos en classes con prefijos hash.

Cada campo del `SpotifySelectors` es una `tuple[str, ...]`: el primer
selector es el preferido (data-testid Q1 2026); el resto son fallbacks
ordenados por probabilidad de estabilidad. La helper `pick_visible_async`
recorre la tupla y devuelve el primero presente en el DOM.

Diseno frozen+slots para que las constantes sean inmutables y la huella
de memoria sea minima en tests (cientos de instancias creadas en paralelo).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from streaming_bot.domain.ports.browser_rich import IRichBrowserSession


# URLs publicas estables (no cambian entre releases).
LOGIN_URL = "https://accounts.spotify.com/login"
HOME_URL = "https://open.spotify.com/"
SEARCH_URL = "https://open.spotify.com/search"
LIBRARY_URL = "https://open.spotify.com/collection/playlists"


@dataclass(frozen=True, slots=True)
class SpotifySelectors:
    """Catalogo de selectores Q1 2026 con fallbacks por estabilidad.

    El metodo `default()` instancia con los selectores preferidos a fecha
    Q1 2026; tests de regresion pueden inyectar instancias custom para
    simular layouts viejos o mocks especificos.
    """

    # ── Auth (accounts.spotify.com/login) ────────────────────────────────
    login_username: tuple[str, ...]
    login_password: tuple[str, ...]
    login_button: tuple[str, ...]
    login_error_hint: tuple[str, ...]

    # ── Auth gate (open.spotify.com tras login) ──────────────────────────
    user_widget: tuple[str, ...]

    # ── Captcha (variantes detectables) ──────────────────────────────────
    captcha_container: tuple[str, ...]
    recaptcha_iframe: tuple[str, ...]
    hcaptcha_iframe: tuple[str, ...]
    turnstile_iframe: tuple[str, ...]

    # ── Player principal ─────────────────────────────────────────────────
    play_button: tuple[str, ...]
    play_pause: tuple[str, ...]
    skip_forward: tuple[str, ...]
    skip_back: tuple[str, ...]
    add_to_queue: tuple[str, ...]
    save_button: tuple[str, ...]
    like_button: tuple[str, ...]
    now_playing_widget: tuple[str, ...]
    track_title: tuple[str, ...]
    track_artist: tuple[str, ...]

    @classmethod
    def default(cls) -> SpotifySelectors:
        """Instancia con selectores preferidos Q1 2026 + fallbacks."""
        return cls(
            login_username=(
                '[data-testid="login-username"]',
                'input[name="username"]',
                'input[autocomplete="username"]',
            ),
            login_password=(
                '[data-testid="login-password"]',
                'input[name="password"]',
                'input[autocomplete="current-password"]',
            ),
            login_button=(
                '[data-testid="login-button"]',
                'button[type="submit"]',
            ),
            login_error_hint=(
                '[data-testid="login-error"]',
                '[role="alert"]',
            ),
            user_widget=(
                '[data-testid="user-widget-name"]',
                '[data-testid="user-widget-link"]',
                'button[aria-label*="Account" i]',
            ),
            captcha_container=(
                '[data-testid="captcha"]',
                '#challenge-container',
                '[id^="captcha"]',
            ),
            recaptcha_iframe=(
                'iframe[src*="recaptcha"]',
                'iframe[title*="reCAPTCHA"]',
            ),
            hcaptcha_iframe=(
                'iframe[src*="hcaptcha"]',
                'iframe[title*="hCaptcha"]',
            ),
            turnstile_iframe=(
                'iframe[src*="challenges.cloudflare.com"]',
                'iframe[title*="Cloudflare"]',
            ),
            play_button=(
                '[data-testid="play-button"]',
                'button[aria-label*="Play" i]',
            ),
            play_pause=(
                '[data-testid="control-button-playpause"]',
                'button[aria-label*="Pause" i]',
                'button[aria-label*="Play" i]',
            ),
            skip_forward=(
                '[data-testid="control-button-skip-forward"]',
                'button[aria-label*="Next" i]',
            ),
            skip_back=(
                '[data-testid="control-button-skip-back"]',
                'button[aria-label*="Previous" i]',
            ),
            add_to_queue=(
                '[data-testid="control-button-add-to-queue"]',
                '[data-testid="add-to-queue-button"]',
                'button[aria-label*="Add to queue" i]',
            ),
            save_button=(
                '[data-testid="control-button-save"]',
                '[data-testid="add-button"]',
                'button[aria-label*="Save to Your Library" i]',
            ),
            like_button=(
                '[data-testid="control-button-like"]',
                '[data-testid="add-button"]',
                'button[aria-label*="Save" i]',
            ),
            now_playing_widget=(
                '[data-testid="now-playing-widget"]',
                'aside[aria-label*="Now playing" i]',
            ),
            track_title=(
                '[data-testid="context-item-info-title"]',
                '[data-testid="track-title"]',
            ),
            track_artist=(
                '[data-testid="context-item-info-artist"]',
                'a[href^="/artist/"]',
            ),
        )


async def pick_visible_async(
    page: IRichBrowserSession,
    candidates: tuple[str, ...],
    *,
    timeout_ms: int = 1500,
) -> str | None:
    """Devuelve el primer selector de la tupla que sea visible en el DOM.

    Usa `is_visible` (no lanza) para tolerar layouts en transicion. Si
    ninguno aparece dentro del timeout total (sumando intentos), retorna
    None. El caller decide si esto es un fallo o solo `selector_not_found`.
    """
    if not candidates:
        return None
    # Repartimos el timeout entre todos los candidates de forma equitativa.
    per_attempt = max(1, timeout_ms // len(candidates))
    for selector in candidates:
        if await page.is_visible(selector, timeout_ms=per_attempt):
            return selector
    return None
