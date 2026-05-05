"""Puerto Deezer Client.

Abstrae el acceso a Deezer en dos canales:
- API publica `api.deezer.com` para metadata (track, artista) sin auth.
- Endpoints privados `www.deezer.com/ajax/gw-light.php` para acciones de
  usuario (historial, follow), que requieren cookies de sesion previas.

El dominio solo conoce este protocolo. Las implementaciones viven en
`infrastructure/deezer/deezer_api_client.py` y pueden ser sustituidas por
fakes en tests sin alterar la capa de aplicacion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from streaming_bot.domain.deezer.listener_history import DeezerListenerHistory
from streaming_bot.domain.exceptions import DomainError


class DeezerApiError(DomainError):
    """Error al hablar con la API publica o privada de Deezer."""


@dataclass(frozen=True, slots=True)
class DeezerTrack:
    """Metadata canonica de un track de Deezer.

    `uri` sigue el formato `deezer:track:{id}` para mantener simetria con
    el resto del codigo (Spotify usa `spotify:track:...`).
    """

    uri: str
    deezer_id: int
    title: str
    duration_seconds: int
    artist_id: int
    artist_name: str
    album_id: int
    album_title: str
    isrc: str | None = None


@dataclass(frozen=True, slots=True)
class DeezerArtist:
    """Metadata canonica de un artista de Deezer."""

    uri: str
    deezer_id: int
    name: str
    nb_fans: int = 0
    nb_albums: int = 0
    picture_url: str | None = None


@runtime_checkable
class IDeezerClient(Protocol):
    """Contrato del cliente Deezer.

    Convencion de errores:
    - 404 / no encontrado -> retorna `None` (no lanza).
    - 401 / sin cookies cuando la operacion las requiere -> `DeezerApiError`.
    - 429 / rate limit -> implementacion debe reintentar/backoff y solo
      lanzar `DeezerApiError` si agota reintentos.
    """

    async def get_user_history(self, account_id: str) -> DeezerListenerHistory | None:
        """Devuelve el historial 30d de la cuenta o None si no hay sesion."""
        ...

    async def get_track(self, track_id: int | str) -> DeezerTrack | None:
        """Devuelve metadata de un track. Acepta `id` numerico o URI."""
        ...

    async def search_artist(self, query: str, *, limit: int = 10) -> list[DeezerArtist]:
        """Busca artistas por nombre. Devuelve lista (puede ser vacia)."""
        ...

    async def follow_artist(self, account_id: str, artist_id: int | str) -> None:
        """Hace que `account_id` siga a `artist_id`. Requiere cookies."""
        ...
