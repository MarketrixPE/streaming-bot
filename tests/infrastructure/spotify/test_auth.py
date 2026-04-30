"""Tests para SpotifyTokenCache (OAuth flows)."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import httpx
import pytest

from streaming_bot.infrastructure.spotify.auth import SpotifyTokenCache
from streaming_bot.infrastructure.spotify.config import SpotifyAuthMode, SpotifyConfig
from streaming_bot.infrastructure.spotify.errors import SpotifyAuthError

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.fixture
def config_client_credentials() -> SpotifyConfig:
    return SpotifyConfig(
        client_id="test_client_id",
        client_secret="test_client_secret",
    )


@pytest.fixture
def config_refresh_token() -> SpotifyConfig:
    return SpotifyConfig(
        client_id="test_client_id",
        client_secret="test_client_secret",
        user_refresh_token="test_refresh_token",
    )


@pytest.mark.asyncio
async def test_client_credentials_flow_caches_token(
    config_client_credentials: SpotifyConfig,
) -> None:
    """El flujo client_credentials cachea el token y no lo refresca si sigue válido."""

    def mock_response(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"access_token": "mock_access_token", "expires_in": 3600},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock_response)) as client:
        cache = SpotifyTokenCache(config_client_credentials, client)

        token1 = await cache.get_token()
        token2 = await cache.get_token()

        assert token1 == "mock_access_token"
        assert token2 == token1


@pytest.mark.asyncio
async def test_client_credentials_refreshes_when_expired(
    config_client_credentials: SpotifyConfig,
    mocker: MockerFixture,
) -> None:
    """El token se refresca cuando expira (considerando 60s de safety)."""

    call_count = 0

    def mock_response(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            200,
            json={"access_token": f"token_{call_count}", "expires_in": 3600},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock_response)) as client:
        cache = SpotifyTokenCache(config_client_credentials, client)

        token1 = await cache.get_token()
        assert token1 == "token_1"

        mocker.patch("time.time", return_value=time.time() + 3600)

        token2 = await cache.get_token()
        assert token2 == "token_2"


@pytest.mark.asyncio
async def test_refresh_token_flow(config_refresh_token: SpotifyConfig) -> None:
    """El flujo refresh_token obtiene un access token de usuario."""

    def mock_response(request: httpx.Request) -> httpx.Response:
        body = request.read().decode("utf-8")
        assert "grant_type=refresh_token" in body
        assert "refresh_token=test_refresh_token" in body
        return httpx.Response(
            200,
            json={"access_token": "user_access_token", "expires_in": 3600},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock_response)) as client:
        cache = SpotifyTokenCache(config_refresh_token, client)

        token = await cache.get_token(requires_user_token=True)
        assert token == "user_access_token"


@pytest.mark.asyncio
async def test_force_refresh(config_client_credentials: SpotifyConfig) -> None:
    """force_refresh() fuerza un nuevo token incluso si el actual es válido."""

    call_count = 0

    def mock_response(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            200,
            json={"access_token": f"token_{call_count}", "expires_in": 3600},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock_response)) as client:
        cache = SpotifyTokenCache(config_client_credentials, client)

        token1 = await cache.get_token()
        assert token1 == "token_1"

        await cache.force_refresh()

        token2 = await cache.get_token()
        assert token2 == "token_2"


@pytest.mark.asyncio
async def test_requires_user_token_without_refresh_token_fails(
    config_client_credentials: SpotifyConfig,
) -> None:
    """Si requires_user_token=True pero no hay refresh_token, lanza SpotifyAuthError."""

    def mock_response(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"access_token": "token", "expires_in": 3600},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock_response)) as client:
        cache = SpotifyTokenCache(config_client_credentials, client)

        with pytest.raises(SpotifyAuthError, match="User token required"):
            await cache.get_token(requires_user_token=True)


@pytest.mark.asyncio
async def test_auth_failure_raises_error(config_client_credentials: SpotifyConfig) -> None:
    """Si la API devuelve 4xx en auth, lanza SpotifyAuthError."""

    def mock_response(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid_client"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock_response)) as client:
        cache = SpotifyTokenCache(config_client_credentials, client)

        with pytest.raises(SpotifyAuthError, match="Client credentials auth failed"):
            await cache.get_token()


@pytest.mark.asyncio
async def test_config_determines_auth_mode() -> None:
    """SpotifyConfig.auth_mode devuelve el modo correcto según la config."""
    config_cc = SpotifyConfig(client_id="id", client_secret="secret")
    assert config_cc.auth_mode == SpotifyAuthMode.CLIENT_CREDENTIALS

    config_rt = SpotifyConfig(
        client_id="id",
        client_secret="secret",
        user_refresh_token="refresh",
    )
    assert config_rt.auth_mode == SpotifyAuthMode.REFRESH_TOKEN
