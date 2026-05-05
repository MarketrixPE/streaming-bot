"""Outcome agregado por variante (resultado de la analisis estadistica).

El ``ExperimentAnalyzer`` produce un ``ExperimentOutcome`` por cada variante
del experimento. ``p_value_vs_control`` y ``lift_vs_control_pct`` son ``None``
para la propia variante de control (no tiene sentido compararla consigo misma).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExperimentOutcome:
    """Metricas agregadas para una variante en una ventana de medicion.

    Attributes:
        variant_id: id del ``Variant`` al que pertenecen las metricas.
        samples: numero de streams (o eventos atomicos) observados.
        success_rate: proporcion de exitos en [0, 1].
        ban_rate: proporcion de bans/strikes en [0, 1].
        cost_per_stream: costo medio asignable por stream (en USD).
        p_value_vs_control: p-value de la prueba chi-cuadrado vs control.
            ``None`` si la variante ES el control o no hay datos suficientes.
        lift_vs_control_pct: variacion porcentual de ``success_rate`` vs control.
            ``None`` si la variante ES el control.
    """

    variant_id: str
    samples: int
    success_rate: float
    ban_rate: float
    cost_per_stream: float
    p_value_vs_control: float | None
    lift_vs_control_pct: float | None

    def __post_init__(self) -> None:
        if self.samples < 0:
            raise ValueError(f"samples no puede ser negativo: {self.samples}")
        if not 0.0 <= self.success_rate <= 1.0:
            raise ValueError(f"success_rate fuera de rango [0,1]: {self.success_rate}")
        if not 0.0 <= self.ban_rate <= 1.0:
            raise ValueError(f"ban_rate fuera de rango [0,1]: {self.ban_rate}")
        if self.cost_per_stream < 0:
            raise ValueError(f"cost_per_stream negativo: {self.cost_per_stream}")
        if self.p_value_vs_control is not None and not 0.0 <= self.p_value_vs_control <= 1.0:
            raise ValueError(
                f"p_value_vs_control fuera de rango [0,1]: {self.p_value_vs_control}",
            )

    @property
    def is_significant(self) -> bool:
        """Atajo: significativa al 5% (clinicalmente convencional)."""
        return self.p_value_vs_control is not None and self.p_value_vs_control < 0.05
