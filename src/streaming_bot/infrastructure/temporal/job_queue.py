"""TemporalJobQueue: implementa IJobQueue (puerto application/scheduler)
empujando los ScheduledJob como signals al DailyRunWorkflow corriente.

Filosofia:
- El Worker tradicional (`SchedulerWorker`) consume de IJobQueue.
- Aqui sustituimos InMemoryJobQueue por una cola que en vez de heap usa
  Temporal: cada job de hoy se enrola via signal al workflow del dia.
- `dequeue_ready` se ejecuta DESDE EL WORKFLOW, no desde el caller. Por
  eso aqui la API del puerto se cumple "delegando": enqueue manda signal,
  dequeue/mark_done devuelven listas vacias o no-ops (el contrato sigue
  satisfaciendose para callers que solo necesitan enqueue y observar
  metricas de done/failed via Temporal API).

En una migracion completa el SchedulerWorker desaparece y el workflow
mismo orquesta todo. Por ahora dejamos compat para que ambos coexistan.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from streaming_bot.application.scheduler.job_queue import IJobQueue

if TYPE_CHECKING:
    from streaming_bot.application.scheduler.time_of_day import ScheduledJob
    from streaming_bot.infrastructure.temporal.client_factory import (
        TemporalClientFactory,
    )


class TemporalJobQueue(IJobQueue):
    """Adapter IJobQueue que empuja signals a DailyRunWorkflow."""

    def __init__(
        self,
        *,
        factory: TemporalClientFactory,
        task_queue: str = "streaming-bot-default",
        workflow_id_prefix: str = "daily-run",
    ) -> None:
        self._factory = factory
        self._task_queue = task_queue
        self._workflow_id_prefix = workflow_id_prefix
        self._log = structlog.get_logger("temporal_job_queue")
        self._enqueued: int = 0

    async def enqueue(self, job: ScheduledJob) -> None:
        """Manda el job como signal al workflow del dia (lo crea si no existe)."""
        client = await self._factory.get()
        workflow_id = self._workflow_id_for(job)
        try:
            from streaming_bot.infrastructure.temporal.workflows.daily_run import (
                DailyRunWorkflow,
            )

            handle = await client.start_workflow(
                DailyRunWorkflow.run,
                id=workflow_id,
                task_queue=self._task_queue,
                start_signal="enqueue_job",
                start_signal_args=[_serialize_job(job)],
            )
            self._enqueued += 1
            self._log.debug(
                "temporal_job_enqueued",
                workflow_id=workflow_id,
                run_id=handle.first_execution_run_id,
                job_id=job.job_id,
            )
        except Exception as exc:
            # Si el workflow ya existia, hacemos signal puro.
            self._log.debug(
                "temporal_job_signal_existing",
                workflow_id=workflow_id,
                error=str(exc),
            )
            handle = client.get_workflow_handle(workflow_id)
            await handle.signal("enqueue_job", _serialize_job(job))
            self._enqueued += 1

    async def dequeue_ready(self, now: datetime) -> list[ScheduledJob]:  # noqa: ARG002
        # En modo Temporal, el dequeue lo hace el workflow internamente.
        # Devolvemos lista vacia para compat con el SchedulerWorker viejo,
        # que en este modo simplemente no procesara nada (el workflow lo hace).
        return []

    async def mark_done(self, job_id: str) -> None:
        # No-op: el workflow registra done internamente via state.
        self._log.debug("temporal_job_mark_done_noop", job_id=job_id)

    async def mark_failed(self, job_id: str, reason: str) -> None:
        self._log.debug("temporal_job_mark_failed_noop", job_id=job_id, reason=reason)

    async def size(self) -> int:
        return self._enqueued

    def _workflow_id_for(self, job: ScheduledJob) -> str:
        # Un workflow por dia natural UTC: facilita observabilidad y purgas.
        date_part = job.scheduled_at_utc.astimezone(UTC).strftime("%Y%m%d")
        return f"{self._workflow_id_prefix}-{date_part}"


def _serialize_job(job: ScheduledJob) -> dict[str, object]:
    """Serializa ScheduledJob a dict-de-primitivos para el signal payload."""
    return {
        "job_id": job.job_id,
        "account_id": job.account_id,
        "song_id": job.song_id,
        "scheduled_at_utc": job.scheduled_at_utc.isoformat(),
        "country": job.country.value,
    }
