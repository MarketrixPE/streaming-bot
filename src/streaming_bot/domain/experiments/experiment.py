"""Agregado raiz ``Experiment``.

El experimento define hipotesis, variantes candidatas, ventana temporal y
``traffic_allocation`` (porcentaje del catalogo elegible que entra en el
experimento). El resto del catalogo recibe la rama de control de forma
incondicional. Las transiciones de estado son explicitas y validan que solo
flujen DRAFT -> RUNNING -> {PAUSED, CONCLUDED} y RUNNING <-> PAUSED.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from streaming_bot.domain.exceptions import DomainError
from streaming_bot.domain.experiments.variant import Variant


class ExperimentStatus(str, Enum):
    """Ciclo de vida del experimento."""

    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    CONCLUDED = "concluded"


@dataclass(frozen=True, slots=True)
class MetricsTargets:
    """Umbrales objetivo para declarar exito del experimento.

    Attributes:
        min_success_rate: piso de ``success_rate`` aceptable por variante.
        max_ban_rate: techo de ``ban_rate`` tolerable por variante.
        max_cost_per_stream: techo de costo USD por stream.
        min_lift_pct: lift minimo vs control para promover ganadora (en %).
        p_value_threshold: umbral de significancia estadistica (default 0.05).
    """

    min_success_rate: float = 0.0
    max_ban_rate: float = 1.0
    max_cost_per_stream: float = float("inf")
    min_lift_pct: float = 5.0
    p_value_threshold: float = 0.05

    def __post_init__(self) -> None:
        if not 0.0 <= self.min_success_rate <= 1.0:
            raise ValueError(f"min_success_rate fuera de rango: {self.min_success_rate}")
        if not 0.0 <= self.max_ban_rate <= 1.0:
            raise ValueError(f"max_ban_rate fuera de rango: {self.max_ban_rate}")
        if self.max_cost_per_stream < 0:
            raise ValueError(f"max_cost_per_stream negativo: {self.max_cost_per_stream}")
        if not 0.0 <= self.p_value_threshold <= 1.0:
            raise ValueError(f"p_value_threshold fuera de rango: {self.p_value_threshold}")


@dataclass(slots=True)
class Experiment:
    """Agregado raiz de un experimento A/B.

    Mutable controladamente: solo los metodos ``start``, ``pause`` y
    ``conclude`` cambian ``status``. Las variantes y el control son
    inmutables tras la creacion.
    """

    id: str
    name: str
    hypothesis: str
    variants: tuple[Variant, ...]
    control_variant_id: str
    traffic_allocation: float
    start_at: datetime
    metrics_targets: MetricsTargets
    end_at: datetime | None = None
    status: ExperimentStatus = ExperimentStatus.DRAFT
    winner_variant_id: str | None = None
    promoted_at: datetime | None = None
    notes: str = field(default="")

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("experiment.id requerido")
        if not self.name:
            raise ValueError("experiment.name requerido")
        if len(self.variants) < 2:
            raise ValueError(
                f"experiment requiere >= 2 variantes (incluido control), got {len(self.variants)}",
            )
        ids = [v.id for v in self.variants]
        if len(set(ids)) != len(ids):
            raise ValueError(f"variant ids duplicados: {ids}")
        if self.control_variant_id not in ids:
            raise ValueError(
                f"control_variant_id={self.control_variant_id} no esta en variants",
            )
        if not 0.0 < self.traffic_allocation <= 1.0:
            raise ValueError(
                f"traffic_allocation fuera de rango (0,1]: {self.traffic_allocation}",
            )
        if self.start_at.tzinfo is None:
            raise ValueError("start_at debe ser timezone-aware")
        if self.end_at is not None:
            if self.end_at.tzinfo is None:
                raise ValueError("end_at debe ser timezone-aware")
            if self.end_at <= self.start_at:
                raise ValueError("end_at debe ser posterior a start_at")

    @property
    def control(self) -> Variant:
        """Devuelve la variante de control."""
        for variant in self.variants:
            if variant.id == self.control_variant_id:
                return variant
        # Validado en __post_init__; jamas deberia ocurrir.
        raise DomainError(f"control_variant_id no encontrado: {self.control_variant_id}")

    @property
    def treatment_variants(self) -> tuple[Variant, ...]:
        """Variantes distintas al control."""
        return tuple(v for v in self.variants if v.id != self.control_variant_id)

    def variant_by_id(self, variant_id: str) -> Variant | None:
        """Lookup defensivo; ``None`` si el id no existe."""
        for variant in self.variants:
            if variant.id == variant_id:
                return variant
        return None

    def total_weight(self) -> int:
        """Suma de ``allocation_weight`` de todas las variantes."""
        return sum(v.allocation_weight for v in self.variants)

    # ---------------------------- transiciones ----------------------------- #

    def start(self) -> None:
        """DRAFT -> RUNNING. Idempotente para RUNNING."""
        if self.status == ExperimentStatus.RUNNING:
            return
        if self.status != ExperimentStatus.DRAFT:
            raise DomainError(
                f"transicion invalida: solo DRAFT puede pasar a RUNNING (actual={self.status})",
            )
        self.status = ExperimentStatus.RUNNING

    def pause(self) -> None:
        """RUNNING -> PAUSED. Idempotente para PAUSED."""
        if self.status == ExperimentStatus.PAUSED:
            return
        if self.status != ExperimentStatus.RUNNING:
            raise DomainError(
                f"transicion invalida: solo RUNNING puede pasar a PAUSED (actual={self.status})",
            )
        self.status = ExperimentStatus.PAUSED

    def resume(self) -> None:
        """PAUSED -> RUNNING."""
        if self.status == ExperimentStatus.RUNNING:
            return
        if self.status != ExperimentStatus.PAUSED:
            raise DomainError(
                f"transicion invalida: solo PAUSED puede pasar a RUNNING (actual={self.status})",
            )
        self.status = ExperimentStatus.RUNNING

    def conclude(self, *, winner_variant_id: str | None = None) -> None:
        """{RUNNING, PAUSED} -> CONCLUDED. Permite registrar el ganador."""
        if self.status == ExperimentStatus.CONCLUDED:
            return
        if self.status not in {ExperimentStatus.RUNNING, ExperimentStatus.PAUSED}:
            raise DomainError(
                f"transicion invalida: solo RUNNING/PAUSED concluyen (actual={self.status})",
            )
        if winner_variant_id is not None and self.variant_by_id(winner_variant_id) is None:
            raise DomainError(f"winner_variant_id desconocido: {winner_variant_id}")
        self.status = ExperimentStatus.CONCLUDED
        self.winner_variant_id = winner_variant_id

    def mark_promoted(self, *, promoted_at: datetime, winner_variant_id: str) -> None:
        """Anota que el ganador fue promovido a default global."""
        if winner_variant_id and self.variant_by_id(winner_variant_id) is None:
            raise DomainError(f"winner_variant_id desconocido: {winner_variant_id}")
        if promoted_at.tzinfo is None:
            raise ValueError("promoted_at debe ser timezone-aware")
        self.winner_variant_id = winner_variant_id
        self.promoted_at = promoted_at
