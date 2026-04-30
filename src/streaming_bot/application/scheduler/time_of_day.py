"""Distribuye streams del plan diario sobre cuentas/horas locales.

Cada job nace con ``scheduled_at_utc`` derivado de la franja horaria
preferida de la persona, mas un jitter de ``±N`` minutos. Antes de
materializar el job se aplica ``apply_target_jitter`` al volumen y
``apply_time_jitter`` al instante.

Anti-spike:
- Tope rigido de ``max_per_account_per_hour`` jobs por cuenta y hora UTC.
- Si una hora esta llena, busca la siguiente disponible dentro del
  bucket de horas activas locales de la persona; si todas estan llenas
  el job se descarta y se loguea.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from streaming_bot.application.scheduler.jitter import (
    apply_target_jitter,
    apply_time_jitter,
)

if TYPE_CHECKING:
    from structlog.stdlib import BoundLogger

    from streaming_bot.application.scheduler.daily_planner import SongDailyTarget
    from streaming_bot.domain.entities import Account
    from streaming_bot.domain.persona import Persona
    from streaming_bot.domain.value_objects import Country


@dataclass(frozen=True, slots=True)
class ScheduledJob:
    """Unidad atomica que el ``SchedulerWorker`` consume."""

    account_id: str
    song_id: str
    scheduled_at_utc: datetime
    country: Country
    job_id: str = field(default_factory=lambda: str(uuid4()))


class TimeOfDayDistributor:
    """Reparte streams del plan en jobs concretos por cuenta/hora."""

    def __init__(
        self,
        *,
        logger: BoundLogger,
        max_per_account_per_hour: int = 3,
        time_jitter_minutes: int = 12,
        target_jitter_pct: float = 0.15,
        rng: random.Random | None = None,
    ) -> None:
        if max_per_account_per_hour <= 0:
            raise ValueError(f"max_per_account_per_hour invalido: {max_per_account_per_hour}")
        self._max_per_hour = max_per_account_per_hour
        self._time_jitter_minutes = time_jitter_minutes
        self._target_jitter_pct = target_jitter_pct
        self._rng = rng if rng is not None else random.Random()  # noqa: S311
        self._log = logger.bind(component="time_of_day_distributor")

    def distribute(
        self,
        plan: list[SongDailyTarget],
        accounts: list[tuple[Account, Persona]],
        day: datetime,
    ) -> list[ScheduledJob]:
        """Genera la lista de jobs concretos para el dia.

        Args:
            plan: targets por cancion calculados por ``DailyPlanner``.
            accounts: pares ``(Account, Persona)`` activos.
            day: fecha base (se considera la parte ``date()``).

        Returns:
            Lista de ``ScheduledJob`` ordenable por ``scheduled_at_utc``.
        """
        jobs: list[ScheduledJob] = []
        bucket_counts: dict[tuple[str, datetime], int] = {}
        dropped = 0

        for target in plan:
            candidates = [
                (acc, persona)
                for acc, persona in accounts
                if acc.status.is_usable and persona.country in target.allowed_countries
            ]
            if not candidates:
                self._log.warning(
                    "distribute.no_candidates",
                    song_id=target.song_id,
                )
                continue

            jittered_streams = apply_target_jitter(
                target.streams_target,
                self._target_jitter_pct,
                rng=self._rng,
            )

            for stream_idx in range(jittered_streams):
                account, persona = candidates[stream_idx % len(candidates)]
                placement = self._place_job(
                    account=account,
                    persona=persona,
                    day=day,
                    bucket_counts=bucket_counts,
                )
                if placement is None:
                    dropped += 1
                    continue
                scheduled_at, bucket_key = placement
                bucket_counts[bucket_key] = bucket_counts.get(bucket_key, 0) + 1
                jobs.append(
                    ScheduledJob(
                        account_id=account.id,
                        song_id=target.song_id,
                        scheduled_at_utc=scheduled_at,
                        country=persona.country,
                    )
                )

        jobs.sort(key=lambda j: j.scheduled_at_utc)
        self._log.info(
            "distribute.done",
            jobs=len(jobs),
            dropped=dropped,
            songs=len(plan),
        )
        return jobs

    def _place_job(
        self,
        *,
        account: Account,
        persona: Persona,
        day: datetime,
        bucket_counts: dict[tuple[str, datetime], int],
    ) -> tuple[datetime, tuple[str, datetime]] | None:
        """Intenta colocar un job en el primer slot horario disponible.

        Recorre la ventana activa local de la persona en orden aleatorio.
        Si todos los slots estan saturados devuelve ``None`` (job dropeado).
        """
        active_hours = self._active_local_hours(persona)
        if not active_hours:
            return None

        order = list(active_hours)
        self._rng.shuffle(order)
        tz = self._zone_for(persona)
        local_day = day.astimezone(tz).date() if day.tzinfo else day.date()

        for hour in order:
            local_dt = datetime.combine(local_day, time(hour=hour), tzinfo=tz)
            jittered = apply_time_jitter(
                local_dt,
                self._time_jitter_minutes,
                rng=self._rng,
            )
            scheduled_utc = jittered.astimezone(UTC)
            bucket_key = (
                account.id,
                scheduled_utc.replace(minute=0, second=0, microsecond=0),
            )
            if bucket_counts.get(bucket_key, 0) < self._max_per_hour:
                offset_seconds = self._rng.randint(0, 59)
                scheduled_utc = scheduled_utc.replace(microsecond=0) + timedelta(
                    seconds=offset_seconds,
                )
                return scheduled_utc, bucket_key
        return None

    def _active_local_hours(self, persona: Persona) -> list[int]:
        """Devuelve horas locales activas de la persona en orden cronologico."""
        start, end = persona.traits.preferred_session_hour_local
        if not 0 <= start <= 23 or not 0 <= end <= 23:
            return []
        if start <= end:
            return list(range(start, end + 1))
        return [*range(start, 24), *range(0, end + 1)]

    def _zone_for(self, persona: Persona) -> ZoneInfo:
        """Resuelve ``ZoneInfo`` con fallback a UTC si la zona es invalida."""
        try:
            return ZoneInfo(persona.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            self._log.warning(
                "time_of_day.invalid_timezone",
                timezone=persona.timezone,
                account_id=persona.account_id,
            )
            return ZoneInfo("UTC")
