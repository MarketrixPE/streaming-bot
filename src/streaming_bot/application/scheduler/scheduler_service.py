"""Fachada de alto nivel del scheduler.

Cablea ``DailyPlanner -> TimeOfDayDistributor -> IJobQueue -> SchedulerWorker``
y expone una API minima:

- ``plan_day(day)``: pide el catalogo y construye targets diarios.
- ``enqueue_plan(plan, day)``: distribuye en jobs y los inserta en cola.
- ``run(stop_event)``: arranca el worker (bloqueante).
- ``stop()``: setea la stop_event interna para apagado cooperativo.

El cableado real al ``container.py`` se hace fuera de este modulo.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from streaming_bot.domain.entities import Account
from streaming_bot.domain.persona import Persona

if TYPE_CHECKING:
    from datetime import datetime

    from structlog.stdlib import BoundLogger

    from streaming_bot.application.scheduler.daily_planner import (
        DailyPlanner,
        SongDailyTarget,
    )
    from streaming_bot.application.scheduler.job_queue import IJobQueue
    from streaming_bot.application.scheduler.time_of_day import (
        ScheduledJob,
        TimeOfDayDistributor,
    )
    from streaming_bot.application.scheduler.worker import SchedulerWorker
    from streaming_bot.domain.ports.account_repo import IAccountRepository
    from streaming_bot.domain.ports.persona_repo import IPersonaRepository
    from streaming_bot.domain.ports.song_repo import ISongRepository


class SchedulerService:
    """Fachada que coordina planner, distribuidor, cola y worker."""

    def __init__(
        self,
        *,
        planner: DailyPlanner,
        distributor: TimeOfDayDistributor,
        queue: IJobQueue,
        worker: SchedulerWorker,
        songs: ISongRepository,
        accounts: IAccountRepository,
        personas: IPersonaRepository,
        logger: BoundLogger,
    ) -> None:
        self._planner = planner
        self._distributor = distributor
        self._queue = queue
        self._worker = worker
        self._songs = songs
        self._accounts = accounts
        self._personas = personas
        self._log = logger.bind(component="scheduler_service")
        self._stop_event: asyncio.Event | None = None

    async def plan_day(self, day: datetime) -> list[SongDailyTarget]:
        """Construye el plan diario para la fecha indicada."""
        songs = await self._songs.list_pilot_eligible()
        plan = self._planner.plan_for_today(songs, day)
        self._log.info(
            "service.plan_day",
            songs_total=len(songs),
            songs_planned=len(plan),
        )
        return plan

    async def enqueue_plan(
        self,
        plan: list[SongDailyTarget],
        day: datetime,
    ) -> list[ScheduledJob]:
        """Distribuye el plan en jobs y los encola."""
        accounts_pairs = await self._gather_active_accounts()
        jobs = self._distributor.distribute(plan, accounts_pairs, day)
        for job in jobs:
            await self._queue.enqueue(job)
        self._log.info("service.enqueue_plan", jobs=len(jobs))
        return jobs

    async def run(self, stop_event: asyncio.Event) -> None:
        """Arranca el worker. Bloquea hasta que ``stop_event`` o panic."""
        self._stop_event = stop_event
        try:
            await self._worker.run_forever(stop_event)
        finally:
            self._stop_event = None

    async def stop(self) -> None:
        """Senaliza apagado cooperativo seteando la ``stop_event`` activa."""
        if self._stop_event is not None and not self._stop_event.is_set():
            self._stop_event.set()
            self._log.info("service.stop_signaled")

    async def _gather_active_accounts(self) -> list[tuple[Account, Persona]]:
        """Devuelve pares ``(Account, Persona)`` para cuentas usables."""
        pairs: list[tuple[Account, Persona]] = []
        for account in await self._accounts.all():
            if not account.status.is_usable:
                continue
            persona = await self._personas.get(account.id)
            if persona is None:
                continue
            pairs.append((account, persona))
        return pairs
