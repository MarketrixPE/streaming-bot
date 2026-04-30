"""Gestión de tokens OAuth para Spotify Web API."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import httpx
import structlog

from streaming_bot.infrastructure.spotify.config import SpotifyAuthMode
from streaming_bot.infrastructure.spotify.errors import SpotifyAuthError

if TYPE_CHECKING:
    from streaming_bot.infrastructure.spotify.config import SpotifyConfig

logger = structlog.get_logger("streaming_bot.spotify.auth")


class SpotifyTokenCache:
    """Cache thread-safe de access token con refresh automático.

    Soporta dos flows OAuth:
    - client_credentials: token de app (solo lectura).
    - refresh_token: token de usuario (lectura + escritura).
    """

    def __init__(self, config: SpotifyConfig, http_client: httpx.AsyncClient) -> None:
        self._config = config
        self._http_client = http_client
        self._lock = asyncio.Lock()
        self._access_token: str | None = None
        self._expires_at: float = 0.0
        self._token_url = "https://accounts.spotify.com/api/token"  # noqa: S105

    async def get_token(self, *, requires_user_token: bool = False) -> str:
        """Obtiene un token válido, refrescando si es necesario.

        Args:
            requires_user_token: Si True, falla si no hay refresh_token configurado.

        Raises:
            SpotifyAuthError: Si la autenticación falla o no hay user token cuando se requiere.
        """
        async with self._lock:
            if requires_user_token and self._config.auth_mode != SpotifyAuthMode.REFRESH_TOKEN:
                raise SpotifyAuthError(
                    "User token required for this operation but no refresh_token configured"
                )

            if self._is_token_valid():
                assert self._access_token is not None
                return self._access_token

            await self._refresh_token()
            assert self._access_token is not None
            return self._access_token

    async def force_refresh(self) -> None:
        """Fuerza un refresh del token (tras recibir 401)."""
        async with self._lock:
            await self._refresh_token()

    def _is_token_valid(self) -> bool:
        """Verifica si el token actual es válido (con 60s de safety margin)."""
        return self._access_token is not None and time.time() < (self._expires_at - 60.0)

    async def _refresh_token(self) -> None:
        """Realiza el flujo OAuth según el modo configurado."""
        if self._config.auth_mode == SpotifyAuthMode.REFRESH_TOKEN:
            await self._refresh_with_user_token()
        else:
            await self._refresh_with_client_credentials()

    async def _refresh_with_client_credentials(self) -> None:
        """Client Credentials flow (sin contexto de usuario)."""
        logger.info("refreshing_token", mode="client_credentials")

        try:
            response = await self._http_client.post(
                self._token_url,
                data={"grant_type": "client_credentials"},
                auth=(self._config.client_id, self._config.client_secret),
                timeout=self._config.request_timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error("auth_failed", status=e.response.status_code, body=e.response.text[:200])
            raise SpotifyAuthError(
                f"Client credentials auth failed: {e.response.status_code}"
            ) from e
        except httpx.RequestError as e:
            logger.error("auth_request_error", error=str(e))
            raise SpotifyAuthError(f"Network error during auth: {e}") from e

        data = response.json()
        self._access_token = data["access_token"]
        expires_in = data["expires_in"]
        self._expires_at = time.time() + expires_in

        logger.info("token_refreshed", expires_in=expires_in, mode="client_credentials")

    async def _refresh_with_user_token(self) -> None:
        """Refresh token flow (con contexto de usuario)."""
        if not self._config.user_refresh_token:
            raise SpotifyAuthError("No refresh_token configured for user auth")

        logger.info("refreshing_token", mode="refresh_token")

        try:
            response = await self._http_client.post(
                self._token_url,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._config.user_refresh_token,
                },
                auth=(self._config.client_id, self._config.client_secret),
                timeout=self._config.request_timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error("auth_failed", status=e.response.status_code, body=e.response.text[:200])
            raise SpotifyAuthError(f"Refresh token auth failed: {e.response.status_code}") from e
        except httpx.RequestError as e:
            logger.error("auth_request_error", error=str(e))
            raise SpotifyAuthError(f"Network error during auth: {e}") from e

        data = response.json()
        self._access_token = data["access_token"]
        expires_in = data["expires_in"]
        self._expires_at = time.time() + expires_in

        logger.info("token_refreshed", expires_in=expires_in, mode="refresh_token")
