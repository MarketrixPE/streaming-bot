"""Puertos de la capa de aplicacion.

Estos puertos extienden los del dominio cuando un caso de uso necesita
contratos mas ricos (e.g. estrategias de sitio que exponen helpers
adicionales). Mantienen la regla D-SOLID: la aplicacion define lo que
necesita, las capas externas (presentation/infrastructure) implementan.
"""

from streaming_bot.application.ports.metrics import IObservabilityMetrics, NullMetrics
from streaming_bot.application.ports.site_strategy import (
    IRichSiteStrategy,
    ISiteStrategy,
)

__all__ = [
    "IObservabilityMetrics",
    "IRichSiteStrategy",
    "ISiteStrategy",
    "NullMetrics",
]
