"""Tests del ``VariantResolver``: routing de keys a params del variant activo."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from streaming_bot.application.experiments.assignment_service import (
    ExperimentAssignmentService,
)
from streaming_bot.application.experiments.variant_resolver import VariantResolver
from streaming_bot.domain.exceptions import DomainError
from streaming_bot.domain.experiments.assignment import VariantAssignment
from streaming_bot.domain.experiments.experiment import (
    Experiment,
    ExperimentStatus,
    MetricsTargets,
)
from streaming_bot.domain.experiments.variant import Variant


def _running_experiment(
    *,
    exp_id: str = "exp-behavior",
    control_params: dict[str, object] | None = None,
    treatment_params: dict[str, object] | None = None,
) -> Experiment:
    return Experiment(
        id=exp_id,
        name="behavior tweak",
        hypothesis="aumentar dwell baja ban_rate",
        variants=(
            Variant(
                id="control",
                name="control",
                params=control_params or {},
                allocation_weight=50,
            ),
            Variant(
                id="treatment",
                name="treatment",
                params=treatment_params or {},
                allocation_weight=50,
            ),
        ),
        control_variant_id="control",
        traffic_allocation=1.0,
        start_at=datetime(2026, 5, 1, tzinfo=UTC),
        metrics_targets=MetricsTargets(),
        status=ExperimentStatus.RUNNING,
    )


def _build_resolver(
    experiment: Experiment,
    *,
    assignment_variant_id: str = "treatment",
) -> VariantResolver:
    experiments = AsyncMock()
    experiments.list_running.return_value = [experiment]
    experiments.get.return_value = experiment

    assignments = AsyncMock()
    assignments.get.return_value = VariantAssignment(
        account_id="acc-1",
        experiment_id=experiment.id,
        variant_id=assignment_variant_id,
        assigned_at=datetime(2026, 4, 1, tzinfo=UTC),
    )
    assignments.add.return_value = None

    assignment_service = ExperimentAssignmentService(
        experiments=experiments,
        assignments=assignments,
    )
    return VariantResolver(assignment_service=assignment_service, experiments=experiments)


class TestVariantResolver:
    async def test_returns_variant_param_when_present(self) -> None:
        exp = _running_experiment(
            treatment_params={"behavior_engine.hover_dwell_ms": 350},
        )
        resolver = _build_resolver(exp, assignment_variant_id="treatment")
        value = await resolver.params_for("acc-1", "behavior_engine.hover_dwell_ms", 250)
        assert value == 350

    async def test_returns_default_when_no_experiment_owns_key(self) -> None:
        exp = _running_experiment(treatment_params={"otro.param": 1})
        resolver = _build_resolver(exp)
        value = await resolver.params_for("acc-1", "behavior_engine.hover_dwell_ms", 250)
        assert value == 250

    async def test_returns_default_when_assigned_variant_lacks_key(self) -> None:
        # Solo treatment override la key; la cuenta cae en control -> default.
        exp = _running_experiment(treatment_params={"behavior_engine.hover_dwell_ms": 999})
        resolver = _build_resolver(exp, assignment_variant_id="control")
        value = await resolver.params_for("acc-1", "behavior_engine.hover_dwell_ms", 250)
        assert value == 250

    async def test_returns_default_when_no_running_experiments(self) -> None:
        experiments = AsyncMock()
        experiments.list_running.return_value = []
        assignments = AsyncMock()
        assignment_service = ExperimentAssignmentService(
            experiments=experiments,
            assignments=assignments,
        )
        resolver = VariantResolver(assignment_service=assignment_service, experiments=experiments)
        value = await resolver.params_for("acc-1", "any.key", 42)
        assert value == 42

    async def test_picks_first_experiment_when_multiple_own_key(self) -> None:
        exp_a = _running_experiment(
            exp_id="exp-A",
            treatment_params={"k": 100},
        )
        exp_b = _running_experiment(
            exp_id="exp-B",
            treatment_params={"k": 200},
        )
        experiments = AsyncMock()
        experiments.list_running.return_value = [exp_a, exp_b]

        async def _get_experiment(experiment_id: str) -> Experiment | None:
            return {"exp-A": exp_a, "exp-B": exp_b}.get(experiment_id)

        experiments.get.side_effect = _get_experiment

        assignments = AsyncMock()

        async def _get_assignment(
            account_id: str,
            experiment_id: str,
        ) -> VariantAssignment | None:
            return VariantAssignment(
                account_id=account_id,
                experiment_id=experiment_id,
                variant_id="treatment",
                assigned_at=datetime(2026, 4, 1, tzinfo=UTC),
            )

        assignments.get.side_effect = _get_assignment

        assignment_service = ExperimentAssignmentService(
            experiments=experiments,
            assignments=assignments,
        )
        resolver = VariantResolver(assignment_service=assignment_service, experiments=experiments)
        value = await resolver.params_for("acc-1", "k", 0)
        assert value == 100

    async def test_empty_key_raises(self) -> None:
        resolver = _build_resolver(_running_experiment())
        with pytest.raises(DomainError, match="key vacia"):
            await resolver.params_for("acc-1", "", 0)
