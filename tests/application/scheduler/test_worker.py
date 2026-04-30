"""Tests del SchedulerWorker: panic, validacion, concurrencia."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
import structlog

from streaming_bot.application.playlist_session import PlaylistSessionResult
from streaming_bot.application.scheduler.job_queue import InMemoryJobQueue
from streaming_bot.application.scheduler.time_of_day import ScheduledJob
from streaming_bot.application.scheduler.worker import SchedulerWorker
from streaming_bot.domain.entities import Account, AccountStatus
from streaming_bot.domain.value_objects import Country
from tests.application.fakes import build_persona


def _result(outcome: str = "success", streams: int = 5) -> PlaylistSessionResult:
    return PlaylistSessionResult(
        session_id="sess-1",
        completed_streams=streams,
        target_streams=streams,
        duration_seconds=120,
        outcome=outcome,
        behaviors_count=3,
    )


def _job(
    *,
    account_id: str = "a1",
    minutes_offset: int = -1,
    song_id: str = "spotify:track:t1",
) -> ScheduledJob:
    base = datetime.now(UTC)
    return ScheduledJob(
        account_id=account_id,
        song_id=song_id,
        scheduled_at_utc=base + timedelta(minutes=minutes_offset),
        country=Country.PE,
    )


def _make_panic(active: bool = False) -> AsyncMock:
    panic = AsyncMock()
    panic.is_active.return_value = active
    return panic


def _make_accounts_repo(
    *,
    banned: bool = False,
    raises: Exception | None = None,
) -> AsyncMock:
    repo = AsyncMock()
    if raises is not None:
        repo.get.side_effect = raises
    else:
        repo.get.return_value = Account(
            id="a1",
            username="u",
            password="p",
            country=Country.PE,
            status=(AccountStatus.banned("test") if banned else AccountStatus.active()),
        )
    return repo


def _make_personas_repo(*, missing: bool = False) -> AsyncMock:
    repo = AsyncMock()
    repo.get.return_value = None if missing else build_persona()
    return repo


def _build_worker(
    *,
    queue: InMemoryJobQueue,
    dispatcher: Callable[[ScheduledJob], Awaitable[PlaylistSessionResult]],
    panic: AsyncMock,
    accounts: AsyncMock,
    personas: AsyncMock,
    concurrency: int = 5,
) -> SchedulerWorker:
    return SchedulerWorker(
        queue=queue,
        dispatcher=dispatcher,
        panic=panic,
        accounts=accounts,
        personas=personas,
        logger=structlog.get_logger("test"),
        concurrency=concurrency,
        poll_interval_seconds=0.01,
    )


class TestSchedulerWorker:
    async def test_dispatches_ready_jobs(self) -> None:
        queue = InMemoryJobQueue()
        await queue.enqueue(_job())

        dispatcher = AsyncMock(return_value=_result("success"))
        worker = _build_worker(
            queue=queue,
            dispatcher=dispatcher,
            panic=_make_panic(),
            accounts=_make_accounts_repo(),
            personas=_make_personas_repo(),
        )

        stop = asyncio.Event()

        async def _stop_after_dispatch() -> None:
            await asyncio.sleep(0.1)
            stop.set()

        await asyncio.gather(worker.run_forever(stop), _stop_after_dispatch())

        dispatcher.assert_awaited()
        assert await queue.done_count() == 1

    async def test_panic_stops_worker_and_drains(self) -> None:
        queue = InMemoryJobQueue()
        await queue.enqueue(_job())

        slow_running = asyncio.Event()
        finish = asyncio.Event()

        async def _slow_dispatch(_job: ScheduledJob) -> PlaylistSessionResult:
            slow_running.set()
            await finish.wait()
            return _result("success")

        panic = _make_panic(active=False)
        worker = _build_worker(
            queue=queue,
            dispatcher=_slow_dispatch,
            panic=panic,
            accounts=_make_accounts_repo(),
            personas=_make_personas_repo(),
        )
        stop = asyncio.Event()

        async def _trigger_panic() -> None:
            await slow_running.wait()
            panic.is_active.return_value = True
            await asyncio.sleep(0.05)
            finish.set()
            await asyncio.sleep(0.05)
            stop.set()

        await asyncio.gather(worker.run_forever(stop), _trigger_panic())
        assert await queue.done_count() == 1

    async def test_skips_banned_account(self) -> None:
        queue = InMemoryJobQueue()
        await queue.enqueue(_job())
        dispatcher = AsyncMock(return_value=_result("success"))
        worker = _build_worker(
            queue=queue,
            dispatcher=dispatcher,
            panic=_make_panic(),
            accounts=_make_accounts_repo(banned=True),
            personas=_make_personas_repo(),
        )
        stop = asyncio.Event()

        async def _stop_soon() -> None:
            await asyncio.sleep(0.1)
            stop.set()

        await asyncio.gather(worker.run_forever(stop), _stop_soon())
        dispatcher.assert_not_awaited()
        assert await queue.failed_count() == 1

    async def test_skips_when_persona_missing(self) -> None:
        queue = InMemoryJobQueue()
        await queue.enqueue(_job())
        dispatcher = AsyncMock(return_value=_result("success"))
        worker = _build_worker(
            queue=queue,
            dispatcher=dispatcher,
            panic=_make_panic(),
            accounts=_make_accounts_repo(),
            personas=_make_personas_repo(missing=True),
        )
        stop = asyncio.Event()

        async def _stop_soon() -> None:
            await asyncio.sleep(0.1)
            stop.set()

        await asyncio.gather(worker.run_forever(stop), _stop_soon())
        dispatcher.assert_not_awaited()
        assert await queue.failed_count() == 1

    async def test_account_lookup_error_marks_failed(self) -> None:
        queue = InMemoryJobQueue()
        await queue.enqueue(_job())
        dispatcher = AsyncMock(return_value=_result("success"))
        worker = _build_worker(
            queue=queue,
            dispatcher=dispatcher,
            panic=_make_panic(),
            accounts=_make_accounts_repo(raises=RuntimeError("db down")),
            personas=_make_personas_repo(),
        )
        stop = asyncio.Event()

        async def _stop_soon() -> None:
            await asyncio.sleep(0.1)
            stop.set()

        await asyncio.gather(worker.run_forever(stop), _stop_soon())
        dispatcher.assert_not_awaited()
        assert await queue.failed_count() == 1

    async def test_dispatcher_exception_marks_failed(self) -> None:
        queue = InMemoryJobQueue()
        await queue.enqueue(_job())

        async def _exploding(_job: ScheduledJob) -> PlaylistSessionResult:
            raise RuntimeError("kaboom")

        worker = _build_worker(
            queue=queue,
            dispatcher=_exploding,
            panic=_make_panic(),
            accounts=_make_accounts_repo(),
            personas=_make_personas_repo(),
        )
        stop = asyncio.Event()

        async def _stop_soon() -> None:
            await asyncio.sleep(0.15)
            stop.set()

        await asyncio.gather(worker.run_forever(stop), _stop_soon())
        assert await queue.failed_count() == 1

    async def test_failed_outcome_marks_failed(self) -> None:
        queue = InMemoryJobQueue()
        await queue.enqueue(_job())
        dispatcher = AsyncMock(return_value=_result("failed"))
        worker = _build_worker(
            queue=queue,
            dispatcher=dispatcher,
            panic=_make_panic(),
            accounts=_make_accounts_repo(),
            personas=_make_personas_repo(),
        )
        stop = asyncio.Event()

        async def _stop_soon() -> None:
            await asyncio.sleep(0.15)
            stop.set()

        await asyncio.gather(worker.run_forever(stop), _stop_soon())
        assert await queue.failed_count() == 1
        assert await queue.done_count() == 0

    async def test_concurrency_limit_respected(self) -> None:
        queue = InMemoryJobQueue()
        for i in range(6):
            await queue.enqueue(_job(account_id=f"a{i}", minutes_offset=-1))

        in_flight: list[int] = []
        max_in_flight = 0

        running = 0

        async def _dispatch(_job: ScheduledJob) -> PlaylistSessionResult:
            nonlocal running, max_in_flight
            running += 1
            in_flight.append(running)
            max_in_flight = max(max_in_flight, running)
            await asyncio.sleep(0.05)
            running -= 1
            return _result("success")

        accounts = AsyncMock()

        async def _get_account(account_id: str) -> Account:
            return Account(
                id=account_id,
                username="u",
                password="p",
                country=Country.PE,
                status=AccountStatus.active(),
            )

        accounts.get.side_effect = _get_account

        worker = _build_worker(
            queue=queue,
            dispatcher=_dispatch,
            panic=_make_panic(),
            accounts=accounts,
            personas=_make_personas_repo(),
            concurrency=2,
        )
        stop = asyncio.Event()

        async def _stop_soon() -> None:
            await asyncio.sleep(0.4)
            stop.set()

        await asyncio.gather(worker.run_forever(stop), _stop_soon())
        assert max_in_flight <= 2
        assert await queue.done_count() == 6

    async def test_invalid_concurrency_raises(self) -> None:
        with pytest.raises(ValueError, match="concurrency"):
            SchedulerWorker(
                queue=InMemoryJobQueue(),
                dispatcher=AsyncMock(return_value=_result()),
                panic=_make_panic(),
                accounts=_make_accounts_repo(),
                personas=_make_personas_repo(),
                logger=structlog.get_logger("test"),
                concurrency=0,
            )

    async def test_partial_outcome_counts_as_done(self) -> None:
        queue = InMemoryJobQueue()
        await queue.enqueue(_job())
        dispatcher = AsyncMock(return_value=_result("partial", streams=2))
        worker = _build_worker(
            queue=queue,
            dispatcher=dispatcher,
            panic=_make_panic(),
            accounts=_make_accounts_repo(),
            personas=_make_personas_repo(),
        )
        stop = asyncio.Event()

        async def _stop_soon() -> None:
            await asyncio.sleep(0.15)
            stop.set()

        await asyncio.gather(worker.run_forever(stop), _stop_soon())
        assert await queue.done_count() == 1


class TestSchedulerWorkerHelpers:
    async def test_invalid_poll_interval_raises(self) -> None:
        with pytest.raises(ValueError, match="poll_interval_seconds"):
            SchedulerWorker(
                queue=InMemoryJobQueue(),
                dispatcher=AsyncMock(return_value=_result()),
                panic=_make_panic(),
                accounts=_make_accounts_repo(),
                personas=_make_personas_repo(),
                logger=structlog.get_logger("test"),
                concurrency=1,
                poll_interval_seconds=-0.5,
            )

    async def test_panic_already_active_returns_immediately(self) -> None:
        """Si panic ya esta activo al arrancar, el worker no despacha nada."""
        queue = InMemoryJobQueue()
        await queue.enqueue(_job())
        dispatcher = AsyncMock(return_value=_result("success"))
        worker = _build_worker(
            queue=queue,
            dispatcher=dispatcher,
            panic=_make_panic(active=True),
            accounts=_make_accounts_repo(),
            personas=_make_personas_repo(),
        )
        await worker.run_forever(asyncio.Event())
        dispatcher.assert_not_awaited()


def _ignore_unused(*_args: Any) -> None:  # pragma: no cover
    """Helper para silenciar imports no usados en tipos."""
