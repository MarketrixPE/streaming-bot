"""Tests del PostgresStreamHistoryRepository y PostgresSessionRecordRepository."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from streaming_bot.domain.entities import Account, AccountStatus
from streaming_bot.domain.exceptions import DomainError
from streaming_bot.domain.history import (
    BehaviorEvent,
    BehaviorType,
    SessionRecord,
    StreamHistory,
    StreamOutcome,
)
from streaming_bot.domain.song import Distributor, Song, SongMetadata, SongRole
from streaming_bot.domain.value_objects import Country
from streaming_bot.infrastructure.persistence.postgres.repos.account_repository import (
    PostgresAccountRepository,
)
from streaming_bot.infrastructure.persistence.postgres.repos.history_repository import (
    PostgresSessionRecordRepository,
    PostgresStreamHistoryRepository,
)
from streaming_bot.infrastructure.persistence.postgres.repos.song_repository import (
    PostgresSongRepository,
)


async def _seed_account_and_song(session: AsyncSession) -> tuple[str, str]:
    account_repo = PostgresAccountRepository(session)
    song_repo = PostgresSongRepository(session)
    account = Account(
        id="acc-history",
        username="history_user",
        password="cipher",
        country=Country.PE,
        status=AccountStatus.active(),
    )
    await account_repo.add(account)
    song = Song(
        spotify_uri="spotify:track:hist",
        title="Hist",
        artist_name="Tony",
        artist_uri="spotify:artist:tj",
        role=SongRole.TARGET,
        metadata=SongMetadata(duration_seconds=180, isrc="ABC"),
        distributor=Distributor.DISTROKID,
        baseline_streams_per_day=10.0,
        target_streams_per_day=40,
    )
    await song_repo.add(song)
    return account.id, song.spotify_uri


async def test_stream_history_add_and_count_today(session: AsyncSession) -> None:
    account_id, song_uri = await _seed_account_and_song(session)
    repo = PostgresStreamHistoryRepository(session)

    now = datetime.now(UTC)
    history = StreamHistory.new(
        account_id=account_id,
        song_uri=song_uri,
        artist_uri="spotify:artist:tj",
        occurred_at=now,
        duration_listened_seconds=42,
        outcome=StreamOutcome.COUNTED,
    )
    await repo.add(history)

    count_account = await repo.count_for_account_today(account_id)
    by_uri = await repo.list_for_song_uri(song_uri)

    assert count_account == 1
    assert len(by_uri) == 1
    assert by_uri[0].outcome == StreamOutcome.COUNTED


async def test_stream_history_add_unknown_song_raises(session: AsyncSession) -> None:
    account_id, _ = await _seed_account_and_song(session)
    repo = PostgresStreamHistoryRepository(session)
    bogus = StreamHistory.new(
        account_id=account_id,
        song_uri="spotify:track:not-existing",
        artist_uri="spotify:artist:x",
        occurred_at=datetime.now(UTC),
    )

    with pytest.raises(DomainError):
        await repo.add(bogus)


async def test_session_record_round_trip_with_events(session: AsyncSession) -> None:
    account_id, song_uri = await _seed_account_and_song(session)
    repo = PostgresSessionRecordRepository(session)

    started = datetime(2026, 4, 27, 18, 0, tzinfo=UTC)
    record = SessionRecord.new(
        account_id=account_id,
        started_at=started,
        proxy_country="PE",
    )
    record.target_streams_attempted = 3
    record.camouflage_streams_attempted = 5
    record.completed_normally = True
    record.ended_at = started + timedelta(minutes=45)
    record.add_event(
        BehaviorEvent.new(
            session_id=record.session_id,
            type=BehaviorType.LIKE,
            occurred_at=started + timedelta(minutes=10),
            target_uri=song_uri,
            duration_ms=120,
        ),
    )

    await repo.add(record)
    fetched = await repo.get(record.session_id)

    assert fetched is not None
    assert fetched.target_streams_attempted == 3
    assert fetched.camouflage_streams_attempted == 5
    assert fetched.completed_normally is True
    assert len(fetched.behavior_events) == 1
    assert fetched.behavior_events[0].type == BehaviorType.LIKE


async def test_session_record_list_for_account_orders_desc(
    session: AsyncSession,
) -> None:
    account_id, _ = await _seed_account_and_song(session)
    repo = PostgresSessionRecordRepository(session)

    older = SessionRecord.new(
        account_id=account_id,
        started_at=datetime(2026, 4, 25, 18, 0, tzinfo=UTC),
    )
    newer = SessionRecord.new(
        account_id=account_id,
        started_at=datetime(2026, 4, 27, 18, 0, tzinfo=UTC),
    )
    await repo.add(older)
    await repo.add(newer)

    records = await repo.list_for_account(account_id, limit=10)

    assert [r.session_id for r in records] == [newer.session_id, older.session_id]
