"""Casos de uso del Multi-Tier Geo Router.

Concentra la logica que decide a que tier enrutar cada track segun la
salud del propio track. Las dependencias del dominio
(``Tier``, ``TrackHealthScore``) se reusan; aqui solo viven politicas
y orquestacion sin I/O.
"""

from streaming_bot.application.routing.policy import RoutingPolicy
from streaming_bot.application.routing.tier_router import MultiTierGeoRouter
from streaming_bot.application.routing.track_health_scorer import TrackHealthScorer

__all__ = [
    "MultiTierGeoRouter",
    "RoutingPolicy",
    "TrackHealthScorer",
]
