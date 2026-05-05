"""Selectores Amazon Music Web Player (Q1 2026).

Amazon Music delega el login al endpoint estandar `https://www.amazon.com/ap/signin`,
por lo que los selectores de email/password viven en el dominio Amazon principal
y no en el subdominio music. Tras login, redirect a `https://music.amazon.com/`.

Convencion: id/data-id primero, aria-label como fallback. Amazon usa ids
estables (ap_email, ap_password) heredados desde decadas atras.
"""

from __future__ import annotations

# ── URLs ────────────────────────────────────────────────────────────────────
HOME_URL = "https://music.amazon.com/"
SIGN_IN_LINK = '[data-testid="sign-in-link"], a[href*="signin"], a[href*="ap/signin"]'

# ── AP signin (https://www.amazon.com/ap/signin) ────────────────────────────
LOGIN_EMAIL = '[id="ap_email"]'
LOGIN_PASSWORD = '[id="ap_password"]'  # noqa: S105 selector, no secret
LOGIN_CONTINUE = '[id="continue"]'
LOGIN_SUBMIT = '[id="signInSubmit"]'

# ── Estado postlogin ────────────────────────────────────────────────────────
USER_AVATAR = '[data-testid="user-avatar"], [aria-label*="Account"], music-image[id*="user-avatar"]'
LIBRARY_LINK = '[data-testid="library-link"], a[href*="/my/library"]'

# ── Captcha (Amazon classico de imagen + 2FA opcional) ──────────────────────
IMAGE_CAPTCHA = '[id="auth-captcha-image"]'
IMAGE_CAPTCHA_INPUT = '[id="auth-captcha-guess"]'
TWO_FACTOR_OTP = '[id="auth-mfa-otpcode"]'
TWO_FACTOR_SUBMIT = '[id="auth-signin-button"]'

# ── Errores de login ────────────────────────────────────────────────────────
LOGIN_ERROR = '[id="auth-error-message-box"], [class*="a-alert-error"]'

# ── Player principal ────────────────────────────────────────────────────────
PLAY_BUTTON = '[data-id="play-button"], music-button[icon-name="play"]'
PLAY_PAUSE = '[data-id="player-play-button"], [aria-label="Play"], [aria-label="Pause"]'
NEXT_TRACK = '[data-id="player-next-button"], [aria-label="Next"]'
PREVIOUS_TRACK = '[data-id="player-previous-button"], [aria-label="Previous"]'
SHUFFLE = '[data-id="player-shuffle-button"], [aria-label*="Shuffle"]'
REPEAT = '[data-id="player-repeat-button"], [aria-label*="Repeat"]'

# ── Now playing ─────────────────────────────────────────────────────────────
NOW_PLAYING_WIDGET = '[data-id="now-playing"], music-detail-header'
NOW_PLAYING_TITLE = '[data-id="now-playing-title"], [class*="trackTitle"]'
NOW_PLAYING_ARTIST = '[data-id="now-playing-artist"], a[href*="/artists/"]'

# ── Engagement ──────────────────────────────────────────────────────────────
LIKE_BUTTON = '[role="button"][aria-label*="Like"], music-button[icon-name="thumbs-up"]'
ADD_TO_PLAYLIST = '[data-id="add-to-playlist-button"], music-button[icon-name="plus"]'

# ── Artista ─────────────────────────────────────────────────────────────────
ARTIST_FOLLOW = '[data-id="follow-button"], [aria-label*="Follow"]'
