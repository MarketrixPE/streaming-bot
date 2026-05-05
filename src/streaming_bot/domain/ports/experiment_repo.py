"""Puerto: repositorio del agregado ``Experiment``.

El dominio define la interfaz; la infraestructura provee la implementacion
(Postgres). El dominio no conoce SQLAlchemy ni ningun cliente concreto.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from streaming_bot.domain.experiments.experiment import Experiment


@runtime_checkable
class IExperimentRepository(Protocol):
    """Persistencia del agregado ``Experiment`` (CRUD basico + listado activos)."""

    async def save(self, experiment: Experiment) -> None:
        """Inserta o actualiza un experimento (upsert por ``id``)."""
        ...

    async def get(self, experiment_id: str) -> Experiment | None:
        """Devuelve el experimento por id, o ``None`` si no existe."""
        ...

    async def list_running(self) -> list[Experiment]:
        """Devuelve los experimentos en estado RUNNING.

        Util para el ``VariantResolver`` y para dashboards de monitoreo.
        """
        ...
