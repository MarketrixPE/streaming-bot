"""Selectores JioSaavn (India) para login + player web Q1 2026.

JioSaavn es el DSP dominante en India: antifraude bajo, payout muy bajo
(~$0.0005/stream) pero VOLUMEN industrial. Mobile-first PWA: el viewport
responsive obliga a usar selectores que existan tanto en layout movil
como en desktop, por eso priorizamos atributos `data-action` y
`data-testid` en lugar de classes CSS minificadas.

Convencion: `data-testid` o `data-action` first, aria/role como fallback,
NUNCA classes CSS minificadas (cambian en cada release de la app).
"""

from __future__ import annotations

# ── URLs canonicas ──────────────────────────────────────────────────────────
LOGIN_URL = "https://www.jiosaavn.com/login"
HOME_URL = "https://www.jiosaavn.com/"

# ── Login form ──────────────────────────────────────────────────────────────
LOGIN_EMAIL = 'input[name="email"]'
LOGIN_PASSWORD = 'input[name="password"]'  # noqa: S105 selector, no secret
LOGIN_SUBMIT = 'button[type="submit"]'

# ── Estado postlogin ────────────────────────────────────────────────────────
USER_AVATAR = '[data-testid="user-avatar"], [aria-label*="account"]'

# ── Errores de login ────────────────────────────────────────────────────────
LOGIN_ERROR = '[role="alert"], [data-testid="login-error"]'
CAPTCHA_HINT = 'iframe[src*="captcha"], [data-testid="captcha"]'

# ── Player principal ────────────────────────────────────────────────────────
# JioSaavn usa la clase semantica `.play-icon` historicamente estable; aun
# asi aceptamos un fallback aria por si la clase rota en algun deploy.
PLAY_ICON = '.play-icon, [aria-label="Play"]'
PLAY_PAUSE = '.play-icon, [aria-label="Play"], [aria-label="Pause"]'
NEXT_TRACK = '[aria-label="Next"], .next-icon'
PREVIOUS_TRACK = '[aria-label="Previous"], .prev-icon'

# ── Now playing widget ──────────────────────────────────────────────────────
NOW_PLAYING_WIDGET = ".player-controls, [data-testid='player-bar']"
NOW_PLAYING_TITLE = ".song-name, [data-testid='player-track-title']"
NOW_PLAYING_ARTIST = ".artist-name, [data-testid='player-track-artist']"
NOW_PLAYING_ARTIST_LINK = ".artist-name a, [data-testid='player-track-artist'] a"

# ── Engagement ──────────────────────────────────────────────────────────────
LIKE_BUTTON = ".song-action--like, [aria-label*='Favourite']"
ADD_TO_PLAYLIST = ".song-action--add, [aria-label*='Add to playlist']"
FOLLOW_ARTIST = '[data-action="follow"], [aria-label*="Follow"]'
