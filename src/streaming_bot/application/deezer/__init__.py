"""Sub-paquete application Deezer.

Compone los value objects de `domain/deezer/` con servicios orquestadores:

- `SuperFanEligibilityService`: dado un account_id consulta `IDeezerClient`,
  evalua el historial frente a `SuperFanProfile` y emite un `EligibilityAssessment`.
- `SuperFanEmulationEngine`: planifica una sesion super-fan (>= 45min) que
  intercala el track objetivo con relleno de otros artistas seguidos.
- `DeezerRoutingPolicy`: decide a que cuentas enrutar un track objetivo,
  rechazando spread plano y aceptando solo super-fans o cuentas en pipeline.
"""

from streaming_bot.application.deezer.routing_policy import (
    DeezerRoutingPolicy,
    RoutingDecision,
    RoutingReason,
)
from streaming_bot.application.deezer.super_fan_eligibility import (
    EligibilityAssessment,
    SuperFanEligibilityService,
)
from streaming_bot.application.deezer.super_fan_emulation_engine import (
    PlannedSession,
    PlannedTrackPlay,
    SuperFanEmulationEngine,
    TrackCandidate,
)

__all__ = [
    "DeezerRoutingPolicy",
    "EligibilityAssessment",
    "PlannedSession",
    "PlannedTrackPlay",
    "RoutingDecision",
    "RoutingReason",
    "SuperFanEligibilityService",
    "SuperFanEmulationEngine",
    "TrackCandidate",
]
