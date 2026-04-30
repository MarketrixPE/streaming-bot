"""Excepciones específicas de Spotify Web API."""

from __future__ import annotations


class SpotifyAuthError(Exception):
    """Error de autenticación con Spotify (OAuth flow, token inválido, etc)."""

    pass


class SpotifyApiError(Exception):
    """Error no-auth de la API (rate limit superado, recurso no encontrado, etc)."""

    def __init__(self, status_code: int, body_snippet: str) -> None:
        self.status_code = status_code
        self.body_snippet = body_snippet
        super().__init__(f"Spotify API error {status_code}: {body_snippet}")
