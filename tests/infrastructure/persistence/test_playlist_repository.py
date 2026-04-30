"""Tests del PostgresPlaylistRepository (incluye list_targeting_song)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from streaming_bot.domain.playlist import (
    Playlist,
    PlaylistKind,
    PlaylistTrack,
    PlaylistVisibility,
)
from streaming_bot.domain.value_objects import Country
from streaming_bot.infrastructure.persistence.postgres.repos.playlist_repository import (
    PostgresPlaylistRepository,
)


def _make_playlist(
    *,
    name: str,
    kind: PlaylistKind = PlaylistKind.PERSONAL_PRIVATE,
    territory: Country | None = Country.PE,
    target_uri: str | None = None,
) -> Playlist:
    pl = Playlist.new(
        name=name,
        kind=kind,
        visibility=PlaylistVisibility.PRIVATE,
        territory=territory,
        genre="reggaeton",
    )
    pl.add_track(
        PlaylistTrack(
            track_uri="spotify:track:camo-1",
            position=0,
            is_target=False,
            duration_ms=180_000,
            artist_uri="spotify:artist:camo",
            title="Camo One",
        ),
    )
    if target_uri is not None:
        pl.add_track(
            PlaylistTrack(
                track_uri=target_uri,
                position=1,
                is_target=True,
                duration_ms=200_000,
                artist_uri="spotify:artist:tonyjaxx",
                title="Tony Jaxx Target",
            ),
        )
    return pl


async def test_add_and_get_with_tracks(session: AsyncSession) -> None:
    repo = PostgresPlaylistRepository(session)
    pl = _make_playlist(name="LATAM Boost", target_uri="spotify:track:tj-1")

    await repo.add(pl)
    fetched = await repo.get(pl.id)

    assert fetched is not None
    assert fetched.total_tracks == 2
    assert fetched.target_tracks[0].track_uri == "spotify:track:tj-1"


async def test_list_by_kind_filters(session: AsyncSession) -> None:
    repo = PostgresPlaylistRepository(session)
    project = _make_playlist(name="Public 1", kind=PlaylistKind.PROJECT_PUBLIC)
    personal = _make_playlist(name="Private 1", kind=PlaylistKind.PERSONAL_PRIVATE)
    await repo.add(project)
    await repo.add(personal)

    personals = await repo.list_by_kind(PlaylistKind.PERSONAL_PRIVATE)

    assert {p.id for p in personals} == {personal.id}


async def test_list_targeting_song_returns_only_targets(
    session: AsyncSession,
) -> None:
    repo = PostgresPlaylistRepository(session)
    target_uri = "spotify:track:tj-target"
    has_target = _make_playlist(name="With target", target_uri=target_uri)
    only_camo = _make_playlist(name="No target", target_uri=None)
    await repo.add(has_target)
    await repo.add(only_camo)

    matches = await repo.list_targeting_song(target_uri)

    assert {p.id for p in matches} == {has_target.id}


async def test_update_replaces_tracks(session: AsyncSession) -> None:
    repo = PostgresPlaylistRepository(session)
    pl = _make_playlist(name="Mutable", target_uri="spotify:track:old")
    await repo.add(pl)

    pl.tracks.clear()
    pl.add_track(
        PlaylistTrack(
            track_uri="spotify:track:new",
            position=0,
            is_target=True,
            artist_uri="spotify:artist:tonyjaxx",
            title="New Target",
        ),
    )
    await repo.update(pl)

    refreshed = await repo.get(pl.id)
    assert refreshed is not None
    assert {t.track_uri for t in refreshed.tracks} == {"spotify:track:new"}
