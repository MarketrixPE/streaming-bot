"""Politica de ramp-up: curva temporal de volumen para evitar spikes detectables.

Diseno post-Oct'25:
- Crecimiento sigmoide suave en lugar de lineal o exponencial.
- Jitter diario (±15%) para evitar patrones identificables.
- Cap por dia por cancion segun tier (zombies/low/mid).
- Pause automatica los domingos (drop natural en consumo musical).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class RampUpPolicy:
    """Curva sigmoide de ramp-up con jitter.

    Streams diarios objetivo en el dia `d`:
      target(d) = floor + (ceiling - floor) * sigmoid((d - midpoint) / steepness)

    `floor` representa el volumen inicial (dia 0), `ceiling` el volumen
    estable post-ramp, y `midpoint` el dia donde se alcanza el 50% del rango.
    """

    floor_per_song_per_day: int = 8  # dia 0
    ceiling_per_song_per_day: int = 80  # estado estable post-ramp
    midpoint_day: int = 30  # 50% en dia 30
    steepness: float = 8.0  # cuanto mas grande, mas suave
    daily_jitter_pct: float = 0.15  # ±15% aleatorio
    sunday_attenuation: float = 0.55  # domingo cae al 55%
    saturday_attenuation: float = 0.78  # sabado cae al 78%

    def streams_per_song_for_day(self, day_offset: int, *, weekday: int) -> int:
        """Calcula streams objetivo por cancion en el dia.

        weekday: 0=Lunes, 6=Domingo (segun datetime.date.weekday()).
        """
        if day_offset < 0:
            return 0
        sigmoid = 1.0 / (1.0 + math.exp(-(day_offset - self.midpoint_day) / self.steepness))
        base = (
            self.floor_per_song_per_day
            + (self.ceiling_per_song_per_day - self.floor_per_song_per_day) * sigmoid
        )

        # Atenuacion por dia de semana (curva organica)
        if weekday == 6:
            base *= self.sunday_attenuation
        elif weekday == 5:
            base *= self.saturday_attenuation

        jitter = random.uniform(-self.daily_jitter_pct, self.daily_jitter_pct)  # noqa: S311
        return max(0, round(base * (1.0 + jitter)))

    def streams_per_song_for_date(
        self,
        today: date,
        program_start: date,
    ) -> int:
        return self.streams_per_song_for_day(
            day_offset=(today - program_start).days,
            weekday=today.weekday(),
        )


@dataclass(frozen=True, slots=True)
class TierRampUp:
    """Politicas de ramp-up diferenciadas por tier de cancion.

    Las HOT/RISING NO se boostean (politica fuera del piloto).
    """

    zombie: RampUpPolicy
    low: RampUpPolicy
    mid: RampUpPolicy

    @classmethod
    def conservative_pilot(cls) -> TierRampUp:
        """Configuracion conservadora para el piloto post-flag."""
        return cls(
            # Zombies: 0 streams hoy, partir de cero. Pueden ramp-up agresivo
            # porque cualquier crecimiento es detectable como organico.
            zombie=RampUpPolicy(
                floor_per_song_per_day=5,
                ceiling_per_song_per_day=40,
                midpoint_day=21,
                steepness=6.0,
            ),
            # Low: tienen baseline. Crecimiento moderado.
            low=RampUpPolicy(
                floor_per_song_per_day=10,
                ceiling_per_song_per_day=60,
                midpoint_day=30,
                steepness=8.0,
            ),
            # Mid: ya tienen volumen. Crecimiento muy suave para no
            # disparar alertas (por la huella de Oct).
            mid=RampUpPolicy(
                floor_per_song_per_day=15,
                ceiling_per_song_per_day=80,
                midpoint_day=45,
                steepness=10.0,
            ),
        )

    @classmethod
    def aggressive_post_pilot(cls) -> TierRampUp:
        """Configuracion mas agresiva tras 60 dias de piloto limpio."""
        return cls(
            zombie=RampUpPolicy(
                floor_per_song_per_day=30,
                ceiling_per_song_per_day=120,
                midpoint_day=15,
                steepness=5.0,
            ),
            low=RampUpPolicy(
                floor_per_song_per_day=50,
                ceiling_per_song_per_day=180,
                midpoint_day=20,
                steepness=6.0,
            ),
            mid=RampUpPolicy(
                floor_per_song_per_day=80,
                ceiling_per_song_per_day=200,
                midpoint_day=25,
                steepness=7.0,
            ),
        )
