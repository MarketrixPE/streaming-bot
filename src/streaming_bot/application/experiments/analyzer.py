"""Analizador de experimentos: outcomes por variante + significancia chi-square.

Diseno:
- Lee metricas crudas (samples, successes, bans, total_cost) por variante via
  un puerto ``IExperimentEventsReader``. La implementacion real consulta
  ClickHouse (``events.stream_events``) con httpx; los tests inyectan un fake.
- Calcula ``success_rate``, ``ban_rate``, ``cost_per_stream`` y compara cada
  variante contra el control via test chi-cuadrado de 2x2 (success/fail).
- ``p_value`` para df=1 se obtiene de la funcion de supervivencia
  ``erfc(sqrt(chi2/2))`` (sin scipy: solo ``math``).
- Yates correction (continuity correction) para muestras chicas.

No persiste outcomes: solo los devuelve. La capa que los consume
(``ExperimentService.promote_winner_to_default``) decide que hacer.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from streaming_bot.domain.exceptions import DomainError
from streaming_bot.domain.experiments.outcome import ExperimentOutcome
from streaming_bot.domain.ports.experiment_repo import IExperimentRepository


@dataclass(frozen=True, slots=True)
class RawVariantMetrics:
    """Metricas crudas agregadas para una variante en la ventana del experimento.

    Attributes:
        variant_id: id del ``Variant`` al que pertenecen.
        samples: total de streams observados.
        successes: streams marcados ``outcome=success`` en ClickHouse.
        bans: streams marcados como ``ban``/``strike``.
        total_cost_usd: suma del costo asignable (proxy + captcha + infra).
    """

    variant_id: str
    samples: int
    successes: int
    bans: int
    total_cost_usd: float

    def __post_init__(self) -> None:
        if self.samples < 0:
            raise ValueError(f"samples negativo: {self.samples}")
        if self.successes < 0 or self.successes > self.samples:
            raise ValueError(
                f"successes={self.successes} fuera de [0, samples={self.samples}]",
            )
        if self.bans < 0 or self.bans > self.samples:
            raise ValueError(
                f"bans={self.bans} fuera de [0, samples={self.samples}]",
            )
        if self.total_cost_usd < 0:
            raise ValueError(f"total_cost_usd negativo: {self.total_cost_usd}")


@runtime_checkable
class IExperimentEventsReader(Protocol):
    """Lee metricas crudas por variante desde el almacen de eventos (ClickHouse).

    La implementacion real construye una query agregada del estilo:

        SELECT variant_id,
               count() AS samples,
               countIf(outcome = 'success') AS successes,
               countIf(outcome = 'ban') AS bans,
               sum(cost_usd) AS total_cost_usd
        FROM events.stream_events
        WHERE experiment_id = {experiment_id}
          AND variant_id IN {variant_ids}
        GROUP BY variant_id

    y la pega via httpx contra el HTTP interface de ClickHouse.
    """

    async def fetch_outcomes(
        self,
        experiment_id: str,
        variant_ids: Sequence[str],
    ) -> dict[str, RawVariantMetrics]: ...


class ExperimentAnalyzer:
    """Calcula ``ExperimentOutcome`` por variante con significancia vs control."""

    def __init__(
        self,
        experiments: IExperimentRepository,
        events: IExperimentEventsReader,
    ) -> None:
        self._experiments = experiments
        self._events = events

    async def analyze(self, experiment_id: str) -> list[ExperimentOutcome]:
        """Devuelve un ``ExperimentOutcome`` por variante del experimento.

        El control se devuelve con ``p_value_vs_control = lift_vs_control_pct = None``.
        """
        experiment = await self._experiments.get(experiment_id)
        if experiment is None:
            raise DomainError(f"experiment no encontrado: {experiment_id}")

        variant_ids = [v.id for v in experiment.variants]
        raw_by_variant = await self._events.fetch_outcomes(experiment_id, variant_ids)

        control_id = experiment.control_variant_id
        control_raw = raw_by_variant.get(control_id) or _empty_raw(control_id)

        outcomes: list[ExperimentOutcome] = []
        for variant in experiment.variants:
            raw = raw_by_variant.get(variant.id) or _empty_raw(variant.id)
            success_rate = _safe_div(raw.successes, raw.samples)
            ban_rate = _safe_div(raw.bans, raw.samples)
            cost_per_stream = _safe_div_float(raw.total_cost_usd, raw.samples)
            if variant.id == control_id:
                p_value = None
                lift_pct = None
            else:
                p_value = _chi_square_p_value(
                    variant_successes=raw.successes,
                    variant_failures=raw.samples - raw.successes,
                    control_successes=control_raw.successes,
                    control_failures=control_raw.samples - control_raw.successes,
                )
                control_rate = _safe_div(control_raw.successes, control_raw.samples)
                lift_pct = _lift_pct(success_rate, control_rate)
            outcomes.append(
                ExperimentOutcome(
                    variant_id=variant.id,
                    samples=raw.samples,
                    success_rate=success_rate,
                    ban_rate=ban_rate,
                    cost_per_stream=cost_per_stream,
                    p_value_vs_control=p_value,
                    lift_vs_control_pct=lift_pct,
                ),
            )
        return outcomes


def _empty_raw(variant_id: str) -> RawVariantMetrics:
    """Variante sin datos: cero en todo. Permite outcomes con muestras=0."""
    return RawVariantMetrics(
        variant_id=variant_id,
        samples=0,
        successes=0,
        bans=0,
        total_cost_usd=0.0,
    )


def _safe_div(numerator: int, denominator: int) -> float:
    """Division segura: 0/0 -> 0.0 para no propagar NaN."""
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _safe_div_float(numerator: float, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _lift_pct(variant_rate: float, control_rate: float) -> float | None:
    """Lift porcentual de la variante vs control.

    Si el control tiene tasa 0, no se puede expresar lift relativo.
    """
    if control_rate <= 0:
        return None
    return ((variant_rate - control_rate) / control_rate) * 100.0


def _chi_square_p_value(
    *,
    variant_successes: int,
    variant_failures: int,
    control_successes: int,
    control_failures: int,
) -> float | None:
    """Test chi-cuadrado 2x2 con correccion de Yates; df=1.

    Devuelve ``None`` si la tabla esta degenerada (alguna marginal en cero):
    no se puede testear sin variabilidad observable en alguna direccion.

    p-value = ``erfc(sqrt(chi2 / 2))`` (funcion de supervivencia para df=1).
    """
    n11 = variant_successes
    n12 = variant_failures
    n21 = control_successes
    n22 = control_failures
    row1 = n11 + n12
    row2 = n21 + n22
    col1 = n11 + n21
    col2 = n12 + n22
    total = row1 + row2
    if row1 == 0 or row2 == 0 or col1 == 0 or col2 == 0 or total == 0:
        return None
    # Estadistico chi-cuadrado de Pearson para tabla 2x2 con correccion de Yates.
    numerator = total * (abs(n11 * n22 - n12 * n21) - total / 2.0) ** 2
    denominator = row1 * row2 * col1 * col2
    if denominator == 0:
        return None
    chi2 = numerator / denominator
    if chi2 < 0:
        chi2 = 0.0
    return math.erfc(math.sqrt(chi2 / 2.0))
