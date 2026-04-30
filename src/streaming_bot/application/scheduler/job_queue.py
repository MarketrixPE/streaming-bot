"""Cola priorizada de jobs por instante programado.

Define el ``Protocol`` ``IJobQueue`` para que cualquier impl (Redis Streams,
Postgres, etc.) pueda reemplazar la in-memory sin tocar al worker. La
implementacion ``InMemoryJobQueue`` usa un heap ordenado por
``scheduled_at_utc`` y un ``asyncio.Lock`` para concurrencia segura.

``IJobQueueStore`` es un stub para snapshots persistentes (se cablea
despues; aqui solo se define el contrato).
"""

from __future__ import annotations

import asyncio
import heapq
from itertools import count
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime

    from streaming_bot.application.scheduler.time_of_day import ScheduledJob


@runtime_checkable
class IJobQueue(Protocol):
    """Cola async de jobs ordenada por ``scheduled_at_utc``."""

    async def enqueue(self, job: ScheduledJob) -> None:
        """Agrega un job nuevo respetando el orden temporal."""
        ...

    async def dequeue_ready(self, now: datetime) -> list[ScheduledJob]:
        """Pop atomico de todos los jobs cuyo ``scheduled_at_utc <= now``."""
        ...

    async def mark_done(self, job_id: str) -> None:
        """Registra un job como completado exitosamente."""
        ...

    async def mark_failed(self, job_id: str, reason: str) -> None:
        """Registra un job como fallido con la razon dada."""
        ...

    async def size(self) -> int:
        """Numero de jobs pendientes (no incluye los ya despachados)."""
        ...


@runtime_checkable
class IJobQueueStore(Protocol):
    """Stub de persistencia para snapshots de la cola.

    Implementaciones futuras: ``RedisStreamsJobQueueStore``,
    ``PostgresJobQueueStore``. Aqui solo definimos la API minima que
    permitira hidratar la cola tras un restart sin perder jobs.
    """

    async def save_snapshot(self, jobs: list[ScheduledJob]) -> None:
        """Persiste el estado actual de la cola."""
        ...

    async def load_snapshot(self) -> list[ScheduledJob]:
        """Carga jobs persistidos previamente (vacio si nunca se persistio)."""
        ...


class InMemoryJobQueue(IJobQueue):
    """Cola in-memory priorizada (min-heap) por ``scheduled_at_utc``.

    Thread/coroutine-safe via ``asyncio.Lock``. Adecuada para tests y
    despliegues mono-proceso; no sobrevive a restarts.
    """

    def __init__(self) -> None:
        self._heap: list[tuple[datetime, int, ScheduledJob]] = []
        self._counter = count()
        self._done: set[str] = set()
        self._failed: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def enqueue(self, job: ScheduledJob) -> None:
        async with self._lock:
            heapq.heappush(
                self._heap,
                (job.scheduled_at_utc, next(self._counter), job),
            )

    async def dequeue_ready(self, now: datetime) -> list[ScheduledJob]:
        ready: list[ScheduledJob] = []
        async with self._lock:
            while self._heap and self._heap[0][0] <= now:
                _, _, job = heapq.heappop(self._heap)
                ready.append(job)
        return ready

    async def mark_done(self, job_id: str) -> None:
        async with self._lock:
            self._done.add(job_id)

    async def mark_failed(self, job_id: str, reason: str) -> None:
        async with self._lock:
            self._failed[job_id] = reason

    async def size(self) -> int:
        async with self._lock:
            return len(self._heap)

    async def done_count(self) -> int:
        """Util para tests/observabilidad: numero de jobs completados."""
        async with self._lock:
            return len(self._done)

    async def failed_count(self) -> int:
        """Util para tests/observabilidad: numero de jobs fallidos."""
        async with self._lock:
            return len(self._failed)
