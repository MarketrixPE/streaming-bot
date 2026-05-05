"""Repositorio Postgres del agregado ``Experiment``.

Maneja:
- ``save``: upsert del agregado completo (experiment + variantes).
- ``get``: lookup por id con eager-load de variantes.
- ``list_running``: filtro por status RUNNING para el ``VariantResolver``.

Estrategia de upsert:
- ``MERGE``/``ON CONFLICT`` no es portatil entre Postgres/SQLite, asi que
  hacemos: 1) upsert del row de ``experiments``; 2) borrado en bloque de
  variantes existentes; 3) re-insert de la tupla actual. El agregado define
  un numero pequeno de variantes (<10), asi que el cost es marginal y la
  semantica es atomica dentro de la transaccion del session.
"""

from __future__ import annotations

from dataclasses import asdict

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from streaming_bot.domain.experiments.experiment import (
    Experiment,
    ExperimentStatus,
    MetricsTargets,
)
from streaming_bot.domain.experiments.variant import Variant
from streaming_bot.infrastructure.persistence.postgres.models.experiment import (
    ExperimentModel,
    ExperimentVariantModel,
)


class PostgresExperimentRepository:
    """Implementacion de ``IExperimentRepository`` sobre Postgres/SQLite."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, experiment: Experiment) -> None:
        """Upsert atomico de experimento + variantes."""
        existing = await self._session.get(ExperimentModel, experiment.id)
        if existing is None:
            self._session.add(self._to_model(experiment))
        else:
            _apply_to_model(experiment, existing)
        # Reset de variantes: borra y re-inserta para reflejar el aggregate
        # actual sin tener que diffear nombre por nombre.
        await self._session.execute(
            delete(ExperimentVariantModel).where(
                ExperimentVariantModel.experiment_id == experiment.id,
            ),
        )
        for position, variant in enumerate(experiment.variants):
            self._session.add(
                ExperimentVariantModel(
                    id=variant.id,
                    experiment_id=experiment.id,
                    name=variant.name,
                    params=dict(variant.params),
                    allocation_weight=variant.allocation_weight,
                    position=position,
                ),
            )
        await self._session.flush()

    async def get(self, experiment_id: str) -> Experiment | None:
        """Carga el agregado completo (experiment + variantes ordenadas)."""
        model = await self._session.get(ExperimentModel, experiment_id)
        if model is None:
            return None
        variants = await self._load_variants(experiment_id)
        return _to_domain(model, variants)

    async def list_running(self) -> list[Experiment]:
        """Devuelve experimentos en status RUNNING (carga variantes por cada uno)."""
        stmt = select(ExperimentModel).where(
            ExperimentModel.status == ExperimentStatus.RUNNING.value,
        )
        result = await self._session.execute(stmt)
        models = list(result.scalars().all())
        out: list[Experiment] = []
        for model in models:
            variants = await self._load_variants(model.id)
            out.append(_to_domain(model, variants))
        return out

    # -- helpers --------------------------------------------------------- #

    async def _load_variants(self, experiment_id: str) -> tuple[Variant, ...]:
        stmt = (
            select(ExperimentVariantModel)
            .where(ExperimentVariantModel.experiment_id == experiment_id)
            .order_by(ExperimentVariantModel.position.asc())
        )
        result = await self._session.execute(stmt)
        rows = result.scalars().all()
        return tuple(
            Variant(
                id=row.id,
                name=row.name,
                params=dict(row.params),
                allocation_weight=row.allocation_weight,
            )
            for row in rows
        )

    def _to_model(self, experiment: Experiment) -> ExperimentModel:
        return ExperimentModel(
            id=experiment.id,
            name=experiment.name,
            hypothesis=experiment.hypothesis,
            status=experiment.status.value,
            control_variant_id=experiment.control_variant_id,
            traffic_allocation=experiment.traffic_allocation,
            start_at=experiment.start_at,
            end_at=experiment.end_at,
            metrics_targets=asdict(experiment.metrics_targets),
            winner_variant_id=experiment.winner_variant_id,
            promoted_at=experiment.promoted_at,
            notes=experiment.notes,
        )


def _apply_to_model(experiment: Experiment, model: ExperimentModel) -> None:
    """UPDATE in-place de los campos mutables del agregado."""
    model.name = experiment.name
    model.hypothesis = experiment.hypothesis
    model.status = experiment.status.value
    model.control_variant_id = experiment.control_variant_id
    model.traffic_allocation = experiment.traffic_allocation
    model.start_at = experiment.start_at
    model.end_at = experiment.end_at
    model.metrics_targets = asdict(experiment.metrics_targets)
    model.winner_variant_id = experiment.winner_variant_id
    model.promoted_at = experiment.promoted_at
    model.notes = experiment.notes


def _to_domain(model: ExperimentModel, variants: tuple[Variant, ...]) -> Experiment:
    """Reconstruye el agregado de dominio a partir del modelo + variantes."""
    targets_data = dict(model.metrics_targets) if model.metrics_targets else {}
    targets = MetricsTargets(
        min_success_rate=float(targets_data.get("min_success_rate", 0.0)),
        max_ban_rate=float(targets_data.get("max_ban_rate", 1.0)),
        max_cost_per_stream=float(targets_data.get("max_cost_per_stream", float("inf"))),
        min_lift_pct=float(targets_data.get("min_lift_pct", 5.0)),
        p_value_threshold=float(targets_data.get("p_value_threshold", 0.05)),
    )
    return Experiment(
        id=model.id,
        name=model.name,
        hypothesis=model.hypothesis,
        variants=variants,
        control_variant_id=model.control_variant_id,
        traffic_allocation=model.traffic_allocation,
        start_at=model.start_at,
        end_at=model.end_at,
        metrics_targets=targets,
        status=ExperimentStatus(model.status),
        winner_variant_id=model.winner_variant_id,
        promoted_at=model.promoted_at,
        notes=model.notes,
    )
