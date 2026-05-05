"""Selectores SoundCloud (Q1 2026).

Estrategia: `data-testid` first, `aria-label` como fallback. Nunca clases
CSS de SoundCloud (cambian semanalmente). Si SoundCloud rota un selector
hay que actualizar UN unico modulo (este).

Tambien declara los hints de DataDome: el WAF de SoundCloud inyecta un
iframe `data-dome` o un atributo en `<html>` cuando bloquea al usuario.
La strategy busca esos hints y delega la resolucion a `ICaptchaSolver`.
"""

from __future__ import annotations

# ── URLs ──────────────────────────────────────────────────────────────────
SIGNIN_URL = "https://soundcloud.com/signin"
HOMEPAGE_URL = "https://soundcloud.com/"

# ── Login form ────────────────────────────────────────────────────────────
SIGNIN_FORM = '[data-testid="signin-form"]'
EMAIL_INPUT = '[data-testid="email-input"]'
PASSWORD_INPUT = '[data-testid="password-input"]'  # noqa: S105  selector, no secret
SIGNIN_BUTTON = '[data-testid="signin-button"]'

# ── Sesion / header ───────────────────────────────────────────────────────
HEADER_USER_NAV = '[data-testid="header-user-nav"]'
HEADER_AVATAR = '[aria-label="User menu"]'

# ── Player / acciones del track ───────────────────────────────────────────
PLAY_BUTTON = ".playButton"
LIKE_BUTTON = ".sc-button-like"
REPOST_BUTTON = ".sc-button-repost"
FOLLOW_BUTTON = ".sc-button-follow"
COMMENT_INPUT = ".commentForm__input"
COMMENT_SUBMIT = ".commentForm__submit"

# ── Fallbacks aria-label ──────────────────────────────────────────────────
PLAY_FALLBACK = '[aria-label="Play"]'
LIKE_FALLBACK = '[aria-label*="Like"]'
REPOST_FALLBACK = '[aria-label*="Repost"]'
FOLLOW_FALLBACK = '[aria-label="Follow"]'

# ── DataDome challenge hints ──────────────────────────────────────────────
DATADOME_IFRAME = 'iframe[src*="datadome"]'
DATADOME_ATTRIBUTE = "[data-cf-data-dome]"
DATADOME_GLOBAL_SELECTOR = "#datadome-captcha"
