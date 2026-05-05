"""Selectores NetEase Cloud Music (China) Q1 2026.

NetEase es el DSP mas dificil del trio asiatico:
- Antifraude agresivo China-specific (heuristicas de IP, firmas de
  Beijing/Shanghai backbones, fechas/horas locales).
- Solo accesible desde IPs dentro de China (proxy CN obligatorio).
- Login restringido a numero +86 con SMS verification (sin fallback
  email/password). Las cuentas farm requieren SIM CN reales o numbers
  CN comprados via 5SIM/HKVPN.
- Player y la mayoria de la UI viven dentro de un iframe principal
  (legacy, hash-bang routing `#/`).

Selectores: classes semanticas legacy (`.ply`, `.icn-add`, `.icn-attent`)
historicamente estables en el host viejo. Si NetEase migra a una nueva
SPA en 2026 estos selectores deberan ser revisitados.
"""

from __future__ import annotations

# ── URLs canonicas ──────────────────────────────────────────────────────────
LOGIN_URL = "https://music.163.com/#/login"
HOME_URL = "https://music.163.com/"

# ── Login form (telefono +86 + SMS) ────────────────────────────────────────
PHONE_INPUT = 'input[name="phone"]'
SMS_CODE_INPUT = 'input[name="captcha"]'
LOGIN_SUBMIT = "button.j-primary"

# ── Estado postlogin ────────────────────────────────────────────────────────
USER_AVATAR = ".m-avatar, [data-testid='user-avatar']"
LOGIN_ERROR = ".j-flag, [role='alert']"

# ── Player y engagement (viven dentro del iframe principal) ────────────────
# El iframe principal historicamente tiene `name="contentFrame"`. Los
# selectores deben aplicarse al frame, no al main document.
MAIN_FRAME_NAME = "contentFrame"

PLAY_BUTTON = ".ply"
PLAY_PAUSE = ".ply"
NEXT_TRACK = ".nxt"
PREVIOUS_TRACK = ".prv"

# Now playing widget (footer player en el frame principal)
NOW_PLAYING_WIDGET = ".m-playbar, .player"
NOW_PLAYING_TITLE = ".words .name, .play-title"
NOW_PLAYING_ARTIST = ".words .by, .play-by"
NOW_PLAYING_ARTIST_LINK = ".words .by a, .play-by a"

# Engagement
LIKE_BUTTON = ".icn-add"
FOLLOW_ARTIST = ".icn-attent"
ADD_TO_PLAYLIST = ".icn-list"
