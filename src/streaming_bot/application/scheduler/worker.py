"""Worker async que consume la cola y despacha sesiones de playlist.

Diseno:
- Bucle ``run_forever`` que polleta ``dequeue_ready(now)`` con concurrencia
  controlada via ``asyncio.Semaphore``.
- Antes de cada poll consulta ``IPanicKillSwitch.is_active``: si esta
  activo, deja de aceptar nuevos jobs y drena los in-flight.
- Cada job pre-valida cuenta + persona via puertos (``IAccountRepository``,
  ``IPersonaRepository``) y despacha por un ``SessionDispatcher``
  inyectado (typicamente un wrapper de ``PlaylistSessionUseCase``).
- Marca exito/fallo en la cola para observabilidad.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from structlog.stdlib import BoundLogger

    from streaming_bot.application.playlist_session import PlaylistSessionResult
    from streaming_bot.application.scheduler.job_queue import IJobQueue
    from streaming_bot.application.scheduler.time_of_day import ScheduledJob
    from streaming_bot.domain.ports.account_repo import IAccountRepository
    from streaming_bot.domain.ports.distributor_monitor import IPanicKillSwitch
    from streaming_bot.domain.ports.persona_repo import IPersonaRepository


SessionDispatcher = Callable[["ScheduledJob"], Awaitable["PlaylistSessionResult"]]
"""Callable async que ejecuta la sesion para un job concreto.

Se inyecta desde ``SchedulerService``, que lo construye sobre
``PlaylistSessionUseCase`` con la logica de mapear ``ScheduledJob ->
PlaylistSessionRequest``. Esto desacopla al worker del construccion
del request real.
"""


class SchedulerWorker:
    """Loop async que consume ``IJobQueue`` con concurrencia + kill-switch."""

    def __init__(
        self,
        *,
        queue: IJobQueue,
        dispatcher: SessionDispatcher,
        panic: IPanicKillSwitch,
        accounts: IAccountRepository,
        personas: IPersonaRepository,
        logger: BoundLogger,
        concurrency: int = 5,
        poll_interval_seconds: float = 1.0,
    ) -> None:
        if concurrency <= 0:
            raise ValueError(f"concurrency invalida: {concurrency}")
        if poll_interval_seconds < 0:
            raise ValueError(f"poll_interval_seconds invalido: {poll_interval_seconds}")
        self._queue = queue
        self._dispatcher = dispatcher
        self._panic = panic
        self._accounts = accounts
        self._personas = personas
        self._concurrency = concurrency
        self._poll_interval = poll_interval_seconds
        self._log = logger.bind(component="scheduler_worker")

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        """Loop principal. Sale cuando ``stop_event`` o panic kill-switch.

        Garantiza drenar los in-flight antes de retornar.
        """
        in_flight: set[asyncio.Task[None]] = set()
        sem = asyncio.Semaphore(self._concurrency)
        self._log.info("worker.start", concurrency=self._concurrency)

        try:
            while not stop_event.is_set():
                if await self._panic.is_active():
                    self._log.warning("worker.panic_active.draining")
                    break

                now = datetime.now(UTC)
                jobs = await self._queue.dequeue_ready(now)

                for job in jobs:
                    task = asyncio.create_task(self._run_one(job, sem))
                    in_flight.add(task)
                    task.add_done_callback(in_flight.discard)

                if not jobs:
                    await self._sleep_or_stop(stop_event)
        finally:
            if in_flight:
                self._log.info("worker.draining", in_flight=len(in_flight))
                await asyncio.gather(*in_flight, return_exceptions=True)
            self._log.info("worker.stopped")

    async def _sleep_or_stop(self, stop_event: asyncio.Event) -> None:
        """Duerme ``poll_interval`` salvo que ``stop_event`` se dispare."""
        if self._poll_interval == 0:
            return
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=self._poll_interval,
            )
        except TimeoutError:
            return

    async def _run_one(
        self,
        job: ScheduledJob,
        sem: asyncio.Semaphore,
    ) -> None:
        """Ejecuta un job aislando excepciones para no romper el loop."""
        async with sem:
            log = self._log.bind(
                job_id=job.job_id,
                song_id=job.song_id,
                account_id=job.account_id,
            )
            try:
                if not await self._validate_job(job, log):
                    return
                result = await self._dispatcher(job)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.exception("worker.job_failed", error=str(exc))
                await self._queue.mark_failed(job.job_id, reason=str(exc))
                return

            if result.outcome in {"success", "partial"}:
                await self._queue.mark_done(job.job_id)
                log.info(
                    "worker.job_done",
                    outcome=result.outcome,
                    streams=result.completed_streams,
                )
            else:
                await self._queue.mark_failed(
                    job.job_id,
                    reason=result.outcome,
                )
                log.warning("worker.job_outcome_failed", outcome=result.outcome)

    async def _validate_job(
        self,
        job: ScheduledJob,
        log: BoundLogger,
    ) -> bool:
        """Verifica que cuenta y persona existan y sean utilizables."""
        try:
            account = await self._accounts.get(job.account_id)
        except Exception as exc:
            log.warning("worker.account_lookup_failed", error=str(exc))
            await self._queue.mark_failed(job.job_id, reason="account_lookup_failed")
            return False

        if not account.status.is_usable:
            await self._queue.mark_failed(
                job.job_id,
                reason=f"account_unusable:{account.status.state}",
            )
            log.warning("worker.account_unusable", state=account.status.state)
            return False

        persona = await self._personas.get(job.account_id)
        if persona is None:
            await self._queue.mark_failed(job.job_id, reason="persona_missing")
            log.warning("worker.persona_missing")
            return False

        return True
