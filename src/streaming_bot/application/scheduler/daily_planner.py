"""Planificador diario: convierte el catalogo en targets por cancion.

Aplica ``RampUpPolicy`` por tier para calcular streams diarios objetivo,
restringe por ``safe_ceiling_today`` (max +50% sobre baseline) y por
``TerritoryPlan`` (paises permitidos en la fase actual).

Excluye:
- Canciones FLAGGED.
- Canciones con ``spike_oct2025_flag=True``.
- HOT/RISING (protegidas, no se boostean).
- Inactivas o no TARGET.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING

from streaming_bot.domain.ramp_up import RampUpPolicy, TierRampUp
from streaming_bot.domain.song import Song, SongTier
from streaming_bot.domain.territory import TerritoryPlan

if TYPE_CHECKING:
    from structlog.stdlib import BoundLogger

    from streaming_bot.domain.value_objects import Country


@dataclass(frozen=True, slots=True)
class SongDailyTarget:
    """Objetivo diario calculado para una cancion target.

    ``allowed_countries`` proviene del ``TerritoryDistribution`` activo
    en la fecha del plan; los workers solo deben asignar streams a
    cuentas en esos paises.
    """

    song_id: str
    streams_target: int
    allowed_countries: frozenset[Country]
    days_since_start: int


class DailyPlanner:
    """Calcula targets diarios por cancion respetando tier y techo seguro."""

    def __init__(
        self,
        *,
        program_start: date,
        tier_policy: TierRampUp,
        logger: BoundLogger,
    ) -> None:
        self._program_start = program_start
        self._tier_policy = tier_policy
        self._log = logger.bind(component="daily_planner")

    def plan_for_today(
        self,
        songs: list[Song],
        date: datetime,
    ) -> list[SongDailyTarget]:
        """Genera el plan diario para la fecha dada.

        Args:
            songs: catalogo completo (la planner filtra elegibilidad).
            date: instante del dia objetivo (se usa solo la parte ``date()``).

        Returns:
            Lista de ``SongDailyTarget``; vacia si ninguna cancion aplica.
        """
        today = date.date()
        days_since_start = max((today - self._program_start).days, 0)
        territory = TerritoryPlan.for_date(today, self._program_start)
        allowed: frozenset[Country] = frozenset(w.country for w in territory.weights)

        plan: list[SongDailyTarget] = []
        excluded = 0
        for song in songs:
            if not self._is_eligible(song):
                excluded += 1
                continue
            policy = self._policy_for(song.tier)
            if policy is None:
                excluded += 1
                continue

            raw_target = policy.streams_per_song_for_date(today, self._program_start)
            ceiling = song.safe_ceiling_today()
            streams_target = max(0, min(raw_target, ceiling))
            if streams_target <= 0:
                continue

            plan.append(
                SongDailyTarget(
                    song_id=song.spotify_uri,
                    streams_target=streams_target,
                    allowed_countries=allowed,
                    days_since_start=days_since_start,
                )
            )

        self._log.info(
            "daily_plan.built",
            songs_planned=len(plan),
            songs_excluded=excluded,
            phase=territory.label,
            days_since_start=days_since_start,
        )
        return plan

    def _is_eligible(self, song: Song) -> bool:
        """Politica unica de elegibilidad delegada al dominio."""
        return song.is_pilot_eligible

    def _policy_for(self, tier: SongTier) -> RampUpPolicy | None:
        """Devuelve la politica del tier o ``None`` si no aplica boost."""
        if tier == SongTier.ZOMBIE:
            return self._tier_policy.zombie
        if tier == SongTier.LOW:
            return self._tier_policy.low
        if tier == SongTier.MID:
            return self._tier_policy.mid
        return None
