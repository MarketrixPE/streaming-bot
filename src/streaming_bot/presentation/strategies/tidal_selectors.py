"""Selectores Tidal Web Player (Q1 2026).

Tidal expone selectores `data-test=*` muy estables en su SPA basada en React.
Es el DSP del trio con menor presion antifraud, pero conviene seguir igual
la convencion: data-test primero, aria-label como fallback.

El tier HiFi/HiFi Plus paga mas por stream que el tier Premium normal, asi
que el adapter incluye un selector para detectar el badge de tier desde la
seccion de cuenta.
"""

from __future__ import annotations

# ── URLs ────────────────────────────────────────────────────────────────────
LOGIN_URL = "https://listen.tidal.com/login"
HOME_URL = "https://listen.tidal.com/"
ACCOUNT_URL = "https://listen.tidal.com/my-collection"
SUBSCRIPTION_URL = "https://listen.tidal.com/account/subscription"

# ── Login ───────────────────────────────────────────────────────────────────
LOGIN_EMAIL = '[data-test="email-field"], [name="email"]'
LOGIN_PASSWORD = '[data-test="password-field"], [name="password"]'  # noqa: S105 selector
LOGIN_BUTTON = '[data-test="login-button"], [type="submit"]'

# ── Estado postlogin ────────────────────────────────────────────────────────
USER_AVATAR = '[data-test="user-avatar"], [data-test="profile-link"]'
SIDEBAR_HOME = '[data-test="sidebar-home"]'

# ── Tier (HiFi vs Premium) ──────────────────────────────────────────────────
SUBSCRIPTION_BADGE = '[data-test="subscription-tier"], [class*="subscriptionTier"]'

# ── Errores de login ────────────────────────────────────────────────────────
LOGIN_ERROR = '[data-test="error-message"], [role="alert"]'

# ── Player principal ────────────────────────────────────────────────────────
PLAY_CONTROLS = '[data-test="play-controls"]'
PLAY_BUTTON = '[data-test="play-button"]'
PLAY_PAUSE = '[data-test="play"], [data-test="pause"]'
NEXT_TRACK = '[data-test="next"]'
PREVIOUS_TRACK = '[data-test="previous"]'
SHUFFLE = '[data-test="shuffle"]'
REPEAT = '[data-test="repeat"]'

# ── Now playing ─────────────────────────────────────────────────────────────
NOW_PLAYING_WIDGET = '[data-test="footer-player"]'
NOW_PLAYING_TITLE = '[data-test="footer-track-title"]'
NOW_PLAYING_ARTIST = '[data-test="grid-item-detail-text-title-artist"], a[href*="/artist/"]'

# ── Engagement ──────────────────────────────────────────────────────────────
LIKE_BUTTON = '[data-test="footer-favorite-button"], [aria-label*="Add to Favorites"]'
ADD_TO_PLAYLIST = '[data-test="add-to-playlist"]'
ADD_TO_QUEUE = '[data-test="add-to-queue"]'

# ── Artista ─────────────────────────────────────────────────────────────────
ARTIST_FOLLOW = '[data-test="follow-button"]'
