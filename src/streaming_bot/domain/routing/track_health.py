"""Score de salud de un track usado por el geo router.

Inmutable, sin I/O. Construido por ``TrackHealthScorer`` desde history
(StreamHistory + behaviors) o por ``ITrackHealthRepository`` cuando el
snapshot ya esta cacheado en ClickHouse.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class TrackHealthScore:
    """Snapshot de la salud reciente de un track para tier routing.

    Atributos:
    - ``age_days``: edad del track en dias desde release.
    - ``plays_30d``: streams contados (>=30s) en los ultimos 30 dias.
    - ``save_rate``: ratio saves / plays_30d (0..1).
    - ``skip_rate``: ratio skips / total_intentos en 30d (0..1).
    - ``saturation_score``: maximo ratio
      ``streams_24h_geo / max_safe_24h_geo`` considerando todos los
      paises donde el track esta activo. Permite detectar saturacion
      en una geo concreta y rotar al siguiente tier menos saturado.
    - ``computed_at``: instante en que se calculo el snapshot.
    """

    age_days: int
    plays_30d: int
    save_rate: float
    skip_rate: float
    saturation_score: float
    computed_at: datetime

    def __post_init__(self) -> None:
        if self.age_days < 0:
            raise ValueError(f"age_days debe ser >=0: {self.age_days}")
        if self.plays_30d < 0:
            raise ValueError(f"plays_30d debe ser >=0: {self.plays_30d}")
        if not 0.0 <= self.save_rate <= 1.0:
            raise ValueError(f"save_rate fuera de rango: {self.save_rate}")
        if not 0.0 <= self.skip_rate <= 1.0:
            raise ValueError(f"skip_rate fuera de rango: {self.skip_rate}")
        if self.saturation_score < 0.0:
            raise ValueError(f"saturation_score negativo: {self.saturation_score}")
