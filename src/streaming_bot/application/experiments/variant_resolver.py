"""Helper de lectura: traduce ``key`` a ``params[key]`` del variant activo.

Caso de uso: el ``HumanBehaviorEngine`` quiere saber el ``hover_dwell_ms``
para una cuenta. Llama:

    value = await resolver.params_for(account_id, "behavior_engine.hover_dwell_ms",
                                       default=250)

El resolver:
1. Lista los experimentos en RUNNING.
2. Encuentra el primero (por orden estable) cuya tupla de variantes contenga
   la ``key`` en sus ``params``.
3. Resuelve la asignacion sticky de la cuenta para ese experimento.
4. Devuelve el valor del param en el variant asignado, o el ``default`` si la
   variante no expone esa key (puede ocurrir si solo el grupo de tratamiento
   define el override y la cuenta cayo en control).
"""

from __future__ import annotations

from typing import TypeVar, cast

from streaming_bot.application.experiments.assignment_service import (
    ExperimentAssignmentService,
)
from streaming_bot.domain.exceptions import DomainError
from streaming_bot.domain.experiments.experiment import Experiment
from streaming_bot.domain.ports.experiment_repo import IExperimentRepository

T = TypeVar("T")


class VariantResolver:
    """Resolutor de params especifico por (cuenta, key).

    No cachea entre llamadas: cada ``params_for`` hace ``list_running``. Si
    eso pesa demasiado en caliente, anadir un cache TTL en infra (no aqui).
    """

    def __init__(
        self,
        assignment_service: ExperimentAssignmentService,
        experiments: IExperimentRepository,
    ) -> None:
        self._assignment_service = assignment_service
        self._experiments = experiments

    async def params_for(
        self,
        account_id: str,
        key: str,
        default: T,
    ) -> T:
        """Resuelve ``key`` contra los experimentos activos.

        Args:
            account_id: cuenta para la que resolver el param.
            key: clave del param (ej. ``"behavior_engine.hover_dwell_ms"``).
            default: valor a devolver si ningun experimento define ``key``
                o la variante asignada no la sobrescribe.

        Returns:
            El valor cast a ``T`` (responsabilidad del caller que coincida).
        """
        if not key:
            raise DomainError("key vacia no es resoluble")
        running = await self._experiments.list_running()
        owner = _find_owner_experiment(running, key)
        if owner is None:
            return default
        assignment = await self._assignment_service.get_or_assign(account_id, owner.id)
        variant = owner.variant_by_id(assignment.variant_id)
        if variant is None or key not in variant.params:
            return default
        return cast(T, variant.params[key])


def _find_owner_experiment(
    experiments: list[Experiment],
    key: str,
) -> Experiment | None:
    """Devuelve el primer experimento cuya tupla de variantes contenga ``key``.

    Iteracion en el orden devuelto por ``list_running`` para que el resolutor
    sea determinista. Si dos experimentos compiten por la misma key, gana el
    que se registro primero (responsabilidad del operador no solaparlos).
    """
    for experiment in experiments:
        if any(key in variant.params for variant in experiment.variants):
            return experiment
    return None
