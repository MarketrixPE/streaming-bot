"""Tests para PostgresArtistRepository."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from streaming_bot.domain.artist import Artist, ArtistStatus
from streaming_bot.domain.value_objects import Country
from streaming_bot.infrastructure.persistence.postgres.repos.artist_repository import (
    PostgresArtistRepository,
)


def _make_artist(
    *,
    name: str = "Tony Jaxx",
    spotify_uri: str | None = "spotify:artist:001",
    status: ArtistStatus = ArtistStatus.ACTIVE,
) -> Artist:
    return (
        Artist.new(
            name=name,
            spotify_uri=spotify_uri,
            primary_country=Country.MX,
        )
        if status == ArtistStatus.ACTIVE
        else Artist(
            id="artist-fixed-1",
            name=name,
            spotify_uri=spotify_uri,
            primary_country=Country.MX,
            status=status,
        )
    )


async def test_save_and_get(session: AsyncSession) -> None:
    repo = PostgresArtistRepository(session)
    artist = _make_artist()
    await repo.save(artist)

    fetched = await repo.get(artist.id)

    assert fetched is not None
    assert fetched.name == "Tony Jaxx"
    assert fetched.spotify_uri == "spotify:artist:001"


async def test_save_idempotent(session: AsyncSession) -> None:
    repo = PostgresArtistRepository(session)
    artist = _make_artist()
    await repo.save(artist)

    artist.notes = "after_update"
    await repo.save(artist)

    fetched = await repo.get(artist.id)
    assert fetched is not None
    assert fetched.notes == "after_update"


async def test_get_by_spotify_uri(session: AsyncSession) -> None:
    repo = PostgresArtistRepository(session)
    artist = _make_artist(spotify_uri="spotify:artist:test-uri")
    await repo.save(artist)

    fetched = await repo.get_by_spotify_uri("spotify:artist:test-uri")

    assert fetched is not None
    assert fetched.id == artist.id


async def test_get_by_name(session: AsyncSession) -> None:
    repo = PostgresArtistRepository(session)
    artist = _make_artist(name="Distinct Name")
    await repo.save(artist)

    fetched = await repo.get_by_name("Distinct Name")

    assert fetched is not None
    assert fetched.id == artist.id


async def test_list_active_excludes_paused(session: AsyncSession) -> None:
    repo = PostgresArtistRepository(session)
    a1 = _make_artist(name="A1", spotify_uri="spotify:artist:a1")
    a2 = _make_artist(name="A2", spotify_uri="spotify:artist:a2")
    a2.pause("test")
    await repo.save(a1)
    await repo.save(a2)

    active = await repo.list_active()

    assert len(active) == 1
    assert active[0].name == "A1"


async def test_list_by_status(session: AsyncSession) -> None:
    repo = PostgresArtistRepository(session)
    a1 = _make_artist(name="X1", spotify_uri="spotify:artist:x1")
    a2 = _make_artist(name="X2", spotify_uri="spotify:artist:x2")
    a2.archive()
    await repo.save(a1)
    await repo.save(a2)

    archived = await repo.list_by_status(ArtistStatus.ARCHIVED)

    assert len(archived) == 1
    assert archived[0].name == "X2"


async def test_list_all_orders_by_name(session: AsyncSession) -> None:
    repo = PostgresArtistRepository(session)
    a1 = _make_artist(name="Zeta", spotify_uri="spotify:artist:z")
    a2 = _make_artist(name="Alfa", spotify_uri="spotify:artist:a")
    await repo.save(a1)
    await repo.save(a2)

    listed = await repo.list_all()

    assert [x.name for x in listed] == ["Alfa", "Zeta"]


async def test_delete_removes(session: AsyncSession) -> None:
    repo = PostgresArtistRepository(session)
    artist = _make_artist()
    await repo.save(artist)

    await repo.delete(artist.id)
    fetched = await repo.get(artist.id)

    assert fetched is None
