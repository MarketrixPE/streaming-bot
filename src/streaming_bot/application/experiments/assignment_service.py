"""Asignacion deterministica y sticky de variantes.

Algoritmo:
1. Lookup en repositorio: si existe ``VariantAssignment`` para
   ``(account_id, experiment_id)``, se devuelve sin recalcular.
2. Si no existe:
   a. Hash SHA-256 de ``account_id + ":" + experiment_id + ":" + salt``.
   b. Reduccion a ``uint64`` y ``mod sum(allocation_weight)``.
   c. Eleccion ponderada determinada por el bucket resultante.
   d. Si la cuenta cae fuera del ``traffic_allocation``, se asigna control.
   e. Persistencia atomica via ``add`` para mantener stickyness entre runs.

Diseno SOLID:
- ``ExperimentAssignmentService`` depende de ``IExperimentRepository`` y
  ``IVariantAssignmentRepository`` (no de implementaciones concretas).
- La logica de hashing es pura y testable sin I/O.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from streaming_bot.domain.exceptions import DomainError
from streaming_bot.domain.experiments.assignment import VariantAssignment
from streaming_bot.domain.experiments.experiment import Experiment
from streaming_bot.domain.ports.experiment_repo import IExperimentRepository
from streaming_bot.domain.ports.variant_assignment_repo import IVariantAssignmentRepository

# Salt fijo del proyecto. Cambiarlo invalida todas las asignaciones existentes;
# si se necesita rotar, debe acompanarse de una migracion que limpie sticky.
DEFAULT_ASSIGNMENT_SALT = "streaming-bot-experiments-v1"


def _hash_to_bucket(account_id: str, experiment_id: str, salt: str) -> int:
    """SHA-256 (account_id|experiment_id|salt) -> ``uint64`` para mod.

    Trazable, deterministico y libre de bias para ``account_id`` razonables
    (los primeros 8 bytes del digest son uniformes para casi todo input).
    """
    payload = f"{account_id}:{experiment_id}:{salt}".encode()
    digest = hashlib.sha256(payload).digest()
    # Primeros 8 bytes -> uint64. Cubre 2^64 buckets >> cualquier total_weight.
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


def _is_in_experiment_traffic(
    account_id: str,
    experiment: Experiment,
    salt: str,
) -> bool:
    """Decide si la cuenta entra en el experimento segun ``traffic_allocation``.

    Usa un segundo hash (con sufijo distinto) para que la decision de
    inclusion sea independiente de la decision de variante. Esto evita
    correlaciones si en el futuro se anaden mas experimentos.
    """
    inclusion_seed = _hash_to_bucket(account_id, experiment.id + ":traffic", salt)
    # Reduccion a [0, 1) con resolucion 10^9 (suficiente para porcentajes).
    bucket = (inclusion_seed % 1_000_000_000) / 1_000_000_000
    return bucket < experiment.traffic_allocation


def _pick_variant_id(experiment: Experiment, account_id: str, salt: str) -> str:
    """Elige variant_id ponderado por ``allocation_weight``.

    Recorrido determinista en el orden de ``experiment.variants`` para que el
    resultado dependa solo del hash y los pesos, no del orden de iteracion
    arbitrario de un dict.
    """
    total = experiment.total_weight()
    if total <= 0:
        # Validado en Variant.__post_init__; defensivo para mypy.
        raise DomainError(f"experiment {experiment.id} sin pesos validos")
    bucket = _hash_to_bucket(account_id, experiment.id, salt) % total
    cursor = 0
    for variant in experiment.variants:
        cursor += variant.allocation_weight
        if bucket < cursor:
            return variant.id
    # Inalcanzable: cursor termina igual a total y bucket < total.
    raise DomainError(f"hashing inconsistente para experiment {experiment.id}")


class ExperimentAssignmentService:
    """Devuelve la variante asignada (sticky) para una ``(cuenta, experimento)``.

    No hace difusion masiva ni asignacion proactiva: trabaja por demanda,
    on the fly cuando un caller pregunta. Esto mantiene el sistema simple y
    permite que el ``VariantResolver`` opere sin precomputar nada.
    """

    def __init__(
        self,
        experiments: IExperimentRepository,
        assignments: IVariantAssignmentRepository,
        *,
        salt: str = DEFAULT_ASSIGNMENT_SALT,
        clock: type[datetime] = datetime,
    ) -> None:
        self._experiments = experiments
        self._assignments = assignments
        self._salt = salt
        self._clock = clock

    async def get_or_assign(
        self,
        account_id: str,
        experiment_id: str,
    ) -> VariantAssignment:
        """Devuelve la asignacion existente o crea una nueva sticky.

        Args:
            account_id: cuenta para la que se solicita variante.
            experiment_id: experimento del que se solicita variante.

        Returns:
            ``VariantAssignment`` persistida (existente o recien creada).

        Raises:
            DomainError: si el experimento no existe o no esta corriendo.
        """
        existing = await self._assignments.get(account_id, experiment_id)
        if existing is not None:
            return existing

        experiment = await self._experiments.get(experiment_id)
        if experiment is None:
            raise DomainError(f"experiment no encontrado: {experiment_id}")

        # Cuentas fuera del traffic_allocation reciben control de forma
        # incondicional para no contaminar el grupo de tratamiento con
        # sub-cuotas mal calibradas.
        if not _is_in_experiment_traffic(account_id, experiment, self._salt):
            variant_id = experiment.control_variant_id
        else:
            variant_id = _pick_variant_id(experiment, account_id, self._salt)

        now = self._clock.now(UTC)
        assignment = VariantAssignment(
            account_id=account_id,
            experiment_id=experiment_id,
            variant_id=variant_id,
            assigned_at=now,
        )
        await self._assignments.add(assignment)
        return assignment
