"""Puerto: repositorio de asignaciones sticky de variante por cuenta.

La asignacion calculada en runtime (deterministica via hashing) se persiste
para garantizar que la misma cuenta caiga siempre en la misma variante,
incluso entre redespliegues. La logica de hashing vive en el servicio de
aplicacion, no en el repositorio.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from streaming_bot.domain.experiments.assignment import VariantAssignment


@runtime_checkable
class IVariantAssignmentRepository(Protocol):
    """Persistencia de ``VariantAssignment``.

    Convencion:
    - ``get``: lookup ``(account_id, experiment_id)``; ``None`` si no existe.
    - ``add``: inserta una asignacion nueva. Falla si ya existe (sticky).
    - ``list_for_account``: todas las asignaciones de una cuenta (para
      diagnosticos / dashboards / debugging).
    """

    async def get(
        self,
        account_id: str,
        experiment_id: str,
    ) -> VariantAssignment | None: ...

    async def add(self, assignment: VariantAssignment) -> None: ...

    async def list_for_account(self, account_id: str) -> list[VariantAssignment]: ...
