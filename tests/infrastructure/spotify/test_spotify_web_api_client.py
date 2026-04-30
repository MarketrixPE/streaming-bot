"""Tests para SpotifyWebApiClient con httpx.MockTransport."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock

import httpx
import pytest

from streaming_bot.domain.value_objects import Country
from streaming_bot.infrastructure.spotify.config import SpotifyConfig
from streaming_bot.infrastructure.spotify.errors import SpotifyApiError, SpotifyAuthError
from streaming_bot.infrastructure.spotify.spotify_web_api_client import SpotifyWebApiClient

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.fixture
def config() -> SpotifyConfig:
    return SpotifyConfig(
        client_id="test_client_id",
        client_secret="test_client_secret",
    )


@pytest.fixture
def config_with_user_token() -> SpotifyConfig:
    return SpotifyConfig(
        client_id="test_client_id",
        client_secret="test_client_secret",
        user_refresh_token="test_refresh_token",
    )


def make_track_payload(track_id: str, *, isrc: str | None = None) -> dict[str, Any]:
    """Helper para generar un payload de track de la API."""
    payload: dict[str, Any] = {
        "uri": f"spotify:track:{track_id}",
        "name": f"Track {track_id}",
        "duration_ms": 180000,
        "artists": [
            {"uri": "spotify:artist:artist1", "name": "Artist One"},
        ],
        "album": {"uri": "spotify:album:album1"},
        "popularity": 75,
        "explicit": False,
    }
    if isrc:
        payload["external_ids"] = {"isrc": isrc}
    return payload


@pytest.mark.asyncio
async def test_get_track_parses_uri_and_maps_dto(config: SpotifyConfig) -> None:
    """get_track() parsea la URI y mapea correctamente el DTO con ISRC."""

    def mock_response(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})

        assert request.url.path == "/v1/tracks/abc123"
        return httpx.Response(200, json=make_track_payload("abc123", isrc="USRC12345678"))

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(mock_response)) as client,
        SpotifyWebApiClient(config, client) as spotify,
    ):
        track = await spotify.get_track("spotify:track:abc123")

    assert track is not None
    assert track.uri == "spotify:track:abc123"
    assert track.name == "Track abc123"
    assert track.isrc == "USRC12345678"
    assert track.artist_uris == ("spotify:artist:artist1",)
    assert track.artist_names == ("Artist One",)


@pytest.mark.asyncio
async def test_get_track_returns_none_on_404(config: SpotifyConfig) -> None:
    """get_track() devuelve None si el track no existe (404)."""

    def mock_response(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        return httpx.Response(404, json={"error": {"status": 404, "message": "Not found"}})

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(mock_response)) as client,
        SpotifyWebApiClient(config, client) as spotify,
    ):
        track = await spotify.get_track("spotify:track:notfound")

    assert track is None


@pytest.mark.asyncio
async def test_get_tracks_batch_chunks_to_50(config: SpotifyConfig) -> None:
    """get_tracks_batch() con 75 URIs hace 2 llamadas (50 + 25)."""

    call_count = 0

    def mock_response(request: httpx.Request) -> httpx.Response:
        nonlocal call_count

        if request.url.path == "/api/token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})

        if request.url.path == "/v1/tracks":
            call_count += 1
            ids = str(request.url.params.get("ids", "")).split(",")
            tracks = [make_track_payload(tid) for tid in ids]
            return httpx.Response(200, json={"tracks": tracks})

        return httpx.Response(400, json={})

    uris = [f"spotify:track:track{i:03d}" for i in range(75)]

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(mock_response)) as client,
        SpotifyWebApiClient(config, client) as spotify,
    ):
        tracks = await spotify.get_tracks_batch(uris)

    assert len(tracks) == 75
    assert call_count == 2


@pytest.mark.asyncio
async def test_search_tracks_sends_correct_params(config: SpotifyConfig) -> None:
    """search_tracks() envía los parámetros correctos."""

    def mock_response(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})

        assert request.url.path == "/v1/search"
        assert request.url.params["q"] == "test query"
        assert request.url.params["type"] == "track"
        assert request.url.params["market"] == "MX"
        assert request.url.params["limit"] == "10"

        return httpx.Response(
            200,
            json={"tracks": {"items": [make_track_payload("search1")]}},
        )

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(mock_response)) as client,
        SpotifyWebApiClient(config, client) as spotify,
    ):
        tracks = await spotify.search_tracks(query="test query", market=Country.MX, limit=10)

    assert len(tracks) == 1


@pytest.mark.asyncio
async def test_get_playlist_tracks_pagination_and_skips_nulls(config: SpotifyConfig) -> None:
    """get_playlist_tracks() pagina y skipea items con track: None."""

    call_count = 0

    def mock_response(request: httpx.Request) -> httpx.Response:
        nonlocal call_count

        if request.url.path == "/api/token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})

        if "/tracks" in request.url.path:
            call_count += 1
            if call_count == 1:
                return httpx.Response(
                    200,
                    json={
                        "items": [
                            {"track": make_track_payload("track1")},
                            {"track": None},
                        ],
                        "next": "https://api.spotify.com/v1/playlists/playlist1/tracks?offset=2",
                    },
                )
            return httpx.Response(
                200,
                json={
                    "items": [{"track": make_track_payload("track2")}],
                    "next": None,
                },
            )

        return httpx.Response(400, json={})

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(mock_response)) as client,
        SpotifyWebApiClient(config, client) as spotify,
    ):
        tracks = await spotify.get_playlist_tracks("spotify:playlist:playlist1")

    assert len(tracks) == 2
    assert tracks[0].uri == "spotify:track:track1"
    assert tracks[1].uri == "spotify:track:track2"
    assert call_count == 2


@pytest.mark.asyncio
async def test_create_playlist_sends_correct_body(config_with_user_token: SpotifyConfig) -> None:
    """create_playlist() envía el body correcto y devuelve DTO con spotify_id."""

    def mock_response(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})

        assert request.url.path == "/v1/users/user123/playlists"
        body = request.read()
        assert b'"name":"My Playlist"' in body
        assert b'"description":"Test desc"' in body
        assert b'"public":true' in body

        return httpx.Response(
            200,
            json={
                "uri": "spotify:playlist:new_playlist",
                "id": "new_playlist",
                "name": "My Playlist",
                "description": "Test desc",
                "owner": {"id": "user123"},
                "public": True,
            },
        )

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(mock_response)) as client,
        SpotifyWebApiClient(config_with_user_token, client) as spotify,
    ):
        playlist = await spotify.create_playlist(
            owner_user_id="user123",
            name="My Playlist",
            description="Test desc",
            public=True,
        )

    assert playlist.spotify_id == "new_playlist"
    assert playlist.name == "My Playlist"


@pytest.mark.asyncio
async def test_add_tracks_to_playlist_chunks_to_100(config_with_user_token: SpotifyConfig) -> None:
    """add_tracks_to_playlist() con 250 URIs hace 3 llamadas."""

    call_count = 0

    def mock_response(request: httpx.Request) -> httpx.Response:
        nonlocal call_count

        if request.url.path == "/api/token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})

        if "/tracks" in request.url.path:
            call_count += 1
            return httpx.Response(200, json={})

        return httpx.Response(400, json={})

    uris = [f"spotify:track:track{i:03d}" for i in range(250)]

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(mock_response)) as client,
        SpotifyWebApiClient(config_with_user_token, client) as spotify,
    ):
        await spotify.add_tracks_to_playlist(playlist_id="playlist1", track_uris=uris)

    assert call_count == 3


@pytest.mark.asyncio
async def test_rate_limit_429_sleeps_and_retries(
    config: SpotifyConfig,
    mocker: MockerFixture,
) -> None:
    """Si la API devuelve 429, sleep(Retry-After) y reintenta."""

    call_count = 0
    mock_sleep = AsyncMock()
    mocker.patch("asyncio.sleep", mock_sleep)

    def mock_response(request: httpx.Request) -> httpx.Response:
        nonlocal call_count

        if request.url.path == "/api/token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})

        call_count += 1
        if call_count == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})

        return httpx.Response(200, json=make_track_payload("track1"))

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(mock_response)) as client,
        SpotifyWebApiClient(config, client) as spotify,
    ):
        track = await spotify.get_track("spotify:track:track1")

    assert track is not None
    mock_sleep.assert_awaited_once_with(2)


@pytest.mark.asyncio
async def test_401_triggers_force_refresh_and_retries_once(
    config: SpotifyConfig,
) -> None:
    """Si la API devuelve 401, force_refresh() y reintenta.
    Si vuelve 401, lanza SpotifyAuthError.
    """

    auth_call_count = 0
    api_call_count = 0

    def mock_response(request: httpx.Request) -> httpx.Response:
        nonlocal auth_call_count, api_call_count

        if request.url.path == "/api/token":
            auth_call_count += 1
            return httpx.Response(
                200,
                json={"access_token": f"token_{auth_call_count}", "expires_in": 3600},
            )

        api_call_count += 1
        if api_call_count == 1:
            return httpx.Response(401, json={"error": "unauthorized"})

        return httpx.Response(200, json=make_track_payload("track1"))

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(mock_response)) as client,
        SpotifyWebApiClient(config, client) as spotify,
    ):
        track = await spotify.get_track("spotify:track:track1")

    assert track is not None
    assert auth_call_count == 2
    assert api_call_count == 2


@pytest.mark.asyncio
async def test_401_twice_raises_auth_error(config: SpotifyConfig) -> None:
    """Si la API devuelve 401 dos veces consecutivas, lanza SpotifyAuthError."""

    def mock_response(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        return httpx.Response(401, json={"error": "unauthorized"})

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(mock_response)) as client,
        SpotifyWebApiClient(config, client) as spotify,
    ):
        with pytest.raises(SpotifyAuthError, match="Authentication failed"):
            await spotify.get_track("spotify:track:track1")


@pytest.mark.asyncio
async def test_503_retries_and_eventually_succeeds(config: SpotifyConfig) -> None:
    """Si la API devuelve 503, reintenta con exponential backoff y eventualmente acierta."""

    call_count = 0

    def mock_response(request: httpx.Request) -> httpx.Response:
        nonlocal call_count

        if request.url.path == "/api/token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})

        call_count += 1
        if call_count < 3:
            return httpx.Response(503, json={"error": "service unavailable"})

        return httpx.Response(200, json=make_track_payload("track1"))

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(mock_response)) as client,
        SpotifyWebApiClient(config, client) as spotify,
    ):
        track = await spotify.get_track("spotify:track:track1")

    assert track is not None
    assert call_count == 3


@pytest.mark.asyncio
async def test_404_raises_api_error(config: SpotifyConfig) -> None:
    """Un 404 en search lanza SpotifyApiError."""

    def mock_response(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        return httpx.Response(404, json={"error": "not found"})

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(mock_response)) as client,
        SpotifyWebApiClient(config, client) as spotify,
    ):
        with pytest.raises(SpotifyApiError) as exc_info:
            await spotify.search_tracks(query="test")

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_extract_id_validates_uri_format() -> None:
    """_extract_id() valida el formato de la URI."""
    client = SpotifyWebApiClient.__new__(SpotifyWebApiClient)

    assert client._extract_id("spotify:track:abc123", "track") == "abc123"
    assert client._extract_id("abc123", "track") == "abc123"

    with pytest.raises(ValueError, match="Invalid Spotify URI"):
        client._extract_id("spotify:artist:xyz", "track")


@pytest.mark.asyncio
async def test_context_manager_closes_owned_client(config: SpotifyConfig) -> None:
    """El context manager cierra el cliente HTTP si es propiedad de SpotifyWebApiClient."""
    async with SpotifyWebApiClient(config) as spotify:
        assert spotify._http_client is not None

    assert spotify._http_client.is_closed


@pytest.mark.asyncio
async def test_get_artist_top_tracks(config: SpotifyConfig) -> None:
    """get_artist_top_tracks() envía el market correcto."""

    def mock_response(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})

        assert "top-tracks" in request.url.path
        assert request.url.params["market"] == "CL"

        return httpx.Response(
            200,
            json={"tracks": [make_track_payload("top1")]},
        )

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(mock_response)) as client,
        SpotifyWebApiClient(config, client) as spotify,
    ):
        tracks = await spotify.get_artist_top_tracks(
            artist_uri="spotify:artist:artist1",
            market=Country.CL,
        )

    assert len(tracks) == 1


@pytest.mark.asyncio
async def test_reorder_playlist_tracks(config_with_user_token: SpotifyConfig) -> None:
    """reorder_playlist_tracks() envía el body correcto."""

    def mock_response(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})

        assert request.method == "PUT"
        body = request.read()
        assert b'"range_start":5' in body
        assert b'"insert_before":10' in body

        return httpx.Response(200, json={})

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(mock_response)) as client,
        SpotifyWebApiClient(config_with_user_token, client) as spotify,
    ):
        await spotify.reorder_playlist_tracks(
            playlist_id="playlist1",
            range_start=5,
            insert_before=10,
        )
