"""Tests del SoundcloudV2Client con httpx.MockTransport."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from streaming_bot.infrastructure.soundcloud.soundcloud_v2_client import (
    SoundcloudClientError,
    SoundcloudV2Client,
)


def _track_payload(track_id: int = 1234, *, playback: int = 5_000) -> dict[str, Any]:
    return {
        "id": track_id,
        "urn": f"soundcloud:tracks:{track_id}",
        "title": "test",
        "permalink_url": f"https://soundcloud.com/x/test-{track_id}",
        "duration": 180_000,
        "user": {"id": 999},
        "playback_count": playback,
        "likes_count": 12,
        "reposts_count": 3,
        "comment_count": 1,
        "monetization_model": "FREE",
        "publisher_metadata": {"isrc": "USRC12345678"},
    }


def _user_payload(user_id: int = 999, *, followers: int = 250) -> dict[str, Any]:
    return {
        "id": user_id,
        "permalink": "x",
        "username": "x",
        "followers_count": followers,
        "verified": False,
    }


def _make_homepage_html() -> str:
    return (
        "<!doctype html><html><head>"
        '<script src="https://a-v2.sndcdn.com/assets/0-bundle.js"></script>'
        '<script src="https://a-v2.sndcdn.com/assets/1-bundle.js"></script>'
        "</head><body></body></html>"
    )


def _bundle_with_client_id(client_id: str) -> str:
    return f'a=1;client_id="{client_id}";b=2;'


@pytest.fixture(autouse=True)
def _patch_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Eliminamos el rate-limit sleep para acelerar los tests."""

    async def _fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("asyncio.sleep", _fake_sleep)


class TestClientIdScraping:
    async def test_scrapes_client_id_from_first_bundle(self) -> None:
        homepage_calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url == "https://soundcloud.com/":
                homepage_calls["n"] += 1
                return httpx.Response(200, text=_make_homepage_html())
            if url.endswith("/0-bundle.js"):
                return httpx.Response(200, text="no client id here")
            if url.endswith("/1-bundle.js"):
                return httpx.Response(200, text=_bundle_with_client_id("ABCDEFG1234567890XYZ"))
            if url.startswith("https://api-v2.soundcloud.com/tracks/"):
                assert request.url.params["client_id"] == "ABCDEFG1234567890XYZ"
                return httpx.Response(200, json=_track_payload(1))
            return httpx.Response(404)

        async with (
            httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http,
            SoundcloudV2Client(http_client=http) as client,
        ):
            track = await client.get_track(1)

        assert track is not None
        assert track.track_id == 1
        assert homepage_calls["n"] == 1

    async def test_refreshes_client_id_on_401(self) -> None:
        client_ids_used: list[str] = []
        scrape_count = {"n": 0}
        ids_to_serve = iter(["FIRSTID0123456789012", "SECONDID01234567890XYZ"])

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url == "https://soundcloud.com/":
                scrape_count["n"] += 1
                return httpx.Response(200, text=_make_homepage_html())
            if url.endswith("/0-bundle.js"):
                return httpx.Response(
                    200,
                    text=_bundle_with_client_id(next(ids_to_serve)),
                )
            if url.endswith("/1-bundle.js"):
                return httpx.Response(200, text="nada")
            if url.startswith("https://api-v2.soundcloud.com/tracks/"):
                cid = str(request.url.params["client_id"])
                client_ids_used.append(cid)
                if cid == "FIRSTID0123456789012":
                    return httpx.Response(401, json={"error": "expired"})
                return httpx.Response(200, json=_track_payload(7))
            return httpx.Response(404)

        async with (
            httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http,
            SoundcloudV2Client(http_client=http) as client,
        ):
            track = await client.get_track(7)

        assert track is not None
        assert client_ids_used == ["FIRSTID0123456789012", "SECONDID01234567890XYZ"]
        assert scrape_count["n"] == 2


class TestGetTrack:
    async def test_returns_none_on_404(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url == "https://soundcloud.com/":
                return httpx.Response(200, text=_make_homepage_html())
            if "bundle.js" in url:
                return httpx.Response(200, text=_bundle_with_client_id("ABCDEFG12345678901234"))
            return httpx.Response(404, json={})

        async with (
            httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http,
            SoundcloudV2Client(http_client=http) as client,
        ):
            track = await client.get_track(999)

        assert track is None

    async def test_uses_cache_within_ttl(self) -> None:
        api_hits = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url == "https://soundcloud.com/":
                return httpx.Response(200, text=_make_homepage_html())
            if "bundle.js" in url:
                return httpx.Response(200, text=_bundle_with_client_id("ABCDEFG12345678901234"))
            if url.startswith("https://api-v2.soundcloud.com/tracks/"):
                api_hits["n"] += 1
                return httpx.Response(200, json=_track_payload(7, playback=42))
            return httpx.Response(404)

        async with (
            httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http,
            SoundcloudV2Client(http_client=http) as client,
        ):
            first = await client.get_track(7)
            second = await client.get_track(7)

        assert first == second
        assert api_hits["n"] == 1

    async def test_track_plays_count_returns_value(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url == "https://soundcloud.com/":
                return httpx.Response(200, text=_make_homepage_html())
            if "bundle.js" in url:
                return httpx.Response(200, text=_bundle_with_client_id("ABCDEFG12345678901234"))
            if url.startswith("https://api-v2.soundcloud.com/tracks/"):
                return httpx.Response(200, json=_track_payload(7, playback=8765))
            return httpx.Response(404)

        async with (
            httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http,
            SoundcloudV2Client(http_client=http) as client,
        ):
            count = await client.get_track_plays_count("soundcloud:tracks:7")

        assert count == 8765


class TestGetUser:
    async def test_get_user_by_numeric_id(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url == "https://soundcloud.com/":
                return httpx.Response(200, text=_make_homepage_html())
            if "bundle.js" in url:
                return httpx.Response(200, text=_bundle_with_client_id("ABCDEFG12345678901234"))
            if url.startswith("https://api-v2.soundcloud.com/users/"):
                return httpx.Response(200, json=_user_payload(42, followers=1234))
            return httpx.Response(404)

        async with (
            httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http,
            SoundcloudV2Client(http_client=http) as client,
        ):
            user = await client.get_user(42)

        assert user is not None
        assert user.user_id == 42
        assert user.followers_count == 1234


class TestSearchTracks:
    async def test_search_returns_collection(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url == "https://soundcloud.com/":
                return httpx.Response(200, text=_make_homepage_html())
            if "bundle.js" in url:
                return httpx.Response(200, text=_bundle_with_client_id("ABCDEFG12345678901234"))
            if "/search/tracks" in url:
                assert request.url.params["q"] == "query"
                assert request.url.params["limit"] == "5"
                return httpx.Response(
                    200,
                    json={"collection": [_track_payload(1), _track_payload(2)]},
                )
            return httpx.Response(404)

        async with (
            httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http,
            SoundcloudV2Client(http_client=http) as client,
        ):
            tracks = await client.search_tracks(query="query", limit=5)

        assert len(tracks) == 2


class TestErrors:
    async def test_homepage_no_bundles_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url) == "https://soundcloud.com/":
                return httpx.Response(200, text="<html><head></head><body></body></html>")
            return httpx.Response(404)

        async with (
            httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http,
            SoundcloudV2Client(http_client=http) as client,
        ):
            with pytest.raises(SoundcloudClientError, match="bundles js"):
                await client.get_track(1)

    async def test_no_client_id_in_bundles_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url == "https://soundcloud.com/":
                return httpx.Response(200, text=_make_homepage_html())
            if "bundle.js" in url:
                return httpx.Response(200, text="window.x = 1;")
            return httpx.Response(404)

        async with (
            httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http,
            SoundcloudV2Client(http_client=http) as client,
        ):
            with pytest.raises(SoundcloudClientError, match="client_id"):
                await client.get_track(1)
