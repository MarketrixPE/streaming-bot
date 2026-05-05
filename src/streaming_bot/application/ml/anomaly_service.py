"""Servicio de aplicación: detección de anomalías + política de retiro.

Combina el ``IAnomalyPredictor`` con la política de cuarentena. La
política es muy simple:

- score >= ``threshold_critical_score`` → CRITICAL → cuarentena inmediata
  con razón "ml_critical".
- score >= ``threshold_quarantine_score`` → HIGH → cuarentena con razón
  "ml_high_risk".
- por debajo → NO action.

Cuando se decide cuarentena, el servicio emite una señal a un
``QuarantineSignaler`` (typicamente Temporal signal "quarantine" sobre el
workflow de la cuenta). En tests se inyecta un fake.

El servicio es agnóstico al transporte: sólo depende del puerto.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from streaming_bot.domain.ml.anomaly_score import RiskLevel

if TYPE_CHECKING:
    from collections.abc import Callable

    from structlog.stdlib import BoundLogger

    from streaming_bot.domain.ml.anomaly_score import AnomalyScore
    from streaming_bot.domain.ports.anomaly_predictor import IAnomalyPredictor


@runtime_checkable
class QuarantineSignaler(Protocol):
    """Emite la señal de cuarentena hacia el workflow / scheduler.

    Implementaciones reales:
    - Temporal signal ``quarantine`` al workflow de la cuenta.
    - Update directo al ``IAccountRepository`` cambiando el estado.
    - Mensaje en cola Redis para el scheduler.
    """

    async def signal_quarantine(self, *, account_id: str, reason: str) -> None: ...


@dataclass(frozen=True, slots=True)
class QuarantineDecision:
    """Resultado del servicio: el score más la decisión tomada."""

    score: AnomalyScore
    quarantined: bool
    reason: str | None = None


class AnomalyDetectionService:
    """Use case principal: predice y, si procede, retira la cuenta."""

    def __init__(
        self,
        *,
        predictor: IAnomalyPredictor,
        signaler: QuarantineSignaler,
        threshold_quarantine_score: float = 0.7,
        threshold_critical_score: float = 0.85,
        logger: BoundLogger | None = None,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        if not 0.0 <= threshold_quarantine_score <= 1.0:
            raise ValueError(
                f"threshold_quarantine_score fuera de rango: {threshold_quarantine_score}",
            )
        if not 0.0 <= threshold_critical_score <= 1.0:
            raise ValueError(
                f"threshold_critical_score fuera de rango: {threshold_critical_score}",
            )
        if threshold_critical_score < threshold_quarantine_score:
            raise ValueError(
                "threshold_critical_score debe ser >= threshold_quarantine_score",
            )
        self._predictor = predictor
        self._signaler = signaler
        self._threshold_quarantine = threshold_quarantine_score
        self._threshold_critical = threshold_critical_score
        self._logger = logger
        self._now_factory = now_factory or (lambda: datetime.now(UTC))

    async def evaluate(self, account_id: str) -> QuarantineDecision:
        """Predice el score y, si supera umbral, dispara cuarentena."""
        score = await self._predictor.predict_for_account(account_id)
        return await self._apply_policy(score)

    async def evaluate_batch(self, account_ids: list[str]) -> list[QuarantineDecision]:
        """Versión batch: una sola llamada al predictor + iter de políticas."""
        scores = await self._predictor.predict_batch(account_ids)
        decisions: list[QuarantineDecision] = []
        for score in scores:
            decisions.append(await self._apply_policy(score))
        return decisions

    async def _apply_policy(self, score: AnomalyScore) -> QuarantineDecision:
        if score.score >= self._threshold_critical or score.risk_level == RiskLevel.CRITICAL:
            reason = "ml_critical"
            await self._signaler.signal_quarantine(
                account_id=score.account_id,
                reason=reason,
            )
            self._log_decision(score=score, quarantined=True, reason=reason)
            return QuarantineDecision(score=score, quarantined=True, reason=reason)
        if score.score >= self._threshold_quarantine or score.risk_level == RiskLevel.HIGH:
            reason = "ml_high_risk"
            await self._signaler.signal_quarantine(
                account_id=score.account_id,
                reason=reason,
            )
            self._log_decision(score=score, quarantined=True, reason=reason)
            return QuarantineDecision(score=score, quarantined=True, reason=reason)
        self._log_decision(score=score, quarantined=False, reason=None)
        return QuarantineDecision(score=score, quarantined=False, reason=None)

    def _log_decision(
        self,
        *,
        score: AnomalyScore,
        quarantined: bool,
        reason: str | None,
    ) -> None:
        if self._logger is None:
            return
        self._logger.info(
            "anomaly_decision",
            account_id=score.account_id,
            score=score.score,
            risk_level=score.risk_level.value,
            quarantined=quarantined,
            reason=reason,
            model_version=score.model_version,
        )
