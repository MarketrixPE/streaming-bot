"""Smoke test del SchedulerService: integracion de planner+distrib+queue+worker."""

from __future__ import annotations

import asyncio
import random
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock

import structlog

from streaming_bot.application.playlist_session import PlaylistSessionResult
from streaming_bot.application.scheduler.daily_planner import DailyPlanner
from streaming_bot.application.scheduler.job_queue import InMemoryJobQueue
from streaming_bot.application.scheduler.scheduler_service import SchedulerService
from streaming_bot.application.scheduler.time_of_day import (
    ScheduledJob,
    TimeOfDayDistributor,
)
from streaming_bot.application.scheduler.worker import SchedulerWorker
from streaming_bot.domain.entities import Account, AccountStatus
from streaming_bot.domain.ramp_up import TierRampUp
from streaming_bot.domain.song import (
    Distributor,
    Song,
    SongMetadata,
    SongRole,
    SongTier,
)
from streaming_bot.domain.value_objects import Country
from tests.application.fakes import build_persona


def _song(
    *,
    uri: str = "spotify:track:t1",
    tier: SongTier = SongTier.MID,
    baseline: float = 50.0,
    target_per_day: int = 100,
) -> Song:
    return Song(
        spotify_uri=uri,
        title=f"title-{uri}",
        artist_name="artist",
        artist_uri="spotify:artist:a1",
        role=SongRole.TARGET,
        metadata=SongMetadata(duration_seconds=180),
        distributor=Distributor.DISTROKID,
        baseline_streams_per_day=baseline,
        target_streams_per_day=target_per_day,
        is_active=True,
        tier=tier,
    )


def _build_service(
    *,
    songs_list: list[Song],
    accounts_list: list[Account],
    panic_active: bool = False,
    queue: InMemoryJobQueue | None = None,
) -> tuple[SchedulerService, AsyncMock, InMemoryJobQueue]:
    log = structlog.get_logger("test")
    queue = queue or InMemoryJobQueue()

    songs_repo = AsyncMock()
    songs_repo.list_pilot_eligible.return_value = songs_list

    accounts_repo = AsyncMock()
    accounts_repo.all.return_value = accounts_list
    accounts_repo.get.side_effect = lambda aid: next(a for a in accounts_list if a.id == aid)

    personas_repo = AsyncMock()
    personas_repo.get.side_effect = lambda aid: (
        build_persona()
        if aid == "a1"
        else (build_persona() if any(a.id == aid for a in accounts_list) else None)
    )

    panic = AsyncMock()
    panic.is_active.return_value = panic_active

    dispatcher = AsyncMock(
        return_value=PlaylistSessionResult(
            session_id="sess",
            completed_streams=3,
            target_streams=3,
            duration_seconds=60,
            outcome="success",
            behaviors_count=2,
        )
    )

    planner = DailyPlanner(
        program_start=date(2026, 4, 1),
        tier_policy=TierRampUp.conservative_pilot(),
        logger=log,
    )
    distributor = TimeOfDayDistributor(
        logger=log,
        max_per_account_per_hour=3,
        time_jitter_minutes=0,
        target_jitter_pct=0.0,
        rng=random.Random(1),
    )
    worker = SchedulerWorker(
        queue=queue,
        dispatcher=dispatcher,
        panic=panic,
        accounts=accounts_repo,
        personas=personas_repo,
        logger=log,
        concurrency=2,
        poll_interval_seconds=0.01,
    )

    service = SchedulerService(
        planner=planner,
        distributor=distributor,
        queue=queue,
        worker=worker,
        songs=songs_repo,
        accounts=accounts_repo,
        personas=personas_repo,
        logger=log,
    )
    return service, dispatcher, queue


class TestSchedulerService:
    async def test_plan_day_filters_via_song_repo(self) -> None:
        random.seed(0)
        service, _dispatcher, _queue = _build_service(
            songs_list=[
                _song(uri="spotify:track:m1"),
                _song(uri="spotify:track:hot", tier=SongTier.HOT),
            ],
            accounts_list=[],
        )
        plan = await service.plan_day(datetime(2026, 5, 1, tzinfo=UTC))
        # HOT excluida por planner; m1 si pasa.
        assert any(p.song_id == "spotify:track:m1" for p in plan)
        assert not any(p.song_id == "spotify:track:hot" for p in plan)

    async def test_enqueue_plan_pushes_jobs_to_queue(self) -> None:
        random.seed(0)
        accounts = [
            Account(
                id="a1",
                username="u",
                password="p",
                country=Country.PE,
                status=AccountStatus.active(),
            ),
        ]
        service, _dispatcher, queue = _build_service(
            songs_list=[_song()],
            accounts_list=accounts,
        )
        plan = await service.plan_day(datetime(2026, 5, 1, tzinfo=UTC))
        jobs = await service.enqueue_plan(plan, datetime(2026, 5, 1, tzinfo=UTC))
        assert all(isinstance(j, ScheduledJob) for j in jobs)
        assert await queue.size() == len(jobs)

    async def test_run_executes_jobs(self) -> None:
        random.seed(0)
        accounts = [
            Account(
                id="a1",
                username="u",
                password="p",
                country=Country.PE,
                status=AccountStatus.active(),
            ),
        ]
        queue = InMemoryJobQueue()
        # Enqueamos un job ya vencido para que el worker lo dispatche enseguida.
        await queue.enqueue(
            ScheduledJob(
                account_id="a1",
                song_id="spotify:track:t1",
                scheduled_at_utc=datetime.now(UTC) - timedelta(minutes=1),
                country=Country.PE,
            )
        )
        service, dispatcher, queue = _build_service(
            songs_list=[_song()],
            accounts_list=accounts,
            queue=queue,
        )
        stop = asyncio.Event()

        async def _stop_soon() -> None:
            await asyncio.sleep(0.15)
            await service.stop()
            stop.set()

        await asyncio.gather(service.run(stop), _stop_soon())
        dispatcher.assert_awaited()
        assert await queue.done_count() >= 1

    async def test_stop_signals_when_running(self) -> None:
        """``stop()`` debe setear el stop_event activo."""
        random.seed(0)
        service, _dispatcher, _queue = _build_service(
            songs_list=[],
            accounts_list=[],
        )
        stop = asyncio.Event()

        async def _stop_via_method() -> None:
            await asyncio.sleep(0.05)
            await service.stop()

        await asyncio.gather(service.run(stop), _stop_via_method())
        assert stop.is_set()

    async def test_stop_before_run_is_safe(self) -> None:
        """``stop()`` antes de ``run()`` no debe explotar."""
        random.seed(0)
        service, _dispatcher, _queue = _build_service(
            songs_list=[],
            accounts_list=[],
        )
        await service.stop()  # debe ser noop

    async def test_active_accounts_filter_excludes_banned(self) -> None:
        random.seed(0)
        accounts = [
            Account(
                id="a1",
                username="u",
                password="p",
                country=Country.PE,
                status=AccountStatus.active(),
            ),
            Account(
                id="a2",
                username="u2",
                password="p",
                country=Country.PE,
                status=AccountStatus.banned("test"),
            ),
        ]
        service, _dispatcher, _queue = _build_service(
            songs_list=[_song()],
            accounts_list=accounts,
        )
        plan = await service.plan_day(datetime(2026, 5, 1, tzinfo=UTC))
        jobs = await service.enqueue_plan(plan, datetime(2026, 5, 1, tzinfo=UTC))
        # Ningun job debe apuntar a a2.
        assert all(j.account_id != "a2" for j in jobs)

    async def test_panic_active_skips_dispatch(self) -> None:
        """Con panic activo desde el inicio no se despacha nada."""
        random.seed(0)
        accounts = [
            Account(
                id="a1",
                username="u",
                password="p",
                country=Country.PE,
                status=AccountStatus.active(),
            ),
        ]
        queue = InMemoryJobQueue()
        await queue.enqueue(
            ScheduledJob(
                account_id="a1",
                song_id="spotify:track:t1",
                scheduled_at_utc=datetime.now(UTC) - timedelta(minutes=1),
                country=Country.PE,
            )
        )
        service, dispatcher, queue = _build_service(
            songs_list=[_song()],
            accounts_list=accounts,
            panic_active=True,
            queue=queue,
        )
        await service.run(asyncio.Event())
        dispatcher.assert_not_awaited()
