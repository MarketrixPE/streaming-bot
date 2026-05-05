"""Sub-paquete dominio Deezer.

Centraliza los value objects que modelan la economia ACPS (Artist-Centric
Payment System) que Deezer adopto en 2024:

- `SuperFanProfile`: define los thresholds que convierten a una cuenta en
  "super-fan" segun la heuristica documentada por Deezer/Universal/Believe.
- `DeezerListenerHistory`: snapshot del comportamiento agregado de la cuenta
  durante los ultimos 30 dias.
- `AcpsScore`: probabilidad de que un stream concreto reciba el boost x2
  ACPS, calculada a partir de cuatro factores.

El dominio no conoce httpx ni Patchright. Toda la I/O vive en
`infrastructure/deezer/` y la orquestacion en `application/deezer/`.
"""

from streaming_bot.domain.deezer.acps_score import AcpsScore, AcpsScoreFactors
from streaming_bot.domain.deezer.listener_history import DeezerListenerHistory, ProfileGap
from streaming_bot.domain.deezer.super_fan_profile import SuperFanProfile

__all__ = [
    "AcpsScore",
    "AcpsScoreFactors",
    "DeezerListenerHistory",
    "ProfileGap",
    "SuperFanProfile",
]
