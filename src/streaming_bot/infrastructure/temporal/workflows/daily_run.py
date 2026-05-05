"""DailyRunWorkflow: workflow durable de un dia operativo.

Recibe ScheduledJob via signals (el TemporalJobQueue los empuja desde
TimeOfDayDistributor) y los ejecuta en el instante programado, llamando
a la activity `execute_stream_job` que internamente invoca al use case
StreamSongUseCase / PlaylistSessionUseCase.

Resilencia:
- Sobrevive restarts del worker (Temporal reconstruye estado).
- Cada activity tiene retry policy independiente con backoff exponencial.
- El workflow expira al final del dia natural (UTC) con history retention
  configurada por namespace.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from streaming_bot.infrastructure.temporal.activities.stream_activity import (
        ExecuteStreamArgs,
        execute_stream_job,
    )


@dataclass(slots=True)
class _PendingJob:
    job_id: str
    account_id: str
    song_id: str
    scheduled_at_utc: datetime
    country: str


@workflow.defn(name="DailyRunWorkflow", sandboxed=False)
class DailyRunWorkflow:
    """Orquesta los streams de un dia natural UTC."""

    def __init__(self) -> None:
        self._jobs: list[_PendingJob] = []
        self._completed: int = 0
        self._failed: int = 0
        self._stop_requested: bool = False

    @workflow.run
    async def run(self) -> dict[str, int]:
        """Punto de entrada del workflow.

        Vive todo el dia recibiendo signals con jobs nuevos y ejecutandolos
        cuando llega su scheduled_at_utc. Termina al fin del dia o cuando
        recibe signal `request_stop`.
        """
        end_of_day = workflow.now() + timedelta(hours=24)

        while not self._stop_requested:
            await workflow.wait_condition(
                lambda: self._stop_requested
                or self._has_due_job(workflow.now())
                or workflow.now() >= end_of_day,
            )
            if self._stop_requested or workflow.now() >= end_of_day:
                break
            await self._dispatch_due(workflow.now())
        return {"completed": self._completed, "failed": self._failed, "queued": len(self._jobs)}

    @workflow.signal(name="enqueue_job")
    def enqueue_job(self, payload: dict[str, Any]) -> None:
        """Recibe un job nuevo del TemporalJobQueue."""
        self._jobs.append(
            _PendingJob(
                job_id=payload["job_id"],
                account_id=payload["account_id"],
                song_id=payload["song_id"],
                scheduled_at_utc=datetime.fromisoformat(payload["scheduled_at_utc"]),
                country=payload["country"],
            ),
        )

    @workflow.signal(name="request_stop")
    def request_stop(self) -> None:
        self._stop_requested = True

    @workflow.query(name="status")
    def status(self) -> dict[str, int]:
        return {
            "completed": self._completed,
            "failed": self._failed,
            "queued": len(self._jobs),
        }

    def _has_due_job(self, now: datetime) -> bool:
        return any(job.scheduled_at_utc <= now for job in self._jobs)

    async def _dispatch_due(self, now: datetime) -> None:
        due = [job for job in self._jobs if job.scheduled_at_utc <= now]
        self._jobs = [job for job in self._jobs if job.scheduled_at_utc > now]

        for job in due:
            args = ExecuteStreamArgs(
                job_id=job.job_id,
                account_id=job.account_id,
                song_id=job.song_id,
                country=job.country,
            )
            try:
                await workflow.execute_activity(
                    execute_stream_job,
                    args,
                    start_to_close_timeout=timedelta(minutes=10),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=2),
                        backoff_coefficient=2.0,
                        maximum_interval=timedelta(minutes=2),
                        maximum_attempts=3,
                    ),
                )
                self._completed += 1
            except Exception as exc:
                workflow.logger.warning(
                    "execute_stream_job_failed",
                    extra={"job_id": job.job_id, "error": str(exc)},
                )
                self._failed += 1


# Marca utilitaria para que ruff no se queje del import "no usado" en runtime.
_ = (UTC,)
