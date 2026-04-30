"""Configuración para Spotify Web API client."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from streaming_bot.domain.value_objects import Country


class SpotifyAuthMode(str, Enum):
    """Modos de autenticación soportados."""

    CLIENT_CREDENTIALS = "client_credentials"
    REFRESH_TOKEN = "refresh_token"  # noqa: S105


class SpotifyConfig(BaseModel):
    """Configuración de Spotify Web API client.

    Soporta dos modos:
    - client_credentials: solo lectura, sin contexto de usuario.
    - refresh_token: operaciones de escritura con user token.
    """

    client_id: str = Field(..., min_length=1)
    client_secret: str = Field(..., min_length=1)
    redirect_uri: str = "http://127.0.0.1:8765/callback"
    user_refresh_token: str | None = None
    default_market: Country = Country.PE
    request_timeout_seconds: float = 20.0
    max_retries: int = 4

    @property
    def auth_mode(self) -> SpotifyAuthMode:
        """Determina el modo de autenticación según la configuración."""
        return (
            SpotifyAuthMode.REFRESH_TOKEN
            if self.user_refresh_token
            else SpotifyAuthMode.CLIENT_CREDENTIALS
        )
