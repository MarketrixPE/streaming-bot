"""Estrategias de la capa de aplicacion (sin acoplamiento al sitio).

Estos componentes implementan politicas que las strategies de presentation
pueden consumir para fabricar comportamientos consistentes y dificiles de
detectar (ej. el `RatioController` central de save/skip/queue/like).
"""

from streaming_bot.application.strategies.ratio_controller import (
    BehaviorIntent,
    RatioController,
    RatioControllerConfig,
)
from streaming_bot.application.strategies.ratio_targets import RatioTargets

__all__ = [
    "BehaviorIntent",
    "RatioController",
    "RatioControllerConfig",
    "RatioTargets",
]
