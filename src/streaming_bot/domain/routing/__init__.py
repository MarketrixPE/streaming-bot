"""Dominio del Multi-Tier Geo Router.

Expone los value objects y enum necesarios para clasificar un track
en el tier de payout/volumen mas adecuado segun su salud actual.

Reglas y politicas viven en ``application/routing``; aqui solo el
modelo inmutable que pueden consumir todas las capas (incluida ML/
catalog pipeline) sin ciclos.
"""

from streaming_bot.domain.routing.tier import TIER_TO_COUNTRIES, Tier
from streaming_bot.domain.routing.track_health import TrackHealthScore

__all__ = [
    "TIER_TO_COUNTRIES",
    "Tier",
    "TrackHealthScore",
]
