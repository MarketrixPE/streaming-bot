"""Tests del TimeOfDayDistributor: respeto de horas locales y cap por hora."""

from __future__ import annotations

import random
from datetime import UTC, datetime
from itertools import pairwise
from zoneinfo import ZoneInfo

import pytest
import structlog

from streaming_bot.application.scheduler.daily_planner import SongDailyTarget
from streaming_bot.application.scheduler.time_of_day import (
    ScheduledJob,
    TimeOfDayDistributor,
)
from streaming_bot.domain.entities import Account, AccountStatus
from streaming_bot.domain.persona import (
    BehaviorProbabilities,
    DeviceType,
    EngagementLevel,
    MouseProfile,
    Persona,
    PersonaMemory,
    PersonaTraits,
    PlatformProfile,
    SessionPattern,
    TypingProfile,
)
from streaming_bot.domain.value_objects import Country


def _make_persona(
    *,
    account_id: str,
    country: Country = Country.PE,
    timezone: str = "America/Lima",
    hours: tuple[int, int] = (18, 23),
) -> Persona:
    traits = PersonaTraits(
        engagement_level=EngagementLevel.ENGAGED,
        preferred_genres=("reggaeton",),
        preferred_session_hour_local=hours,
        device=DeviceType.DESKTOP_CHROME,
        platform=PlatformProfile.WINDOWS_DESKTOP,
        ui_language="es-PE",
        timezone=timezone,
        country=country,
        behaviors=BehaviorProbabilities(),
        typing=TypingProfile(),
        mouse=MouseProfile(),
        session=SessionPattern(),
    )
    return Persona(
        account_id=account_id,
        traits=traits,
        memory=PersonaMemory(),
    )


def _make_account(
    account_id: str,
    *,
    country: Country = Country.PE,
    banned: bool = False,
) -> Account:
    return Account(
        id=account_id,
        username=f"u-{account_id}",
        password="x",
        country=country,
        status=AccountStatus.banned("test") if banned else AccountStatus.active(),
    )


def _make_distributor(
    *,
    seed: int = 42,
    max_per_hour: int = 3,
    time_jitter_minutes: int = 0,
    target_jitter_pct: float = 0.0,
) -> TimeOfDayDistributor:
    return TimeOfDayDistributor(
        logger=structlog.get_logger("test"),
        max_per_account_per_hour=max_per_hour,
        time_jitter_minutes=time_jitter_minutes,
        target_jitter_pct=target_jitter_pct,
        rng=random.Random(seed),
    )


class TestTimeOfDayDistributor:
    def test_jobs_in_local_active_window(self) -> None:
        distributor = _make_distributor()
        plan = [
            SongDailyTarget(
                song_id="spotify:track:t1",
                streams_target=10,
                allowed_countries=frozenset({Country.PE}),
                days_since_start=5,
            ),
        ]
        accounts = [(_make_account("a1"), _make_persona(account_id="a1"))]
        day = datetime(2026, 5, 1, tzinfo=UTC)
        jobs = distributor.distribute(plan, accounts, day)
        tz = ZoneInfo("America/Lima")
        for job in jobs:
            local_hour = job.scheduled_at_utc.astimezone(tz).hour
            assert 18 <= local_hour <= 23

    def test_max_per_account_per_hour_enforced(self) -> None:
        """Con max=2 y target=20, una sola cuenta no puede recibir mas de
        2 jobs por bucket de hora UTC."""
        distributor = _make_distributor(max_per_hour=2, time_jitter_minutes=0)
        plan = [
            SongDailyTarget(
                song_id="spotify:track:tt",
                streams_target=20,
                allowed_countries=frozenset({Country.PE}),
                days_since_start=5,
            ),
        ]
        accounts = [(_make_account("solo"), _make_persona(account_id="solo"))]
        jobs = distributor.distribute(plan, accounts, datetime(2026, 5, 1, tzinfo=UTC))
        per_bucket: dict[tuple[str, datetime], int] = {}
        for job in jobs:
            key = (
                job.account_id,
                job.scheduled_at_utc.replace(minute=0, second=0, microsecond=0),
            )
            per_bucket[key] = per_bucket.get(key, 0) + 1
        assert per_bucket
        assert max(per_bucket.values()) <= 2

    def test_jobs_filtered_by_allowed_countries(self) -> None:
        """Cuentas en paises NO permitidos no reciben jobs."""
        distributor = _make_distributor()
        plan = [
            SongDailyTarget(
                song_id="spotify:track:t1",
                streams_target=5,
                allowed_countries=frozenset({Country.PE}),
                days_since_start=1,
            ),
        ]
        accounts = [
            (
                _make_account("mx-only", country=Country.MX),
                _make_persona(
                    account_id="mx-only",
                    country=Country.MX,
                    timezone="America/Mexico_City",
                ),
            ),
        ]
        jobs = distributor.distribute(plan, accounts, datetime(2026, 5, 1, tzinfo=UTC))
        assert jobs == []

    def test_banned_accounts_excluded(self) -> None:
        distributor = _make_distributor()
        plan = [
            SongDailyTarget(
                song_id="spotify:track:t1",
                streams_target=5,
                allowed_countries=frozenset({Country.PE}),
                days_since_start=1,
            ),
        ]
        banned = (
            _make_account("banned", banned=True),
            _make_persona(account_id="banned"),
        )
        ok = (_make_account("ok"), _make_persona(account_id="ok"))
        jobs = distributor.distribute(plan, [banned, ok], datetime(2026, 5, 1, tzinfo=UTC))
        assert all(job.account_id == "ok" for job in jobs)

    def test_jobs_sorted_by_scheduled_at(self) -> None:
        distributor = _make_distributor()
        plan = [
            SongDailyTarget(
                song_id="spotify:track:t1",
                streams_target=8,
                allowed_countries=frozenset({Country.PE}),
                days_since_start=1,
            ),
        ]
        accounts = [
            (_make_account("a1"), _make_persona(account_id="a1")),
            (_make_account("a2"), _make_persona(account_id="a2")),
        ]
        jobs = distributor.distribute(plan, accounts, datetime(2026, 5, 1, tzinfo=UTC))
        for prev, curr in pairwise(jobs):
            assert prev.scheduled_at_utc <= curr.scheduled_at_utc

    def test_jobs_carry_persona_country(self) -> None:
        distributor = _make_distributor()
        plan = [
            SongDailyTarget(
                song_id="spotify:track:t1",
                streams_target=2,
                allowed_countries=frozenset({Country.PE, Country.MX}),
                days_since_start=1,
            ),
        ]
        accounts = [(_make_account("pe"), _make_persona(account_id="pe"))]
        jobs = distributor.distribute(plan, accounts, datetime(2026, 5, 1, tzinfo=UTC))
        assert jobs
        assert all(job.country == Country.PE for job in jobs)

    def test_returns_scheduled_job_instances(self) -> None:
        distributor = _make_distributor()
        plan = [
            SongDailyTarget(
                song_id="spotify:track:t1",
                streams_target=2,
                allowed_countries=frozenset({Country.PE}),
                days_since_start=1,
            ),
        ]
        accounts = [(_make_account("a1"), _make_persona(account_id="a1"))]
        jobs = distributor.distribute(plan, accounts, datetime(2026, 5, 1, tzinfo=UTC))
        assert all(isinstance(j, ScheduledJob) for j in jobs)
        assert all(j.scheduled_at_utc.tzinfo is not None for j in jobs)

    def test_no_candidates_returns_empty(self) -> None:
        distributor = _make_distributor()
        plan = [
            SongDailyTarget(
                song_id="spotify:track:t1",
                streams_target=5,
                allowed_countries=frozenset({Country.PE}),
                days_since_start=1,
            ),
        ]
        jobs = distributor.distribute(plan, [], datetime(2026, 5, 1, tzinfo=UTC))
        assert jobs == []

    def test_invalid_max_per_hour_raises(self) -> None:
        with pytest.raises(ValueError, match="max_per_account_per_hour"):
            TimeOfDayDistributor(
                logger=structlog.get_logger("test"),
                max_per_account_per_hour=0,
            )

    def test_round_robin_across_accounts(self) -> None:
        """Con N cuentas y M streams, cada cuenta recibe ~M/N jobs."""
        distributor = _make_distributor(max_per_hour=10)
        plan = [
            SongDailyTarget(
                song_id="spotify:track:t1",
                streams_target=10,
                allowed_countries=frozenset({Country.PE}),
                days_since_start=1,
            ),
        ]
        accounts = [
            (_make_account("a1"), _make_persona(account_id="a1")),
            (_make_account("a2"), _make_persona(account_id="a2")),
        ]
        jobs = distributor.distribute(plan, accounts, datetime(2026, 5, 1, tzinfo=UTC))
        per_account = {"a1": 0, "a2": 0}
        for job in jobs:
            per_account[job.account_id] += 1
        assert abs(per_account["a1"] - per_account["a2"]) <= 1

    def test_invalid_timezone_falls_back_to_utc(self) -> None:
        """Persona con tz invalida debe mantener jobs (con fallback UTC)."""
        distributor = _make_distributor()
        bogus_persona = _make_persona(
            account_id="ghost",
            timezone="Mars/Olympus_Mons",
            hours=(8, 12),
        )
        plan = [
            SongDailyTarget(
                song_id="spotify:track:t1",
                streams_target=2,
                allowed_countries=frozenset({Country.PE}),
                days_since_start=1,
            ),
        ]
        jobs = distributor.distribute(
            plan,
            [(_make_account("ghost"), bogus_persona)],
            datetime(2026, 5, 1, tzinfo=UTC),
        )
        # No crashea; los jobs caen en horas UTC 8-12 por fallback.
        assert jobs
