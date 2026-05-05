"""Selectores estables del Deezer Web Player (Q2 2026).

Convencion: `data-testid` primero (mas estable), `aria-label` como fallback,
nunca CSS classes (Deezer las cambia con cada deploy).

Si Deezer cambia el layout, este es el unico archivo que debe tocar la
estrategia. La engine y el caso de uso permanecen intactos.
"""

from __future__ import annotations

# ── Login ─────────────────────────────────────────────────────────────────
LOGIN_URL = "https://www.deezer.com/login"

LOGIN_EMAIL = '[data-testid="form-email"]'
LOGIN_PASSWORD = '[data-testid="form-password"]'  # noqa: S105  selector, no secret
LOGIN_SUBMIT = '[data-testid="form-submit"]'

# Indicador de sesion activa (avatar/menu del usuario tras login).
USER_MENU = '[data-testid="user-menu"]'

# Hints de error post-login.
LOGIN_ERROR = '[data-testid="form-error"]'
HCAPTCHA_FRAME = 'iframe[src*="hcaptcha.com"]'
HCAPTCHA_CONTAINER = '[data-testid="hcaptcha"]'

# Site key de hCaptcha (estable; lo tomamos del DOM con `data-sitekey`).
HCAPTCHA_SITEKEY_ATTR = "data-sitekey"
HCAPTCHA_RESPONSE_TEXTAREA = 'textarea[name="h-captcha-response"]'

# ── Player ────────────────────────────────────────────────────────────────
PLAY_PAUSE = ".player-controls__play-pause"
PLAYER_NEXT = '[data-testid="player-next"]'
PLAYER_PREV = '[data-testid="player-prev"]'
PROGRESS_BAR = '[data-testid="progress-bar"]'
NOW_PLAYING_TITLE = '[data-testid="player-track-title"]'
NOW_PLAYING_ARTIST = '[data-testid="player-track-artist"]'
NOW_PLAYING_WIDGET = '[data-testid="now-playing"]'
