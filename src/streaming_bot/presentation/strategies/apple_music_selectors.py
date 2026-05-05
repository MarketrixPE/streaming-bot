"""Selectores Apple Music Web Player (Q1 2026).

Apple Music es el DSP mas duro del trio: anti-bot agresivo, requiere
AppleID con metodo de pago verificado y device-binding 2FA. Mantenemos
estos selectores aislados del codigo de la estrategia para que un cambio
en el DOM solo toque un archivo.

Convencion: data-testid primero, aria-label como fallback. Nunca classes
CSS minificadas (cambian en cada deploy).
"""

from __future__ import annotations

# ── URLs canonicas ──────────────────────────────────────────────────────────
LOGIN_URL = "https://music.apple.com/login"
HOME_URL = "https://music.apple.com/"

# ── AppleID iframe (login) ──────────────────────────────────────────────────
LOGIN_IFRAME_NAME = "aid-auth-widget-iFrame"
LOGIN_USERNAME = '[name="account_name_text_field"]'
LOGIN_USERNAME_SUBMIT = '[id="sign-in"]'
LOGIN_PASSWORD = '[name="password_text_field"]'  # noqa: S105 selector, no secret
LOGIN_PASSWORD_SUBMIT = '[id="sign-in"]'  # noqa: S105 selector, no secret

# ── Estado postlogin ────────────────────────────────────────────────────────
USER_AVATAR = '[data-testid="account-button"], [aria-label*="Account"]'
TWO_FACTOR_HINT = '[id*="trust-browser"], [data-testid="two-factor"]'

# ── Captcha ─────────────────────────────────────────────────────────────────
HCAPTCHA_FRAME = 'iframe[src*="hcaptcha.com"]'
HCAPTCHA_SITE_KEY_NODE = "[data-sitekey]"

# ── Errores de login ────────────────────────────────────────────────────────
LOGIN_ERROR = '[id="errMsg"], [role="alert"]'

# ── Player principal ────────────────────────────────────────────────────────
PLAY_BUTTON = '[data-testid="play-button"]'
PLAY_PAUSE = '[data-testid="play-pause-button"], [aria-label="Play"], [aria-label="Pause"]'
NEXT_TRACK = '[data-testid="next-button"], [aria-label="Next"]'
PREVIOUS_TRACK = '[data-testid="previous-button"], [aria-label="Previous"]'
SHUFFLE = '[data-testid="shuffle-button"]'
REPEAT = '[data-testid="repeat-button"]'

# ── Now playing widget ──────────────────────────────────────────────────────
NOW_PLAYING_WIDGET = '[data-testid="chrome-player"]'
NOW_PLAYING_TITLE = '[data-testid="now-playing-title"]'
NOW_PLAYING_ARTIST = '[data-testid="now-playing-artist"]'
NOW_PLAYING_ALBUM_LINK = '[data-testid="now-playing-album-link"]'

# ── Engagement ──────────────────────────────────────────────────────────────
LIKE_BUTTON = '[data-testid="love-button"], [aria-label*="Love"]'
DISLIKE_BUTTON = '[data-testid="dislike-button"], [aria-label*="Dislike"]'
ADD_TO_LIBRARY = '[data-testid="add-to-library-button"], [aria-label*="Add to Library"]'
ADD_TO_PLAYLIST = '[data-testid="add-to-playlist-button"], [aria-label*="Add to Playlist"]'

# ── Artista ─────────────────────────────────────────────────────────────────
ARTIST_FOLLOW = '[data-testid="follow-button"], [aria-label*="Follow"]'

# ── Volumen ─────────────────────────────────────────────────────────────────
VOLUME_BAR = '[data-testid="volume-slider"]'
MUTE_BUTTON = '[data-testid="mute-button"]'
