"""Politica de routing Deezer ACPS-aware.

Regla central: NO hacer brute-force en Deezer. El sistema solo enruta el
track objetivo a:

1. Cuentas que ya cumplen `SuperFanProfile` (super-fans plenos).
2. Cuentas en pipeline de "construccion super-fan": casi cumplen (gap
   tolerable) y siguen el camino correcto (replay_rate y catalogo no nulos).

Las cuentas con spread plano (muchas cuentas con pocos plays cada una) son
RECHAZADAS. Esa es la unica forma de no quemar la economia ACPS x2.

`DeezerRoutingPolicy` es un servicio de aplicacion: orquesta el
`SuperFanEligibilityService` y devuelve un veredicto por cuenta + un
ordenamiento que prioriza super-fans sobre pipeline.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from streaming_bot.application.deezer.super_fan_eligibility import (
    EligibilityAssessment,
    SuperFanEligibilityService,
)


class RoutingReason(str, Enum):
    """Por que se acepta o rechaza una cuenta."""

    SUPER_FAN = "super_fan"
    PIPELINE = "pipeline"
    REJECTED_FLAT_SPREAD = "rejected_flat_spread"
    NO_HISTORY = "no_history"


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """Decision para una cuenta concreta dentro del proceso de routing."""

    account_id: str
    accepted: bool
    reason: RoutingReason
    acps_score: float


class DeezerRoutingPolicy:
    """Filtra cuentas candidatas para enrutarles un track objetivo.

    `select_accounts_for_track` evalua cada cuenta en paralelo (asyncio.gather)
    y devuelve solo las aceptadas, ordenadas por score ACPS descendente.
    Limita el resultado a `max_routes` para no sobre-cargar pocas cuentas.
    """

    def __init__(
        self,
        *,
        eligibility: SuperFanEligibilityService,
        max_routes: int = 5,
        accept_pipeline: bool = True,
    ) -> None:
        if max_routes <= 0:
            raise ValueError(f"max_routes debe ser > 0: {max_routes}")
        self._eligibility = eligibility
        self._max_routes = max_routes
        self._accept_pipeline = accept_pipeline

    async def select_accounts_for_track(
        self,
        candidate_account_ids: Sequence[str],
        *,
        max_routes: int | None = None,
    ) -> list[RoutingDecision]:
        """Evalua candidatas y devuelve solo las que pueden recibir el track.

        Args:
            candidate_account_ids: pool inicial de cuentas a evaluar.
            max_routes: limite override del default del constructor.

        Returns:
            Lista (puede estar vacia) ordenada por score ACPS descendente.
            Solo incluye cuentas con `accepted=True`.
        """
        if not candidate_account_ids:
            return []
        cap = max_routes if max_routes is not None else self._max_routes
        if cap <= 0:
            raise ValueError(f"max_routes debe ser > 0: {cap}")

        # Evaluacion en paralelo: cada cuenta es independiente.
        assessments = await asyncio.gather(
            *(self._eligibility.assess(account_id) for account_id in candidate_account_ids),
        )
        decisions = [self._to_decision(a) for a in assessments]
        accepted = [d for d in decisions if d.accepted]
        accepted.sort(key=lambda d: (d.reason != RoutingReason.SUPER_FAN, -d.acps_score))
        return accepted[:cap]

    async def evaluate_all(
        self,
        candidate_account_ids: Sequence[str],
    ) -> list[RoutingDecision]:
        """Devuelve TODAS las decisiones (aceptadas y rechazadas).

        Util para auditoria/dashboards: permite ver cuantas cuentas estan
        en spread plano vs en pipeline vs ya super-fans.
        """
        if not candidate_account_ids:
            return []
        assessments = await asyncio.gather(
            *(self._eligibility.assess(account_id) for account_id in candidate_account_ids),
        )
        return [self._to_decision(a) for a in assessments]

    def _to_decision(self, assessment: EligibilityAssessment) -> RoutingDecision:
        """Mapea un `EligibilityAssessment` a `RoutingDecision`."""
        score = assessment.score.value if assessment.score is not None else 0.0
        if assessment.history is None:
            return RoutingDecision(
                account_id=assessment.account_id,
                accepted=False,
                reason=RoutingReason.NO_HISTORY,
                acps_score=score,
            )
        if assessment.is_eligible:
            return RoutingDecision(
                account_id=assessment.account_id,
                accepted=True,
                reason=RoutingReason.SUPER_FAN,
                acps_score=score,
            )
        if assessment.is_in_pipeline and self._accept_pipeline:
            return RoutingDecision(
                account_id=assessment.account_id,
                accepted=True,
                reason=RoutingReason.PIPELINE,
                acps_score=score,
            )
        return RoutingDecision(
            account_id=assessment.account_id,
            accepted=False,
            reason=RoutingReason.REJECTED_FLAT_SPREAD,
            acps_score=score,
        )
