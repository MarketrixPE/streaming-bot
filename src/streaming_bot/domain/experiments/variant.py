"""Variante de un experimento A/B.

Cada ``Variant`` es una receta concreta de parametros (mouse profile,
hover dwell, save_rate, etc.) con un peso de asignacion. El servicio de
asignacion usa ``allocation_weight`` como ponderacion para distribuir
trafico entre variantes via hashing deterministico.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Variant:
    """Variante candidata dentro de un experimento.

    Attributes:
        id: identificador estable (UUID o slug). Inmutable.
        name: nombre legible para dashboards/logs.
        params: diccionario de parametros que sustituyen los defaults del
            sistema cuando esta variante esta activa para una cuenta.
        allocation_weight: peso entero >0 usado para reparto proporcional.
            Ej. control=70, tratamiento_a=15, tratamiento_b=15.
    """

    id: str
    name: str
    params: dict[str, Any]
    allocation_weight: int

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("variant.id no puede ser vacio")
        if not self.name:
            raise ValueError("variant.name no puede ser vacio")
        if self.allocation_weight <= 0:
            raise ValueError(
                f"variant.allocation_weight debe ser > 0, got {self.allocation_weight}",
            )
