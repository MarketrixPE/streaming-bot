"""Asignacion sticky de variante a cuenta.

Una vez calculado el variant para ``(account_id, experiment_id)``, se persiste
para que cualquier ejecucion futura respete la misma decision (sticky).
Esto evita contaminar resultados con cuentas que cambian de variante.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class VariantAssignment:
    """Persistencia de la decision de asignacion para una (cuenta, experimento).

    Attributes:
        account_id: cuenta a la que se asigna el variant.
        experiment_id: experimento del que se asigna.
        variant_id: id del ``Variant`` elegido por el ``ExperimentAssignmentService``.
        assigned_at: timestamp UTC de la primera asignacion (inmutable).
    """

    account_id: str
    experiment_id: str
    variant_id: str
    assigned_at: datetime

    def __post_init__(self) -> None:
        if not self.account_id:
            raise ValueError("VariantAssignment.account_id requerido")
        if not self.experiment_id:
            raise ValueError("VariantAssignment.experiment_id requerido")
        if not self.variant_id:
            raise ValueError("VariantAssignment.variant_id requerido")
        if self.assigned_at.tzinfo is None:
            raise ValueError("VariantAssignment.assigned_at debe ser timezone-aware")
