"""Tests del SyncReposAdapter.

Validamos que:
- ``AsyncRunner`` ejecuta corutinas y devuelve resultados.
- Multiples llamadas no rompen el binding del engine async.
- Los wrappers sincronos atraviesan transactional_session correctamente
  (insert + read-back).
"""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from streaming_bot.domain.entities import Account
from streaming_bot.domain.modem import Modem, ModemHardware
from streaming_bot.domain.song import (
    Distributor,
    Song,
    SongMetadata,
    SongRole,
    SongTier,
)
from streaming_bot.domain.value_objects import Country
from streaming_bot.infrastructure.persistence.postgres.database import (
    transactional_session,
)
from streaming_bot.infrastructure.persistence.postgres.repos.account_repository import (
    PostgresAccountRepository,
)
from streaming_bot.infrastructure.persistence.postgres.repos.modem_repository import (
    PostgresModemRepository,
)
from streaming_bot.infrastructure.persistence.postgres.repos.song_repository import (
    PostgresSongRepository,
)
from streaming_bot.presentation.dashboard.repos_adapter import (
    AsyncRunner,
    SyncReposAdapter,
)


def test_runner_runs_simple_coroutine() -> None:
    runner = AsyncRunner()
    try:

        async def _hello() -> str:
            return "hi"

        assert runner.run(_hello()) == "hi"
        assert runner.run(_hello()) == "hi"
    finally:
        runner.shutdown()


def test_runner_uses_dedicated_loop() -> None:
    runner = AsyncRunner()
    try:

        async def _loop_id() -> int:
            return id(asyncio.get_running_loop())

        first = runner.run(_loop_id())
        second = runner.run(_loop_id())
        assert first == second
    finally:
        runner.shutdown()


def test_list_target_songs_roundtrip(
    repos: SyncReposAdapter,
    session_factory: async_sessionmaker[AsyncSession],
    runner: AsyncRunner,
) -> None:
    song = Song(
        spotify_uri="spotify:track:test1",
        title="Test Song",
        artist_name="Test Artist",
        artist_uri="spotify:artist:1",
        role=SongRole.TARGET,
        metadata=SongMetadata(duration_seconds=180),
        distributor=Distributor.DISTROKID,
        baseline_streams_per_day=10.0,
        target_streams_per_day=40,
        tier=SongTier.LOW,
    )

    async def _seed() -> None:
        async with transactional_session(session_factory) as session:
            repo = PostgresSongRepository(session)
            await repo.add(song)

    runner.run(_seed())

    listed = repos.list_target_songs()
    assert len(listed) == 1
    assert listed[0].spotify_uri == "spotify:track:test1"
    assert repos.count_active_targets() == 1


def test_list_pilot_eligible_filters_flagged(
    repos: SyncReposAdapter,
    session_factory: async_sessionmaker[AsyncSession],
    runner: AsyncRunner,
) -> None:
    eligible = Song(
        spotify_uri="spotify:track:elig",
        title="Elig",
        artist_name="A",
        artist_uri="spotify:artist:a",
        role=SongRole.TARGET,
        metadata=SongMetadata(duration_seconds=180),
        baseline_streams_per_day=5.0,
        target_streams_per_day=30,
    )
    flagged = Song(
        spotify_uri="spotify:track:flag",
        title="Flag",
        artist_name="A",
        artist_uri="spotify:artist:a",
        role=SongRole.TARGET,
        metadata=SongMetadata(duration_seconds=180),
        baseline_streams_per_day=10.0,
        target_streams_per_day=40,
        spike_oct2025_flag=True,
    )

    async def _seed() -> None:
        async with transactional_session(session_factory) as session:
            repo = PostgresSongRepository(session)
            await repo.add(eligible)
            await repo.add(flagged)

    runner.run(_seed())

    pilot = repos.list_pilot_eligible(max_songs=10)
    uris = {s.spotify_uri for s in pilot}
    assert "spotify:track:elig" in uris
    assert "spotify:track:flag" not in uris


def test_update_song_persists_is_active_toggle(
    repos: SyncReposAdapter,
    session_factory: async_sessionmaker[AsyncSession],
    runner: AsyncRunner,
) -> None:
    song = Song(
        spotify_uri="spotify:track:upd",
        title="Upd",
        artist_name="X",
        artist_uri="spotify:artist:x",
        role=SongRole.TARGET,
        metadata=SongMetadata(duration_seconds=180),
        baseline_streams_per_day=20.0,
        target_streams_per_day=80,
    )

    async def _seed() -> None:
        async with transactional_session(session_factory) as session:
            await PostgresSongRepository(session).add(song)

    runner.run(_seed())

    fetched = repos.list_target_songs()[0]
    fetched.is_active = False
    repos.update_song(fetched)

    again = repos.list_target_songs()[0]
    assert again.is_active is False


def test_list_accounts_and_modems_empty(repos: SyncReposAdapter) -> None:
    assert repos.list_accounts() == []
    assert repos.list_modems() == []


def test_list_accounts_returns_inserted(
    repos: SyncReposAdapter,
    session_factory: async_sessionmaker[AsyncSession],
    runner: AsyncRunner,
) -> None:
    account = Account.new(
        username="alice@example.com",
        password="cypher",
        country=Country.PE,
    )

    async def _seed() -> None:
        async with transactional_session(session_factory) as session:
            await PostgresAccountRepository(session).add(account)

    runner.run(_seed())

    listed = repos.list_accounts()
    assert len(listed) == 1
    assert listed[0].username == "alice@example.com"


def test_list_modems_returns_inserted(
    repos: SyncReposAdapter,
    session_factory: async_sessionmaker[AsyncSession],
    runner: AsyncRunner,
) -> None:
    modem = Modem.new(
        hardware=ModemHardware(
            imei="86010012345",
            iccid="89510320",
            model="Quectel EG25",
            serial_port="/dev/ttyUSB0",
            operator="Movistar PE",
            sim_country=Country.PE,
        )
    )

    async def _seed() -> None:
        async with transactional_session(session_factory) as session:
            await PostgresModemRepository(session).add(modem)

    runner.run(_seed())

    listed = repos.list_modems()
    assert len(listed) == 1
    assert listed[0].hardware.operator == "Movistar PE"


def test_list_recent_sessions_empty(repos: SyncReposAdapter) -> None:
    assert repos.list_recent_sessions(limit=10) == []
