"""Tests del router /v1 catalogo (tracks, artistas, labels)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from streaming_bot.config import Settings
from streaming_bot.domain.artist import Artist, ArtistStatus
from streaming_bot.domain.label import DistributorType, Label, LabelHealth
from streaming_bot.domain.song import Song, SongMetadata, SongRole, SongTier
from streaming_bot.domain.value_objects import Country
from streaming_bot.presentation.api.auth import JWTAuthValidator
from tests.presentation.conftest import build_app_with_overrides


def _make_song(
    *,
    spotify_uri: str = "spotify:track:abc",
    title: str = "Demo",
    role: SongRole = SongRole.TARGET,
    tier: SongTier = SongTier.MID,
) -> Song:
    return Song(
        spotify_uri=spotify_uri,
        title=title,
        artist_name="Artista Demo",
        artist_uri="spotify:artist:xyz",
        role=role,
        metadata=SongMetadata(duration_seconds=180, isrc="USRC11900001"),
        tier=tier,
        baseline_streams_per_day=100.0,
        target_streams_per_day=500,
        is_active=True,
    )


def _make_artist(name: str = "Artista Demo") -> Artist:
    now = datetime.now(UTC)
    return Artist(
        id="01ARTIST",
        name=name,
        spotify_uri="spotify:artist:xyz",
        primary_country=Country.PE,
        status=ArtistStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )


def _make_label(name: str = "Worldwide Hits") -> Label:
    now = datetime.now(UTC)
    return Label(
        id="01LABEL",
        name=name,
        distributor=DistributorType.DISTROKID,
        health=LabelHealth.HEALTHY,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_list_tracks_default_returns_targets(
    fake_settings: Settings,
    fake_validator: JWTAuthValidator,
    make_user,
) -> None:
    songs_repo = AsyncMock()
    songs_repo.list_by_role.return_value = [
        _make_song(),
        _make_song(spotify_uri="spotify:track:def"),
    ]
    app = build_app_with_overrides(
        settings=fake_settings,
        validator=fake_validator,
        user=make_user("viewer"),
        song_repo=songs_repo,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/v1/tracks")
    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 50
    assert body["total"] == 2
    assert body["next_cursor"] is None
    assert body["items"][0]["spotify_uri"] == "spotify:track:abc"
    assert body["items"][0]["tier"] == "mid"
    songs_repo.list_by_role.assert_awaited_once_with(SongRole.TARGET)


@pytest.mark.asyncio
async def test_list_tracks_filters_by_role(
    fake_settings: Settings,
    fake_validator: JWTAuthValidator,
    make_user,
) -> None:
    songs_repo = AsyncMock()
    songs_repo.list_by_role.return_value = [_make_song(role=SongRole.CAMOUFLAGE)]
    app = build_app_with_overrides(
        settings=fake_settings,
        validator=fake_validator,
        user=make_user(),
        song_repo=songs_repo,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/v1/tracks", params={"role": "camouflage"})
    assert response.status_code == 200
    songs_repo.list_by_role.assert_awaited_once_with(SongRole.CAMOUFLAGE)


@pytest.mark.asyncio
async def test_list_tracks_filters_by_market(
    fake_settings: Settings,
    fake_validator: JWTAuthValidator,
    make_user,
) -> None:
    songs_repo = AsyncMock()
    songs_repo.list_targets_by_market.return_value = [_make_song()]
    app = build_app_with_overrides(
        settings=fake_settings,
        validator=fake_validator,
        user=make_user(),
        song_repo=songs_repo,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/v1/tracks", params={"market": "PE"})
    assert response.status_code == 200
    songs_repo.list_targets_by_market.assert_awaited_once_with(Country.PE)


@pytest.mark.asyncio
async def test_list_tracks_invalid_market_returns_404(
    fake_settings: Settings,
    fake_validator: JWTAuthValidator,
    make_user,
) -> None:
    songs_repo = AsyncMock()
    app = build_app_with_overrides(
        settings=fake_settings,
        validator=fake_validator,
        user=make_user(),
        song_repo=songs_repo,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/v1/tracks", params={"market": "INVALID"})
    assert response.status_code == 404
    body = response.json()
    assert body["error_code"] == "market_not_found"
    assert body["request_id"]


@pytest.mark.asyncio
async def test_list_tracks_pagination_cursor(
    fake_settings: Settings,
    fake_validator: JWTAuthValidator,
    make_user,
) -> None:
    songs_repo = AsyncMock()
    songs_repo.list_by_role.return_value = [
        _make_song(spotify_uri=f"spotify:track:{i}") for i in range(5)
    ]
    app = build_app_with_overrides(
        settings=fake_settings,
        validator=fake_validator,
        user=make_user(),
        song_repo=songs_repo,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        first = await ac.get("/v1/tracks", params={"limit": 2})
        assert first.status_code == 200
        body = first.json()
        assert len(body["items"]) == 2
        assert body["next_cursor"] is not None
        second = await ac.get(
            "/v1/tracks",
            params={"limit": 2, "cursor": body["next_cursor"]},
        )
    assert second.status_code == 200
    second_body = second.json()
    assert len(second_body["items"]) == 2
    assert second_body["items"][0]["spotify_uri"] == "spotify:track:2"


@pytest.mark.asyncio
async def test_get_track_by_id_404(
    fake_settings: Settings,
    fake_validator: JWTAuthValidator,
    make_user,
) -> None:
    songs_repo = AsyncMock()
    songs_repo.get.return_value = None
    app = build_app_with_overrides(
        settings=fake_settings,
        validator=fake_validator,
        user=make_user(),
        song_repo=songs_repo,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/v1/tracks/missing-id")
    assert response.status_code == 404
    body = response.json()
    assert body["error_code"] == "track_not_found"


@pytest.mark.asyncio
async def test_get_track_by_id_ok(
    fake_settings: Settings,
    fake_validator: JWTAuthValidator,
    make_user,
) -> None:
    song = _make_song()
    songs_repo = AsyncMock()
    songs_repo.get.return_value = song
    app = build_app_with_overrides(
        settings=fake_settings,
        validator=fake_validator,
        user=make_user(),
        song_repo=songs_repo,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/v1/tracks/01TRACK")
    assert response.status_code == 200
    body = response.json()
    assert body["spotify_uri"] == song.spotify_uri
    songs_repo.get.assert_awaited_once_with("01TRACK")


@pytest.mark.asyncio
async def test_list_artists(
    fake_settings: Settings,
    fake_validator: JWTAuthValidator,
    make_user,
) -> None:
    artists_repo = AsyncMock()
    artists_repo.list_all.return_value = [_make_artist("Uno"), _make_artist("Dos")]
    app = build_app_with_overrides(
        settings=fake_settings,
        validator=fake_validator,
        user=make_user(),
        artist_repo=artists_repo,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/v1/artists")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert {item["name"] for item in body["items"]} == {"Uno", "Dos"}


@pytest.mark.asyncio
async def test_list_labels(
    fake_settings: Settings,
    fake_validator: JWTAuthValidator,
    make_user,
) -> None:
    labels_repo = AsyncMock()
    labels_repo.list_all.return_value = [_make_label()]
    app = build_app_with_overrides(
        settings=fake_settings,
        validator=fake_validator,
        user=make_user(),
        label_repo=labels_repo,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/v1/labels")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["distributor"] == "distrokid"
