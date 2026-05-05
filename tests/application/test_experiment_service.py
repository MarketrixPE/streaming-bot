"""Tests del ``ExperimentService``: ciclo de vida + promocion de ganador."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from streaming_bot.application.experiments.experiment_service import ExperimentService
from streaming_bot.domain.exceptions import DomainError
from streaming_bot.domain.experiments.experiment import (
    Experiment,
    ExperimentStatus,
    MetricsTargets,
)
from streaming_bot.domain.experiments.outcome import ExperimentOutcome
from streaming_bot.domain.experiments.variant import Variant


def _variants() -> tuple[Variant, ...]:
    return (
        Variant(id="ctrl", name="control", params={}, allocation_weight=70),
        Variant(
            id="treat",
            name="treatment",
            params={"behavior_engine.hover_dwell_ms": 350},
            allocation_weight=30,
        ),
    )


def _experiment(
    *,
    status: ExperimentStatus = ExperimentStatus.DRAFT,
    targets: MetricsTargets | None = None,
) -> Experiment:
    return Experiment(
        id="exp-1",
        name="hover dwell uplift",
        hypothesis="dwell mas largo reduce ban",
        variants=_variants(),
        control_variant_id="ctrl",
        traffic_allocation=0.5,
        start_at=datetime(2026, 5, 1, tzinfo=UTC),
        metrics_targets=targets or MetricsTargets(),
        status=status,
    )


class TestCreateExperiment:
    async def test_creates_in_draft_and_persists(self) -> None:
        repo = AsyncMock()
        repo.get.return_value = None
        service = ExperimentService(experiments=repo)
        experiment = await service.create_experiment(
            experiment_id="exp-1",
            name="hover dwell uplift",
            hypothesis="dwell mas largo reduce ban",
            variants=_variants(),
            control_variant_id="ctrl",
            traffic_allocation=0.5,
            start_at=datetime(2026, 5, 1, tzinfo=UTC),
        )
        assert experiment.status == ExperimentStatus.DRAFT
        repo.save.assert_awaited_once()

    async def test_duplicate_id_raises(self) -> None:
        repo = AsyncMock()
        repo.get.return_value = _experiment()
        service = ExperimentService(experiments=repo)
        with pytest.raises(DomainError, match="ya existe"):
            await service.create_experiment(
                experiment_id="exp-1",
                name="x",
                hypothesis="y",
                variants=_variants(),
                control_variant_id="ctrl",
                traffic_allocation=0.5,
                start_at=datetime(2026, 5, 1, tzinfo=UTC),
            )


class TestLifecycleTransitions:
    async def test_start_moves_draft_to_running(self) -> None:
        repo = AsyncMock()
        repo.get.return_value = _experiment()
        service = ExperimentService(experiments=repo)
        result = await service.start("exp-1")
        assert result.status == ExperimentStatus.RUNNING

    async def test_pause_only_from_running(self) -> None:
        repo = AsyncMock()
        repo.get.return_value = _experiment()  # DRAFT
        service = ExperimentService(experiments=repo)
        with pytest.raises(DomainError, match="transicion invalida"):
            await service.pause("exp-1")

    async def test_resume_from_paused(self) -> None:
        repo = AsyncMock()
        repo.get.return_value = _experiment(status=ExperimentStatus.PAUSED)
        service = ExperimentService(experiments=repo)
        result = await service.resume("exp-1")
        assert result.status == ExperimentStatus.RUNNING

    async def test_conclude_from_running(self) -> None:
        repo = AsyncMock()
        repo.get.return_value = _experiment(status=ExperimentStatus.RUNNING)
        service = ExperimentService(experiments=repo)
        result = await service.conclude("exp-1", winner_variant_id="treat")
        assert result.status == ExperimentStatus.CONCLUDED
        assert result.winner_variant_id == "treat"

    async def test_load_missing_raises(self) -> None:
        repo = AsyncMock()
        repo.get.return_value = None
        service = ExperimentService(experiments=repo)
        with pytest.raises(DomainError, match="experiment no encontrado"):
            await service.start("missing")


class TestPromoteWinner:
    async def test_promotes_when_significant_and_lift_above_threshold(self) -> None:
        repo = AsyncMock()
        repo.get.return_value = _experiment(status=ExperimentStatus.RUNNING)
        writer = AsyncMock()
        service = ExperimentService(experiments=repo, settings_writer=writer)
        outcome = ExperimentOutcome(
            variant_id="treat",
            samples=1000,
            success_rate=0.45,
            ban_rate=0.01,
            cost_per_stream=0.012,
            p_value_vs_control=0.01,
            lift_vs_control_pct=12.0,
        )
        promoted = await service.promote_winner_to_default(
            "exp-1",
            winner_variant_id="treat",
            outcome=outcome,
        )
        assert promoted is True
        writer.write_defaults.assert_awaited_once()
        # tras promover, el experimento debe estar concluido y marcado.
        repo.save.assert_awaited()

    async def test_does_not_promote_when_p_value_above_threshold(self) -> None:
        repo = AsyncMock()
        repo.get.return_value = _experiment(status=ExperimentStatus.RUNNING)
        writer = AsyncMock()
        service = ExperimentService(experiments=repo, settings_writer=writer)
        outcome = ExperimentOutcome(
            variant_id="treat",
            samples=1000,
            success_rate=0.42,
            ban_rate=0.01,
            cost_per_stream=0.012,
            p_value_vs_control=0.20,  # No significativo.
            lift_vs_control_pct=12.0,
        )
        promoted = await service.promote_winner_to_default(
            "exp-1",
            winner_variant_id="treat",
            outcome=outcome,
        )
        assert promoted is False
        writer.write_defaults.assert_not_awaited()

    async def test_does_not_promote_when_lift_below_min(self) -> None:
        repo = AsyncMock()
        repo.get.return_value = _experiment(
            status=ExperimentStatus.RUNNING,
            targets=MetricsTargets(min_lift_pct=10.0),
        )
        writer = AsyncMock()
        service = ExperimentService(experiments=repo, settings_writer=writer)
        outcome = ExperimentOutcome(
            variant_id="treat",
            samples=1000,
            success_rate=0.41,
            ban_rate=0.01,
            cost_per_stream=0.012,
            p_value_vs_control=0.001,
            lift_vs_control_pct=2.5,  # < min_lift_pct=10.
        )
        promoted = await service.promote_winner_to_default(
            "exp-1",
            winner_variant_id="treat",
            outcome=outcome,
        )
        assert promoted is False
        writer.write_defaults.assert_not_awaited()

    async def test_promote_control_returns_false(self) -> None:
        repo = AsyncMock()
        repo.get.return_value = _experiment(status=ExperimentStatus.RUNNING)
        writer = AsyncMock()
        service = ExperimentService(experiments=repo, settings_writer=writer)
        outcome = ExperimentOutcome(
            variant_id="ctrl",
            samples=1000,
            success_rate=0.40,
            ban_rate=0.01,
            cost_per_stream=0.01,
            p_value_vs_control=0.0,
            lift_vs_control_pct=0.0,
        )
        promoted = await service.promote_winner_to_default(
            "exp-1",
            winner_variant_id="ctrl",
            outcome=outcome,
        )
        assert promoted is False
        writer.write_defaults.assert_not_awaited()

    async def test_outcome_variant_mismatch_raises(self) -> None:
        repo = AsyncMock()
        repo.get.return_value = _experiment(status=ExperimentStatus.RUNNING)
        service = ExperimentService(experiments=repo)
        outcome = ExperimentOutcome(
            variant_id="ctrl",  # No coincide con winner_variant_id.
            samples=10,
            success_rate=0.5,
            ban_rate=0.0,
            cost_per_stream=0.01,
            p_value_vs_control=0.001,
            lift_vs_control_pct=20.0,
        )
        with pytest.raises(DomainError, match="no coincide"):
            await service.promote_winner_to_default(
                "exp-1",
                winner_variant_id="treat",
                outcome=outcome,
            )

    async def test_unknown_winner_variant_raises(self) -> None:
        repo = AsyncMock()
        repo.get.return_value = _experiment(status=ExperimentStatus.RUNNING)
        service = ExperimentService(experiments=repo)
        outcome = ExperimentOutcome(
            variant_id="ghost",
            samples=10,
            success_rate=0.5,
            ban_rate=0.0,
            cost_per_stream=0.01,
            p_value_vs_control=0.001,
            lift_vs_control_pct=20.0,
        )
        with pytest.raises(DomainError, match="winner_variant_id desconocido"):
            await service.promote_winner_to_default(
                "exp-1",
                winner_variant_id="ghost",
                outcome=outcome,
            )

    async def test_promote_without_writer_still_marks_experiment(self) -> None:
        """Sin writer configurado, igual marca winner + concluye en repo."""
        repo = AsyncMock()
        repo.get.return_value = _experiment(status=ExperimentStatus.RUNNING)
        service = ExperimentService(experiments=repo, settings_writer=None)
        outcome = ExperimentOutcome(
            variant_id="treat",
            samples=1000,
            success_rate=0.45,
            ban_rate=0.01,
            cost_per_stream=0.012,
            p_value_vs_control=0.001,
            lift_vs_control_pct=12.0,
        )
        promoted = await service.promote_winner_to_default(
            "exp-1",
            winner_variant_id="treat",
            outcome=outcome,
        )
        assert promoted is True
        repo.save.assert_awaited()
