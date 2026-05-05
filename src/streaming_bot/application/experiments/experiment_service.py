"""Caso de uso de gestion del ciclo de vida de experimentos.

Encapsula:
- Creacion de experimentos en estado DRAFT.
- Transiciones explicitas (start/pause/conclude).
- Promocion del ganador a default global, contra un escritor de overrides
  abstraido por el puerto ``ISettingsOverridesWriter`` (Postgres table o JSON).

Reglas de promocion:
- Solo se puede promover un variant si su ``ExperimentOutcome`` cumple:
  ``p_value_vs_control < experiment.metrics_targets.p_value_threshold`` y
  ``lift_vs_control_pct >= experiment.metrics_targets.min_lift_pct``.
- La promocion es idempotente: re-llamar con el mismo ganador no hace nada.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from streaming_bot.domain.exceptions import DomainError
from streaming_bot.domain.experiments.experiment import (
    Experiment,
    ExperimentStatus,
    MetricsTargets,
)
from streaming_bot.domain.experiments.outcome import ExperimentOutcome
from streaming_bot.domain.experiments.variant import Variant
from streaming_bot.domain.ports.experiment_repo import IExperimentRepository


@runtime_checkable
class ISettingsOverridesWriter(Protocol):
    """Sink generica para promover params ganadores a default global.

    La implementacion concreta puede escribir en una tabla
    ``settings_overrides`` de Postgres o en un JSON file. El servicio se
    queda agnostico del backend.
    """

    async def write_defaults(
        self,
        *,
        experiment_id: str,
        variant_id: str,
        params: dict[str, Any],
        promoted_at: datetime,
    ) -> None: ...


class ExperimentService:
    """Casos de uso del agregado ``Experiment``.

    No mantiene estado entre llamadas: cada metodo recarga el agregado del
    repositorio para evitar lecturas obsoletas en escenarios concurrentes.
    """

    def __init__(
        self,
        experiments: IExperimentRepository,
        *,
        settings_writer: ISettingsOverridesWriter | None = None,
        clock: type[datetime] = datetime,
    ) -> None:
        self._experiments = experiments
        self._settings_writer = settings_writer
        self._clock = clock

    async def create_experiment(
        self,
        *,
        experiment_id: str,
        name: str,
        hypothesis: str,
        variants: tuple[Variant, ...],
        control_variant_id: str,
        traffic_allocation: float,
        start_at: datetime,
        end_at: datetime | None = None,
        metrics_targets: MetricsTargets | None = None,
        notes: str = "",
    ) -> Experiment:
        """Crea un experimento en estado DRAFT y lo persiste."""
        if await self._experiments.get(experiment_id) is not None:
            raise DomainError(f"experiment ya existe: {experiment_id}")
        experiment = Experiment(
            id=experiment_id,
            name=name,
            hypothesis=hypothesis,
            variants=variants,
            control_variant_id=control_variant_id,
            traffic_allocation=traffic_allocation,
            start_at=start_at,
            end_at=end_at,
            metrics_targets=metrics_targets or MetricsTargets(),
            notes=notes,
        )
        await self._experiments.save(experiment)
        return experiment

    async def start(self, experiment_id: str) -> Experiment:
        """DRAFT -> RUNNING (idempotente para RUNNING)."""
        experiment = await self._load(experiment_id)
        experiment.start()
        await self._experiments.save(experiment)
        return experiment

    async def pause(self, experiment_id: str) -> Experiment:
        """RUNNING -> PAUSED (idempotente)."""
        experiment = await self._load(experiment_id)
        experiment.pause()
        await self._experiments.save(experiment)
        return experiment

    async def resume(self, experiment_id: str) -> Experiment:
        """PAUSED -> RUNNING."""
        experiment = await self._load(experiment_id)
        experiment.resume()
        await self._experiments.save(experiment)
        return experiment

    async def conclude(
        self,
        experiment_id: str,
        *,
        winner_variant_id: str | None = None,
    ) -> Experiment:
        """{RUNNING, PAUSED} -> CONCLUDED."""
        experiment = await self._load(experiment_id)
        experiment.conclude(winner_variant_id=winner_variant_id)
        await self._experiments.save(experiment)
        return experiment

    async def promote_winner_to_default(
        self,
        experiment_id: str,
        *,
        winner_variant_id: str,
        outcome: ExperimentOutcome,
    ) -> bool:
        """Promueve los params del variant ganador a default global.

        Returns:
            ``True`` si se promovio (y se escribio en ``settings_writer``).
            ``False`` si los criterios de significancia/lift no se cumplen.

        Raises:
            DomainError: si el experimento no existe, el variant no
                pertenece al experimento, o el outcome no apunta al variant
                indicado.
        """
        experiment = await self._load(experiment_id)
        winner = experiment.variant_by_id(winner_variant_id)
        if winner is None:
            raise DomainError(
                f"winner_variant_id desconocido: {winner_variant_id}",
            )
        if outcome.variant_id != winner_variant_id:
            raise DomainError(
                "outcome.variant_id no coincide con winner_variant_id",
            )
        if winner_variant_id == experiment.control_variant_id:
            # No se "promueve" el control: ya es el default.
            return False
        if not self._meets_promotion_criteria(experiment.metrics_targets, outcome):
            return False
        now = self._clock.now(UTC)
        if self._settings_writer is not None:
            await self._settings_writer.write_defaults(
                experiment_id=experiment.id,
                variant_id=winner.id,
                params=dict(winner.params),
                promoted_at=now,
            )
        experiment.mark_promoted(promoted_at=now, winner_variant_id=winner.id)
        if experiment.status != ExperimentStatus.CONCLUDED:
            experiment.conclude(winner_variant_id=winner.id)
        await self._experiments.save(experiment)
        return True

    @staticmethod
    def _meets_promotion_criteria(
        targets: MetricsTargets,
        outcome: ExperimentOutcome,
    ) -> bool:
        """Aplica los umbrales de p-value y lift configurados en el experimento."""
        if outcome.p_value_vs_control is None:
            return False
        if outcome.lift_vs_control_pct is None:
            return False
        if outcome.p_value_vs_control >= targets.p_value_threshold:
            return False
        return outcome.lift_vs_control_pct >= targets.min_lift_pct

    async def _load(self, experiment_id: str) -> Experiment:
        experiment = await self._experiments.get(experiment_id)
        if experiment is None:
            raise DomainError(f"experiment no encontrado: {experiment_id}")
        return experiment
