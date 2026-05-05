"""Selectores KKBox (Taiwan + Hong Kong + Sudeste Asiatico) Q1 2026.

KKBox es un DSP regional asiatico (sede en Taiwan, presencia fuerte en
HK/JP/SG/MY/TH). Antifraude moderado, payout ~$0.002/stream. Web player
basado en React: usa `data-testid` ampliamente, lo que nos da
selectores estables. Captcha solo aparece en signup (hCaptcha).

Convencion: `data-testid` first, aria como fallback. Nunca classes
hashed (cambian en cada build).
"""

from __future__ import annotations

# ── URLs canonicas ──────────────────────────────────────────────────────────
LOGIN_URL = "https://accounts.kkbox.com/login"
HOME_URL = "https://www.kkbox.com/"

# ── Login form ──────────────────────────────────────────────────────────────
LOGIN_EMAIL = 'input[name="email"]'
LOGIN_PASSWORD = 'input[name="password"]'  # noqa: S105 selector, no secret
LOGIN_SUBMIT = 'button[type="submit"]'

# ── Estado postlogin ────────────────────────────────────────────────────────
USER_AVATAR = '[data-testid="user-avatar"], [aria-label*="account"]'

# ── Captcha (solo signup, defensivo en login) ──────────────────────────────
HCAPTCHA_FRAME = 'iframe[src*="hcaptcha.com"]'
HCAPTCHA_SITE_KEY_NODE = "[data-sitekey]"

# ── Errores de login ────────────────────────────────────────────────────────
LOGIN_ERROR = '[data-testid="login-error"], [role="alert"]'

# ── Player principal ────────────────────────────────────────────────────────
PLAY_PAUSE = '[data-testid="play-pause-button"]'
NEXT_TRACK = '[data-testid="next-button"]'
PREVIOUS_TRACK = '[data-testid="previous-button"]'
SHUFFLE = '[data-testid="shuffle-button"]'
REPEAT = '[data-testid="repeat-button"]'

# ── Now playing widget ──────────────────────────────────────────────────────
NOW_PLAYING_WIDGET = '[data-testid="player-bar"], [data-testid="now-playing"]'
NOW_PLAYING_TITLE = '[data-testid="now-playing-title"]'
NOW_PLAYING_ARTIST = '[data-testid="now-playing-artist"]'
NOW_PLAYING_ARTIST_LINK = '[data-testid="now-playing-artist"] a'

# ── Engagement ──────────────────────────────────────────────────────────────
LIKE_BUTTON = '[data-testid="like-button"]'
ADD_TO_PLAYLIST = '[data-testid="add-to-playlist-button"]'
FOLLOW_ARTIST = '[data-testid="follow-artist"]'
