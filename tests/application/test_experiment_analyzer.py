"""Tests del ``ExperimentAnalyzer``: outcomes + chi-square + lift vs control."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from streaming_bot.application.experiments.analyzer import (
    ExperimentAnalyzer,
    RawVariantMetrics,
)
from streaming_bot.domain.exceptions import DomainError
from streaming_bot.domain.experiments.experiment import (
    Experiment,
    ExperimentStatus,
    MetricsTargets,
)
from streaming_bot.domain.experiments.outcome import ExperimentOutcome
from streaming_bot.domain.experiments.variant import Variant


def _two_variant_experiment() -> Experiment:
    return Experiment(
        id="exp-1",
        name="ban reduction",
        hypothesis="hover dwell baja ban_rate",
        variants=(
            Variant(id="ctrl", name="control", params={}, allocation_weight=50),
            Variant(id="treat", name="treatment", params={"x": 1}, allocation_weight=50),
        ),
        control_variant_id="ctrl",
        traffic_allocation=1.0,
        start_at=datetime(2026, 5, 1, tzinfo=UTC),
        metrics_targets=MetricsTargets(),
        status=ExperimentStatus.RUNNING,
    )


def _build_analyzer(
    experiment: Experiment,
    raw_by_variant: dict[str, RawVariantMetrics],
) -> ExperimentAnalyzer:
    experiments = AsyncMock()
    experiments.get.return_value = experiment

    events = AsyncMock()

    async def _fetch(
        experiment_id: str,
        variant_ids: Sequence[str],
    ) -> dict[str, RawVariantMetrics]:
        assert experiment_id == experiment.id
        assert set(variant_ids) == {v.id for v in experiment.variants}
        return raw_by_variant

    events.fetch_outcomes.side_effect = _fetch
    return ExperimentAnalyzer(experiments=experiments, events=events)


class TestAnalyzeOutcomes:
    async def test_control_has_no_p_value_or_lift(self) -> None:
        exp = _two_variant_experiment()
        raw = {
            "ctrl": RawVariantMetrics(
                variant_id="ctrl", samples=200, successes=80, bans=8, total_cost_usd=2.5,
            ),
            "treat": RawVariantMetrics(
                variant_id="treat", samples=200, successes=110, bans=4, total_cost_usd=2.0,
            ),
        }
        analyzer = _build_analyzer(exp, raw)
        outcomes = await analyzer.analyze("exp-1")
        by_id: dict[str, ExperimentOutcome] = {o.variant_id: o for o in outcomes}
        assert by_id["ctrl"].p_value_vs_control is None
        assert by_id["ctrl"].lift_vs_control_pct is None
        # Tasas calculadas correctamente.
        assert by_id["ctrl"].success_rate == pytest.approx(0.40)
        assert by_id["treat"].success_rate == pytest.approx(0.55)
        # Lift (0.55 - 0.40) / 0.40 = 37.5%.
        assert by_id["treat"].lift_vs_control_pct == pytest.approx(37.5, rel=1e-3)
        # Costo medio.
        assert by_id["ctrl"].cost_per_stream == pytest.approx(0.0125)

    async def test_chi_square_significant_for_strong_signal(self) -> None:
        """Diferencia clara debe dar p-value < 0.05."""
        exp = _two_variant_experiment()
        raw = {
            "ctrl": RawVariantMetrics(
                variant_id="ctrl", samples=500, successes=200, bans=20, total_cost_usd=1.0,
            ),
            "treat": RawVariantMetrics(
                variant_id="treat", samples=500, successes=300, bans=10, total_cost_usd=1.0,
            ),
        }
        analyzer = _build_analyzer(exp, raw)
        outcomes = await analyzer.analyze("exp-1")
        treat = next(o for o in outcomes if o.variant_id == "treat")
        assert treat.p_value_vs_control is not None
        assert treat.p_value_vs_control < 0.05
        assert treat.is_significant

    async def test_chi_square_not_significant_for_noise(self) -> None:
        """Diferencias minimas (51 vs 50 / 100) NO son significativas."""
        exp = _two_variant_experiment()
        raw = {
            "ctrl": RawVariantMetrics(
                variant_id="ctrl", samples=100, successes=50, bans=0, total_cost_usd=0.0,
            ),
            "treat": RawVariantMetrics(
                variant_id="treat", samples=100, successes=51, bans=0, total_cost_usd=0.0,
            ),
        }
        analyzer = _build_analyzer(exp, raw)
        outcomes = await analyzer.analyze("exp-1")
        treat = next(o for o in outcomes if o.variant_id == "treat")
        assert treat.p_value_vs_control is not None
        assert treat.p_value_vs_control > 0.05
        assert not treat.is_significant

    async def test_zero_samples_yields_zero_rates(self) -> None:
        exp = _two_variant_experiment()
        raw = {
            "ctrl": RawVariantMetrics(
                variant_id="ctrl", samples=0, successes=0, bans=0, total_cost_usd=0.0,
            ),
            "treat": RawVariantMetrics(
                variant_id="treat", samples=0, successes=0, bans=0, total_cost_usd=0.0,
            ),
        }
        analyzer = _build_analyzer(exp, raw)
        outcomes = await analyzer.analyze("exp-1")
        for outcome in outcomes:
            assert outcome.success_rate == 0.0
            assert outcome.ban_rate == 0.0
            assert outcome.cost_per_stream == 0.0
        # Sin datos, p-value y lift son None (todos los marginales en cero).
        treat = next(o for o in outcomes if o.variant_id == "treat")
        assert treat.p_value_vs_control is None
        assert treat.lift_vs_control_pct is None

    async def test_missing_variant_data_treated_as_zero(self) -> None:
        exp = _two_variant_experiment()
        # Solo el control tiene datos en ClickHouse.
        raw = {
            "ctrl": RawVariantMetrics(
                variant_id="ctrl", samples=100, successes=40, bans=2, total_cost_usd=1.0,
            ),
        }
        analyzer = _build_analyzer(exp, raw)
        outcomes = await analyzer.analyze("exp-1")
        treat = next(o for o in outcomes if o.variant_id == "treat")
        assert treat.samples == 0
        assert treat.success_rate == 0.0
        assert treat.cost_per_stream == 0.0

    async def test_unknown_experiment_raises(self) -> None:
        experiments = AsyncMock()
        experiments.get.return_value = None
        events = AsyncMock()
        analyzer = ExperimentAnalyzer(experiments=experiments, events=events)
        with pytest.raises(DomainError, match="experiment no encontrado"):
            await analyzer.analyze("ghost")

    async def test_lift_undefined_when_control_rate_zero(self) -> None:
        exp = _two_variant_experiment()
        raw = {
            "ctrl": RawVariantMetrics(
                variant_id="ctrl", samples=100, successes=0, bans=0, total_cost_usd=0.0,
            ),
            "treat": RawVariantMetrics(
                variant_id="treat", samples=100, successes=10, bans=0, total_cost_usd=0.0,
            ),
        }
        analyzer = _build_analyzer(exp, raw)
        outcomes = await analyzer.analyze("exp-1")
        treat = next(o for o in outcomes if o.variant_id == "treat")
        assert treat.lift_vs_control_pct is None
