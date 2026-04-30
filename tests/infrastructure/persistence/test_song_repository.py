"""Tests del PostgresSongRepository (incluye filtro pilot_eligible)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from streaming_bot.domain.song import Distributor, Song, SongMetadata, SongRole
from streaming_bot.domain.value_objects import Country
from streaming_bot.infrastructure.persistence.postgres.repos.song_repository import (
    PostgresSongRepository,
)


def _make_song(
    *,
    uri: str,
    role: SongRole = SongRole.TARGET,
    baseline: float = 5.0,
    isrc: str | None = None,
    distribution: dict[Country, float] | None = None,
) -> Song:
    return Song(
        spotify_uri=uri,
        title=f"Song-{uri}",
        artist_name="Tony Jaxx",
        artist_uri="spotify:artist:001",
        role=role,
        metadata=SongMetadata(duration_seconds=180, isrc=isrc),
        distributor=Distributor.DISTROKID,
        baseline_streams_per_day=baseline,
        target_streams_per_day=int(baseline * 4) or 50,
        top_country_distribution=distribution or {},
    )


async def test_add_and_get_by_uri(session: AsyncSession) -> None:
    repo = PostgresSongRepository(session)
    song = _make_song(uri="spotify:track:abc", isrc="QM-XYZ-26-00001")

    await repo.add(song)
    fetched = await repo.get_by_uri("spotify:track:abc")

    assert fetched is not None
    assert fetched.title == "Song-spotify:track:abc"
    assert fetched.metadata.isrc == "QM-XYZ-26-00001"


async def test_get_by_isrc_returns_match(session: AsyncSession) -> None:
    repo = PostgresSongRepository(session)
    await repo.add(_make_song(uri="spotify:track:1", isrc="ABC123"))

    fetched = await repo.get_by_isrc("ABC123")

    assert fetched is not None
    assert fetched.spotify_uri == "spotify:track:1"


async def test_list_by_role_filters(session: AsyncSession) -> None:
    repo = PostgresSongRepository(session)
    await repo.add(_make_song(uri="spotify:track:t", role=SongRole.TARGET))
    await repo.add(_make_song(uri="spotify:track:c", role=SongRole.CAMOUFLAGE))

    targets = await repo.list_by_role(SongRole.TARGET)
    camo = await repo.list_by_role(SongRole.CAMOUFLAGE)

    assert {s.spotify_uri for s in targets} == {"spotify:track:t"}
    assert {s.spotify_uri for s in camo} == {"spotify:track:c"}


async def test_list_pilot_eligible_excludes_high_and_spike(
    session: AsyncSession,
) -> None:
    repo = PostgresSongRepository(session)
    # zombie + low + mid + high + uno con spike flag
    zombie = _make_song(uri="spotify:track:z", baseline=2.0)
    low = _make_song(uri="spotify:track:l", baseline=50.0)
    mid = _make_song(uri="spotify:track:m", baseline=300.0)
    high = _make_song(uri="spotify:track:h", baseline=900.0)
    flagged = _make_song(uri="spotify:track:f", baseline=80.0)
    camo = _make_song(uri="spotify:track:c2", baseline=20.0, role=SongRole.CAMOUFLAGE)

    for s in (zombie, low, mid, high, flagged, camo):
        await repo.add(s)
    await repo.mark_spike_oct2025(spotify_uri="spotify:track:f")

    eligible = await repo.list_pilot_eligible(max_songs=10)

    uris = {s.spotify_uri for s in eligible}
    assert uris == {"spotify:track:z", "spotify:track:l", "spotify:track:m"}


async def test_count_active_targets(session: AsyncSession) -> None:
    repo = PostgresSongRepository(session)
    await repo.add(_make_song(uri="spotify:track:a"))
    await repo.add(_make_song(uri="spotify:track:b"))
    inactive = _make_song(uri="spotify:track:c")
    inactive.is_active = False
    await repo.add(inactive)

    count = await repo.count_active_targets()

    assert count == 2


async def test_list_targets_by_market_filters_by_distribution(
    session: AsyncSession,
) -> None:
    repo = PostgresSongRepository(session)
    pe_song = _make_song(
        uri="spotify:track:pe",
        distribution={Country.PE: 0.6, Country.MX: 0.2},
    )
    mx_only = _make_song(
        uri="spotify:track:mx",
        distribution={Country.MX: 0.9},
    )
    await repo.add(pe_song)
    await repo.add(mx_only)

    pe_results = await repo.list_targets_by_market(Country.PE)

    assert {s.spotify_uri for s in pe_results} == {"spotify:track:pe"}
