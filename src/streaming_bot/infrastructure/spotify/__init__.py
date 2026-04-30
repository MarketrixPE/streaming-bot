"""Spotify Web API client infrastructure."""

from streaming_bot.infrastructure.spotify.config import SpotifyAuthMode, SpotifyConfig
from streaming_bot.infrastructure.spotify.errors import SpotifyApiError, SpotifyAuthError
from streaming_bot.infrastructure.spotify.spotify_web_api_client import SpotifyWebApiClient

__all__ = [
    "SpotifyApiError",
    "SpotifyAuthError",
    "SpotifyAuthMode",
    "SpotifyConfig",
    "SpotifyWebApiClient",
]
