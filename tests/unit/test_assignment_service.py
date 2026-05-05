"""Tests del ``ExperimentAssignmentService``: hashing deterministico + sticky."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from streaming_bot.application.experiments.assignment_service import (
    DEFAULT_ASSIGNMENT_SALT,
    ExperimentAssignmentService,
)
from streaming_bot.domain.exceptions import DomainError
from streaming_bot.domain.experiments.assignment import VariantAssignment
from streaming_bot.domain.experiments.experiment import (
    Experiment,
    ExperimentStatus,
    MetricsTargets,
)
from streaming_bot.domain.experiments.variant import Variant


def _experiment(
    *,
    exp_id: str = "exp-1",
    weights: tuple[int, ...] = (50, 50),
    traffic_allocation: float = 1.0,
) -> Experiment:
    """Construye un experimento con N variantes y pesos especificados."""
    variants = tuple(
        Variant(
            id=f"v{idx}",
            name=f"variant-{idx}",
            params={f"k{idx}": idx},
            allocation_weight=w,
        )
        for idx, w in enumerate(weights)
    )
    return Experiment(
        id=exp_id,
        name="exp",
        hypothesis="h",
        variants=variants,
        control_variant_id="v0",
        traffic_allocation=traffic_allocation,
        start_at=datetime(2026, 5, 1, tzinfo=UTC),
        metrics_targets=MetricsTargets(),
        status=ExperimentStatus.RUNNING,
    )


def _build_service(
    *,
    experiment: Experiment,
    existing_assignment: VariantAssignment | None = None,
) -> tuple[ExperimentAssignmentService, AsyncMock, AsyncMock]:
    experiments = AsyncMock()
    experiments.get.return_value = experiment

    assignments = AsyncMock()
    assignments.get.return_value = existing_assignment
    assignments.add.return_value = None

    service = ExperimentAssignmentService(
        experiments=experiments,
        assignments=assignments,
        salt=DEFAULT_ASSIGNMENT_SALT,
    )
    return service, experiments, assignments


class TestStickyAssignment:
    async def test_returns_existing_assignment_without_calling_experiment(self) -> None:
        existing = VariantAssignment(
            account_id="acc-1",
            experiment_id="exp-1",
            variant_id="v1",
            assigned_at=datetime(2026, 4, 1, tzinfo=UTC),
        )
        service, experiments, assignments = _build_service(
            experiment=_experiment(),
            existing_assignment=existing,
        )
        result = await service.get_or_assign("acc-1", "exp-1")
        assert result is existing
        # Sticky: no se debio cargar el experimento ni insertar nada nuevo.
        experiments.get.assert_not_awaited()
        assignments.add.assert_not_awaited()

    async def test_persists_new_assignment_when_missing(self) -> None:
        service, _experiments, assignments = _build_service(experiment=_experiment())
        result = await service.get_or_assign("acc-xyz", "exp-1")
        assert result.account_id == "acc-xyz"
        assert result.experiment_id == "exp-1"
        assert result.variant_id in {"v0", "v1"}
        assert result.assigned_at.tzinfo is not None
        assignments.add.assert_awaited_once()

    async def test_missing_experiment_raises(self) -> None:
        experiments = AsyncMock()
        experiments.get.return_value = None
        assignments = AsyncMock()
        assignments.get.return_value = None
        service = ExperimentAssignmentService(
            experiments=experiments,
            assignments=assignments,
        )
        with pytest.raises(DomainError, match="experiment no encontrado"):
            await service.get_or_assign("acc-1", "missing")


class TestDeterministicHashing:
    async def test_same_inputs_yield_same_variant(self) -> None:
        exp = _experiment()
        service_a, _exp_a, _ass_a = _build_service(experiment=exp)
        service_b, _exp_b, _ass_b = _build_service(experiment=exp)
        result_a = await service_a.get_or_assign("acc-stable", "exp-1")
        result_b = await service_b.get_or_assign("acc-stable", "exp-1")
        assert result_a.variant_id == result_b.variant_id

    async def test_different_salt_can_change_variant(self) -> None:
        exp = _experiment()
        common_assignments = AsyncMock()
        common_assignments.get.return_value = None
        common_assignments.add.return_value = None
        common_experiments = AsyncMock()
        common_experiments.get.return_value = exp

        salts_to_variants: dict[str, str] = {}
        # Probamos varios salts y juntamos las decisiones para una misma cuenta.
        for salt in ["salt-A", "salt-B", "salt-C", "salt-D", "salt-E"]:
            service = ExperimentAssignmentService(
                experiments=common_experiments,
                assignments=common_assignments,
                salt=salt,
            )
            result = await service.get_or_assign("acc-fixed", "exp-1")
            salts_to_variants[salt] = result.variant_id
        # Esperamos al menos 2 variantes distintas en 5 salts (probabilistico
        # pero practicamente seguro con pesos 50/50).
        assert len(set(salts_to_variants.values())) >= 2

    async def test_distribution_respects_weights(self) -> None:
        """Con pesos 80/20 y 1000 cuentas, la distribucion ronda 80/20."""
        exp = _experiment(weights=(80, 20))
        # Mock que persiste el assignment como sticky en memoria.
        memory: dict[tuple[str, str], VariantAssignment] = {}

        async def _get(account_id: str, experiment_id: str) -> VariantAssignment | None:
            return memory.get((account_id, experiment_id))

        async def _add(assignment: VariantAssignment) -> None:
            memory[(assignment.account_id, assignment.experiment_id)] = assignment

        assignments = AsyncMock()
        assignments.get.side_effect = _get
        assignments.add.side_effect = _add
        experiments = AsyncMock()
        experiments.get.return_value = exp

        service = ExperimentAssignmentService(
            experiments=experiments,
            assignments=assignments,
            salt="dist-test",
        )
        counts: Counter[str] = Counter()
        for i in range(1000):
            assignment = await service.get_or_assign(f"acc-{i}", "exp-1")
            counts[assignment.variant_id] += 1
        # Tolerancia amplia: 80/20 con N=1000 deberia caer en [70, 90] / [10, 30].
        assert 700 <= counts["v0"] <= 900
        assert 100 <= counts["v1"] <= 300

    async def test_traffic_allocation_routes_excluded_to_control(self) -> None:
        """Con traffic 0.05 la mayoria de cuentas deberia caer en control."""
        exp = _experiment(weights=(1, 99), traffic_allocation=0.05)
        memory: dict[tuple[str, str], VariantAssignment] = {}

        async def _get(account_id: str, experiment_id: str) -> VariantAssignment | None:
            return memory.get((account_id, experiment_id))

        async def _add(assignment: VariantAssignment) -> None:
            memory[(assignment.account_id, assignment.experiment_id)] = assignment

        assignments = AsyncMock()
        assignments.get.side_effect = _get
        assignments.add.side_effect = _add
        experiments = AsyncMock()
        experiments.get.return_value = exp

        service = ExperimentAssignmentService(
            experiments=experiments,
            assignments=assignments,
            salt="traffic-test",
        )
        counts: Counter[str] = Counter()
        for i in range(500):
            assignment = await service.get_or_assign(f"acc-{i}", "exp-1")
            counts[assignment.variant_id] += 1
        # Solo ~5% deberia caer en v1 (la unica de tratamiento, peso 99 dentro
        # del 5% incluido). El resto va a control de forma incondicional.
        assert counts["v0"] >= 400
        assert counts["v1"] <= 100
