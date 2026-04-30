"""Tests de la cola in-memory de jobs."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from streaming_bot.application.scheduler.job_queue import (
    IJobQueue,
    InMemoryJobQueue,
)
from streaming_bot.application.scheduler.time_of_day import ScheduledJob
from streaming_bot.domain.value_objects import Country


def _job(
    *,
    account_id: str = "a1",
    minutes_offset: int = 0,
    song_id: str = "spotify:track:t1",
) -> ScheduledJob:
    base = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    return ScheduledJob(
        account_id=account_id,
        song_id=song_id,
        scheduled_at_utc=base + timedelta(minutes=minutes_offset),
        country=Country.PE,
    )


class TestInMemoryJobQueue:
    async def test_enqueue_and_size(self) -> None:
        queue = InMemoryJobQueue()
        await queue.enqueue(_job())
        await queue.enqueue(_job(minutes_offset=10))
        assert await queue.size() == 2

    async def test_dequeue_ready_respects_time(self) -> None:
        queue = InMemoryJobQueue()
        future = _job(minutes_offset=10)
        past = _job(minutes_offset=-10)
        await queue.enqueue(future)
        await queue.enqueue(past)

        ready = await queue.dequeue_ready(datetime(2026, 5, 1, 12, 0, tzinfo=UTC))
        assert len(ready) == 1
        assert ready[0].job_id == past.job_id

    async def test_dequeue_returns_jobs_in_chronological_order(self) -> None:
        queue = InMemoryJobQueue()
        a = _job(minutes_offset=-30)
        b = _job(minutes_offset=-10)
        c = _job(minutes_offset=-20)
        await queue.enqueue(a)
        await queue.enqueue(b)
        await queue.enqueue(c)

        ready = await queue.dequeue_ready(datetime(2026, 5, 1, 13, 0, tzinfo=UTC))
        ids = [j.job_id for j in ready]
        assert ids == [a.job_id, c.job_id, b.job_id]

    async def test_dequeue_does_not_pop_future(self) -> None:
        queue = InMemoryJobQueue()
        await queue.enqueue(_job(minutes_offset=60))
        ready = await queue.dequeue_ready(datetime(2026, 5, 1, 12, 0, tzinfo=UTC))
        assert ready == []
        assert await queue.size() == 1

    async def test_mark_done_increments_done_count(self) -> None:
        queue = InMemoryJobQueue()
        await queue.mark_done("job-1")
        await queue.mark_done("job-2")
        assert await queue.done_count() == 2

    async def test_mark_failed_increments_failed_count(self) -> None:
        queue = InMemoryJobQueue()
        await queue.mark_failed("job-1", reason="oops")
        await queue.mark_failed("job-2", reason="boom")
        assert await queue.failed_count() == 2

    async def test_implements_protocol(self) -> None:
        queue = InMemoryJobQueue()
        assert isinstance(queue, IJobQueue)

    async def test_concurrent_enqueue_safe(self) -> None:
        """Multiples enqueue concurrentes no deben perder jobs."""
        queue = InMemoryJobQueue()
        await asyncio.gather(*[queue.enqueue(_job(minutes_offset=i)) for i in range(50)])
        assert await queue.size() == 50

    async def test_dequeue_clears_queue_when_all_ready(self) -> None:
        queue = InMemoryJobQueue()
        for offset in (-30, -20, -10):
            await queue.enqueue(_job(minutes_offset=offset))
        ready = await queue.dequeue_ready(datetime(2026, 5, 1, 13, 0, tzinfo=UTC))
        assert len(ready) == 3
        assert await queue.size() == 0
