"""Tests del VO ``AnomalyScore``."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from streaming_bot.domain.ml.anomaly_score import (
    AnomalyScore,
    FeatureContribution,
    RiskLevel,
)


def _now() -> datetime:
    return datetime(2026, 4, 27, 12, 0, 0, tzinfo=UTC)


class TestConstruction:
    def test_valid_score(self) -> None:
        score = AnomalyScore(
            account_id="acc-1",
            score=0.42,
            risk_level=RiskLevel.MEDIUM,
            computed_at=_now(),
        )
        assert score.score == 0.42
        assert score.risk_level == RiskLevel.MEDIUM

    @pytest.mark.parametrize("bad", [-0.01, 1.01, 1.5, -10.0])
    def test_score_out_of_range(self, bad: float) -> None:
        with pytest.raises(ValueError, match="score fuera de rango"):
            AnomalyScore(
                account_id="acc-1",
                score=bad,
                risk_level=RiskLevel.LOW,
                computed_at=_now(),
            )

    def test_too_many_top_features(self) -> None:
        many = tuple(
            FeatureContribution(feature_name=f"f{i}", contribution=0.1) for i in range(11)
        )
        with pytest.raises(ValueError, match="top_features"):
            AnomalyScore(
                account_id="acc-1",
                score=0.5,
                risk_level=RiskLevel.MEDIUM,
                computed_at=_now(),
                top_features=many,
            )


class TestFromScore:
    @pytest.mark.parametrize(
        ("score", "expected"),
        [
            (0.0, RiskLevel.LOW),
            (0.39, RiskLevel.LOW),
            (0.4, RiskLevel.MEDIUM),
            (0.69, RiskLevel.MEDIUM),
            (0.7, RiskLevel.HIGH),
            (0.84, RiskLevel.HIGH),
            (0.85, RiskLevel.CRITICAL),
            (1.0, RiskLevel.CRITICAL),
        ],
    )
    def test_classification_with_default_thresholds(
        self,
        score: float,
        expected: RiskLevel,
    ) -> None:
        result = AnomalyScore.from_score(
            account_id="acc-x",
            score=score,
            computed_at=_now(),
        )
        assert result.risk_level == expected

    def test_custom_thresholds(self) -> None:
        score = AnomalyScore.from_score(
            account_id="acc-x",
            score=0.55,
            computed_at=_now(),
            threshold_medium=0.5,
            threshold_high=0.6,
            threshold_critical=0.9,
        )
        assert score.risk_level == RiskLevel.MEDIUM


class TestActionable:
    def test_high_is_actionable(self) -> None:
        score = AnomalyScore.from_score(
            account_id="acc-x",
            score=0.75,
            computed_at=_now(),
        )
        assert score.is_actionable is True

    def test_medium_is_not_actionable(self) -> None:
        score = AnomalyScore.from_score(
            account_id="acc-x",
            score=0.5,
            computed_at=_now(),
        )
        assert score.is_actionable is False


class TestImmutability:
    def test_frozen(self) -> None:
        score = AnomalyScore(
            account_id="acc-1",
            score=0.5,
            risk_level=RiskLevel.MEDIUM,
            computed_at=_now(),
        )
        with pytest.raises(AttributeError):
            score.score = 0.9  # type: ignore[misc]
