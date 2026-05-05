"""Dominio Meta (Instagram).

Modela las entidades del "vehiculo de spillover organico":
- ``InstagramAccount``: cuenta IG mapeada 1:1 a un artista del catalogo.
- ``Reel``: video corto vertical con audio del catalogo + caption + hashtags.
- ``SmartLink``: link unico con geo-routing a DSPs (Spotify, Apple, etc).

Reglas:
- Sin dependencias de Flutter/UI ni de infraestructura.
- Las entidades viven aqui aisladas para no contaminar el dominio existente
  (Spotify-first); otros adapters de meta (instagrapi, ffmpeg, smart link)
  dependen de estos protocols/value objects.
"""

from streaming_bot.domain.meta.instagram_account import (
    InstagramAccount,
    InstagramAccountStatus,
)
from streaming_bot.domain.meta.reel import Reel, ReelMetrics
from streaming_bot.domain.meta.smart_link import DSP, SmartLink

__all__ = [
    "DSP",
    "InstagramAccount",
    "InstagramAccountStatus",
    "Reel",
    "ReelMetrics",
    "SmartLink",
]
