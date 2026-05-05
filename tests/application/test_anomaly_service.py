"""Tests del ``AnomalyDetectionService``.

Usamos un fake ``IAnomalyPredictor`` con scores deterministas para
verificar que la política de cuarentena se aplica correctamente sin
depender de LightGBM real.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from streaming_bot.application.ml.anomaly_service import (
    AnomalyDetectionService,
    QuarantineSignaler,
)
from streaming_bot.domain.ml.anomaly_score import AnomalyScore
from streaming_bot.domain.ml.feature_vector import AccountFeatureVector


def _now() -> datetime:
    return datetime(2026, 4, 27, 12, 0, 0, tzinfo=UTC)


class FakePredictor:
    """Devuelve scores predefinidos por ``account_id``."""

    def __init__(self, scores: dict[str, float]) -> None:
        self._scores = scores
        self.calls: list[str] = []

    @property
    def model_version(self) -> str:
        return "fake-v1.0.0"

    async def predict_for_account(self, account_id: str) -> AnomalyScore:
        self.calls.append(account_id)
        score_value = self._scores.get(account_id, 0.0)
        return AnomalyScore.from_score(
            account_id=account_id,
            score=score_value,
            computed_at=_now(),
            model_version=self.model_version,
        )

    async def predict_batch(self, account_ids: list[str]) -> list[AnomalyScore]:
        return [await self.predict_for_account(a) for a in account_ids]

    async def predict_from_features(
        self,
        features: AccountFeatureVector,
    ) -> AnomalyScore:
        return await self.predict_for_account(features.account_id)


@dataclass
class FakeSignaler(QuarantineSignaler):
    """Signaler que registra cada cuarentena emitida."""

    signals: list[tuple[str, str]] = field(default_factory=list)

    async def signal_quarantine(self, *, account_id: str, reason: str) -> None:
        self.signals.append((account_id, reason))


def _service(
    *,
    scores: dict[str, float],
    threshold_quarantine: float = 0.7,
    threshold_critical: float = 0.85,
) -> tuple[AnomalyDetectionService, FakePredictor, FakeSignaler]:
    predictor = FakePredictor(scores)
    signaler = FakeSignaler()
    service = AnomalyDetectionService(
        predictor=predictor,
        signaler=signaler,
        threshold_quarantine_score=threshold_quarantine,
        threshold_critical_score=threshold_critical,
        now_factory=_now,
    )
    return service, predictor, signaler


class TestThresholdEnforcement:
    async def test_low_score_does_not_quarantine(self) -> None:
        service, _, signaler = _service(scores={"acc-1": 0.2})
        decision = await service.evaluate("acc-1")
        assert decision.quarantined is False
        assert decision.reason is None
        assert signaler.signals == []

    async def test_high_score_triggers_quarantine(self) -> None:
        service, _, signaler = _service(scores={"acc-1": 0.75})
        decision = await service.evaluate("acc-1")
        assert decision.quarantined is True
        assert decision.reason == "ml_high_risk"
        assert signaler.signals == [("acc-1", "ml_high_risk")]

    async def test_critical_score_triggers_critical_reason(self) -> None:
        service, _, signaler = _service(scores={"acc-1": 0.92})
        decision = await service.evaluate("acc-1")
        assert decision.quarantined is True
        assert decision.reason == "ml_critical"
        assert signaler.signals == [("acc-1", "ml_critical")]

    async def test_threshold_boundary_inclusive(self) -> None:
        service, _, signaler = _service(scores={"acc-1": 0.7})
        decision = await service.evaluate("acc-1")
        assert decision.quarantined is True
        assert signaler.signals == [("acc-1", "ml_high_risk")]


class TestBatchEvaluation:
    async def test_batch_returns_one_decision_per_account(self) -> None:
        service, predictor, signaler = _service(
            scores={"a": 0.1, "b": 0.8, "c": 0.95},
        )
        decisions = await service.evaluate_batch(["a", "b", "c"])
        assert [d.score.account_id for d in decisions] == ["a", "b", "c"]
        assert [d.quarantined for d in decisions] == [False, True, True]
        assert predictor.calls == ["a", "b", "c"]
        assert signaler.signals == [("b", "ml_high_risk"), ("c", "ml_critical")]


class TestThresholdValidation:
    def test_critical_must_be_at_least_quarantine(self) -> None:
        with pytest.raises(ValueError, match="threshold_critical_score"):
            _service(
                scores={},
                threshold_quarantine=0.8,
                threshold_critical=0.5,
            )

    @pytest.mark.parametrize("bad", [-0.1, 1.5])
    def test_quarantine_threshold_in_range(self, bad: float) -> None:
        with pytest.raises(ValueError, match="threshold_quarantine_score"):
            _service(scores={}, threshold_quarantine=bad)
