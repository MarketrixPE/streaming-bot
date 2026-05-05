"""Servicio que evalua si una cuenta cumple `SuperFanProfile`.

El servicio es un orquestador delgado:
1. Pide el historial 30d a `IDeezerClient`.
2. Compara con `SuperFanProfile` via `DeezerListenerHistory.gap_against`.
3. Devuelve `EligibilityAssessment` con la decision + diagnostico.

`EligibilityAssessment` es lo que `DeezerRoutingPolicy` consume para decidir
si enrutar un track a la cuenta.
"""

from __future__ import annotations

from dataclasses import dataclass

from streaming_bot.domain.deezer.acps_score import AcpsScore
from streaming_bot.domain.deezer.listener_history import (
    DeezerListenerHistory,
    ProfileGap,
)
from streaming_bot.domain.deezer.super_fan_profile import SuperFanProfile
from streaming_bot.domain.ports.deezer_client import IDeezerClient

# Tolerancia por defecto del pipeline: si una cuenta esta a menos de N
# artistas y M minutos del perfil pleno, se considera "en pipeline".
_DEFAULT_PIPELINE_GAP_ARTISTS = 20
_DEFAULT_PIPELINE_GAP_SESSION_MINUTES = 15.0


@dataclass(frozen=True, slots=True)
class EligibilityAssessment:
    """Veredicto sobre la cuenta + datos para auditar la decision."""

    account_id: str
    is_eligible: bool
    is_in_pipeline: bool
    score: AcpsScore | None
    history: DeezerListenerHistory | None
    gap: ProfileGap | None
    rejection_reason: str | None = None


class SuperFanEligibilityService:
    """Evalua cuentas frente a un `SuperFanProfile`.

    Args del constructor:
    - `deezer_client`: puerto para obtener historial de la cuenta.
    - `profile`: umbrales objetivos (default: `SuperFanProfile.strict()`).
    - `pipeline_gap_artists`: tolerancia para "casi llega" (default 20).
    - `pipeline_gap_session_minutes`: tolerancia en minutos de sesion.
    """

    def __init__(
        self,
        *,
        deezer_client: IDeezerClient,
        profile: SuperFanProfile | None = None,
        pipeline_gap_artists: int = _DEFAULT_PIPELINE_GAP_ARTISTS,
        pipeline_gap_session_minutes: float = _DEFAULT_PIPELINE_GAP_SESSION_MINUTES,
    ) -> None:
        if pipeline_gap_artists < 0:
            raise ValueError(
                f"pipeline_gap_artists debe ser >= 0: {pipeline_gap_artists}"
            )
        if pipeline_gap_session_minutes < 0:
            raise ValueError(
                f"pipeline_gap_session_minutes debe ser >= 0: "
                f"{pipeline_gap_session_minutes}"
            )
        self._client = deezer_client
        self._profile = profile if profile is not None else SuperFanProfile.strict()
        self._pipeline_gap_artists = pipeline_gap_artists
        self._pipeline_gap_session_minutes = pipeline_gap_session_minutes

    @property
    def profile(self) -> SuperFanProfile:
        return self._profile

    async def is_eligible(self, account_id: str) -> bool:
        """Atajo: True si la cuenta cumple el perfil estricto."""
        assessment = await self.assess(account_id)
        return assessment.is_eligible

    async def assess(self, account_id: str) -> EligibilityAssessment:
        """Obtiene el historial y emite el veredicto completo."""
        history = await self._client.get_user_history(account_id)
        if history is None:
            return EligibilityAssessment(
                account_id=account_id,
                is_eligible=False,
                is_in_pipeline=False,
                score=None,
                history=None,
                gap=None,
                rejection_reason="no_history_available",
            )

        gap = history.gap_against(self._profile)
        score = AcpsScore.from_history(history, self._profile)
        is_eligible = gap.is_zero
        is_in_pipeline = not is_eligible and self._fits_pipeline(gap)
        rejection_reason = None
        if not is_eligible and not is_in_pipeline:
            rejection_reason = "flat_spread_or_too_far_from_profile"

        return EligibilityAssessment(
            account_id=account_id,
            is_eligible=is_eligible,
            is_in_pipeline=is_in_pipeline,
            score=score,
            history=history,
            gap=gap,
            rejection_reason=rejection_reason,
        )

    def _fits_pipeline(self, gap: ProfileGap) -> bool:
        """Decide si la cuenta esta "lo bastante cerca" para nutrirla.

        Politica: tolera gaps en artistas y minutos de sesion (las dos
        metricas mas faciles de subir con tiempo). NO tolera replay_rate
        bajo (eso es senal estructural de bot) ni catalogo cero.
        """
        if gap.replay_rate_missing > 0:
            return False
        if gap.distinct_tracks_30d_missing > 0 and gap.distinct_tracks_30d_missing > 80:
            return False
        if gap.distinct_albums_30d_missing > 15:
            return False
        return (
            gap.artists_followed_missing <= self._pipeline_gap_artists
            and gap.avg_session_minutes_missing <= self._pipeline_gap_session_minutes
        )
